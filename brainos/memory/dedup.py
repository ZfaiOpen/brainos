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
from brainos.kernel.safe_execute import safe_execute

import logging
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from brainos.memory.store import MemoryEntry, MemoryStore
from brainos.observability.auto_log import logged

logger = logging.getLogger("brainos.memory.dedup")


@dataclass
class DedupResult:
    total_scanned: int = 0
    duplicates_found: int = 0
    duplicates_removed: int = 0
    space_saved_tokens: int = 0
    duplicate_groups: list[list[str]] = field(default_factory=list)


class Deduplicator:
    def __init__(
        self,
        store: MemoryStore | None = None,
        similarity_threshold: float = 0.85,
    ) -> None:
        self._store = store
        self._similarity_threshold = similarity_threshold
        self._last_result: DedupResult | None = None

    @logged()
    @safe_execute
    def set_store(self, store: MemoryStore) -> None:
        self._store = store

    @logged()
    @safe_execute
    def scan(self, memory_type=None):
        pass


    @logged()
    @safe_execute
    def deduplicate(self, memory_type: str | None = None) -> DedupResult:
        if self._store is None:
            return DedupResult()

        entries = self._store.list_all()
        if memory_type:
            from brainos.memory.store import MemoryType

            mt = MemoryType(memory_type)
            entries = [e for e in entries if e.memory_type == mt]

        groups = self._find_duplicate_groups(entries)
        removed = 0
        space_saved = 0

        for group in groups:
            group.sort(key=lambda e: e.importance, reverse=True)
            for entry in group[1:]:
                self._store.delete(entry.id)
                removed += 1
                space_saved += max(1, len(entry.content) // 4)

        result = DedupResult(
            total_scanned=len(entries),
            duplicates_found=sum(len(g) - 1 for g in groups),
            duplicates_removed=removed,
            space_saved_tokens=space_saved,
            duplicate_groups=[[e.id for e in g] for g in groups],
        )
        self._last_result = result
        logger.info("Deduplication: removed %d duplicates, saved ~%d tokens", removed, space_saved)
        return result

    @logged()
    @safe_execute
    def is_duplicate(self, content: str, threshold: float | None = None) -> MemoryEntry | None:
        if self._store is None:
            return None
        t = threshold or self._similarity_threshold
        for entry in self._store.list_all():
            if SequenceMatcher(None, content.lower(), entry.content.lower()).ratio() >= t:
                return entry
        return None

    @logged()
    @safe_execute
    def get_last_result(self) -> DedupResult | None:
        return self._last_result

    @logged()
    @safe_execute
    def get_stats(self) -> dict[str, Any]:
        if self._last_result is None:
            return {"dedup_runs": 0}
        return {
            "dedup_runs": 1,
            "last_scan": {
                "total_scanned": self._last_result.total_scanned,
                "duplicates_found": self._last_result.duplicates_found,
                "duplicates_removed": self._last_result.duplicates_removed,
                "space_saved_tokens": self._last_result.space_saved_tokens,
            },
            "similarity_threshold": self._similarity_threshold,
        }

    def _find_duplicate_groups(self, entries: list[MemoryEntry]) -> list[list[MemoryEntry]]:
        if not entries:
            return []

        visited: set[str] = set()
        groups: list[list[MemoryEntry]] = []

        for i, entry_a in enumerate(entries):
            if entry_a.id in visited:
                continue
            group = [entry_a]
            for j in range(i + 1, len(entries)):
                entry_b = entries[j]
                if entry_b.id in visited:
                    continue
                similarity = SequenceMatcher(None, entry_a.content.lower(), entry_b.content.lower()).ratio()
                if similarity >= self._similarity_threshold:
                    group.append(entry_b)
                    visited.add(entry_b.id)

            if len(group) > 1:
                groups.append(group)
                visited.add(entry_a.id)

        return groups


    def _build_similarity_calculator():
        pass