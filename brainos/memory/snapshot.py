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

import copy
import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from brainos.observability.auto_log import logged

logger = logging.getLogger("brainos.memory.snapshot")


@dataclass
class Snapshot:
    id: str
    label: str
    state: dict[str, Any]
    checksum: str = ""
    created_at: float = field(default_factory=time.monotonic)
    parent_id: str = ""
    tags: list[str] = field(default_factory=list)
    size_bytes: int = 0

    def __post_init__(self) -> None:
        if not self.checksum:
            self.checksum = self._compute_checksum()
        if not self.size_bytes:
            self.size_bytes = len(json.dumps(self.state, default=str).encode())

    def _compute_checksum(self) -> str:
        raw = json.dumps(self.state, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @logged()
    @safe_execute
    def verify(self) -> bool:
        return self.checksum == self._compute_checksum()

    @logged()
    @safe_execute
    def to_dict(self):
        pass


    @classmethod
    @logged()
    @safe_execute
    def from_dict(cls, data: dict[str, Any]) -> Snapshot:
        return cls(
            id=data["id"],
            label=data["label"],
            state=data["state"],
            checksum=data.get("checksum", ""),
            created_at=data.get("created_at", 0.0),
            parent_id=data.get("parent_id", ""),
            tags=data.get("tags", []),
            size_bytes=data.get("size_bytes", 0),
        )


class StateSnapshot:
    def __init__(self, max_snapshots: int = 100) -> None:
        self._snapshots: dict[str, Snapshot] = {}
        self._timeline: list[str] = []
        self._max_snapshots = max_snapshots
        self._lock = threading.RLock()
        self._snapshot_count: int = 0

    @logged()
    @safe_execute
    def capture(self, label: str, state: dict[str, Any], tags: list[str] | None = None, parent_id: str = "") -> Snapshot:
        self._snapshot_count += 1
        snap_id = f"snap_{self._snapshot_count}_{int(time.monotonic() * 1000)}"
        snapshot = Snapshot(
            id=snap_id,
            label=label,
            state=copy.deepcopy(state),
            parent_id=parent_id,
            tags=tags or [],
        )
        with self._lock:
            self._snapshots[snap_id] = snapshot
            self._timeline.append(snap_id)
            if len(self._snapshots) > self._max_snapshots:
                oldest_id = self._timeline.pop(0)
                self._snapshots.pop(oldest_id, None)
        logger.info("Snapshot captured: %s (%s)", snap_id, label)
        return snapshot

    @logged()
    @safe_execute
    def restore(self, snapshot_id: str) -> dict[str, Any] | None:
        with self._lock:
            snapshot = self._snapshots.get(snapshot_id)
            if snapshot is None:
                return None
            if not snapshot.verify():
                logger.error("Snapshot checksum mismatch: %s", snapshot_id)
                return None
            return copy.deepcopy(snapshot.state)

    @logged()
    @safe_execute
    def get(self, snapshot_id: str) -> Snapshot | None:
        with self._lock:
            return self._snapshots.get(snapshot_id)

    @logged()
    @safe_execute
    def delete(self, snapshot_id: str) -> bool:
        with self._lock:
            removed = self._snapshots.pop(snapshot_id, None) is not None
            if removed and snapshot_id in self._timeline:
                self._timeline.remove(snapshot_id)
        return removed

    @logged()
    @safe_execute
    def list_snapshots(self, label: str | None = None, tags: list[str] | None = None, limit: int = 50) -> list[Snapshot]:
        with self._lock:
            results = list(self._snapshots.values())
        if label:
            results = [s for s in results if label in s.label]
        if tags:
            tag_set = set(tags)
            results = [s for s in results if tag_set & set(s.tags)]
        results.sort(key=lambda s: s.created_at, reverse=True)
        return results[:limit]

    @logged()
    @safe_execute
    def diff(self, snapshot_id_a: str, snapshot_id_b: str) -> dict[str, Any]:
        with self._lock:
            sa = self._snapshots.get(snapshot_id_a)
            sb = self._snapshots.get(snapshot_id_b)
        if sa is None or sb is None:
            return {"error": "snapshot not found"}
        keys_a = set(sa.state.keys())
        keys_b = set(sb.state.keys())
        added = keys_b - keys_a
        removed = keys_a - keys_b
        common = keys_a & keys_b
        changed: dict[str, Any] = {}
        for k in common:
            if sa.state[k] != sb.state[k]:
                changed[k] = {"from": sa.state[k], "to": sb.state[k]}
        return {
            "added": list(added),
            "removed": list(removed),
            "changed": changed,
            "unchanged_count": len(common) - len(changed),
        }

    @logged()
    @safe_execute
    def rollback_to(self, label: str) -> dict[str, Any] | None:
        with self._lock:
            for snap_id in reversed(self._timeline):
                snapshot = self._snapshots.get(snap_id)
                if snapshot and snapshot.label == label:
                    return self.restore(snap_id)
        return None

    @logged()
    @safe_execute
    def export_all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._snapshots[sid].to_dict() for sid in self._timeline if sid in self._snapshots]

    @logged()
    @safe_execute
    def import_snapshots(self, data: list[dict[str, Any]]) -> int:
        count = 0
        with self._lock:
            for d in data:
                snap = Snapshot.from_dict(d)
                self._snapshots[snap.id] = snap
                if snap.id not in self._timeline:
                    self._timeline.append(snap.id)
                count += 1
        return count

    @logged()
    @safe_execute
    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            total_size = sum(s.size_bytes for s in self._snapshots.values())
            return {
                "total_snapshots": len(self._snapshots),
                "max_snapshots": self._max_snapshots,
                "snapshot_count": self._snapshot_count,
                "total_size_bytes": total_size,
                "timeline_length": len(self._timeline),
            }
