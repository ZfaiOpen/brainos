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
import threading

import logging
from dataclasses import asdict, dataclass
from typing import Any


logger = logging.getLogger("brainos.memory.sdk")


@dataclass
class MemoryResult:
    id: str = ""
    content: str = ""
    confidence: float = 0.0
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MemoryClient:
    def __init__(self, api_key: str, base_url: str = "http://localhost:8080") -> None:
        self._lock = threading.RLock()
