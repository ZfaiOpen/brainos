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
from __future__ import annotations
from typing import TYPE_CHECKING

from brainos.observability.auto_log import logged
from brainos.kernel.safe_execute import safe_execute

if TYPE_CHECKING:
    from brainos.api.server import BrainOSAPI
    from brainos.memory.context import ContextEngine
    from brainos.memory.recall import RecallEngine
    from brainos.memory.store import MemoryStore

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from brainos.api.middleware import Request, Response

logger = logging.getLogger("brainos.api.routes.memory")


@dataclass
class MemoryRouteConfig:
    max_page_size: int = 100
    default_page_size: int = 20
    max_anchor_size_bytes: int = 1024 * 1024
    enable_semantic_search: bool = True
    context_max_layers: int = 5

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "max_page_size": self.max_page_size,
            "default_page_size": self.default_page_size,
            "enable_semantic_search": self.enable_semantic_search,
        }


@dataclass
class MemoryRouteMetrics:
    total_queries: int = 0
    total_stores: int = 0
    total_deletes: int = 0
    total_recall: int = 0
    total_context: int = 0
    query_latency_total_ms: float = 0.0
    store_latency_total_ms: float = 0.0
    errors: int = 0

    @logged()
    @safe_execute
    def record_query(self, latency_ms):
        pass


    @logged()
    @safe_execute
    def record_store(self, latency_ms: float) -> None:
        self.total_stores += 1
        self.store_latency_total_ms += latency_ms

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        avg_query = self.query_latency_total_ms / max(1, self.total_queries)
        avg_store = self.store_latency_total_ms / max(1, self.total_stores)
        return {
            "total_queries": self.total_queries,
            "total_stores": self.total_stores,
            "total_deletes": self.total_deletes,
            "total_recall": self.total_recall,
            "total_context": self.total_context,
            "avg_query_latency_ms": round(avg_query, 2),
            "avg_store_latency_ms": round(avg_store, 2),
            "errors": self.errors,
        }


