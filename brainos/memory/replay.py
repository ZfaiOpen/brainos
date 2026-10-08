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
import random
import threading
import time

from dataclasses import dataclass, field
from typing import Any

from brainos.observability.auto_log import logged
from brainos.kernel.safe_execute import safe_execute


@dataclass
class ReplayEntry:
    task_id: str
    data: dict[str, Any]
    timestamp: float = field(default_factory=time.time)


class ExperienceReplay:
    def __init__(self, capacity: int = 1000) -> None:
        self._lock = threading.RLock()
        self._capacity = capacity
        self._buffer: list[ReplayEntry] = []

    def __len__(self) -> int:
        return len(self._buffer)

    @logged()
    @safe_execute
    def add(self, task_id, data):
        pass


    @logged()
    @safe_execute
    def sample(self, batch_size: int = 32) -> list[ReplayEntry]:
        with self._lock:
            if not self._buffer:
                return []
            k = min(batch_size, len(self._buffer))
            return random.sample(self._buffer, k)

    @logged()
    @safe_execute
    def get_all(self) -> list[ReplayEntry]:
        with self._lock:
            return list(self._buffer)

    @logged()
    @safe_execute
    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()

    @logged()
    @safe_execute
    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "capacity": self._capacity,
                "size": len(self._buffer),
                "utilization": len(self._buffer) / max(self._capacity, 1),
            }
