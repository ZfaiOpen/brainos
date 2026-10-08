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
import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from brainos.governance.constitution import ConstitutionEngine, GovernanceAction
from brainos.kernel.safe_execute import safe_call

logger = logging.getLogger(__name__)


@dataclass
class MemoryGovernanceBridgeStats:
    total_audits: int = 0
    compliant: int = 0
    violations: int = 0
    by_operation: dict[str, int] = field(default_factory=dict)
    bridge_errors: int = 0


class MemoryGovernanceBridge:
    _instance: MemoryGovernanceBridge | None = None
    _init_lock: threading.Lock = threading.Lock()

    def __init__(self, constitution: Any | None = None) -> None:
        self._constitution: Any = constitution
        self._stats = MemoryGovernanceBridgeStats()
        self._lock = threading.Lock()
        self._sensitive_layers: set[str] = {"core", "semantic"}

    @classmethod
    def get_instance(cls) -> MemoryGovernanceBridge:
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def bind_constitution(self, constitution: ConstitutionEngine) -> None:
        self._constitution = constitution

    from typing import Any
    def audit_memory_access(self, operation, key, layer, accessor=""):
            try:
                if not operation or not key or not layer:
                    with self._lock:
                        self._stats.bridge_errors += 1
                    return GovernanceAction.BLOCK

                with self._lock:
                    self._stats.total_audits += 1
                    self._stats.by_operation[operation] = self._stats.by_operation.get(operation, 0) + 1

                action = self._evaluate_risk() if hasattr(self, '_evaluate_risk') else None

                if self._constitution is not None:
                    safe_call(
                        lambda: self._constitution.check_action(
                            action_type="memory_access",
                            context={"operation": operation, "key": key, "layer": layer, "accessor": accessor},
                        ),
                        default=None,
                    )

                with self._lock:
                    if action == GovernanceAction.ALLOW:
                        self._stats.compliant += 1
                    else:
                        self._stats.violations += 1

                if action != GovernanceAction.ALLOW:
                    logger.warning("Memory audit blocked: op=%s layer=%s accessor=%s action=%s", operation, layer, accessor, action)

                return action
            except Exception as _exc:
                logger.warning("Audit failed: %s (op=%s key=%s)", _exc, operation, key)
                with self._lock:
                    self._stats.bridge_errors += 1
                return GovernanceAction.BLOCK

            op_lower = operation.lower()
            key_lower = key.lower()
            is_trusted = bool(accessor) and accessor in getattr(self, '_trusted_accessors', set())

            if layer in getattr(self, '_sensitive_layers', None) and op_lower == "delete":
                return GovernanceAction.BLOCK
            if layer == "core" and op_lower in ("modify", "overwrite") and not is_trusted:
                return GovernanceAction.BLOCK
            if layer == "core" and op_lower in ("modify", "overwrite"):
                return GovernanceAction.WARN
            if not is_trusted and any(s in key_lower for s in ("personal", "secret", "credential", "token")):
                return GovernanceAction.WARN
            if op_lower == "read" and "personal" in key_lower:
                return GovernanceAction.WARN

            return GovernanceAction.ALLOW


    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "total_audits": self._stats.total_audits,
                "compliant": self._stats.compliant,
                "violations": self._stats.violations,
                "by_operation": dict(self._stats.by_operation),
                "bridge_errors": self._stats.bridge_errors,
            }
