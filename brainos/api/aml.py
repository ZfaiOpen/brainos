# Copyright 2026 zfai-open contributors
#
# Copyright (C) 2026 Zfai Open
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See the License for the details in the LICENSE file.
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""brainos/api/aml.py — AML wire contract for the memory surface (open baseline).

Endpoints (registered by :func:`register_aml_routes`):

  POST /add    {"request_id", "user_id", "session_id",
                "messages": [{"role", "timestamp", "content"}]}
               → 200 {"success": true, "request_id", "user_id", "session_id"}
               with the three IDs echoed byte-for-byte. ``request_id`` is
               idempotent: replaying it returns the stored response and never
               double-stores. Unknown extra fields (metadata / app_id /
               agent_id / async_mode / …) are deliberately ignored. Multimodal
               content degrades honestly: text parts are joined, image parts
               become an ``[image]`` marker, unknown part types are skipped.
  POST /search {"query", "user_id", "top_k" (, "options": [...])}
               → 200 {"data": [{"id", "content", "created_at"}]}
               Evidence only — zero answer generation. At most ``top_k``
               items, ``[]`` when nothing matches. ``options`` is ignored.
  POST /search/stream  same body as /search, Server-Sent-Events response:
               ``meta`` → ``evidence``* → ``summary`` — evidence items always
               precede the summary event.
  GET  /health exempt from auth.

Auth: when ``BRAINOS_API_KEY`` (or the ``api_key`` constructor argument) is
set, /add, /search and /search/stream require ``Authorization: Token <KEY>``.
With no key configured, auth is disabled — the open-baseline default for
local development; set the env var in production.

Failure semantics are honest: malformed input → 4xx, internal errors → 5xx,
never a fabricated 200. Streaming temporal rules (verified by the suite):
adds are saved strictly in call order, a search never sees an add that has
not been committed, users are fully isolated, and each request commits as an
independent transaction (a malformed add never poisons other requests).
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from brainos.api.middleware import Request, Response
from brainos.memory.recall import RecallEngine, RecallMode
from brainos.memory.store import MemoryStore
from brainos.memory.types import MemoryEntry, MemoryType
from brainos.observability.auto_log import logged

logger = logging.getLogger("brainos.api.aml")

_MAX_TOP_K = 100
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
_IMAGE_MARKER = "[image]"


class AMLBadRequest(Exception):
    """Malformed request — maps to HTTP 4xx."""


class AMLInternalError(Exception):
    """Internal failure — maps to HTTP 5xx (honest failure, no fake 200)."""


# ── payload helpers (pure functions) ────────────────────────────────────────


def content_to_text(content: Any) -> tuple[str, int]:
    """AML ``content`` (str | list[part]) → (text, image_count).

    Text parts are joined with newlines, image parts degrade to an
    ``[image]`` marker, unknown part types are skipped (lenient parsing).
    """
    if content is None:
        return "", 0
    if isinstance(content, str):
        return content, 0
    if isinstance(content, list):
        parts: list[str] = []
        n_images = 0
        for part in content:
            if not isinstance(part, dict):
                continue
            kind = part.get("type")
            if kind == "text" and isinstance(part.get("text"), str):
                parts.append(part["text"])
            elif kind == "image_url":
                n_images += 1
            # unknown part type: skip (lenient)
        if n_images:
            parts.append(_IMAGE_MARKER if n_images == 1 else f"{_IMAGE_MARKER}x{n_images}")
        return "\n".join(p for p in parts if p), n_images
    return str(content), 0


def timestamp_to_epoch(ts: Any) -> float:
    """Message timestamp (seconds or milliseconds epoch) → seconds; else now."""
    try:
        value = float(ts)
    except (TypeError, ValueError):
        return time.time()
    if value > 1e11:  # milliseconds
        value /= 1000.0
    return value


def format_dt(epoch: float) -> str:
    """Epoch seconds → UTC ISO string (wire format of ``created_at``)."""
    try:
        return datetime.fromtimestamp(float(epoch), tz=timezone.utc).strftime(_DATE_FORMAT)
    except (TypeError, ValueError, OSError, OverflowError):
        return datetime.now(tz=timezone.utc).strftime(_DATE_FORMAT)


