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
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from brainos.observability.auto_log import logged

logger = logging.getLogger("brainos.memory.consolidator")


class ConsolidationPhase(Enum):
    ENCODE = "encode"
    STABILIZE = "stabilize"
    INTEGRATE = "integrate"
    CONSOLIDATE = "consolidate"


@dataclass
class ConsolidationEntry:
    key: str
    value: Any
    phase: ConsolidationPhase = ConsolidationPhase.ENCODE
    importance: float = 0.5
    access_count: int = 0
    created_at: float = field(default_factory=time.monotonic)
    last_accessed: float = field(default_factory=time.monotonic)
    phase_entered_at: float = field(default_factory=time.monotonic)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def age_seconds(self):
        pass


    @property
    def phase_duration_seconds(self) -> float:
        return time.monotonic() - self.phase_entered_at


@dataclass
class ConsolidationResult:
    key: str
    from_phase: ConsolidationPhase
    to_phase: ConsolidationPhase
    promoted: bool
    reason: str
    timestamp: float = field(default_factory=time.monotonic)


PHASE_THRESHOLDS: dict[ConsolidationPhase, dict[str, Any]] = {
    ConsolidationPhase.ENCODE: {
        "min_age_seconds": 60.0,
        "min_access_count": 1,
        "min_importance": 0.2,
    },
    ConsolidationPhase.STABILIZE: {
        "min_age_seconds": 300.0,
        "min_access_count": 2,
        "min_importance": 0.4,
    },
    ConsolidationPhase.INTEGRATE: {
        "min_age_seconds": 1800.0,
        "min_access_count": 3,
        "min_importance": 0.6,
    },
    ConsolidationPhase.CONSOLIDATE: {
        "min_age_seconds": 7200.0,
        "min_access_count": 5,
        "min_importance": 0.8,
    },
}

PHASE_ORDER = [
    ConsolidationPhase.ENCODE,
    ConsolidationPhase.STABILIZE,
    ConsolidationPhase.INTEGRATE,
    ConsolidationPhase.CONSOLIDATE,
]


class MemoryConsolidator:
    def __init__(self, store: Any = None) -> None:
        self._store = store
        self._entries: dict[str, ConsolidationEntry] = {}
        self._results: list[ConsolidationResult] = []
        self._lock = threading.RLock()
        self._consolidation_count: int = 0

    @logged()
    @safe_execute
    def add(self, key: str, value: Any, importance: float = 0.5, metadata: dict[str, Any] | None = None) -> ConsolidationEntry:
        entry = ConsolidationEntry(key=key, value=value, importance=importance, metadata=metadata or {})
        with self._lock:
            self._entries[key] = entry
        logger.debug("Memory added for consolidation: %s (importance=%.2f)", key, importance)
        return entry

    @logged()
    @safe_execute
    def access(self, key: str) -> Any | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            entry.access_count += 1
            entry.last_accessed = time.monotonic()
            return entry.value

    @logged()
    @safe_execute
    def consolidate(self, key: str | None = None) -> list[ConsolidationResult]:
        self._consolidation_count += 1
        results: list[ConsolidationResult] = []
        with self._lock:
            entries = [self._entries[key]] if key and key in self._entries else list(self._entries.values())
        for entry in entries:
            result = self._try_promote(entry)
            if result:
                results.append(result)
                with self._lock:
                    self._results.append(result)
        if results:
            logger.info("Consolidation pass: %d/%d promoted", len(results), len(entries))
        return results

    def _try_promote(self, entry: ConsolidationEntry) -> ConsolidationResult | None:
        current_idx = PHASE_ORDER.index(entry.phase)
        if current_idx >= len(PHASE_ORDER) - 1:
            return None
        next_phase = PHASE_ORDER[current_idx + 1]
        thresholds = PHASE_THRESHOLDS.get(next_phase, {})
        min_age = thresholds.get("min_age_seconds", 0)
        min_access = thresholds.get("min_access_count", 0)
        min_importance = thresholds.get("min_importance", 0)
        if entry.phase_duration_seconds < min_age:
            return None
        if entry.access_count < min_access:
            return None
        if entry.importance < min_importance:
            return None
        from_phase = entry.phase
        entry.phase = next_phase
        entry.phase_entered_at = time.monotonic()
        return ConsolidationResult(
            key=entry.key,
            from_phase=from_phase,
            to_phase=next_phase,
            promoted=True,
            reason=(f"met thresholds: age={entry.phase_duration_seconds:.0f}s>={min_age}s, access={entry.access_count}>={min_access}, importance={entry.importance:.2f}>={min_importance:.2f}"),
        )

    @logged()
    @safe_execute
    def demote(self, key: str, reason: str = "") -> ConsolidationResult | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            current_idx = PHASE_ORDER.index(entry.phase)
            if current_idx <= 0:
                return None
            from_phase = entry.phase
            entry.phase = PHASE_ORDER[current_idx - 1]
            entry.phase_entered_at = time.monotonic()
        result = ConsolidationResult(key=key, from_phase=from_phase, to_phase=entry.phase, promoted=False, reason=reason or "demoted")
        with self._lock:
            self._results.append(result)
        return result

    @logged()
    @safe_execute
    def get_entry(self, key: str) -> ConsolidationEntry | None:
        with self._lock:
            return self._entries.get(key)

    @logged()
    @safe_execute
    def get_by_phase(self, phase: ConsolidationPhase) -> list[ConsolidationEntry]:
        with self._lock:
            return [e for e in self._entries.values() if e.phase == phase]

    @logged()
    @safe_execute
    def remove(self, key: str) -> bool:
        with self._lock:
            return self._entries.pop(key, None) is not None

    @logged()
    @safe_execute
    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            by_phase: dict[str, int] = {}
            for e in self._entries.values():
                by_phase[e.phase.value] = by_phase.get(e.phase.value, 0) + 1
            total_promoted = sum(1 for r in self._results if r.promoted)
            total_demoted = sum(1 for r in self._results if not r.promoted)
            return {
                "total_entries": len(self._entries),
                "by_phase": by_phase,
                "consolidation_count": self._consolidation_count,
                "total_promoted": total_promoted,
                "total_demoted": total_demoted,
            }
