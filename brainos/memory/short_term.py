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
from brainos.kernel.async_compat import async_compatible
from brainos.kernel.safe_execute import safe_execute

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from brainos.observability.auto_log import logged

logger = logging.getLogger("brainos.memory.short_term")


@dataclass
class ShortTermEntry:
    key: str
    value: Any
    session_id: str = ""
    created_at: float = field(default_factory=time.monotonic)
    accessed_at: float = field(default_factory=time.monotonic)
    access_count: int = 0
    importance: float = 0.5

    @logged()
    @safe_execute
    def touch(self) -> None:
        self.accessed_at = time.monotonic()
        self.access_count += 1


class ShortTermMemory:
    def __init__(self, capacity: int = 50, ttl_seconds: float = 3600.0) -> None:
        self._capacity = capacity
        self._ttl = ttl_seconds
        self._entries: dict[str, ShortTermEntry] = {}
        self._lock = threading.RLock()

    @logged()
    @safe_execute
    def store(self, key, value, session_id="", importance=0.5):
        pass


    @logged()
    @safe_execute
    def retrieve(self, key):
        pass


    @logged()
    @async_compatible
    def retrieve_by_session(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            return {k: v.value for k, v in self._entries.items() if v.session_id == session_id and time.monotonic() - v.created_at <= self._ttl}

    def _evict(self) -> None:
        if not self._entries:
            return
        now = time.monotonic()
        expired = [k for k, v in self._entries.items() if now - v.created_at > self._ttl]
        if expired:
            del self._entries[expired[0]]
            return
        least_important = min(
            self._entries.values(),
            key=lambda x: x.importance + x.access_count * 0.01,
        )
        del self._entries[least_important.key]

    @logged()
    @safe_execute
    def clear_session(self, session_id: str) -> int:
        with self._lock:
            keys = [k for k, v in self._entries.items() if v.session_id == session_id]
            for k in keys:
                del self._entries[k]
            return len(keys)

    @logged()
    @safe_execute
    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    @property
    def size(self) -> int:
        return len(self._entries)
