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
Temporal Awareness v1.0

Inspired by Zep Temporal Knowledge Graph (2025) — 双时间轴记忆感知
每条记忆加 valid_from/valid_until 时间戳，新记忆自动使旧矛盾记忆过期

核心能力:
  1. 时间戳标记: store时自动加valid_from
  2. 矛盾失效: 新矛盾记忆自动标记旧记忆valid_until
  3. 有效过滤: retrieve时自动排除已过期记忆
  4. 时间冲突检测: 发现同一key的矛盾时间线
"""

from __future__ import annotations

import time
import logging
import threading
from dataclasses import dataclass, field, asdict
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TemporalEntry:
    key: str
    value: Any
    valid_from: float = 0.0
    valid_until: float = 0.0
    superseded_by: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_valid(self):
        pass


    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TemporalAwareness:
    def __init__(self) -> None:
        self._entries: dict[str, list[TemporalEntry]] = {}
        self._lock = threading.Lock()
        self._stats = {
            "stored": 0,
            "invalidated": 0,
            "conflicts_detected": 0,
            "valid_retrieves": 0,
            "expired_filtered": 0,
        }

    def store(self, key: str, value: Any, metadata: dict[str, Any] | None = None) -> TemporalEntry:
        now = time.time()
        entry = TemporalEntry(
            key=key,
            value=value,
            valid_from=now,
            valid_until=0.0,
            metadata=metadata or {},
        )

        with self._lock:
            existing = self._entries.get(key, [])
            for old in existing:
                if old.is_valid and str(old.value) != str(value):
                    old.valid_until = now
                    old.superseded_by = f"{key}@{now:.0f}"
                    self._stats["invalidated"] += 1
                    self._stats["conflicts_detected"] += 1
                    logger.debug("temporal invalidation: %s '%s' -> '%s'", key, old.value, value)

            self._entries.setdefault(key, []).append(entry)
            self._stats["stored"] += 1

        return entry

    def retrieve(self, key: str) -> TemporalEntry | None:
        with self._lock:
            entries = self._entries.get(key, [])
            valid = [e for e in entries if e.is_valid]
            if not valid:
                self._stats["expired_filtered"] += 1
                return None
            latest = max(valid, key=lambda e: e.valid_from)
            self._stats["valid_retrieves"] += 1
            return latest

    def retrieve_history(self, key: str, include_expired: bool = False) -> list[TemporalEntry]:
        with self._lock:
            entries = self._entries.get(key, [])
            if include_expired:
                return sorted(entries, key=lambda e: e.valid_from)
            return sorted([e for e in entries if e.is_valid], key=lambda e: e.valid_from)

    def detect_temporal_conflicts(self) -> list[tuple[TemporalEntry, TemporalEntry]]:
        conflicts: list[tuple[TemporalEntry, TemporalEntry]] = []
        with self._lock:
            for key, entries in self._entries.items():
                for i in range(len(entries)):
                    for j in range(i + 1, len(entries)):
                        a, b = entries[i], entries[j]
                        if a.is_valid and b.is_valid and str(a.value) != str(b.value):
                            conflicts.append((a, b))
        return conflicts

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            total_entries = sum(len(v) for v in self._entries.values())
            valid_entries = sum(1 for entries in self._entries.values() for e in entries if e.is_valid)
            return {
                **self._stats,
                "total_entries": total_entries,
                "valid_entries": valid_entries,
                "expired_entries": total_entries - valid_entries,
                "keys_tracked": len(self._entries),
            }
