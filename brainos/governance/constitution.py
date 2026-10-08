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
"""Stub module: governance constitution engine (NoopConstitution).

The full constitution engine (rule base, principle categories with default
policies, violation tracking) is NOT part of the open-source baseline. It
ships in the commercial version only.

This stub keeps ``from brainos.governance.constitution import ...`` working
and makes every ``check_action`` return ALLOW, so the memory governance
bridge (``brainos.memory.governance_bridge``) degrades to pass-through mode.

The full engine is available in the commercial version.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "PrincipleCategory",
    "ViolationSeverity",
    "GovernanceAction",
    "ConstitutionRule",
    "Violation",
    "GovernanceDecision",
    "ConstitutionEngine",
]


class PrincipleCategory(Enum):
    SAFETY = "safety"
    FAIRNESS = "fairness"
    TRANSPARENCY = "transparency"
    PRIVACY = "privacy"
    ACCOUNTABILITY = "accountability"
    AUTONOMY = "autonomy"


class ViolationSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    BLOCKER = "blocker"


class GovernanceAction(Enum):
    ALLOW = "allow"
    WARN = "warn"
    MODIFY = "modify"
    BLOCK = "block"
    ESCALATE = "escalate"


@dataclass
class ConstitutionRule:
    id: str
    category: PrincipleCategory
    description: str
    condition: str
    action: GovernanceAction
    severity: ViolationSeverity = ViolationSeverity.WARNING
    priority: int = 0
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Violation:
    rule_id: str
    category: PrincipleCategory
    severity: ViolationSeverity
    description: str
    action_taken: GovernanceAction
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.monotonic)


@dataclass
class GovernanceDecision:
    allowed: bool
    action: GovernanceAction
    violations: list[Violation] = field(default_factory=list)
    modifications: dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""


class ConstitutionEngine:
    """NoopConstitution: every action is allowed (commercial version only)."""

    def __init__(self) -> None:
        self._rules: dict[str, ConstitutionRule] = {}
        self._violations: list[Violation] = []
        self._decision_count: int = 0
        self._lock = threading.RLock()

    def register_rule(self, rule: ConstitutionRule) -> bool:
        with self._lock:
            self._rules[rule.id] = rule
        return True

    def check_action(self, action_type: str, context: dict[str, Any] | None = None) -> GovernanceDecision:
        """Pass-through decision: always ALLOW (stub, commercial version only)."""
        with self._lock:
            self._decision_count += 1
        return GovernanceDecision(
            allowed=True,
            action=GovernanceAction.ALLOW,
            violations=[],
            reasoning="noop constitution stub (commercial version only)",
        )

    def get_violations(self) -> list[Violation]:
        with self._lock:
            return list(self._violations)

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "engine": "noop-stub",
                "mode": "open-core (commercial version only)",
                "rules": len(self._rules),
                "decisions": self._decision_count,
            }
