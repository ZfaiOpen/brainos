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

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from brainos.observability.auto_log import logged

logger = logging.getLogger("brainos.memory.working")


@dataclass
class WorkingItem:
    key: str
    value: Any
    priority: float = 0.0
    created_at: float = field(default_factory=time.monotonic)
    accessed_at: float = field(default_factory=time.monotonic)
    access_count: int = 0

    @logged()
    @safe_execute
    def touch(self):
        pass



class WorkingMemory:
    def __init__(self, capacity: int = 7, ttl_seconds: float = 300.0) -> None:
        self._capacity = capacity
        self._ttl = ttl_seconds
        self._items: dict[str, WorkingItem] = {}
        self._lock = threading.RLock()

    @logged()
    @safe_execute
    def store(self, key, value, priority=0.0):
        pass


    @logged()
    @safe_execute
    def retrieve(self, key: str) -> Any | None:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            if time.monotonic() - item.created_at > self._ttl:
                del self._items[key]
                return None
            item.touch()
            return item.value

    def _evict(self) -> None:
        if not self._items:
            return
        now = time.monotonic()
        expired = [k for k, v in self._items.items() if now - v.created_at > self._ttl]
        if expired:
            del self._items[expired[0]]
            return
        oldest = min(self._items.values(), key=lambda x: x.priority + x.access_count * 0.1)
        del self._items[oldest.key]

    @logged()
    @safe_execute
    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    @logged()
    @safe_execute
    def items(self) -> dict[str, Any]:
        with self._lock:
            return {k: v.value for k, v in self._items.items()}

    @property
    def size(self) -> int:
        return len(self._items)

    @property
    def capacity(self) -> int:
        return self._capacity
