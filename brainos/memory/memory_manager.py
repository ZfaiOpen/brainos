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
"""Memory Manager — 统一记忆管理门面（5层分层版）"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class _MemoryLayer:
    def __init__(self, name: str, capacity: int = 10000) -> None:
        self.name = name
        self.capacity = capacity
        self._store: dict[str, dict[str, Any]] = {}

    def store(self, key: str, value: dict[str, Any]) -> bool:
        entry = {"value": value, "stored_at": time.monotonic(), "access_count": 0}
        self._store[key] = entry
        if len(self._store) > self.capacity:
            oldest = min(self._store, key=lambda k: self._store[k]["stored_at"])
            del self._store[oldest]
        return True

    def retrieve(self, key: str) -> dict[str, Any] | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        entry["access_count"] += 1
        entry["last_accessed"] = time.monotonic()
        return entry["value"]

    def clear(self):
            """清空所有记忆层并同步至磁盘 (分层原子清理算法)"""
            cleared_count = 0
            try:
                # 1. 清理主存储并统计
                primary_count = len(self._store)
                self._store.clear()
                cleared_count += primary_count

                # 2. 清理分层记忆池 (L4 分层架构联动)
                layers = getattr(self, '_layers', {})
                for layer_name, layer in layers.items():
                    try:
                        if hasattr(layer, 'clear'):
                            cleared_count += layer.clear()
                    except Exception as _layer_exc:
                        logger.warning(
                            "MemoryManager.clear: Failed to clear layer '%s': %s",
                            layer_name,
                            _layer_exc,
                            exc_info=False
                        )

                # 3. 持久化清理状态 (保证内存与磁盘一致性)
                if hasattr(self, '_save'):
                    self._save()

                logger.info(
                    "MemoryManager.clear: Successfully cleared %d entries across all layers.",
                    cleared_count
                )
                return cleared_count

            except Exception as _exc:
                logger.error(
                    "MemoryManager.clear: Catastrophic failure during memory clearance: %s",
                    _exc,
                    exc_info=True
                )
                return cleared_count


    def size(self) -> int:
        return len(self._store)

    def keys(self) -> list[str]:
        return list(self._store.keys())

    def search(self, query: str, limit: int = 10) -> list[dict]:
        results = []
        query_lower = query.lower()
        for k, entry in self._store.items():
            v_str = str(entry["value"]).lower()
            if query_lower in k.lower() or query_lower in v_str:
                results.append({"key": k, "value": entry["value"], "access_count": entry["access_count"]})
                if len(results) >= limit:
                    break
        return results


class MemoryManager:
    _instance: MemoryManager | None = None

    def __init__(self, data_dir: str | Path | None = None) -> None:
        if data_dir is None:
            try:
                from brainos.core.paths import paths

                self._data_dir = paths.data_dir
            except Exception as _exc:
                self._data_dir = Path(__file__).resolve().parent.parent.parent / "data"
        else:
            self._data_dir = Path(data_dir)

        self._memory_file = self._data_dir / "memory_store.json"
        self._store: dict[str, Any] = {}

        self.sensory = _MemoryLayer("sensory", capacity=1000)
        self.working = _MemoryLayer("working", capacity=5000)
        self.episodic = _MemoryLayer("episodic", capacity=20000)
        self.semantic = _MemoryLayer("semantic", capacity=50000)
        self.metacognitive = _MemoryLayer("metacognitive", capacity=10000)

        self._sensory = self.sensory
        self._working = self.working
        self._episodic = self.episodic
        self._semantic = self.semantic
        self._metacognitive = self.metacognitive

        self._layers = {
            "sensory": self.sensory,
            "working": self.working,
            "episodic": self.episodic,
            "semantic": self.semantic,
            "metacognitive": self.metacognitive,
        }

        self._load()

    @classmethod
    def get_instance(cls) -> MemoryManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load(self) -> None:
        if self._memory_file.exists():
            try:
                with open(self._memory_file, "r", encoding="utf-8") as f:
                    self._store = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._store = {}
        else:
            self._store = {}

    def _save(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        with open(self._memory_file, "w", encoding="utf-8") as f:
            json.dump(self._store, f, ensure_ascii=False, indent=2)

    def store_to_layer(self, layer_name: str, key: str, value: dict[str, Any]) -> bool:
        layer = self._layers.get(layer_name)
        if layer is None:
            logger.warning("Unknown layer: %s", layer_name)
            return False
        return layer.store(key, value)

    def retrieve_from_layer(self, layer_name: str, key: str) -> dict[str, Any] | None:
        layer = self._layers.get(layer_name)
        if layer is None:
            return None
        return layer.retrieve(key)

    def consolidate(self, from_layer: str, to_layer: str, key: str) -> bool:
        src = self._layers.get(from_layer)
        dst = self._layers.get(to_layer)
        if src is None or dst is None:
            return False
        entry = src.retrieve(key)
        if entry is None:
            return False
        dst.store(key, entry)
        return True

    def get(self, key: str, default: Any = None) -> Any:
        return self._store.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._store[key] = value
        self._save()

    def delete(self, key: str) -> bool:
        if key in self._store:
            del self._store[key]
            self._save()
            return True
        return False

    def list_keys(self, prefix: str = "") -> list[str]:
        if prefix:
            return [k for k in self._store if k.startswith(prefix)]
        return list(self._store.keys())

    def search(self, query: str, limit: int = 10) -> list[dict]:
        results = []
        query_lower = query.lower()
        for k, v in self._store.items():
            if query_lower in k.lower() or query_lower in str(v).lower():
                results.append({"key": k, "value": v})
                if len(results) >= limit:
                    break
        return results

    def get_stats(self) -> dict[str, Any]:
        layer_stats = {}
        for name, layer in self._layers.items():
            layer_stats[name] = {"size": layer.size(), "capacity": layer.capacity}
        return {
            "total_keys": len(self._store),
            "data_dir": str(self._data_dir),
            "memory_file_size": self._memory_file.stat().st_size if self._memory_file.exists() else 0,
            "layers": layer_stats,
        }


_memory_manager: MemoryManager | None = None


def get_memory_manager() -> MemoryManager:
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager.get_instance()
    return _memory_manager
