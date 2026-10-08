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
"""
Hippocampal Dream Engine v1.0

Inspired by Anthropic Dreaming (2026.05.06) — 异步海马体记忆整合
在会话间自动: 检测矛盾记忆 → 合并重复 → 发现跨域关联 → 提炼经验定律

核心能力:
  1. 矛盾检测: 发现时间冲突的记忆对 (如 "用TypeScript" vs "用Python")
  2. 记忆合并: 相似度过高的记忆自动合并为一条
  3. 跨域关联: 发现认知域的教训可复用到进化域
  4. 经验提炼: 从重复失败模式中自动生成铁律建议
"""

from __future__ import annotations

import time
import logging
import threading
from dataclasses import dataclass, field, asdict
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DreamResult:
    contradictions_found: int = 0
    memories_merged: int = 0
    cross_domain_links: int = 0
    iron_law_proposals: list[str] = field(default_factory=list)
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MemoryItem:
    key: str
    value: Any
    layer: str = "short_term"
    timestamp: float = 0.0
    domain: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class HippocampalDreamEngine:
    def __init__(self, memory_store: Any = None) -> None:
        self._store = memory_store
        self._dream_count: int = 0
        self._total_contradictions: int = 0
        self._total_merges: int = 0
        self._total_cross_links: int = 0
        self._iron_laws: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._failure_patterns: dict[str, int] = {}
        logger.info("HippocampalDreamEngine initialized")

    def dream_cycle(self, memories: list[MemoryItem] | None = None) -> DreamResult:
        t0 = time.monotonic()
        result = DreamResult()

        if memories is None:
            memories = self._load_memories()

        if not memories:
            logger.debug("dream_cycle: no memories to process")
            with self._lock:
                self._dream_count += 1
            return result

        step1 = self._detect_contradictions(memories)
        result.contradictions_found = len(step1)

        step2 = self._merge_duplicates(memories)
        result.memories_merged = len(step2)

        step3 = self._discover_cross_domain_links(memories)
        result.cross_domain_links = len(step3)

        step4 = self._extract_iron_laws(step1)
        result.iron_law_proposals = step4

        result.duration_ms = (time.monotonic() - t0) * 1000

        with self._lock:
            self._dream_count += 1
            self._total_contradictions += result.contradictions_found
            self._total_merges += result.memories_merged
            self._total_cross_links += result.cross_domain_links

        logger.info(
            "dream_cycle #%d done: %d contradictions, %d merges, %d cross-links, %d laws, %.1fms",
            self._dream_count, result.contradictions_found, result.memories_merged,
            result.cross_domain_links, len(result.iron_law_proposals), result.duration_ms,
        )
        return result

    def _load_memories(self):
            if self._store is None:
                return []
            items: list[MemoryItem] = []
            try:
                for layer in ("short_term", "medium_term", "long_term", "core"):
                    try:
                        val = self._store.retrieve(f"__layer_{layer}")
                        if isinstance(val, list):
                            items.extend(val)
                    except Exception as _exc:
                        logger.warning("dream _load_memories: layer '%s' retrieve failed: %s", layer, _exc)

                deduped: dict[str, MemoryItem] = {}
                for item in items:
                    if not isinstance(item, MemoryItem):
                        continue
                    key = getattr(item, "key", None)
                    if not key:
                        continue
                    ts = getattr(item, "timestamp", 0.0)
                    if key not in deduped or ts > getattr(deduped[key], "timestamp", 0.0):
                        deduped[key] = item
                return list(deduped.values())
            except Exception as _exc:
                logger.warning("dream _load_memories: unexpected error: %s", _exc)
                return []


    def _detect_contradictions(self, memories: list[MemoryItem]) -> list[tuple[MemoryItem, MemoryItem, str]]:
        contradictions: list[tuple[MemoryItem, MemoryItem, str]] = []
        seen_keys: dict[str, list[MemoryItem]] = {}
        for m in memories:
            base = m.key.split(":")[0] if ":" in m.key else m.key
            seen_keys.setdefault(base, []).append(m)

        for base, items in seen_keys.items():
            if len(items) < 2:
                continue
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    a, b = items[i], items[j]
                    if a.value != b.value and a.timestamp > 0 and b.timestamp > 0:
                        if abs(a.timestamp - b.timestamp) > 3600:
                            contradictions.append((a, b, f"key={base} values differ"))

        for m in memories:
            val = str(m.value).lower() if m.value else ""
            for m2 in memories:
                if m.key == m2.key or m.domain == m2.domain:
                    continue
                val2 = str(m2.value).lower() if m2.value else ""
                if val and val2 and val == val2 and m.domain != m2.domain:
                    contradictions.append((m, m2, "same_value_diff_domain"))

        return contradictions

    def _merge_duplicates(self, memories: list[MemoryItem]) -> list[tuple[MemoryItem, MemoryItem]]:
        merges: list[tuple[MemoryItem, MemoryItem]] = []
        val_map: dict[str, list[MemoryItem]] = {}
        for m in memories:
            vs = str(m.value)[:100] if m.value else ""
            if vs:
                val_map.setdefault(vs, []).append(m)

        for vs, items in val_map.items():
            if len(items) < 2:
                continue
            latest = max(items, key=lambda x: x.timestamp)
            for item in items:
                if item is not latest and item.layer == latest.layer:
                    merges.append((item, latest))

        return merges

    def _discover_cross_domain_links(self, memories: list[MemoryItem]) -> list[tuple[str, str, str]]:
        links: list[tuple[str, str, str]] = []
        domain_map: dict[str, list[MemoryItem]] = {}
        for m in memories:
            if m.domain:
                domain_map.setdefault(m.domain, []).append(m)

        domains = list(domain_map.keys())
        for i in range(len(domains)):
            for j in range(i + 1, len(domains)):
                da, db = domains[i], domains[j]
                va = {str(m.value)[:50] for m in domain_map[da] if m.value}
                vb = {str(m.value)[:50] for m in domain_map[db] if m.value}
                overlap = va & vb
                if overlap:
                    links.append((da, db, f"shared_patterns={len(overlap)}"))

        return links

    def _extract_iron_laws(self, contradictions: list[tuple[MemoryItem, MemoryItem, str]]) -> list[str]:
        patterns: dict[str, int] = {}
        for a, b, reason in contradictions:
            pattern_key = reason.split("=")[0] if "=" in reason else reason
            patterns[pattern_key] = patterns.get(pattern_key, 0) + 1

        laws: list[str] = []
        for pattern, count in patterns.items():
            if count >= 2:
                law = f"[DreamLaw] {pattern}: detected {count}x contradiction — consider adding validation"
                laws.append(law)
                self._iron_laws.append({
                    "pattern": pattern,
                    "count": count,
                    "proposal": law,
                    "timestamp": time.time(),
                })

        return laws

    def record_failure_pattern(self, pattern: str) -> None:
        with self._lock:
            self._failure_patterns[pattern] = self._failure_patterns.get(pattern, 0) + 1

    def get_dream_stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "dream_count": self._dream_count,
                "total_contradictions": self._total_contradictions,
                "total_merges": self._total_merges,
                "total_cross_links": self._total_cross_links,
                "iron_laws_generated": len(self._iron_laws),
                "failure_patterns_tracked": len(self._failure_patterns),
            }
