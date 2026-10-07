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
from brainos.kernel.safe_execute import safe_execute

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from brainos.memory.core import CoreMemory
from brainos.memory.procedural import ProceduralMemory
from brainos.memory.short_term import ShortTermMemory
from brainos.memory.working import WorkingMemory
from brainos.observability.auto_log import logged

logger = logging.getLogger("brainos.memory.xmemory")


class MemoryLayer(Enum):
    SENSORY = "sensory"
    WORKING = "working"
    SHORT_TERM = "short_term"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    CORE = "core"
    CROSS_CONTEXT = "cross_context"
    META_COGNITIVE = "meta_cognitive"


@dataclass
class HebbianLink:
    source_key: str
    target_key: str
    strength: float = 0.1
    co_activation_count: int = 0
    last_co_activation: float = field(default_factory=time.monotonic)

    @logged()
    @safe_execute
    def strengthen(self, delta: float = 0.1) -> None:
        self.strength = min(1.0, self.strength + delta)
        self.co_activation_count += 1
        self.last_co_activation = time.monotonic()

    @logged()
    @safe_execute
    def decay(self, rate: float = 0.01) -> None:
        self.strength = max(0.0, self.strength - rate)


@dataclass
class FSRSParams:
    stability: float = 1.0
    difficulty: float = 0.3
    retrievability: float = 1.0
    last_review: float = field(default_factory=time.monotonic)
    review_count: int = 0

    @logged()
    @safe_execute
    def update(self, rating: float) -> None:
        self.review_count += 1
        self.last_review = time.monotonic()
        if rating >= 0.6:
            self.stability *= 1.0 + 0.5 * (1.0 - self.difficulty) * math.log(1.0 + self.review_count)
        else:
            self.stability *= max(0.1, 1.0 - 0.3 * self.difficulty)
        self.difficulty = max(0.0, min(1.0, self.difficulty + (0.5 - rating) * 0.1))
        elapsed = time.monotonic() - self.last_review
        self.retrievability = math.exp(-elapsed / max(0.1, self.stability))

    @logged()
    @safe_execute
    def next_interval(self) -> float:
        return self.stability * 24.0 * 3600.0


