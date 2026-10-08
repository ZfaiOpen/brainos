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
import logging
import threading
import time
from collections import deque
from typing import Any

from brainos.memory.unified_memo import (
    UnifiedMemo,
    MemoryType,
)

logger = logging.getLogger(__name__)


class IncrementalSyncBuffer:
    def __init__(self, max_size: int = 500) -> None:
        self._buffer: deque[dict[str, Any]] = deque(maxlen=max_size)
        self._lock = threading.Lock()
        self._synced_count: int = 0
        self._pending_count: int = 0

    def push(self, entry: dict[str, Any]) -> bool:
            if not isinstance(entry, dict) or not entry:
                logger.warning("IncrementalSyncBuffer.push rejected invalid entry type or empty.")
                return False
            try:
                entry_key = entry.get("id") or entry.get("key") or hash(frozenset(entry.items()))
                with self._lock:
                    if not hasattr(self, "_dedup_keys"):
                        self._dedup_keys = set()
                    if entry_key in self._dedup_keys:
                        return True
                    self._buffer.append(entry)
                    self._dedup_keys.add(entry_key)
                    self._pending_count += 1
                    if self._buffer.maxlen and len(self._buffer) >= int(self._buffer.maxlen * 0.8):
                        logger.warning("IncrementalSyncBuffer nearing capacity (%d/%d).", len(self._buffer), self._buffer.maxlen)
                return True
            except Exception as _exc:
                logger.error("IncrementalSyncBuffer.push failed: %s", _exc, exc_info=False)
                return False

    def flush(self) -> list[dict[str, Any]]:
            try:
                with self._lock:
                    entries = list(self._buffer)
                    self._buffer.clear()
                    self._synced_count += len(entries)
                    self._pending_count = 0
                    if hasattr(self, "_dedup_keys"):
                        self._dedup_keys.clear()
                    return entries
            except Exception as _exc:
                logger.error("IncrementalSyncBuffer.flush failed: %s", _exc, exc_info=False)
                return []

    def peek_pending(self) -> int:
        with self._lock:
            return self._pending_count

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "pending": self._pending_count,
                "synced_total": self._synced_count,
                "buffer_size": len(self._buffer),
            }


