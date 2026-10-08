# Zfai Open — brainos

Biologically-inspired memory engine for AI agents, with a minimal HTTP/SDK surface.
仿生物记忆引擎 + 最小服务面。AGPL-3.0 开源，由 Zfai Open 团队维护。

> **Note:** BRAIOS is a Python prototype system for memory algorithm validation.
> ZfaiOS is an independent commercial re-implementation from scratch in Rust,
> inheriting the memory architecture and experimental findings from BRAIOS.
> Both projects are developed by the same team.


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
curl http://127.0.0.1:8080/health     # → {"status": "ok", "memory": {...}}
```

#### Memory contract (add / search)

```bash
# store conversation messages (idempotent request_id; extra fields ignored)
curl -X POST http://127.0.0.1:8080/add -H 'Content-Type: application/json' -d '{
  "request_id": "req-1", "user_id": "u1", "session_id": "s1",
  "messages": [{"role": "user", "content": "Alice chose project Apollo for the Q1 launch.",
                "timestamp": "2026-10-08T10:00:00Z"}]}'
# → {"success": true, "request_id": "req-1", "user_id": "u1", "session_id": "s1"}

# evidence-only retrieval (no answer generation), ≤ top_k items
curl -X POST http://127.0.0.1:8080/search -H 'Content-Type: application/json' -d '{
  "query": "Which project did Alice choose?", "user_id": "u1", "top_k": 5}'
# → {"data": [{"id": "...", "content": "...", "created_at": "2026-10-08T10:00:00"}]}

# the same search as Server-Sent Events (meta → evidence* → summary)
curl -N -X POST http://127.0.0.1:8080/search/stream -H 'Content-Type: application/json' \
  -d '{"query": "Alice project", "user_id": "u1", "top_k": 5}'
```

Retrieval is a fixed-strategy multi-channel ranker (inverted-index BM25 +
char-trigram overlap + recency, fused with reciprocal rank fusion) — pure
stdlib, zero LLM, zero network. Search results are scoped by `user_id`:
users never see each other's memories. Temporal guarantees (covered by the
test suite): adds are stored strictly in call order, a search never sees an
uncommitted add, and each request commits as an independent transaction.

The memory core itself is standard-library only — no third-party packages
required:

```python
from brainos.memory.sdk import MemoryClient
c = MemoryClient(api_key="<token>")     # or use the library directly:
from brainos.memory import CoreMemory   # embed in-process
```

Notes:
- Set `BRAINOS_API_KEY` to require `Authorization: Token <KEY>` on
  /add, /search and /search/stream; with no key set, auth is disabled
  (local-development default — always set it in production).
- Set `BRAINOS_DB` to a SQLite path for durable storage + idempotent-replay
  across restarts; the default is per-process memory.
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

AGPL-3.0. © 2026 Zfai Open contributors.

## 中文

### 这是什么

brainos 是记忆系统的开源内核：分层仿生物记忆引擎（情景/语义/程序/工作记忆、
记忆固化、遗忘曲线、CRDT 一致性、时序知识图谱、海马梦境巩固），配最小
HTTP API 与 Python 客户端。

### 快速上手

```bash
pip install -e ".[server]"            # server 依赖：fastapi/uvicorn/sqlalchemy
python -m brainos.api.brainos_serve   # 默认 :8080 端口
curl http://127.0.0.1:8080/health     # → {"status": "ok", "memory": {...}}
```

#### 记忆契约（add / search）

```bash
# 写入对话记忆（request_id 幂等；多余字段一律忽略）
curl -X POST http://127.0.0.1:8080/add -H 'Content-Type: application/json' -d '{
  "request_id": "req-1", "user_id": "u1", "session_id": "s1",
  "messages": [{"role": "user", "content": "Alice chose project Apollo for the Q1 launch.",
                "timestamp": "2026-10-08T10:00:00Z"}]}'

# 纯证据检索（零答案生成），返回条数 ≤ top_k
curl -X POST http://127.0.0.1:8080/search -H 'Content-Type: application/json' -d '{
  "query": "Which project did Alice choose?", "user_id": "u1", "top_k": 5}'

# 同一检索的 SSE 流式形态（meta → evidence* → summary）
curl -N -X POST http://127.0.0.1:8080/search/stream -H 'Content-Type: application/json' \
  -d '{"query": "Alice project", "user_id": "u1", "top_k": 5}'
```

检索为固定策略多通道排序（倒排 BM25 + 字符三 Gram + 新近度，RRF 融合）——
纯标准库、零 LLM、零外网。检索按 `user_id` 隔离：用户之间零串扰。时序保证
（测试套件覆盖）：Add 严格按调用序落库、Search 永不见未提交的 Add、
每请求独立事务。

memory 内核仅依赖 Python 标准库，零第三方包：

```python
from brainos.memory.sdk import MemoryClient      # 远程客户端
from brainos.memory import CoreMemory            # 进程内嵌入
```

说明：
- 设置 `BRAINOS_API_KEY` 后 /add、/search、/search/stream 要求
  `Authorization: Token <KEY>` 鉴权；未设置=鉴权关闭（本地开发默认，
  生产必设）。
- 设置 `BRAINOS_DB` 指定 SQLite 持久化路径（重启后幂等重放仍生效）；
  缺省为进程内存储。
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

This project is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.

This means:
- You are free to use, study, modify, and distribute this software
- If you run modified versions as a network service, you **must** make the modified source code available to users
- Any derivative work must also be licensed under AGPL-3.0
- Commercial licensing is available separately — contact ceo@zfai.cc

Copyright (C) 2026 Zfai Open. All rights reserved under AGPL-3.0.
