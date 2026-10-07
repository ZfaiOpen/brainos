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
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import logging

logger = logging.getLogger(__name__)


class IntegrityStatus(str, Enum):
    VALID = "valid"
    TAMPERED = "tampered"
    CORRUPTED = "corrupted"
    MISSING = "missing"
    REPAIRED = "repaired"


@dataclass
class IntegrityRecord:
    record_id: str = ""
    content_hash: str = ""
    anchor_hash: str = ""
    parent_hash: str = ""
    timestamp: float = 0.0
    tier: str = ""
    status: IntegrityStatus = IntegrityStatus.VALID
    verification_count: int = 0
    last_verified: float = 0.0

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = time.time()


@dataclass
class IntegrityReport:
    total_records: int = 0
    valid_count: int = 0
    tampered_count: int = 0
    corrupted_count: int = 0
    missing_count: int = 0
    repaired_count: int = 0
    anchor_chain_valid: bool = True
    verification_time_ms: float = 0.0
    details: list[dict[str, Any]] = field(default_factory=list)


class MemoryIntegrityGuard:
    _CHAIN_FILE = "anchor_chain.json"
    _MAX_RECORDS = 10000

    def __init__(self, storage_path: str | None = None) -> None:
        self._records: dict[str, IntegrityRecord] = {}
        self._anchor_chain: list[str] = []
        self._lock = threading.Lock()
        self._verification_count: int = 0
        self._repair_count: int = 0
        self._chain_genesis_hash = self._compute_hash("brainos_genesis_anchor_v1")

    def register_memory(self, record_id, content, tier="", is_anchor=False):
            if not record_id or content is None:
                logger.warning("register_memory rejected invalid input: id=%s", bool(record_id))
                return IntegrityRecord(record_id=str(record_id or ""), status=IntegrityStatus.CORRUPTED)

            try:
                content_hash = self._compute_hash(content)
                parent_hash = getattr(self, '_anchor_chain', None)[-1] if getattr(self, '_anchor_chain', None) else self._chain_genesis_hash
                current_time = time.time()

                record = IntegrityRecord(
                    record_id=record_id,
                    content_hash=content_hash,
                    anchor_hash=content_hash if is_anchor else "",
                    parent_hash=parent_hash,
                    tier=tier,
                    status=IntegrityStatus.VALID,
                    verification_count=1,
                    last_verified=current_time,
                )

                with self._lock:
                    getattr(self, '_records', [])[record_id] = record
                    if is_anchor:
                        getattr(self, '_anchor_chain', None).append(content_hash)
                    if len(getattr(self, '_records', [])) > getattr(self, '_MAX_RECORDS', 0):
                        oldest = sorted(getattr(self, '_records', []).items(), key=lambda x: x[1].timestamp)
                        for rid, _ in oldest[: len(getattr(self, '_records', [])) - getattr(self, '_MAX_RECORDS', 0)]:
                            del getattr(self, '_records', [])[rid]
                return record

            except Exception as _exc:
                logger.error("register_memory failed critically for %s: %s", record_id, _exc, exc_info=False)
                return IntegrityRecord(record_id=record_id, status=IntegrityStatus.CORRUPTED)


    def verify_memory(self, record_id: str, current_content: str) -> IntegrityStatus:
        with self._lock:
            record = self._records.get(record_id)

        if record is None:
            return IntegrityStatus.MISSING

        current_hash = self._compute_hash(current_content)
        record.verification_count += 1
        record.last_verified = time.time()

        if current_hash == record.content_hash:
            record.status = IntegrityStatus.VALID
            return IntegrityStatus.VALID

        if record.anchor_hash and current_hash != record.anchor_hash:
            record.status = IntegrityStatus.TAMPERED
            logger.warning("Memory tampering detected: %s (expected=%s, got=%s)", record_id, record.content_hash[:8], current_hash[:8])
            return IntegrityStatus.TAMPERED

        record.status = IntegrityStatus.CORRUPTED
        return IntegrityStatus.CORRUPTED

    def verify_anchor_chain(self):
            try:
                with self._lock:
                    if not getattr(self, '_anchor_chain', None):
                        return True
                    if not getattr(self, '_records', []):
                        logger.warning("Anchor chain has %d links but no base records exist.", len(getattr(self, '_anchor_chain', None)))
                        return False
                    chain_snapshot = list(getattr(self, '_anchor_chain', None))
                    valid_anchors = {
                        r.anchor_hash: r.parent_hash
                        for r in getattr(self, '_records', []).values()
                        if r.anchor_hash
                    }

                if chain_snapshot[0] not in valid_anchors and len(chain_snapshot) > 0:
                    if valid_anchors.get(chain_snapshot[0]) != self._chain_genesis_hash:
                        logger.warning("Anchor chain genesis link broken at position 0")
                        return False

                for i in range(1, len(chain_snapshot)):
                    prev_hash = chain_snapshot[i - 1]
                    curr_hash = chain_snapshot[i]
                    expected_parent = valid_anchors.get(curr_hash)
                    if expected_parent is None or expected_parent != prev_hash:
                        logger.warning(
                            "Anchor chain break at position %d: expected parent %s, got %s",
                            i, prev_hash[:8], str(expected_parent)[:8] if expected_parent else "None"
                        )
                        return False

                return True
            except Exception as _exc:
                logger.error("Anchor chain verification failed critically: %s", _exc, exc_info=False)
                return False


    def full_verification(self, memory_store: Any = None) -> IntegrityReport:
        start = time.monotonic()
        report = IntegrityReport()

        with self._lock:
            report.total_records = len(self._records)
            records_copy = dict(self._records)

        for rid, record in records_copy.items():
            if record.status == IntegrityStatus.VALID:
                report.valid_count += 1
            elif record.status == IntegrityStatus.TAMPERED:
                report.tampered_count += 1
                report.details.append(
                    {
                        "record_id": rid,
                        "status": "tampered",
                        "tier": record.tier,
                    }
                )
            elif record.status == IntegrityStatus.CORRUPTED:
                report.corrupted_count += 1
                report.details.append(
                    {
                        "record_id": rid,
                        "status": "corrupted",
                        "tier": record.tier,
                    }
                )
            elif record.status == IntegrityStatus.MISSING:
                report.missing_count += 1

        report.anchor_chain_valid = self.verify_anchor_chain()
        report.verification_time_ms = (time.monotonic() - start) * 1000
        self._verification_count += 1

        return report

    def attempt_repair(self, record_id: str, backup_content: str | None = None) -> IntegrityStatus:
        with self._lock:
            record = self._records.get(record_id)

        if record is None:
            return IntegrityStatus.MISSING

        if backup_content is not None:
            backup_hash = self._compute_hash(backup_content)
            if backup_hash == record.content_hash:
                record.status = IntegrityStatus.REPAIRED
                self._repair_count += 1
                logger.info("Memory repaired from backup: %s", record_id)
                return IntegrityStatus.REPAIRED

        record.status = IntegrityStatus.CORRUPTED
        return IntegrityStatus.CORRUPTED

    def _compute_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            status_counts: dict[str, int] = {}
            for record in self._records.values():
                key = record.status.value
                status_counts[key] = status_counts.get(key, 0) + 1

            return {
                "total_records": len(self._records),
                "anchor_chain_length": len(self._anchor_chain),
                "status_distribution": status_counts,
                "total_verifications": self._verification_count,
                "total_repairs": self._repair_count,
            }

    def health_check(self) -> dict[str, Any]:
        with self._lock:
            corrupted = sum(1 for r in self._records.values() if r.status == IntegrityStatus.TAMPERED)
            return {
                "healthy": corrupted == 0,
                "total_records": len(self._records),
                "corrupted_count": corrupted,
                "anchor_chain_intact": self.verify_anchor_chain(),
                "timestamp": time.time(),
            }

    def memory_count(self) -> int:
        return len(self._records)

    def get_records(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "record_id": r.record_id,
                    "status": r.status.value,
                    "tier": r.tier,
                    "verification_count": r.verification_count,
                    "last_verified": r.last_verified,
                }
                for r in self._records.values()
            ]

    def anchor_chain_length(self) -> int:
        return len(self._anchor_chain)

    def tampered_records(self) -> list[str]:
        with self._lock:
            return [rid for rid, r in self._records.items() if r.status == IntegrityStatus.TAMPERED]

    def record_count(self) -> int:
        with self._lock:
            return len(self._records)

    def anchor_count(self) -> int:
        return len(self._anchor_chain)

    def verification_count(self) -> int:
        return self._verification_count

    def reset_records(self) -> dict[str, Any]:
        with self._lock:
            old_count = len(self._records)
            old_anchors = len(self._anchor_chain)
            self._records.clear()
            self._anchor_chain.clear()
            self._verification_count = 0
            self._repair_count = 0
            return {"cleared_records": old_count, "cleared_anchors": old_anchors}
