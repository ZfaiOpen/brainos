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
from brainos.kernel.resilience import resilient
from brainos.kernel.async_compat import async_compatible

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from brainos.memory.store import MemoryStore
from brainos.observability.auto_log import logged

logger = logging.getLogger("brainos.memory.distiller")


class DistillationStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class DistillationRequest:
    id: str = ""
    source_entry_id: str = ""
    source_content: str = ""
    distilled_content: str = ""
    status: DistillationStatus = DistillationStatus.PENDING
    created_at: float = field(default_factory=time.time)
    reviewed_at: float = 0.0
    reviewer: str = ""
    notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class Distiller:
    def __init__(
        self,
        store: MemoryStore | None = None,
        auto_approve_threshold: float = 0.9,
        pending_ttl: float = 86400.0,
    ) -> None:
        self._store = store
        self._auto_approve_threshold = auto_approve_threshold
        self._pending_ttl = pending_ttl
        self._requests: dict[str, DistillationRequest] = {}
        self._counter: int = 0

    @logged()
    @resilient(max_retries=2, fallback=None)
    @safe_execute
    @async_compatible
    def set_store(self, store: MemoryStore) -> None:
        self._store = store

    @logged()
    @safe_execute
    def submit(self, source_entry_id, source_content, distilled_content, confidence=0.0, metadata=None):
        pass


    @logged()
    @resilient(max_retries=2, fallback=None)
    @safe_execute
    @async_compatible
    def approve(self, request_id, reviewer="human"):
        pass


    @logged()
    @resilient(max_retries=2, fallback=None)
    @safe_execute
    @async_compatible
    def reject(self, request_id: str, reviewer: str = "human", notes: str = "") -> DistillationRequest | None:
        request = self._requests.get(request_id)
        if request is None:
            return None
        if request.status != DistillationStatus.PENDING:
            return None
        request.status = DistillationStatus.REJECTED
        request.reviewed_at = time.time()
        request.reviewer = reviewer
        request.notes = notes
        logger.info("Rejected distillation %s by %s", request_id, reviewer)
        return request

    @logged()
    @resilient(max_retries=2, fallback=None)
    @safe_execute
    @async_compatible
    def get_pending(self) -> list[DistillationRequest]:
        self._expire_old_requests()
        return [r for r in self._requests.values() if r.status == DistillationStatus.PENDING]

    @logged()
    @safe_execute
    def get_request(self, request_id: str) -> DistillationRequest | None:
        return self._requests.get(request_id)

    @logged()
    @resilient(max_retries=2, fallback=None)
    @safe_execute
    @async_compatible
    def get_stats(self) -> dict[str, Any]:
        counts = {s: 0 for s in DistillationStatus}
        for r in self._requests.values():
            counts[r.status] += 1
        return {
            "total_requests": len(self._requests),
            "by_status": {s.value: c for s, c in counts.items()},
            "auto_approve_threshold": self._auto_approve_threshold,
        }

    def _apply_distillation(self, request: DistillationRequest) -> None:
        if self._store is None:
            return
        entry = self._store.retrieve(request.source_entry_id)
        if entry is not None:
            self._store.update(entry.id, content=request.distilled_content)

    def _expire_old_requests(self) -> None:
        now = time.time()
        for request in list(self._requests.values()):
            if request.status == DistillationStatus.PENDING and (now - request.created_at) > self._pending_ttl:
                request.status = DistillationStatus.EXPIRED
                request.reviewed_at = now
                request.reviewer = "system"
