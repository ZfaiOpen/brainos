# CARVE NOTICE — brainos v0.9 open-core boundary

This repository is the **open-core baseline (v0.9.0)** of the memory system,
published by Zfai Open under AGPL-3.0. This notice documents what is
deliberately **not** included and why.

## Included (open core)

| Layer | Contents |
|---|---|
| `brainos/memory/` | 43 modules: core/store/persistence, episodic/semantic/procedural/working memory, consolidation, forgetting curves, CRDT consistency, temporal knowledge graphs (v1 + v2), anchoring, weaving, hippocampal-dream consolidation, integrity guard, unified memo engine |
| `brainos/api/` | Minimal HTTP/WS surface: server, gateway, router, middleware, JWT/bearer auth, rate limiter, memory + observability route handlers, SQLite session layer |
| `brainos/kernel/` | Generic support primitives: safe_execute, async_compat, resilience (retry/circuit), config, protocol interfaces. The cross-domain combo engine ships as an import-compatible no-op stub |
| `brainos/observability/` | auto_log only |
| `brainos/governance/` | constitution ships as a NoopConstitution stub (pass-through decisions) |

## Excluded (commercial version only)

| Domain | Reason |
|---|---|
| Agentic meta-architecture (`agent_loop`, `amcc`, `autonomous`, `ans`) | Core commercial differentiator |
| Battle-tuned scheduling layer (FSRS parameter sets, retrieval boosting, fidelity & surprise metrics) | Competition-tuned parameters; the open core ships the model skeletons, not the tuned parameters |
| Cross-domain combo engine (full rule/routing implementation) | Replaced here by a no-op stub |
| Governance engine (full constitution rule base, compliance, policy engine, explainability) | Replaced here by a NoopConstitution stub |
| Multi-tenant services and billing | Commercial capability |
| Benchmarks and baseline number sets | Competitive data |
| Full `/api/v1` route registry and evolution API | Legacy/commercial surface; the open core serves the minimal memory/observability routes |
| Process bootstrap and full CLI | Commercial boot surface; `import brainos` in the open core is side-effect free |

## Version anchors

- `memory/temporal_graph_v2.py` is **frozen at v0.9.0**: its evolution continues
  in the commercial version only (see the banner in the file).
- `MemoryClient` (`brainos/memory/sdk.py`) is the stable SDK entry point.