# ── idempotency ledger ──────────────────────────────────────────────────────


class AddLedger:
    """request_id → stored response. SQLite (WAL) when a db path is given,
    else in-memory. Guarantees: a replayed ``request_id`` returns the original
    response and never re-stores entries."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._memory: dict[str, str] = {}
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        if db_path:
            path = Path(db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS aml_ledger (
                       request_id TEXT PRIMARY KEY,
                       response_json TEXT NOT NULL,
                       created_ms INTEGER NOT NULL)"""
            )
            self._conn.commit()

    def get(self, request_id: str) -> dict[str, Any] | None:
        with self._lock:
            if self._conn is not None:
                row = self._conn.execute(
                    "SELECT response_json FROM aml_ledger WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
                raw = row[0] if row else None
            else:
                raw = self._memory.get(request_id)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def put(self, request_id: str, response: dict[str, Any]) -> bool:
        """True when this call performed the first write for ``request_id``."""
        payload = json.dumps(response, ensure_ascii=False)
        with self._lock:
            if self._conn is not None:
                cur = self._conn.execute(
                    "INSERT OR IGNORE INTO aml_ledger VALUES (?, ?, ?)",
                    (request_id, payload, int(time.time() * 1000)),
                )
                self._conn.commit()
                return cur.rowcount > 0
            if request_id in self._memory:
                return False
            self._memory[request_id] = payload
            return True

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


# ── service (transport-neutral core; HTTP layers are thin adapters) ─────────


class AMLService:
    def __init__(
        self,
        store: MemoryStore | None = None,
        db_path: str | Path | None = None,
        api_key: str | None = None,
    ) -> None:
        self._store = store or MemoryStore(db_path=db_path)
        self._recall = RecallEngine(self._store)
        self._ledger = AddLedger(db_path)
        key = api_key if api_key is not None else os.environ.get("BRAINOS_API_KEY", "")
        self._api_key = str(key)
        self._commit_lock = threading.Lock()

    # exposed for wiring (route handlers / hosts) — single source of truth
    @property
    def store(self) -> MemoryStore:
        return self._store

    @property
    def recall_engine(self) -> RecallEngine:
        return self._recall

    # ── auth ────────────────────────────────────────────────────────────

    def check_auth(self, auth_header: str | None) -> bool:
        """``Authorization: Token <KEY>``; disabled when no key configured."""
        if not self._api_key:
            return True
        if not auth_header:
            return False
        scheme, _, token = auth_header.strip().partition(" ")
        return scheme.lower() == "token" and hmac.compare_digest(token.strip(), self._api_key)

    # ── health ──────────────────────────────────────────────────────────

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "brainos-aml",
            "version": "0.9.1",
            "entries": self._store.count().get("total", 0),
            "pid": os.getpid(),
            "memory": {
                "store_active": True,
                "routes": ["POST /add", "POST /search", "POST /search/stream"],
                "recall": "open baseline: fixed-strategy multi-channel",
            },
        }

    # ── add ─────────────────────────────────────────────────────────────

    def add(self, payload: Any) -> tuple[int, dict[str, Any]]:
        rid, uid, sid = self._validate_add(payload)
        stored = self._ledger.get(rid)
        if stored is not None:
            return 200, stored

        entries = self._build_entries(payload)  # validate-then-commit: parse everything first

        with self._commit_lock:
            stored = self._ledger.get(rid)  # re-check: concurrent replay of same rid
            if stored is not None:
                return 200, stored
            stored_ids: list[str] = []
            try:
                for entry in entries:
                    self._store.store(entry)
                    stored_ids.append(entry.id)
                response = {"success": True, "request_id": rid, "user_id": uid, "session_id": sid}
                first = self._ledger.put(rid, response)
            except Exception as exc:  # rollback this request's writes — independent transactions
                for mid in stored_ids:
                    self._store.delete(mid)
                raise AMLInternalError(f"add failed: {type(exc).__name__}") from exc
            if not first:
                stored = self._ledger.get(rid)
                if stored is not None:
                    return 200, stored

        # response self-check: never return a fabricated success
        if not (
            isinstance(response, dict)
            and response.get("success") is True
            and response.get("request_id") == rid
            and response.get("user_id") == uid
            and response.get("session_id") == sid
        ):
            raise AMLInternalError("response self-check failed")
        return 200, response

    @staticmethod
    def _validate_add(payload: Any) -> tuple[str, str, str]:
        if not isinstance(payload, dict):
            raise AMLBadRequest("body must be a JSON object")
        rid = payload.get("request_id")
        uid = payload.get("user_id")
        sid = payload.get("session_id")
        if not isinstance(rid, str) or not rid:
            raise AMLBadRequest("request_id (non-empty string) required")
        if not isinstance(uid, str) or not isinstance(sid, str):
            raise AMLBadRequest("user_id/session_id (strings) required")
        return rid, uid, sid

    def _build_entries(self, payload: dict[str, Any]) -> list[MemoryEntry]:
        rid = str(payload["request_id"])
        uid = str(payload["user_id"])
        sid = str(payload["session_id"])
        messages = payload.get("messages")
        if not isinstance(messages, list):
            raise AMLBadRequest("messages must be a list")
        entries: list[MemoryEntry] = []
        for i, message in enumerate(messages):
            if not isinstance(message, dict):
                raise AMLBadRequest(f"messages[{i}] must be an object")
            text, n_images = content_to_text(message.get("content"))
            if not text:
                continue  # empty/unknown-only message: nothing to remember
            epoch = timestamp_to_epoch(message.get("timestamp"))
            entries.append(
                MemoryEntry(
                    content=text,
                    memory_type=MemoryType.CONVERSATION,
                    created_at=epoch,
                    accessed_at=epoch,
                    source="aml",
                    metadata={
                        "user_id": uid,
                        "session_id": sid,
                        "request_id": rid,
                        "message_index": i,
                        "role": str(message.get("role", "user")),
                        "message_dt": format_dt(epoch),
                        "images": n_images,
                    },
                )
            )
        return entries

    # ── search ──────────────────────────────────────────────────────────

    def validate_search(self, payload: Any) -> str | None:
        """Returns an error message for a malformed /search body, else None."""
        if not isinstance(payload, dict):
            return "body must be a JSON object"
        query = payload.get("query")
        uid = payload.get("user_id")
        if not isinstance(query, str) or not query:
            return "query (non-empty string) required"
        if not isinstance(uid, str) or not uid:
            return "user_id (non-empty string) required"
        if "top_k" in payload:
            try:
                int(payload.get("top_k"))
            except (TypeError, ValueError):
                return "top_k must be an integer"
        return None

    def search(self, payload: Any) -> tuple[int, dict[str, Any]]:
        error = self.validate_search(payload)
        if error:
            raise AMLBadRequest(error)
        items = self._search_items(payload)
        return 200, {"data": items}

    def _search_items(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        query = str(payload["query"])
        uid = str(payload["user_id"])
        try:
            top_k = int(payload.get("top_k") or _MAX_TOP_K)
        except (TypeError, ValueError):
            raise AMLBadRequest("top_k must be an integer") from None
        top_k = max(1, min(top_k, _MAX_TOP_K))
        results = self._recall.recall(
            query,
            mode=RecallMode.HYBRID,
            limit=top_k,
            scope={"user_id": uid},
        )
        items = [
            {
                "id": r.entry.id,
                "content": r.entry.content,
                "created_at": format_dt(r.entry.created_at),
            }
            for r in results
            if r.entry.content
        ]
        # response self-check: id/content non-empty, count ≤ top_k strictly
        if len(items) > top_k or any(not item["id"] or not item["content"] for item in items):
            raise AMLInternalError("response self-check failed")
        return items

    # ── streaming (SSE event stream: meta → evidence* → summary) ────────

    def search_events(self, payload: Any) -> Iterator[tuple[str, dict[str, Any]]]:
        error = self.validate_search(payload)
        if error:
            yield "error", {"error": error, "status": 400}
            return
        query = str(payload["query"])
        uid = str(payload["user_id"])
        try:
            top_k = max(1, min(int(payload.get("top_k") or _MAX_TOP_K), _MAX_TOP_K))
        except (TypeError, ValueError):
            top_k = _MAX_TOP_K
        yield "meta", {"query": query, "user_id": uid, "top_k": top_k}
        items = self._search_items(payload)
        for item in items:
            yield "evidence", item
        yield "summary", {"count": len(items), "top_k": top_k}


def format_sse(event: str, data: dict[str, Any]) -> str:
    """One SSE frame."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ── route registration (brainos api style) ──────────────────────────────────


def _header(request: Request, name: str) -> str | None:
    """Case-insensitive header lookup (HTTP header names are case-insensitive;
    ASGI transports deliver lower-cased keys)."""
    lowered = name.lower()
    for key, value in request.headers.items():
        if str(key).lower() == lowered:
            return str(value)
    return None


class AMLRouteHandler:
    """Async handlers adapting the AMLService onto the brainos Request/Response
    pipeline (the same handlers serve both api.run and api.brainos_serve)."""

    def __init__(self, service: AMLService) -> None:
        self._service = service

    @property
    def service(self) -> AMLService:
        return self._service

    @logged()
    async def handle_health(self, request: Request) -> Response:
        return Response.ok(self._service.health(), request.request_id)

    @logged()
    async def handle_add(self, request: Request) -> Response:
        if not self._service.check_auth(_header(request, "Authorization")):
            return Response.unauthorized("Unauthorized", request.request_id)
        try:
            status, body = self._service.add(request.body)
        except AMLBadRequest as exc:
            return Response.bad_request(str(exc), request.request_id)
        except AMLInternalError as exc:
            return Response.internal_error(str(exc), request.request_id)
        response = Response.ok(body, request.request_id) if status == 200 else Response(status_code=status, body=body)
        return response

    @logged()
    async def handle_search(self, request: Request) -> Response:
        if not self._service.check_auth(_header(request, "Authorization")):
            return Response.unauthorized("Unauthorized", request.request_id)
        try:
            status, body = self._service.search(request.body)
        except AMLBadRequest as exc:
            return Response.bad_request(str(exc), request.request_id)
        except AMLInternalError as exc:
            return Response.internal_error(str(exc), request.request_id)
        return Response.ok(body, request.request_id)

    @logged()
    async def handle_search_stream(self, request: Request) -> Response:
        """Non-streaming twin: returns the full event list as JSON so the
        event sequence is testable through the plain router. The FastAPI host
        streams the same ``search_events`` generator as real SSE."""
        if not self._service.check_auth(_header(request, "Authorization")):
            return Response.unauthorized("Unauthorized", request.request_id)
        events: list[dict[str, Any]] = []
        for kind, data in self._service.search_events(request.body):
            if kind == "error":
                return Response.bad_request(str(data.get("error", "bad request")), request.request_id)
            events.append({"event": kind, **data})
        return Response.ok({"events": events}, request.request_id)


@logged()
def register_aml_routes(api: Any, service: AMLService | None = None) -> AMLRouteHandler:
    """Register the AML contract endpoints on a BrainOSAPI instance."""
    handler = AMLRouteHandler(service or AMLService())
    api.get("/health", handler.handle_health)
    api.post("/add", handler.handle_add)
    api.post("/search", handler.handle_search)
    api.post("/search/stream", handler.handle_search_stream)
    logger.info("AML contract routes registered: /health /add /search /search/stream")
    return handler


@logged()
def wire_memory_surface(
    api: Any,
    service: AMLService | None = None,
    db_path: str | Path | None = None,
) -> tuple[Any, AMLService]:
    """One-stop wiring of the open-core memory surface onto an API:
    the AML contract endpoints plus the legacy memory route handlers,
    both backed by the same store and recall engine."""
    svc = service or AMLService(db_path=db_path)
    aml_handler = register_aml_routes(api, svc)
    from brainos.api.route_handlers.memory import register_memory_routes

    memory_handler = register_memory_routes(api)
    memory_handler.set_store(svc.store)
    memory_handler.set_recall_engine(svc.recall_engine)
    logger.info("Memory surface wired: AML contract + memory routes on one store")
    return aml_handler, svc
