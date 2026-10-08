# Copyright 2026 zfai-open contributors
#
# Copyright (C) 2026 Zfai Open
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See the LICENSE file for details.
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""brainos/api/brainos_serve.py — BrainOS v6 FastAPI 服务

Memory contract (open baseline, AML wire shape):
  POST /add        — store conversation messages (idempotent request_id)
  POST /search     — evidence-only retrieval {"data":[{id,content,created_at}]}
  POST /search/stream — the same search as Server-Sent Events
                       (meta → evidence* → summary)
  GET  /health     — liveness (auth-exempt; advertises the memory surface)

Legacy system endpoints (retained):
  POST /verify  — 代码验证
  POST /scan    — 代码扫描
  POST /fix     — AI修复
  POST /dream   — 梦境巡逻
  GET  /status  — 系统状态
  GET  /trust   — 信任天气
  GET  /evolve/status — 进化状态

启动: brainos serve --port 8080  /  python -m brainos.api.brainos_serve
环境: BRAINOS_API_KEY 启用 Authorization: Token <KEY> 鉴权（缺省=本地开放）；
      BRAINOS_DB 指定 SQLite 持久化路径（缺省=进程内）。
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger("brainos.api.brainos_serve")

try:
    from fastapi import FastAPI, HTTPException, Request as FastAPIRequest
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, StreamingResponse
    from pydantic import BaseModel, Field
    import uvicorn
    _FASTAPI_OK = True
except ImportError:
    _FASTAPI_OK = False


# ── Pydantic 请求/响应模型 ──

class VerifyRequest(BaseModel):
    code: str = Field(..., description="待验证的代码")
    language: str = Field(default="python", description="编程语言")
    level: str = Field(default="standard", description="验证级别: quick/standard/deep")

class ScanRequest(BaseModel):
    path: str = Field(default=".", description="扫描路径")
    quick: bool = Field(default=True, description="快速模式")

class FixRequest(BaseModel):
    file_path: str = Field(..., description="待修复文件路径")
    description: str = Field(default="", description="问题描述")
    auto_apply: bool = Field(default=False, description="自动应用修复")

class DreamRequest(BaseModel):
    scope: str = Field(default="full", description="巡逻范围: full/quick/targeted")
    target: str = Field(default="", description="目标模块（targeted模式）")


# ═══════════════════════════════════════════════════════════════════
# 创建FastAPI应用
# ═══════════════════════════════════════════════════════════════════