class XMemory:
    def __init__(
        self,
        working_capacity: int = 7,
        short_term_capacity: int = 50,
        procedural_capacity: int = 200,
    ) -> None:
        self.working = WorkingMemory(capacity=working_capacity)
        self.short_term = ShortTermMemory(capacity=short_term_capacity)
        self.procedural = ProceduralMemory(capacity=procedural_capacity)
        self.core = CoreMemory()
        self._hebbian_links: dict[str, list[HebbianLink]] = {}
        self._fsrs: dict[str, FSRSParams] = {}
        self._sensory_store: dict[str, dict[str, Any]] = {}
        self._meta_cognitive_store: dict[str, dict[str, Any]] = {}
        self._cross_context: dict[str, dict[str, Any]] = {}
        self._episodic_store: dict[str, dict[str, Any]] = {}
        self._semantic_store: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._disabled: bool = False

    def set_disabled(self, disabled: bool) -> None:
        self._disabled = disabled

    @logged()
    @safe_execute
    def store(self, key: str, value: Any, layer: MemoryLayer | str = MemoryLayer.SHORT_TERM, **kwargs: Any) -> bool:
        if self._disabled:
            logger.debug("store blocked: XMemory is disabled")
            return False
        if isinstance(layer, str):
            try:
                layer = MemoryLayer(layer)
            except ValueError:
                logger.error("store failed: invalid layer=%r for key=%r", layer, key)
                return False
        if layer == MemoryLayer.SENSORY:
            with self._lock:
                self._sensory_store[key] = {"value": value, "timestamp": time.monotonic(), "intensity": kwargs.get("intensity", 0.5), "modality": kwargs.get("modality", "generic")}
        elif layer == MemoryLayer.WORKING:
            self.working.store(key, value, priority=kwargs.get("priority", 0.0))
        elif layer == MemoryLayer.SHORT_TERM:
            self.short_term.store(key, value, session_id=kwargs.get("session_id", ""), importance=kwargs.get("importance", 0.5))
        elif layer == MemoryLayer.PROCEDURAL:
            self.procedural.store(key, kwargs.get("steps", []), category=kwargs.get("category", "general"))
        elif layer == MemoryLayer.CORE:
            self.core.store(key, value, immutable=kwargs.get("immutable", False), confidence=kwargs.get("confidence", 1.0))
        elif layer == MemoryLayer.CROSS_CONTEXT:
            with self._lock:
                self._cross_context[key] = {"value": value, "timestamp": time.monotonic(), **kwargs}
        elif layer == MemoryLayer.EPISODIC:
            with self._lock:
                self._episodic_store[key] = {"value": value, "timestamp": time.monotonic(), "importance": kwargs.get("importance", 0.5), "context": kwargs.get("context", {})}
        elif layer == MemoryLayer.SEMANTIC:
            with self._lock:
                self._semantic_store[key] = {"value": value, "timestamp": time.monotonic(), "confidence": kwargs.get("confidence", 1.0), "source": kwargs.get("source", "")}
        elif layer == MemoryLayer.META_COGNITIVE:
            with self._lock:
                self._meta_cognitive_store[key] = {
                    "value": value,
                    "timestamp": time.monotonic(),
                    "retrieval_count": kwargs.get("retrieval_count", 0),
                    "self_reference": kwargs.get("self_reference", False),
                }
        self._fsrs.setdefault(key, FSRSParams())
        self._update_hebbian(key)
        return True

    @logged()
    @safe_execute
    def retrieve(self, key: str, layer: MemoryLayer | str | None = None, layers: list[MemoryLayer] | None = None) -> Any | None:
        if self._disabled:
            logger.debug("retrieve blocked: XMemory is disabled")
            return None
        if layer is not None and layers is None:
            if isinstance(layer, str):
                try:
                    layer = MemoryLayer(layer)
                except ValueError:
                    logger.error("retrieve failed: invalid layer=%r", layer)
                    return None
            layers = [layer]
        search_layers = layers or [
            MemoryLayer.SENSORY,
            MemoryLayer.WORKING,
            MemoryLayer.SHORT_TERM,
            MemoryLayer.EPISODIC,
            MemoryLayer.SEMANTIC,
            MemoryLayer.CORE,
            MemoryLayer.PROCEDURAL,
            MemoryLayer.CROSS_CONTEXT,
            MemoryLayer.META_COGNITIVE,
        ]
        for layer in search_layers:
            result = self._retrieve_from_layer(key, layer)
            if result is not None:
                fsrs = self._fsrs.get(key)
                if fsrs:
                    fsrs.update(0.8)
                self._update_hebbian(key)
                return result
        fsrs = self._fsrs.get(key)
        if fsrs:
            fsrs.update(0.2)
        return None

    def _retrieve_from_layer(self, key: str, layer: MemoryLayer) -> Any | None:
        if layer == MemoryLayer.SENSORY:
            with self._lock:
                entry = self._sensory_store.get(key)
                return entry.get("value") if entry else None
        if layer == MemoryLayer.WORKING:
            return self.working.retrieve(key)
        if layer == MemoryLayer.SHORT_TERM:
            return self.short_term.retrieve(key)
        if layer == MemoryLayer.CORE:
            return self.core.retrieve(key)
        if layer == MemoryLayer.PROCEDURAL:
            proc = self.procedural.retrieve(key)
            return proc.steps if proc else None
        if layer == MemoryLayer.CROSS_CONTEXT:
            with self._lock:
                entry = self._cross_context.get(key)
                return entry.get("value") if entry else None
        if layer == MemoryLayer.EPISODIC:
            with self._lock:
                entry = self._episodic_store.get(key)
                return entry.get("value") if entry else None
        if layer == MemoryLayer.SEMANTIC:
            with self._lock:
                entry = self._semantic_store.get(key)
                return entry.get("value") if entry else None
        if layer == MemoryLayer.META_COGNITIVE:
            with self._lock:
                entry = self._meta_cognitive_store.get(key)
                if entry:
                    entry["retrieval_count"] = entry.get("retrieval_count", 0) + 1
                return entry.get("value") if entry else None
        return None

    def _update_hebbian(self, activated_key: str) -> None:
        with self._lock:
            for other_key in list(self._hebbian_links.keys()):
                if other_key != activated_key:
                    for link in self._hebbian_links[other_key]:
                        if link.target_key == activated_key:
                            link.strengthen()
            self._hebbian_links.setdefault(activated_key, [])

    @logged()
    @safe_execute
    def link(self, source_key: str, target_key: str, strength: float = 0.1) -> None:
        if self._disabled:
            logger.debug("link blocked: XMemory is disabled")
            return
        with self._lock:
            link = HebbianLink(source_key=source_key, target_key=target_key, strength=strength)
            self._hebbian_links.setdefault(source_key, []).append(link)

    @logged()
    @safe_execute
    def get_related(self, key: str, min_strength: float = 0.3) -> list[tuple[str, float]]:
        if self._disabled:
            logger.debug("get_related blocked: XMemory is disabled")
            return []
        with self._lock:
            links = self._hebbian_links.get(key, [])
            return [(lnk.target_key, lnk.strength) for lnk in links if lnk.strength >= min_strength]

    @logged()
    @safe_execute
    def sleep_consolidate(self) -> dict[str, int]:
        if self._disabled:
            logger.debug("sleep_consolidate blocked: XMemory is disabled")
            return {"promoted": 0, "decayed": 0, "linked": 0}
        stats: dict[str, int] = {"promoted": 0, "decayed": 0, "linked": 0}
        with self._lock:
            for key, links in self._hebbian_links.items():
                for link in links:
                    link.decay(rate=0.01)
                self._hebbian_links[key] = [lnk for lnk in links if lnk.strength > 0.01]
                stats["decayed"] += len(links) - len(self._hebbian_links[key])
            for key, fsrs in self._fsrs.items():
                if fsrs.retrievability < 0.3 and fsrs.review_count > 2:
                    stats["promoted"] += 1
            sensory_promote_keys: list[str] = []
            now = time.monotonic()
            for key, entry in list(self._sensory_store.items()):
                age = now - entry.get("timestamp", now)
                intensity = entry.get("intensity", 0.5)
                if age > 60.0 and intensity >= 0.3:
                    sensory_promote_keys.append(key)
            for key in sensory_promote_keys:
                entry = self._sensory_store.pop(key)
                self.short_term.store(key, entry.get("value"), session_id="", importance=entry.get("intensity", 0.5))
                stats["promoted"] += 1
                logger.debug("SENSORY→SHORT_TERM promoted key=%s", key)
            st_promote_keys: list[str] = []
            for key, fsrs in self._fsrs.items():
                if fsrs.review_count >= 3 and fsrs.retrievability >= 0.5:
                    val = self.short_term.retrieve(key)
                    if val is not None:
                        st_promote_keys.append(key)
            for key in st_promote_keys:
                val = self.short_term.retrieve(key)
                if val is not None:
                    self.working.store(key, val, priority=0.5)
                    stats["promoted"] += 1
                    logger.debug("SHORT_TERM→WORKING promoted key=%s", key)
            working_promote_keys: list[str] = []
            for key, fsrs in self._fsrs.items():
                if fsrs.review_count >= 5 and fsrs.retrievability >= 0.4:
                    working_val = self.working.retrieve(key)
                    if working_val is not None:
                        working_promote_keys.append(key)
            for key in working_promote_keys:
                val = self.working.retrieve(key)
                if val is not None:
                    if isinstance(val, dict) and val.get("type") in ("reasoning", "insight", "reflection"):
                        self._semantic_store[key] = {"value": val, "timestamp": now, "confidence": 0.8, "source": "consolidation"}
                    else:
                        self._episodic_store[key] = {"value": val, "timestamp": now, "importance": 0.7, "context": {"promoted_from": "working"}}
                    stats["promoted"] += 1
                    logger.debug("WORKING→EPISODIC/SEMANTIC promoted key=%s", key)
            meta_promote_keys: list[str] = []
            for key, entry in list(self._meta_cognitive_store.items()):
                if entry.get("retrieval_count", 0) >= 3 or entry.get("self_reference", False):
                    continue
            for key, entry in list(self._episodic_store.items()):
                val = entry.get("value")
                if isinstance(val, dict) and val.get("type") in ("reflection", "self_doubt") and entry.get("importance", 0) >= 0.6:
                    fsrs = self._fsrs.get(key)
                    if fsrs and fsrs.review_count >= 3:
                        meta_promote_keys.append(key)
            for key in meta_promote_keys:
                entry = self._episodic_store.pop(key)
                self._meta_cognitive_store[key] = {"value": entry.get("value"), "timestamp": now, "retrieval_count": 0, "self_reference": True}
                stats["promoted"] += 1
                logger.debug("EPISODIC→META_COGNITIVE promoted key=%s", key)
            for key, entry in list(self._semantic_store.items()):
                val = entry.get("value")
                if isinstance(val, dict) and val.get("type") in ("reflection", "self_doubt"):
                    fsrs = self._fsrs.get(key)
                    if fsrs and fsrs.review_count >= 3:
                        self._meta_cognitive_store[key] = {"value": val, "timestamp": now, "retrieval_count": 0, "self_reference": True}
                        stats["promoted"] += 1
                        logger.debug("SEMANTIC→META_COGNITIVE promoted key=%s", key)
        return stats

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "sensory_size": len(self._sensory_store),
            "working_size": self.working.size,
            "short_term_size": self.short_term.size,
            "procedural_size": self.procedural.size,
            "core_size": self.core.size,
            "cross_context_size": len(self._cross_context),
            "episodic_size": len(self._episodic_store),
            "semantic_size": len(self._semantic_store),
            "meta_cognitive_size": len(self._meta_cognitive_store),
            "hebbian_links": sum(len(v) for v in self._hebbian_links.values()),
            "fsrs_entries": len(self._fsrs),
        }
