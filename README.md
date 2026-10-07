# Zfai Open — brainos

Biologically-inspired memory engine for AI agents, with a minimal HTTP/SDK surface.
仿生物记忆引擎 + 最小服务面。Apache-2.0 开源，由 Zfai Open 团队维护。

[English](#english) | [中文](#中文)

## English

### What is this

brainos is the open core of the memory system: a layered, biologically-inspired
memory engine (episodic / semantic / procedural / working memory, consolidation,
forgetting curves, CRDT consistency, temporal knowledge graphs, hippocampal-dream
consolidation) exposed through a small HTTP API and a Python client.

### Architecture

```text
                    +----------------------------------+
   HTTP/WS -------> |  api: server / gateway / auth    |
   Python SDK ----> |  rate_limiter / middleware       |
                    +----------------+-----------------+
                                     |
                                     v
                    +----------------------------------+
                    |        memory (open core)        |
                    | core / store / persistence       |
                    | episode / semantic / procedural  |
                    | consolidator / forgetting        |
                    | anchor / weaver / crdt           |
                    | temporal_graph_v2 / integrity    |
                    +----------------+-----------------+
                                     |
                                     v
                    +----------------------------------+
                    | kernel support: safe_execute     |
                    | async_compat / resilience        |
                    | observability: auto_log          |
                    +----------------------------------+
```

### Quick start

```bash
pip install -e ".[server]"     # server extras: fastapi/uvicorn/sqlalchemy
python -m brainos.api.brainos_serve   # default :8080
```

The memory core itself is standard-library only — no third-party packages
required:

```python
from brainos.memory.sdk import MemoryClient
c = MemoryClient(api_key="<token>")     # or use the library directly:
from brainos.memory import CoreMemory   # embed in-process
```

Notes:
- Set `BRAINOS_AUTH_SECRET` in production; the auth layer falls back to a
  random per-process secret otherwise.
- `BRAINOS_API_HOST` / `BRAINOS_API_PORT` / `BRAINOS_API_WORKERS` configure
  the launcher (`python -m brainos.api.run`).

### What is NOT in this repository

Agentic meta-architecture (agent loop / AMCC / autonomous / ANS), the
battle-tuned scheduling layer (FSRS parameter sets, retrieval boosting,
fidelity & surprise metrics), billing, and benchmarks remain proprietary.
See `CARVE_NOTICE.md`.

### License

Apache-2.0. © 2026 zfai-open contributors.

## 中文

### 这是什么

brainos 是记忆系统的开源内核：分层仿生物记忆引擎（情景/语义/程序/工作记忆、
记忆固化、遗忘曲线、CRDT 一致性、时序知识图谱、海马梦境巩固），配最小
HTTP API 与 Python 客户端。

### 快速上手

```bash
pip install -e ".[server]"            # server 依赖：fastapi/uvicorn/sqlalchemy
python -m brainos.api.brainos_serve   # 默认 :8080 端口
```

memory 内核仅依赖 Python 标准库，零第三方包：

```python
from brainos.memory.sdk import MemoryClient      # 远程客户端
from brainos.memory import CoreMemory            # 进程内嵌入
```

说明：
- 生产环境请设置 `BRAINOS_AUTH_SECRET`；否则认证层回退到进程内随机密钥。
- `BRAINOS_API_HOST` / `BRAINOS_API_PORT` / `BRAINOS_API_WORKERS` 配置启动器
  （`python -m brainos.api.run`）。

### 本仓库不包含

Agent 元架构（agent_loop/AMCC/autonomous/ANS）、战役级调度调优层（FSRS 参数组、
检索加权、保真度与惊讶度度量）、计费与基准评测，均为闭源部分。

### 与商业版的关系

本仓库是 **Zfai Open** 开源基线（v0.9）。商业版在其之上叠加：Agent 元架构、
战役级调优层、多租户与计费、企业治理与评测体系。开源版与商业版共享 memory
内核架构，商业版并非本仓库的简单超集，两者能力边界见 `CARVE_NOTICE.md`。

### License

Apache-2.0