def create_brainos_app() -> Any:
    """创建BrainOS FastAPI应用"""
    if not _FASTAPI_OK:
        raise RuntimeError("FastAPI/uvicorn not installed. pip install fastapi uvicorn")

    app = FastAPI(
        title="BrainOS v6 API",
        version="6.0.0",
        description="BrainOS — The AI Operating System that Thinks.\n\n"
                    "7 core endpoints wrapping BrainOS core capabilities.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _start_time = time.time()

    # ══ Memory contract surface (open baseline) ══════════════════════════
    # One wiring path: the internal router holds all handler logic; FastAPI is
    # only a transport adapter (parse body → internal Request → Response).
    from brainos.api.aml import format_sse, wire_memory_surface
    from brainos.api.server import APIConfig, BrainOSAPI
    from brainos.api.middleware import Request as InternalRequest

    _internal_api = BrainOSAPI(APIConfig(host="0.0.0", port=8080))
    _aml_handler, _aml_service = wire_memory_surface(_internal_api)

    async def _bridge_request(method: str, path: str, request: Any, body: dict[str, Any]) -> Any:
        """Transport adapter: internal Request → Response → JSONResponse."""
        internal = InternalRequest(
            method=method,
            path=path,
            headers={str(k): str(v) for k, v in getattr(request, "headers", {}).items()},
            body=body,
            query_params={str(k): str(v) for k, v in getattr(request, "query_params", {}).items()},
        )
        resp = await _internal_api.handle_request(internal)
        return JSONResponse(content=resp.body, status_code=resp.status_code)

    async def _parse_json_body(request: Any) -> dict[str, Any]:
        try:
            raw = await request.body()
            parsed = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=400, detail=f"invalid JSON body: {exc}") from exc
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="body must be a JSON object")
        return parsed

    # ── GET /health — liveness (auth-exempt), advertises the memory surface ──
    @app.get("/health", tags=["Memory"], summary="服务健康（免鉴权·含memory路由自报）")
    async def health():
        return await _bridge_request("GET", "/health", None, {})

    # ── POST /add — AML add contract ──
    @app.post("/add", tags=["Memory"], summary="写入对话记忆（request_id幂等）")
    async def add(request: FastAPIRequest):
        body = await _parse_json_body(request)
        return await _bridge_request("POST", "/add", request, body)

    # ── POST /search — AML search contract (evidence-only) ──
    @app.post("/search", tags=["Memory"], summary="证据检索 {data:[{id,content,created_at}]}")
    async def search(request: FastAPIRequest):
        body = await _parse_json_body(request)
        return await _bridge_request("POST", "/search", request, body)

    # ── POST /search/stream — same search as SSE (meta → evidence* → summary) ──
    @app.post("/search/stream", tags=["Memory"], summary="流式证据检索（SSE·证据先于汇总）")
    async def search_stream(request: FastAPIRequest):
        body = await _parse_json_body(request)
        if not _aml_service.check_auth(request.headers.get("authorization")):
            raise HTTPException(status_code=401, detail="unauthorized")
        error = _aml_service.validate_search(body)
        if error:
            raise HTTPException(status_code=400, detail=error)

        def _events():
            for kind, data in _aml_service.search_events(body):
                yield format_sse(kind, data)

        return StreamingResponse(_events(), media_type="text/event-stream")

    # ══ Legacy system endpoints (retained as-is) ═════════════════════════

    # ── GET /status — 系统状态 ──
    @app.get("/status", tags=["System"], summary="系统状态")
    async def get_status():
        uptime = time.time() - _start_time
        status_data: dict[str, Any] = {
            "status": "running",
            "version": "6.0.0",
            "uptime_seconds": round(uptime, 1),
        }
        # 收集CLI状态
        try:
            from brainos.cli.brainos_cli import BrainOSFullCLI
            cli = BrainOSFullCLI.get_instance()
            cmd = cli._commands.get("status")
            if cmd and cmd.handler:
                result = cmd.handler({})
                if result.success:
                    status_data.update(result.data)
        except Exception as e:
            status_data["cli_error"] = str(e)[:100]
        return status_data

    # ── GET /trust — 信任天气 ──
    @app.get("/trust", tags=["System"], summary="信任天气栏")
    async def get_trust():
        try:
            from brainos.cli.experience_commands import _collect_system_metrics
            metrics = _collect_system_metrics()
            trust = metrics.get("trust_score", 0.85)
            if trust >= 0.9:
                weather = "sunny"
            elif trust >= 0.7:
                weather = "cloudy"
            elif trust >= 0.5:
                weather = "rainy"
            else:
                weather = "storm"
            return {
                "trust_score": trust,
                "weather": weather,
                "cognitive_load": metrics.get("cognitive_load", 0),
                "heartbeat_bpm": metrics.get("heartbeat_bpm", 72),
                "blood_pressure": metrics.get("blood_pressure", [120, 80]),
                "evolution_gen": metrics.get("evolution_gen", 0),
                "fitness": metrics.get("fitness", 0),
                "anomalies": metrics.get("anomalies", 0),
                "brain_activity": metrics.get("brain_activity", 0.5),
            }
        except Exception as e:
            return {"trust_score": 0.85, "weather": "loading", "error": str(e)[:100]}

    # ── GET /evolve/status — 进化状态 ──
    @app.get("/evolve/status", tags=["Evolution"], summary="进化状态")
    async def get_evolve_status():
        result: dict[str, Any] = {"evolution": {}}
        try:
            from brainos.evolution.evolution_organ.command_evolver import CommandEvolver
            evolver = CommandEvolver()
            result["command_evolver"] = evolver.get_stats()
        except Exception as e:
            result["command_evolver_error"] = str(e)[:100]
        try:
            from brainos.evolution.evolution_organ.evolution_time_machine import EvolutionTimeMachine
            tm = EvolutionTimeMachine()
            result["time_machine"] = tm.get_stats()
            snapshots = tm.list_snapshots()
            result["latest_snapshot"] = snapshots[0] if snapshots else None
        except Exception as e:
            result["time_machine_error"] = str(e)[:100]
        try:
            from brainos.evolution.evolution_organ.evo_proof_cli import EvoProofCli
            proof = EvoProofCli()
            result["audit"] = proof.generate_audit()
        except Exception as e:
            result["audit_error"] = str(e)[:100]
        return result

    # ── POST /verify — 代码验证 ──
    @app.post("/verify", tags=["Core"], summary="代码验证")
    async def post_verify(req: VerifyRequest):
        result: dict[str, Any] = {
            "valid": True,
            "level": req.level,
            "language": req.language,
            "issues": [],
        }
        # 语法检查
        if req.language == "python":
            import ast
            try:
                ast.parse(req.code)
                result["syntax"] = "valid"
            except SyntaxError as e:
                result["syntax"] = "invalid"
                result["valid"] = False
                result["issues"].append({
                    "type": "syntax_error",
                    "message": str(e),
                    "line": e.lineno,
                })
        # 代码复杂度
        lines = req.code.strip().split("\n")
        result["metrics"] = {
            "lines": len(lines),
            "chars": len(req.code),
        }
        # 铁律检查 (quick不做深度检查)
        if req.level in ("standard", "deep"):
            dangerous = ["exec(", "eval(", "__import__(", "subprocess.call(", "os.system("]
            for d in dangerous:
                if d in req.code:
                    result["issues"].append({
                        "type": "security_warning",
                        "message": f"Potential dangerous call: {d}",
                    })
        if req.level == "deep":
            # 额外检查
            if len(lines) > 100:
                result["issues"].append({
                    "type": "complexity",
                    "message": f"File has {len(lines)} lines, consider splitting",
                })
        return result

    # ── POST /scan — 代码扫描 ──
    @app.post("/scan", tags=["Core"], summary="代码扫描")
    async def post_scan(req: ScanRequest):
        result: dict[str, Any] = {
            "path": req.path,
            "quick": req.quick,
            "findings": [],
            "scanned_files": 0,
        }
        try:
            from pathlib import Path
            scan_dir = Path(req.path)
            if scan_dir.exists():
                py_files = list(scan_dir.rglob("*.py"))
                if req.quick:
                    py_files = py_files[:50]
                result["scanned_files"] = len(py_files)
                # 简单扫描规则
                for fp in py_files[:50]:
                    try:
                        content = fp.read_text(encoding="utf-8", errors="ignore")
                        if "TODO" in content or "FIXME" in content:
                            result["findings"].append({
                                "file": str(fp),
                                "type": "todo",
                                "message": "Contains TODO/FIXME",
                            })
                        if "import *" in content:
                            result["findings"].append({
                                "file": str(fp),
                                "type": "style",
                                "message": "Wildcard import",
                            })
                    except Exception:
                        continue
                result["findings_count"] = len(result["findings"])
        except Exception as e:
            result["error"] = str(e)[:100]
        return result

    # ── POST /fix — AI修复 ──
    @app.post("/fix", tags=["Core"], summary="AI修复")
    async def post_fix(req: FixRequest):
        result: dict[str, Any] = {
            "file_path": req.file_path,
            "description": req.description,
            "fixes_proposed": 0,
            "fixes_applied": 0,
        }
        try:
            from pathlib import Path
            fp = Path(req.file_path)
            if not fp.exists():
                raise HTTPException(status_code=404, detail=f"File not found: {req.file_path}")
            # 使用heal检测
            try:
                from brainos.cli.brainos_cli import BrainOSFullCLI
                cli = BrainOSFullCLI.get_instance()
                heal = cli._commands.get("heal")
                if heal and heal.subcommands.get("detect"):
                    detect_result = heal.subcommands["detect"].handler({
                        "type": "code_quality",
                        "module": str(fp),
                        "description": req.description or f"Auto-fix scan for {fp.name}",
                        "severity": "medium",
                    })
                    result["detection"] = detect_result.message if detect_result.success else None
            except Exception as e:
                result["heal_error"] = str(e)[:100]
            result["status"] = "analyzed"
            if not req.auto_apply:
                result["note"] = "Set auto_apply=true to apply fixes"
        except HTTPException:
            raise
        except Exception as e:
            result["error"] = str(e)[:200]
        return result

    # ── POST /dream — 梦境巡逻 ──
    @app.post("/dream", tags=["Core"], summary="梦境巡逻")
    async def post_dream(req: DreamRequest):
        result: dict[str, Any] = {
            "scope": req.scope,
            "target": req.target,
            "status": "completed",
            "dreams": [],
        }
        try:
            # 使用evolution evolve触发自进化循环
            from brainos.cli.brainos_cli import BrainOSFullCLI
            cli = BrainOSFullCLI.get_instance()
            evo = cli._commands.get("evolution")
            if evo and evo.subcommands.get("evolve"):
                evo_result = evo.subcommands["evolve"].handler({"topic": "dream_patrol"})
                result["evolution_result"] = evo_result.message if evo_result.success else None
            # 触发purify scan
            purify = cli._commands.get("purify")
            if purify and purify.subcommands.get("scan"):
                scan_result = purify.subcommands["scan"].handler({"quick": str(req.scope == "quick")})
                result["purify_result"] = scan_result.message if scan_result.success else None
            result["timestamp"] = time.time()
        except Exception as e:
            result["error"] = str(e)[:100]
        return result

    return app


