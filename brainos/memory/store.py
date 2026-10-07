# Copyright 2026 zfai-open contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import annotations
from brainos.kernel.async_compat import async_compatible
from brainos.kernel.safe_execute import safe_execute

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from brainos.kernel.config import atomic_json_write, safe_json_read
from brainos.observability.auto_log import logged
from brainos.memory.types import MemoryTier, MemoryType

logger = logging.getLogger("brainos.memory.store")


_TIER_ORDER = [MemoryTier.ARCHIVE, MemoryTier.COLD, MemoryTier.WARM, MemoryTier.HOT, MemoryTier.CRITICAL]


from brainos.memory.types import MemoryEntry  # noqa: E402


class MemoryStore:
    def __init__(
        self,
        db_path: str | Path | None = None,
        max_hot: int = 100,
        max_warm: int = 1000,
        max_cold: int = 10000,
    ) -> None:
        self._store: dict[str, MemoryEntry] = {}
        self._lock = threading.RLock()
        self._db_path = Path(db_path) if db_path else None
        self._max_hot = max_hot
        self._max_warm = max_warm
        self._max_cold = max_cold
        self._index_tags: dict[str, set[str]] = {}
        self._index_type: dict[MemoryType, set[str]] = {}
        self._conn: sqlite3.Connection | None = None
        if self._db_path:
            self._init_db()
            self._load_from_db()

    def _init_db(self) -> None:
        if self._db_path is None:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                tier TEXT NOT NULL,
                importance REAL DEFAULT 0.5,
                confidence REAL DEFAULT 1.0,
                created_at REAL,
                accessed_at REAL,
                access_count INTEGER DEFAULT 0,
                tags TEXT DEFAULT '[]',
                metadata TEXT DEFAULT '{}'
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_type ON memories(memory_type)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tier ON memories(tier)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_importance ON memories(importance)
        """)
        self._conn.commit()

    @logged()
    @safe_execute
    def store(self, entry: MemoryEntry) -> str:
        with self._lock:
            self._store[entry.id] = entry
            self._update_indices(entry.id, entry)
            self._auto_tier(entry.id)
            self._persist_entry(entry)
            logger.info("Stored memory %s type=%s tier=%s", entry.id, getattr(entry.memory_type, "value", entry.memory_type), getattr(entry.tier, "value", entry.tier))
            return entry.id

    @logged()
    @safe_execute
    def retrieve(self, memory_id):
        pass


    @logged()
    @safe_execute
    def search(self, query: str, limit: int = 10) -> list[MemoryEntry]:
        with self._lock:
            q_lower = query.lower()
            results = [e for e in self._store.values() if q_lower in e.content.lower()]
            results.sort(key=lambda e: e.importance, reverse=True)
            return results[:limit]

    @logged()
    @async_compatible
    def search_by_tag(self, tag: str, limit: int = 10) -> list[MemoryEntry]:
        with self._lock:
            ids = self._index_tags.get(tag.lower(), set())
            results = [self._store[mid] for mid in ids if mid in self._store]
            results.sort(key=lambda e: e.importance, reverse=True)
            return results[:limit]

    @logged()
    @async_compatible
    def search_by_type(self, memory_type: MemoryType, limit: int = 10) -> list[MemoryEntry]:
        with self._lock:
            ids = self._index_type.get(memory_type, set())
            results = [self._store[mid] for mid in ids if mid in self._store]
            results.sort(key=lambda e: e.accessed_at, reverse=True)
            return results[:limit]

    @logged()
    @safe_execute
    def delete(self, memory_id: str) -> bool:
        with self._lock:
            entry = self._store.pop(memory_id, None)
            if entry is None:
                return False
            self._remove_indices(memory_id, entry)
            self._delete_entry(memory_id)
            return True

    @logged()
    @safe_execute
    def update(self, memory_id: str, **kwargs: Any) -> MemoryEntry | None:
        with self._lock:
            entry = self._store.get(memory_id)
            if entry is None:
                return None
            needs_reindex = {"tags", "memory_type"} & kwargs.keys()
            if needs_reindex:
                self._remove_indices(memory_id, entry)
            for k, v in kwargs.items():
                if hasattr(entry, k):
                    setattr(entry, k, v)
            if needs_reindex:
                self._update_indices(memory_id, entry)
            self._persist_entry(entry)
            return entry

    @logged()
    @safe_execute
    def count(self) -> dict[str, int]:
        with self._lock:
            counts: dict[str, int] = {"total": len(self._store)}
            for tier in MemoryTier:
                counts[tier.value] = sum(1 for e in self._store.values() if e.tier == tier)
            return counts

    @logged()
    @safe_execute
    def consolidate(
        self,
        threshold_access: int = 5,
        threshold_time: float = 3600.0,
    ) -> int:
        with self._lock:
            promoted = 0
            now = time.time()
            for entry in list(self._store.values()):
                if entry.access_count >= threshold_access:
                    if entry.promote():
                        promoted += 1
                        self._persist_entry(entry)
                elif (now - entry.accessed_at) > threshold_time:
                    entry.demote()
                    self._persist_entry(entry)
            return promoted

    @logged()
    @safe_execute
    def backup(self, path: str | Path) -> int:
        p = Path(path)
        with self._lock:
            data = {mid: entry.to_dict() for mid, entry in self._store.items()}
        atomic_json_write(p, data)
        return len(data)

    @logged()
    @safe_execute
    def restore(self, path: str | Path) -> int:
        p = Path(path)
        data = safe_json_read(p)
        with self._lock:
            self._store.clear()
            self._index_tags.clear()
            self._index_type.clear()
            for mid, entry_data in data.items():
                entry = MemoryEntry.from_dict(entry_data)
                self._store[mid] = entry
                self._update_indices(mid, entry)
        return len(self._store)

    @logged()
    @safe_execute
    def flush(self) -> int:
        if self._conn is None:
            return 0
        with self._lock:
            count = 0
            for entry in self._store.values():
                self._persist_entry(entry)
                count += 1
            return count

    @logged()
    @safe_execute
    def list_all(self) -> list[MemoryEntry]:
        with self._lock:
            return list(self._store.values())

    @logged()
    @safe_execute
    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _persist_entry(self, entry: MemoryEntry) -> None:
        if self._conn is None:
            return
        try:
            self._conn.execute(
                """INSERT OR REPLACE INTO memories
                   (id, content, memory_type, tier, importance, confidence,
                    created_at, accessed_at, access_count, tags, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.id,
                    entry.content,
                    getattr(entry.memory_type, "value", entry.memory_type),
                    getattr(entry.tier, "value", entry.tier),
                    entry.importance,
                    entry.confidence,
                    entry.created_at,
                    entry.accessed_at,
                    entry.access_count,
                    json.dumps(entry.tags),
                    json.dumps(entry.metadata),
                ),
            )
            self._conn.commit()
        except Exception as _exc:
            logger.warning("Failed to persist memory %s: %s", entry.id)

    def _delete_entry(self, memory_id: str) -> None:
        if self._conn is None:
            return
        try:
            self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            self._conn.commit()
        except Exception as _exc:
            logger.warning("Failed to delete memory %s: %s", memory_id)

    def _load_from_db(self) -> None:
        if self._conn is None:
            return
        try:
            cursor = self._conn.execute("SELECT * FROM memories")
            for row in cursor.fetchall():
                entry = MemoryEntry(
                    id=row[0],
                    content=row[1],
                    memory_type=MemoryType(row[2]),
                    tier=MemoryTier(row[3]),
                    importance=row[4],
                    confidence=row[5],
                    created_at=row[6],
                    accessed_at=row[7],
                    access_count=row[8],
                    tags=json.loads(row[9]),
                    metadata=json.loads(row[10]),
                )
                self._store[entry.id] = entry
                self._update_indices(entry.id, entry)
            logger.info("Loaded %d memories from DB", len(self._store))
        except Exception as _exc:
            logger.warning("Failed to load memories from DB: %s")

    def _update_indices(self, memory_id: str, entry: MemoryEntry) -> None:
        for tag in entry.tags:
            self._index_tags.setdefault(tag.lower(), set()).add(memory_id)
        self._index_type.setdefault(entry.memory_type, set()).add(memory_id)

    def _remove_indices(self, memory_id: str, entry: MemoryEntry) -> None:
        for tag in entry.tags:
            ids = self._index_tags.get(tag.lower())
            if ids:
                ids.discard(memory_id)
        ids = self._index_type.get(entry.memory_type)
        if ids:
            ids.discard(memory_id)

    def _auto_tier(self, memory_id: str) -> None:
        entry = self._store.get(memory_id)
        if not entry:
            return
        if entry.tier == MemoryTier.HOT:
            hot_count = sum(1 for e in self._store.values() if e.tier == MemoryTier.HOT)
            if hot_count > self._max_hot:
                coldest = min(
                    (e for e in self._store.values() if e.tier == MemoryTier.HOT),
                    key=lambda e: e.accessed_at,
                )
                coldest.demote()
                self._persist_entry(coldest)
        elif entry.tier == MemoryTier.WARM:
            warm_count = sum(1 for e in self._store.values() if e.tier == MemoryTier.WARM)
            if warm_count > self._max_warm:
                coldest = min(
                    (e for e in self._store.values() if e.tier == MemoryTier.WARM),
                    key=lambda e: e.accessed_at,
                )
                coldest.demote()
                self._persist_entry(coldest)
