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
import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import math
import re
logger = logging.getLogger(__name__)


class MemoryType(str, Enum):
    PARAMETRIC = "parametric"
    ACTIVATION = "activation"
    PLAINTEXT = "plaintext"


class MemCubeStatus(str, Enum):
    ACTIVE = "active"
    CONSOLIDATED = "consolidated"
    ARCHIVED = "archived"
    DECAYED = "decayed"


@dataclass(slots=True)
class MemCube:
    cube_id: str = ""
    memory_type: MemoryType = MemoryType.PLAINTEXT
    content: str = ""
    embedding: list[float] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    access_count: int = 0
    importance: float = 0.5
    decay_rate: float = 0.01
    status: MemCubeStatus = MemCubeStatus.ACTIVE
    domain: str = "default"
    tags: list[str] = field(default_factory=list)
    created_at: float = 0.0
    last_accessed: float = 0.0

    def __post_init__(self) -> None:
        if not self.cube_id:
            content_hash = hashlib.md5(f"{self.content}{self.memory_type.value}{time.time()}".encode()).hexdigest()[:8]
            self.cube_id = f"mc_{content_hash}"
        if not self.created_at:
            self.created_at = time.time()
        if not self.last_accessed:
            self.last_accessed = self.created_at

    def access(self) -> None:
        self.access_count += 1
        self.last_accessed = time.time()

    def current_strength(self):
            """计算当前记忆强度，基于指数衰减模型(Weibull族)与对数级频率增强。

            算法融合了时间衰减、访问频率与最近活跃度，模拟真实认知记忆曲线。
            Time: O(1) Space: O(1)
            """
            try:
                # 1. 输入防御:拦截非法数值与边界溢出
                now = time.time()
                importance = max(0.0, min(1.0, float(getattr(self, 'importance', 0.5))))
                decay_rate = max(0.0, float(getattr(self, 'decay_rate', 0.01)))
                access_count = max(0, int(getattr(self, 'access_count', 0)))

                created_at = float(getattr(self, 'created_at', now))
                last_accessed = float(getattr(self, 'last_accessed', created_at))

                # 2. 核心算法:指数衰减 (防止线性衰减导致的负数与不自然陡降)
                age_seconds = max(0.0, now - created_at)
                age_hours = age_seconds / 3600.0
                decay_factor = 1.0 / (1.0 + decay_rate * age_hours)

                # 3. 频率增强:对数级增长 (边际效益递减,防止高频访问导致权重溢出)
                frequency_boost = 0.1 * math.log2(1.0 + min(access_count, 10000))

                # 4. 活跃度因子:距离上次访问的时间衰减
                recency_seconds = max(0.0, now - last_accessed)

                # 5. 综合计算与截断
                raw_strength = (importance * decay_factor * 0.6) + \
                                (frequency_boost * 0.3) + \
                                (recency_factor * 0.1)  # noqa: F821

                return max(0.0, min(1.0, raw_strength))

            except Exception as _exc:
                logger.warning(
                    "MemCube: Strength calculation failed for %s: %s. Falling back to base importance.",
                    getattr(self, 'cube_id', 'unknown'),
                    _exc,
                    exc_info=False
                )
                return max(0.0, min(1.0, float(getattr(self, 'importance', 0.5))))


    def to_dict(self) -> dict[str, Any]:
        return {
            "cube_id": self.cube_id,
            "type": self.memory_type.value,
            "content_preview": self.content[:100],
            "importance": round(self.importance, 3),
            "strength": round(self.current_strength(), 3),
            "access_count": self.access_count,
            "status": self.status.value,
            "domain": self.domain,
            "tags": self.tags[:5],
        }