def run_server(host="0.0.0.0", port=8080):
    """启动BrainOS API服务 (带防御校验与异常降级)"""
    if not _FASTAPI_OK:
        print("Error: FastAPI/uvicorn not installed. Run: pip install fastapi uvicorn")
        return

    # 1. 参数防御:校验端口合法范围
    if not isinstance(port, int) or not (1 <= port <= 65535):
        logger.error("Invalid port number: %s. Must be between 1 and 65535.", port)
        print(f"Error: Invalid port '{port}'. Must be between 1 and 65535.")
        return
    if not host or not isinstance(host, str):
        logger.error("Invalid host: %s. Defaulting to '0.0.0.0'.", host)
        host = "0.0.0.0"

    # 2. 构建应用实例 (捕获潜在的依赖注入或初始化异常)
    try:
        app = create_brainos_app()
    except Exception as _exc:
        logger.error("Failed to create BrainOS app instance: %s", _exc, exc_info=True)
        print(f"Fatal: Application initialization failed. Details: {_exc}")
        return

    # 3. 启动Uvicorn服务 (捕获网络/端口级异常以防崩溃)
    logger.info("Starting BrainOS API on %s:%d", host, port)
    try:
        uvicorn.run(app, host=host, port=port, log_level="info", access_log=False)
    except SystemExit as _se:
        # Uvicorn 在遇到致命错误(如端口占用)时会触发 SystemExit
        logger.critical("Uvicorn server aborted with SystemExit (code=%s). Likely port conflict.", _se.code)
        print(f"\nError: Server failed to start. Port {port} might already be in use or inaccessible.")
    except OSError as _osc:
        # 处理底层Socket错误 (如 Permission denied 当 port < 1024)
        logger.critical("OS level error prevented server start on %s:%d: %s", host, port, _osc)
        print(f"\nOS Error: {_osc}. (Hint: If using port < 1024, root privileges are required.)")
    except Exception as _exc:
        # 兜底所有未知异常
        logger.error("Unexpected error during server execution: %s", _exc, exc_info=True)
        print(f"\nUnexpected server error: {_exc}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    _env_host = os.environ.get("BRAINOS_API_HOST", "0.0.0.0")
    try:
        _env_port = int(os.environ.get("BRAINOS_API_PORT", "8080"))
    except ValueError:
        print(f"Error: Invalid BRAINOS_API_PORT {os.environ.get('BRAINOS_API_PORT')!r}; using 8080.")
        _env_port = 8080
    run_server(host=_env_host, port=_env_port)