class MemoryRouteHandler:
    def __init__(self, config: MemoryRouteConfig | None = None) -> None:
        self._config = config or MemoryRouteConfig()
        self._metrics = MemoryRouteMetrics()
        self._memory_store: MemoryStore | None = None
        self._context_engine: ContextEngine | None = None
        self._recall_engine: RecallEngine | None = None

    @logged()
    @safe_execute
    def set_store(self, store: MemoryStore) -> None:
        self._memory_store = store

    @logged()
    @safe_execute
    def set_context_engine(self, engine: ContextEngine) -> None:
        self._context_engine = engine

    @logged()
    @safe_execute
    def set_recall_engine(self, engine: RecallEngine) -> None:
        self._recall_engine = engine

    @logged()
    async def handle_get_anchors(self, request: Request) -> Response:
        start = time.monotonic()
        page = int(request.query_params.get("page", "1"))
        page_size = min(
            int(request.query_params.get("page_size", str(self._config.default_page_size))),
            self._config.max_page_size,
        )
        anchor_type = request.query_params.get("type", "")

        if self._memory_store:
            try:
                if anchor_type:
                    results = self._memory_store.search_by_type(anchor_type)
                else:
                    results = self._memory_store.list_all()
                total = len(results) if isinstance(results, list) else 0
                offset = (page - 1) * page_size
                page_results = results[offset : offset + page_size] if isinstance(results, list) else []
                anchors = [r.to_dict() if hasattr(r, "to_dict") else r for r in page_results]
            except Exception as _exc:
                logger.exception("Failed to list anchors")
                self._metrics.errors += 1
                anchors = []
                total = 0
        else:
            anchors = []
            total = 0

        latency = (time.monotonic() - start) * 1000.0
        self._metrics.record_query(latency)

        return Response.ok(
            {
                "anchors": anchors,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size if page_size > 0 else 0,
            },
            request.request_id,
        )

    @logged()
    async def handle_get_anchor(self, request: Request) -> Response:
        anchor_id = request.query_params.get("id", "")
        if not anchor_id:
            return Response.bad_request("Missing anchor id", request.request_id)

        start = time.monotonic()

        if self._memory_store:
            try:
                anchor = self._memory_store.retrieve(anchor_id)
                if anchor is None:
                    return Response.not_found(f"Anchor {anchor_id} not found", request.request_id)
                data = anchor.to_dict() if hasattr(anchor, "to_dict") else anchor
            except Exception as _exc:
                logger.exception("Failed to retrieve anchor", anchor_id)
                self._metrics.errors += 1
                return Response.not_found(f"Anchor {anchor_id} not found", request.request_id)
        else:
            return Response.not_found(f"Anchor {anchor_id} not found (no store)", request.request_id)

        latency = (time.monotonic() - start) * 1000.0
        self._metrics.record_query(latency)

        return Response.ok(data, request.request_id)

    @logged()
    async def handle_create_anchor(self, request: Request) -> Response:
        content = request.body.get("content", "")
        anchor_type = request.body.get("anchor_type", "KNOWLEDGE")
        strength = request.body.get("strength", "MEDIUM")
        tags = request.body.get("tags", [])
        metadata = request.body.get("metadata", {})

        if not content:
            return Response.bad_request("Missing content", request.request_id)

        content_size = len(content.encode("utf-8"))
        if content_size > self._config.max_anchor_size_bytes:
            max_kb = self._config.max_anchor_size_bytes // 1024
            return Response.bad_request(
                f"Content too large ({content_size} bytes). Max: {max_kb}KB",
                request.request_id,
            )

        start = time.monotonic()
        anchor_id = f"anchor_{uuid.uuid4().hex[:12]}"

        if self._memory_store:
            try:
                from brainos.memory.anchor import AnchorStrength, AnchorType, MemoryAnchor

                at = AnchorType[anchor_type] if anchor_type in AnchorType.__members__ else AnchorType.KNOWLEDGE
                astrength = AnchorStrength[strength] if strength in AnchorStrength.__members__ else AnchorStrength.MEDIUM
                anchor = MemoryAnchor(
                    anchor_type=at,
                    strength=astrength,
                    content=content,
                )
                if hasattr(anchor, "tags"):
                    anchor.tags = tags
                if hasattr(anchor, "metadata"):
                    anchor.metadata = metadata
                self._memory_store.save_anchor(anchor)
                anchor_id = anchor.anchor_id if hasattr(anchor, "anchor_id") else anchor_id
            except Exception as _exc:
                logger.exception("Failed to create anchor")
                self._metrics.errors += 1

        latency = (time.monotonic() - start) * 1000.0
        self._metrics.record_store(latency)

        return Response.created(
            {
                "anchor_id": anchor_id,
                "anchor_type": anchor_type,
                "strength": strength,
                "content_size": content_size,
                "created": True,
            },
            request.request_id,
        )

    @logged()
    async def handle_delete_anchor(self, request: Request) -> Response:
        anchor_id = request.body.get("anchor_id", "")
        if not anchor_id:
            return Response.bad_request("Missing anchor_id", request.request_id)

        if self._memory_store:
            try:
                deleted = self._memory_store.delete_anchor(anchor_id)
                if not deleted:
                    return Response.not_found(f"Anchor {anchor_id} not found", request.request_id)
            except Exception as e:
                logger.exception("Failed to delete anchor", anchor_id)
                self._metrics.errors += 1
                return Response.internal_error(str(e), request.request_id)
        else:
            return Response.not_found("No memory store available", request.request_id)

        self._metrics.total_deletes += 1
        return Response.ok({"deleted": True, "anchor_id": anchor_id}, request.request_id)

    @logged()
    async def handle_get_context(self, request: Request) -> Response:
        self._metrics.total_context += 1

        if self._context_engine:
            try:
                ctx = self._context_engine.get_context()
                data = ctx if isinstance(ctx, dict) else {"context": str(ctx)}
                return Response.ok(data, request.request_id)
            except Exception as _exc:
                logger.exception("Failed to get context")

        layers = ["system", "session", "task", "working", "scratch"]
        return Response.ok(
            {
                "layers": {layer: {"content": None, "size": 0} for layer in layers},
                "total_tokens": 0,
                "compression_ratio": 1.0,
            },
            request.request_id,
        )

    @logged()
    async def handle_update_context(self, request: Request) -> Response:
        layer = request.body.get("layer", "")
        content = request.body.get("content", "")

        valid_layers = {"system", "session", "task", "working", "scratch"}
        if layer not in valid_layers:
            return Response.bad_request(
                f"Invalid layer. Must be one of: {valid_layers}",
                request.request_id,
            )
        if not content:
            return Response.bad_request("Missing content", request.request_id)

        if self._context_engine:
            try:
                from brainos.memory.context import ContextLayer

                cl_map = {
                    "system": ContextLayer.SYSTEM,
                    "session": ContextLayer.SESSION,
                    "task": ContextLayer.TASK,
                    "working": ContextLayer.WORKING,
                    "scratch": ContextLayer.SCRATCH,
                }
                self._context_engine.push(cl_map[layer], content)
            except Exception as _exc:
                logger.exception("Failed to update context")

        self._metrics.total_context += 1
        return Response.ok({"updated": True, "layer": layer, "content_length": len(content)}, request.request_id)

    @logged()
    async def handle_recall(self, request: Request) -> Response:
        query = request.body.get("query", "")
        top_k = min(int(request.body.get("top_k", "10")), self._config.max_page_size)
        search_mode = request.body.get("mode", "hybrid")

        if not query:
            return Response.bad_request("Missing query", request.request_id)

        valid_modes = {"keyword", "semantic", "hybrid"}
        if search_mode not in valid_modes:
            return Response.bad_request(f"Invalid mode. Must be one of: {valid_modes}", request.request_id)

        start = time.monotonic()
        self._metrics.total_recall += 1

        if self._recall_engine:
            try:
                if search_mode == "keyword":
                    results = self._recall_engine.keyword_search(query)
                elif search_mode == "semantic":
                    results = self._recall_engine.semantic_search(query, top_k=top_k)
                else:
                    results = self._recall_engine.hybrid_search(query, top_k=top_k)
                memories = [r.to_dict() if hasattr(r, "to_dict") else r for r in results[:top_k]]
            except Exception as _exc:
                logger.exception("Recall failed")
                self._metrics.errors += 1
                memories = []
        else:
            memories = []

        latency = (time.monotonic() - start) * 1000.0
        self._metrics.record_query(latency)

        return Response.ok(
            {
                "results": memories,
                "total": len(memories),
                "query": query,
                "mode": search_mode,
                "top_k": top_k,
                "latency_ms": round(latency, 2),
            },
            request.request_id,
        )

    @logged()
    async def handle_get_memory_status(self, request: Request) -> Response:
        if self._memory_store:
            try:
                counts = self._memory_store.count()
                by_type = self._memory_store.count_by_type()
                by_strength = self._memory_store.count_by_strength()
                total_size = self._memory_store.total_size()
                return Response.ok(
                    {
                        "counts": counts,
                        "by_type": by_type,
                        "by_strength": by_strength,
                        "total_size_bytes": total_size,
                        "store_active": True,
                    },
                    request.request_id,
                )
            except Exception as _exc:
                logger.exception("Failed to get memory status")

        return Response.ok(
            {
                "module": "memory",
                "version": "2.0.0",
                "store_active": False,
                "hot_count": 0,
                "warm_count": 0,
                "cold_count": 0,
            },
            request.request_id,
        )

    @logged()
    async def handle_search(self, request: Request) -> Response:
        query = request.query_params.get("q", "")
        limit = min(int(request.query_params.get("limit", "20")), self._config.max_page_size)

        if not query:
            return Response.bad_request("Missing query parameter 'q'", request.request_id)

        start = time.monotonic()

        if self._memory_store:
            try:
                results = self._memory_store.search(query)
                items = results[:limit] if isinstance(results, list) else []
                data = [r.to_dict() if hasattr(r, "to_dict") else r for r in items]
            except Exception as _exc:
                logger.exception("Search failed")
                self._metrics.errors += 1
                data = []
        else:
            data = []

        latency = (time.monotonic() - start) * 1000.0
        self._metrics.record_query(latency)

        return Response.ok(
            {
                "results": data,
                "total": len(data),
                "query": query,
                "latency_ms": round(latency, 2),
            },
            request.request_id,
        )

    @logged()
    async def handle_get_metrics(self, request: Request) -> Response:
        return Response.ok(self._metrics.to_dict(), request.request_id)

    @logged()
    @safe_execute
    def stats(self) -> dict[str, Any]:
        return {
            "metrics": self._metrics.to_dict(),
            "config": self._config.to_dict(),
        }


@logged()
@safe_execute
def register_memory_routes(api: BrainOSAPI, handler: MemoryRouteHandler | None = None) -> MemoryRouteHandler:
    h = handler or MemoryRouteHandler()
    api.get("/api/v1/memory/anchors", h.handle_get_anchors)
    api.get("/api/v1/memory/anchor", h.handle_get_anchor)
    api.post("/api/v1/memory/anchors", h.handle_create_anchor)
    api.delete("/api/v1/memory/anchors", h.handle_delete_anchor)
    api.get("/api/v1/memory/context", h.handle_get_context)
    api.post("/api/v1/memory/context", h.handle_update_context)
    api.post("/api/v1/memory/recall", h.handle_recall)
    api.get("/api/v1/memory/status", h.handle_get_memory_status)
    api.get("/api/v1/memory/search", h.handle_search)
    api.get("/api/v1/memory/metrics", h.handle_get_metrics)
    logger.info("Memory routes registered: 10 endpoints")
    return h