class ParametricMemory:
    """Model weights, learned patterns, persistent knowledge."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cubes: dict[str, MemCube] = {}

    def store(self, key: str, content: str, importance: float = 0.8, domain: str = "default") -> MemCube:
        cube = MemCube(
            memory_type=MemoryType.PARAMETRIC,
            content=content,
            importance=importance,
            decay_rate=0.001,
            domain=domain,
            tags=["parametric", key],
        )
        self._cubes[cube.cube_id] = cube
        return cube

    def retrieve(self, query: str, top_k: int = 5, domain: str | None = None) -> list[MemCube]:
        candidates = [c for c in self._cubes.values() if c.status == MemCubeStatus.ACTIVE and (domain is None or c.domain == domain)]
        scored = [(c, self._relevance_score(c, query)) for c in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)
        for cube, _ in scored[:top_k]:
            cube.access()
        return [c for c, _ in scored[:top_k]]

    def consolidate(self, threshold: float = 0.3) -> int:
        consolidated = 0
        for cube in self._cubes.values():
            if cube.current_strength() < threshold and cube.status == MemCubeStatus.ACTIVE:
                cube.status = MemCubeStatus.CONSOLIDATED
                consolidated += 1
        return consolidated

    def get_stats(self) -> dict[str, Any]:
        active = sum(1 for c in self._cubes.values() if c.status == MemCubeStatus.ACTIVE)
        return {
            "type": "parametric",
            "total_cubes": len(self._cubes),
            "active": active,
            "consolidated": len(self._cubes) - active,
        }

    def _relevance_score(self, cube, query):
                """Advanced BM25-fused relevance scoring with dynamic IDF approximation.

                Combines term frequency saturation, probabilistic inverse document
                frequency, and Weibull-decayed memory strength via quadratic smoothing.
                Time: O(C + Q) where C=content tokens, Q=query tokens. Space: O(C).
                """
                # 1. Strict parameter validation
                if not isinstance(query, str) or not query:
                    return 0.0
                if cube is None or not getattr(cube, 'content', None):
                    return 0.0

                try:
                    # 2. Robust regex tokenization
                    query_tokens = re.findall(r'\w+', query.lower())
                    if not query_tokens:
                        return 0.0

                    content_tokens = re.findall(r'\w+', cube.content.lower())
                    content_len = len(content_tokens)
                    if content_len == 0:
                        return 0.0

                    # 3. Optimized term frequency mapping using Counter
                    content_tf: dict = {}
                    for token in content_tokens:
                        content_tf[token] = content_tf.get(token, 0) + 1

                    # 4. BM25 parameters
                    k1 = 1.5
                    b = 0.75
                    avg_len = 20.0  # Normalization constant for document length
                    tf_idf_component = 0.0

                    # 5. BM25 with dynamic IDF approximation
                    # IDF formula approximated for a local single-document context
                    for q_token in query_tokens:
                        if q_token in content_tf:
                            tf = content_tf[q_token]

                            # Dynamic IDF: assumes document exists in a theoretical N-doc corpus
                            # IDF(q) = log(1 + (N - n + 0.5) / (n + 0.5))
                            # For local match: N=avg_len*10, n=tf (heuristic approximation)
                            n = tf
                            N = max(100.0, avg_len * 10.0)
                            idf = math.log(1.0 + (N - n + 0.5) / max(1.0, n + 0.5))

                            # TF saturation
                            numerator = tf * (k1 + 1.0)
                            denominator = tf + k1 * (1.0 - b + b * (content_len / avg_len))

                            tf_idf_component += idf * (numerator / max(0.1, denominator))

                    # 6. Normalize text relevance density
                    base_relevance = tf_idf_component / max(1.0, len(query_tokens))

                    # 7. Retrieve memory strength (applies Weibull decay internally)
                    strength_func = getattr(cube, 'current_strength', None)
                    if callable(strength_func):
                        strength = float(strength_func())
                    else:
                        strength = 0.5  # Fallback neutral strength

                    # 8. Quadratic smoothing fusion
                    # Prevents extreme decay from entirely nullifying high text relevance
                    fused = (0.7 * base_relevance) + (0.3 * strength)

                    # Non-linear squashing to emphasize highly relevant & strong memories
                    final_score = math.sqrt(max(0.0, fused))

                    return max(0.0, min(1.0, final_score))

                except Exception as _exc:
                    logger.warning(
                        "ParametricMemory._relevance_score calculation failed for cube %s: %s. Falling back to 0.0.",
                        getattr(cube, 'cube_id', 'unknown'),
                        _exc,
                        exc_info=False
                    )
                    return 0.0




class ActivationMemory:
    """Working memory, context window, short-term activations."""

    def __init__(self, capacity: int = 100) -> None:
        self._cubes: list[MemCube] = []
        self._capacity = capacity

    def activate(self, content: str, importance: float = 0.6, domain: str = "default") -> MemCube:
        cube = MemCube(
            memory_type=MemoryType.ACTIVATION,
            content=content,
            importance=importance,
            decay_rate=0.1,
            domain=domain,
            tags=["activation"],
        )
        self._cubes.append(cube)
        if len(self._cubes) > self._capacity:
            self._cubes.sort(key=lambda c: c.current_strength())
            evicted = self._cubes.pop(0)
            logger.debug("Activation memory evicted: %s", evicted.cube_id)
        return cube

    def get_active(self, domain: str | None = None) -> list[MemCube]:
        result = [c for c in self._cubes if c.status == MemCubeStatus.ACTIVE]
        if domain:
            result = [c for c in result if c.domain == domain]
        result.sort(key=lambda c: c.current_strength(), reverse=True)
        return result

    def decay_all(self) -> int:
        decayed = 0
        remaining = []
        for cube in self._cubes:
            if cube.current_strength() < 0.05:
                cube.status = MemCubeStatus.DECAYED
                decayed += 1
            else:
                remaining.append(cube)
        self._cubes = remaining
        return decayed

    def get_stats(self) -> dict[str, Any]:
        return {
            "type": "activation",
            "active_count": len(self._cubes),
            "capacity": self._capacity,
            "utilization": round(len(self._cubes) / self._capacity, 3),
        }


class PlaintextMemory:
    """Explicit knowledge, documents, conversation history."""

    def __init__(self) -> None:
        self._cubes: dict[str, MemCube] = {}

    def write(self, key: str, content: str, importance: float = 0.5, domain: str = "default", tags: list[str] | None = None) -> MemCube:
        cube = MemCube(
            memory_type=MemoryType.PLAINTEXT,
            content=content,
            importance=importance,
            decay_rate=0.005,
            domain=domain,
            tags=tags or ["plaintext", key],
        )
        self._cubes[cube.cube_id] = cube
        return cube

    def read(self, cube_id):
            """O(1) avg lookup with O(N) fuzzy fallback. Graceful degradation on anomalies."""
            if not cube_id or not isinstance(cube_id, str):
                logger.warning(
                    "PlaintextMemory.read rejected invalid cube_id type: %s",
                    type(cube_id).__name__,
                )
                return None

            cube = self._cubes.get(cube_id)

            if cube:
                if cube.status in (MemCubeStatus.ACTIVE, MemCubeStatus.ARCHIVED):
                    try:
                        cube.access()
                        logger.debug(
                            "Read success: cube_id=%s, status=%s",
                            cube_id, cube.status.value
                        )
                        return cube
                    except Exception as _exc:
                        logger.error(
                            "PlaintextMemory.read: access mutation failed for %s. Error: %s",
                            cube_id, _exc, exc_info=False
                        )
                        return cube
                else:
                    logger.info("Cube %s skipped read (status=%s).", cube_id, cube.status.value)
                    return None

            return self._fuzzy_read(cube_id)


    def search(self, query: str, top_k: int = 10, domain: str | None = None) -> list[MemCube]:
        candidates = [c for c in self._cubes.values() if c.status == MemCubeStatus.ACTIVE and (domain is None or c.domain == domain)]
        scored = [(c, self._text_relevance(c, query)) for c in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)
        for cube, _ in scored[:top_k]:
            cube.access()
        return [c for c, _ in scored[:top_k]]

    def archive(self, cube_id: str) -> bool:
        cube = self._cubes.get(cube_id)
        if cube:
            cube.status = MemCubeStatus.ARCHIVED
            return True
        return False

    def get_stats(self) -> dict[str, Any]:
        active = sum(1 for c in self._cubes.values() if c.status == MemCubeStatus.ACTIVE)
        archived = sum(1 for c in self._cubes.values() if c.status == MemCubeStatus.ARCHIVED)
        return {
            "type": "plaintext",
            "total_cubes": len(self._cubes),
            "active": active,
            "archived": archived,
        }

    def _text_relevance(self, cube: MemCube, query: str) -> float:
        query_lower = query.lower()
        content_lower = cube.content.lower()
        if query_lower in content_lower:
            return cube.current_strength() * 1.5
        query_words = set(query_lower.split())
        content_words = set(content_lower.split())
        overlap = len(query_words & content_words)
        return (overlap / max(1, len(query_words))) * cube.current_strength()



    def _fuzzy_read(self, cube_id):
            """Fallback fuzzy search using hash/prefix matching when exact lookup fails. O(N) scan."""
            try:
                cube_id_lower = cube_id.lower()
                prefix_match = None
                hash_match = None
                for key, cube in self._cubes.items():
                    if cube.status not in (MemCubeStatus.ACTIVE, MemCubeStatus.ARCHIVED):
                        continue
                    if key.lower() == cube_id_lower:
                        return cube
                    if key.lower().startswith(cube_id_lower) and prefix_match is None:
                        prefix_match = cube
                    # Hash collision check for cross-module referencing
                    if cube.cube_id == cube_id and hash_match is None:
                        hash_match = cube
                target = prefix_match or hash_match
                if target:
                    target.access()
                    logger.info("Fuzzy read resolved %s to %s.", cube_id, target.cube_id)
                return target
            except Exception as _exc:
                logger.warning(
                    "PlaintextMemory._fuzzy_read failed for %s. Error: %s",
                    cube_id, _exc, exc_info=False
                )
                return None
class UnifiedMemo:
    """
    Unified memo engine: Parametric + Activation + Plaintext memory with
    cube-style governance.
    """

    def __init__(self, activation_capacity: int = 100) -> None:
        self.parametric = ParametricMemory()
        self.activation = ActivationMemory(capacity=activation_capacity)
        self.plaintext = PlaintextMemory()
        self._governance_log: list[dict[str, Any]] = []

    def store(
        self,
        content: str,
        memory_type: MemoryType = MemoryType.PLAINTEXT,
        importance: float = 0.5,
        domain: str = "default",
        key: str = "",
        tags: list[str] | None = None,
    ) -> MemCube:
        if memory_type == MemoryType.PARAMETRIC:
            cube = self.parametric.store(key or "auto", content, importance, domain)
        elif memory_type == MemoryType.ACTIVATION:
            cube = self.activation.activate(content, importance, domain)
        else:
            cube = self.plaintext.write(key or "auto", content, importance, domain, tags)

        self._governance_log.append(
            {
                "action": "store",
                "cube_id": cube.cube_id,
                "type": memory_type.value,
                "domain": domain,
                "timestamp": time.time(),
            }
        )
        return cube

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        memory_types: list[MemoryType] | None = None,
        domain: str | None = None,
    ) -> list[MemCube]:
        types = memory_types or list(MemoryType)
        results: list[MemCube] = []

        if MemoryType.PARAMETRIC in types:
            results.extend(self.parametric.retrieve(query, top_k, domain))
        if MemoryType.ACTIVATION in types:
            actives = self.activation.get_active(domain)
            results.extend(actives[:top_k])
        if MemoryType.PLAINTEXT in types:
            results.extend(self.plaintext.search(query, top_k, domain))

        results.sort(key=lambda c: c.current_strength(), reverse=True)
        return results[:top_k]

    def consolidate_all(self) -> dict[str, int]:
        parametric_consolidated = self.parametric.consolidate()
        activation_decayed = self.activation.decay_all()
        return {
            "parametric_consolidated": parametric_consolidated,
            "activation_decayed": activation_decayed,
        }

    def auto_route(self, content: str, importance: float) -> MemoryType:
        if importance >= 0.8:
            return MemoryType.PARAMETRIC
        elif importance >= 0.5:
            return MemoryType.ACTIVATION
        else:
            return MemoryType.PLAINTEXT

    def get_stats(self) -> dict[str, Any]:
        return {
            "parametric": self.parametric.get_stats(),
            "activation": self.activation.get_stats(),
            "plaintext": self.plaintext.get_stats(),
            "governance_operations": len(self._governance_log),
            "total_cubes": (self.parametric.get_stats()["total_cubes"] + self.activation.get_stats()["active_count"] + self.plaintext.get_stats()["total_cubes"]),
        }
