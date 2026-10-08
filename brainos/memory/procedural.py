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
from typing import Any

from brainos.observability.auto_log import logged

logger = logging.getLogger("brainos.memory.procedural")


@dataclass
class Procedure:
    name: str
    steps: list[dict[str, Any]]
    category: str = "general"
    success_count: int = 0
    failure_count: int = 0
    last_used: float = field(default_factory=time.monotonic)
    created_at: float = field(default_factory=time.monotonic)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0

    @logged()
    @safe_execute
    def record_success(self, duration=None):
        pass


    @logged()
    @safe_execute
    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_used = time.monotonic()


class ProceduralMemory:
    def __init__(self, capacity: int = 200) -> None:
        self._capacity = capacity
        self._procedures: dict[str, Procedure] = {}
        self._lock = threading.RLock()

    @logged()
    @safe_execute
    def store(self, name: str, steps: list[dict[str, Any]], category: str = "general", metadata: dict[str, Any] | None = None) -> bool:
        with self._lock:
            if name in self._procedures:
                self._procedures[name].steps = steps
                self._procedures[name].category = category
                if metadata:
                    self._procedures[name].metadata.update(metadata)
                return True
            if len(self._procedures) >= self._capacity:
                self._evict()
            self._procedures[name] = Procedure(name=name, steps=steps, category=category, metadata=metadata or {})
            return True

    @logged()
    @safe_execute
    def retrieve(self, name: str) -> Procedure | None:
        with self._lock:
            proc = self._procedures.get(name)
            if proc:
                proc.last_used = time.monotonic()
            return proc

    @logged()
    @safe_execute
    def find_by_category(self, category: str) -> list[Procedure]:
        with self._lock:
            return [p for p in self._procedures.values() if p.category == category]

    @logged()
    @safe_execute
    def find_similar(self, task_description: str, top_k: int = 5) -> list[Procedure]:
        with self._lock:
            scored: list[tuple[float, Procedure]] = []
            task_lower = task_description.lower()
            for proc in self._procedures.values():
                score = 0.0
                name_lower = proc.name.lower()
                if name_lower in task_lower or task_lower in name_lower:
                    score += 2.0
                for step in proc.steps:
                    step_desc = str(step.get("description", "")).lower()
                    if any(w in step_desc for w in task_lower.split()):
                        score += 0.5
                score += proc.success_rate * 0.5
                scored.append((score, proc))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [p for _, p in scored[:top_k]]

    @logged()
    @safe_execute
    def record_outcome(self, name: str, success: bool) -> None:
        with self._lock:
            proc = self._procedures.get(name)
            if proc:
                if success:
                    proc.record_success()
                else:
                    proc.record_failure()

    def _evict(self) -> None:
        if not self._procedures:
            return
        worst = min(
            self._procedures.values(),
            key=lambda p: p.success_rate + (1 if p.success_count + p.failure_count > 0 else 0),
        )
        del self._procedures[worst.name]

    @logged()
    @safe_execute
    def clear(self) -> None:
        with self._lock:
            self._procedures.clear()

    @property
    def size(self) -> int:
        return len(self._procedures)