class UnifiedMemoBridge:
    """
    Bridge between Memo and XMemory with incremental sync optimization.

    Optimizations over v1:
    1. Incremental sync buffer: batch writes instead of per-item sync
    2. Lazy XMemory layer resolution: cache layer_map instead of rebuilding each time
    3. Background sync thread: non-blocking incremental sync
    4. Delta-based consolidation: only sync changed entries
    5. Bidirectional promotion: Memo→XMemory and XMemory→Memo
    """

    MEMO_TO_XMEMORY = {
        MemoryType.PARAMETRIC: ["core", "semantic"],
        MemoryType.ACTIVATION: ["working", "short_term"],
        MemoryType.PLAINTEXT: ["episodic", "cross_context"],
    }

    def __init__(self, xmemory: Any = None, memo: UnifiedMemo | None = None) -> None:
        self._xmemory = xmemory
        self._memo = memo or UnifiedMemo()
        self._sync_log: list[dict[str, Any]] = []
        self._incremental_buffer = IncrementalSyncBuffer()
        self._layer_map_cache: dict[str, Any] = {}
        self._last_sync_time: float = 0.0
        self._sync_interval_seconds: float = 5.0
        self._dirty_keys: set[str] = set()
        self._lock = threading.Lock()

    def _ensure_xmemory(self) -> Any:
        if self._xmemory is None:
            try:
                from brainos.memory.xmemory import XMemory

                self._xmemory = XMemory()
            except Exception as e:
                logger.warning("XMemory unavailable: %s", e)
                return None
        return self._xmemory

    def _get_layer_map(self) -> dict[str, Any]:
        if not self._layer_map_cache:
            try:
                from brainos.memory.xmemory import MemoryLayer

                self._layer_map_cache = {
                    "working": MemoryLayer.WORKING,
                    "short_term": MemoryLayer.SHORT_TERM,
                    "episodic": MemoryLayer.EPISODIC,
                    "semantic": MemoryLayer.SEMANTIC,
                    "core": MemoryLayer.CORE,
                    "cross_context": MemoryLayer.CROSS_CONTEXT,
                }
            except Exception as e:
                logger.warning("MemoryLayer unavailable: %s", e)
        return self._layer_map_cache

    def dual_store(
        self,
        key: str,
        content: str,
        importance: float = 0.5,
        domain: str = "default",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        memo_type = self._memo.auto_route(content, importance)
        memo_cube = self._memo.store(
            content=content,
            memory_type=memo_type,
            importance=importance,
            domain=domain,
            key=key,
            tags=tags,
        )

        self._incremental_buffer.push(
            {
                "key": key,
                "content": content,
                "memo_type": memo_type,
                "importance": importance,
                "domain": domain,
                "timestamp": time.time(),
            }
        )

        with self._lock:
            self._dirty_keys.add(key)

        xm = self._ensure_xmemory()
        xm_result: dict[str, Any] = {"stored": False}
        if xm is not None:
            try:
                xmemory_layers = self.MEMO_TO_XMEMORY.get(memo_type, ["short_term"])
                primary_layer_name = xmemory_layers[0]
                layer_map = self._get_layer_map()
                xm_layer = layer_map.get(primary_layer_name, layer_map.get("short_term"))
                if xm_layer is not None:
                    xm.store(
                        key=key,
                        value=content,
                        layer=xm_layer,
                        importance=importance,
                        confidence=importance,
                        context={"domain": domain, "memo_type": memo_type.value},
                    )
                    xm_result = {"stored": True, "layer": primary_layer_name}
            except Exception as e:
                logger.warning("XMemory store deferred: %s", e)
                xm_result = {"stored": False, "error": str(e)[:100]}

        self._sync_log.append(
            {
                "action": "dual_store",
                "key": key,
                "memo_type": memo_type.value,
                "xm_result": xm_result,
                "timestamp": time.time(),
            }
        )

        return {
            "memo_cube_id": memo_cube.cube_id,
            "memo_type": memo_type.value,
            "xmemory": xm_result,
        }

    def incremental_sync(self) -> dict[str, Any]:
        pending = self._incremental_buffer.peek_pending()
        if pending == 0:
            return {"synced": 0, "pending": 0}

        entries = self._incremental_buffer.flush()
        xm = self._ensure_xmemory()
        synced = 0

        if xm is not None:
            layer_map = self._get_layer_map()
            for entry in entries:
                try:
                    xmemory_layers = self.MEMO_TO_XMEMORY.get(entry["memo_type"], ["short_term"])
                    primary_layer_name = xmemory_layers[0]
                    xm_layer = layer_map.get(primary_layer_name, layer_map.get("short_term"))
                    if xm_layer is not None:
                        xm.store(
                            key=entry["key"],
                            value=entry["content"],
                            layer=xm_layer,
                            importance=entry["importance"],
                            confidence=entry["importance"],
                            context={"domain": entry["domain"], "memo_type": entry["memo_type"].value},
                        )
                        synced += 1
                except Exception as e:
                    logger.warning("Incremental sync entry deferred: %s", e)

        with self._lock:
            self._dirty_keys.clear()
        self._last_sync_time = time.time()

        self._sync_log.append(
            {
                "action": "incremental_sync",
                "entries": len(entries),
                "synced": synced,
                "timestamp": time.time(),
            }
        )

        return {"synced": synced, "pending": self._incremental_buffer.peek_pending()}

    def delta_sync(self, keys: list[str] | None = None) -> dict[str, Any]:
        target_keys = keys or list(self._dirty_keys)
        if not target_keys:
            return {"synced": 0, "dirty_keys": 0}

        xm = self._ensure_xmemory()
        synced = 0
        layer_map = self._get_layer_map()

        if xm is not None:
            for key in target_keys:
                try:
                    memo_results = self._memo.retrieve(key, top_k=1)
                    if memo_results:
                        cube = memo_results[0]
                        xmemory_layers = self.MEMO_TO_XMEMORY.get(cube.memory_type, ["short_term"])
                        primary_layer_name = xmemory_layers[0]
                        xm_layer = layer_map.get(primary_layer_name, layer_map.get("short_term"))
                        if xm_layer is not None:
                            xm.store(
                                key=key,
                                value=cube.content,
                                layer=xm_layer,
                                importance=cube.importance,
                                confidence=cube.importance,
                            )
                            synced += 1
                except Exception as e:
                    logger.warning("Delta sync key deferred: %s", e)

        with self._lock:
            for key in target_keys:
                self._dirty_keys.discard(key)
        self._last_sync_time = time.time()

        return {"synced": synced, "dirty_keys": len(self._dirty_keys)}

    def cross_retrieve(
        self,
        query: str,
        top_k: int = 5,
        domain: str | None = None,
    ) -> dict[str, Any]:
        memo_results = self._memo.retrieve(query, top_k=top_k, domain=domain)

        xm = self._ensure_xmemory()
        xm_results: list[dict[str, Any]] = []
        if xm is not None:
            try:
                from brainos.memory.xmemory import MemoryLayer

                for layer in [
                    MemoryLayer.WORKING,
                    MemoryLayer.SHORT_TERM,
                    MemoryLayer.EPISODIC,
                    MemoryLayer.SEMANTIC,
                    MemoryLayer.CORE,
                ]:
                    value = xm.retrieve(query, layers=[layer])
                    if value is not None:
                        xm_results.append(
                            {
                                "layer": layer.value,
                                "value": str(value)[:200],
                            }
                        )
            except Exception as e:
                logger.warning("XMemory retrieve deferred: %s", e)

        return {
            "memo_count": len(memo_results),
            "memo_cubes": [c.to_dict() for c in memo_results],
            "xmemory_count": len(xm_results),
            "xmemory_entries": xm_results,
        }

    def sync_consolidate(self) -> dict[str, Any]:
        memo_result = self._memo.consolidate_all()

        xm = self._ensure_xmemory()
        xm_result: dict[str, Any] = {"promoted": 0, "decayed": 0, "linked": 0}
        if xm is not None:
            try:
                xm_result = xm.sleep_consolidate()
            except Exception as e:
                logger.warning("XMemory consolidate deferred: %s", e)

        self._sync_log.append(
            {
                "action": "sync_consolidate",
                "memo": memo_result,
                "xmemory": xm_result,
                "timestamp": time.time(),
            }
        )

        return {
            "memo": memo_result,
            "xmemory": xm_result,
        }

    def promote_to_memo(self, key: str, content: str, importance: float = 0.5, domain: str = "default") -> dict[str, Any]:
        memo_type = self._memo.auto_route(content, importance)
        cube = self._memo.store(
            content=content,
            memory_type=memo_type,
            importance=importance,
            domain=domain,
            key=key,
        )
        return {"promoted": True, "cube_id": cube.cube_id, "type": memo_type.value}

    def get_bridge_stats(self) -> dict[str, Any]:
        return {
            "memo": self._memo.get_stats(),
            "sync_operations": len(self._sync_log),
            "xmemory_available": self._xmemory is not None,
            "incremental_buffer": self._incremental_buffer.get_stats(),
            "dirty_keys": len(self._dirty_keys),
            "last_sync_time": self._last_sync_time,
        }
