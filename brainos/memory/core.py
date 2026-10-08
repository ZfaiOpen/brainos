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
from dataclasses import dataclass, field
from typing import Any

from brainos.observability.auto_log import logged

logger = logging.getLogger("brainos.memory.core")


@dataclass
class CoreBelief:
    key: str
    value: Any
    immutable: bool = False
    confidence: float = 1.0
    category: str = "identity"
    metadata: dict[str, Any] = field(default_factory=dict)


class CoreMemory:
    def __init__(self) -> None:
        self._beliefs: dict[str, CoreBelief] = {}
        self._lock = threading.RLock()
        self._initialize_defaults()

    def _initialize_defaults(self):
            # 声明式配置: (key, value, immutable, category, confidence)
            defaults = [
                ("identity.name", "BrainOS", True, "identity", 1.0),
                ("identity.version", "2.0", False, "identity", 1.0),
                ("identity.purpose", "AI Capability Bus", True, "identity", 1.0),
                ("values.safety_first", True, True, "values", 1.0),
                ("values.privacy_by_default", True, True, "values", 1.0),
                ("values.transparency", True, False, "values", 0.9),
                ("values.user_autonomy", True, False, "values", 0.9),
                ("constraints.no_harm", True, True, "constraints", 1.0),
                ("constraints.no_deception", True, True, "constraints", 1.0),
            ]
            beliefs = getattr(self, "_beliefs", None)
            if not isinstance(beliefs, dict):
                logger.error("CoreMemory._initialize_defaults aborted: _beliefs is not initialized.")
                return
            for key, val, immutable, category, confidence in defaults:
                try:
                    beliefs[key] = CoreBelief(
                        key=key, value=val, immutable=immutable, category=category, confidence=confidence
                    )
                except Exception as _exc:
                    logger.warning("Failed to initialize default belief '%s': %s", key, _exc)


    @logged()
    @safe_execute
    def store(self, key: str, value: Any, immutable: bool = False, confidence: float = 1.0, category: str = "general") -> bool:
        with self._lock:
            existing = self._beliefs.get(key)
            if existing and existing.immutable:
                logger.warning("Cannot modify immutable core belief: %s", key)
                return False
            self._beliefs[key] = CoreBelief(key=key, value=value, immutable=immutable, confidence=confidence, category=category)
            return True

    @logged()
    @safe_execute
    def retrieve(self, key: str) -> Any | None:
        with self._lock:
            belief = self._beliefs.get(key)
            return belief.value if belief else None

    @logged()
    @async_compatible
    def retrieve_belief(self, key: str) -> CoreBelief | None:
        with self._lock:
            return self._beliefs.get(key)

    @logged()
    @safe_execute
    def delete(self, key: str) -> bool:
        with self._lock:
            belief = self._beliefs.get(key)
            if belief and belief.immutable:
                logger.warning("Cannot delete immutable core belief: %s", key)
                return False
            return self._beliefs.pop(key, None) is not None

    @logged()
    @safe_execute
    def get_by_category(self, category: str) -> list[CoreBelief]:
        with self._lock:
            return [b for b in self._beliefs.values() if b.category == category]

    @logged()
    @safe_execute
    def get_identity(self) -> dict[str, Any]:
        with self._lock:
            return {k: v.value for k, v in self._beliefs.items() if v.category == "identity"}

    @logged()
    @safe_execute
    def get_values(self) -> dict[str, Any]:
        with self._lock:
            return {k: v.value for k, v in self._beliefs.items() if v.category in ("values", "constraints")}

    @logged()
    @safe_execute
    def check_constraint(self, constraint_key: str) -> bool:
        with self._lock:
            belief = self._beliefs.get(constraint_key)
            if belief is None:
                return True
            return bool(belief.value)

    @property
    def size(self) -> int:
        return len(self._beliefs)
