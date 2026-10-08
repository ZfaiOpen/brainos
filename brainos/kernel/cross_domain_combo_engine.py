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
"""Stub module: cross-domain combo engine (import-compatibility surface).

The full cross-domain combo engine (rule matching, multi-domain event routing,
reflex/rollback chains) is NOT part of the open-source baseline. It ships in
the commercial version only.

This stub keeps ``from brainos.kernel.cross_domain_combo_engine import ...``
working so the open-core memory engine degrades gracefully: ``ComboEngine``
instances are no-ops that log and discard events.

The full engine is available in the commercial version.
"""

from __future__ import annotations

import logging
import threading
import time
import hashlib
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger("brainos.kernel.cross_domain_combo_engine")


class ComboDomain(str, Enum):
    COGNITION = "cognition"
    MEMORY = "memory"
    SECURITY = "security"
    PROTOCOL = "protocol"
    EVOLUTION = "evolution"
    COST = "cost"
    GOVERNANCE = "governance"


class ComboTrigger(str, Enum):
    HIGH_LOAD = "high_load"
    SECURITY_THREAT = "security_threat"
    COST_ANOMALY = "cost_anomaly"
    EVOLUTION_PROPOSAL = "evolution_proposal"
    COMPLIANCE_CHECK = "compliance_check"
    MEMORY_SYNC = "memory_sync"
    AUDIT_EVENT = "audit_event"
    CROSS_DOMAIN_INSIGHT = "cross_domain_insight"
    CIRCUIT_BREAKER_OPEN = "circuit_breaker_open"
    OBSERVABILITY_ALERT = "observability_alert"
    SKILL_USED = "skill_used"
    KNOWLEDGE_UPDATED = "knowledge_updated"
    DISTILLATION_COMPLETED = "distillation_completed"
    OUTPUT_VALIDATION_FAILED = "output_validation_failed"
    CONTEXT_RETRIEVAL_REQUESTED = "context_retrieval_requested"
    PROTOCOL_BRIDGE_REQUESTED = "protocol_bridge_requested"


class ComboAction(str, Enum):
    DEGRADE_AND_PROTECT = "degrade_and_protect"
    VACCINATE_AND_EVOLVE = "vaccinate_and_evolve"
    AUDIT_AND_COMPLY = "audit_and_comply"
    PREDICT_AND_ROUTE = "predict_and_route"
    SYNC_AND_VERIFY = "sync_and_verify"
    TEST_AND_QUANTIFY = "test_and_quantify"
    REFLEX_AND_ROLLBACK = "reflex_and_rollback"
    FULL_CHAIN_GUARD = "full_chain_guard"
    SELF_HEAL_AND_RECOVER = "self_heal_and_recover"
    ANOMALY_EVOLVE_PREVENT = "anomaly_evolve_prevent"
    SKILL_CAPABILITY_BRIDGE = "skill_capability_bridge"
    KNOWLEDGE_RAG_INJECT = "knowledge_rag_inject"
    DISTILLATION_EVOLVE_FEEDBACK = "distillation_evolve_feedback"


@dataclass
class ComboRule:
    rule_id: str = ""
    name: str = ""
    trigger: ComboTrigger = ComboTrigger.HIGH_LOAD
    source_domains: list[ComboDomain] = field(default_factory=list)
    target_domains: list[ComboDomain] = field(default_factory=list)
    action: ComboAction = ComboAction.DEGRADE_AND_PROTECT
    priority: int = 0
    enabled: bool = True
    description: str = ""
    fire_count: int = 0
    last_fired: float = 0.0

    def __post_init__(self) -> None:
        if not self.rule_id:
            raw = f"{self.name}:{self.trigger.value}:{self.action.value}"
            self.rule_id = f"combo_{hashlib.sha256(raw.encode()).hexdigest()[:10]}"


@dataclass
class ComboEvent:
    event_id: str = ""
    trigger: ComboTrigger = ComboTrigger.HIGH_LOAD
    source_domain: ComboDomain = ComboDomain.COGNITION
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = time.time()
        if not self.event_id:
            self.event_id = f"evt_{hashlib.sha256(f'{self.trigger.value}:{self.timestamp}'.encode()).hexdigest()[:10]}"


@dataclass
class ComboResult:
    rule_id: str = ""
    action: ComboAction = ComboAction.DEGRADE_AND_PROTECT
    domains_affected: list[str] = field(default_factory=list)
    success: bool = False
    details: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    fitness_score: float = 0.0


class CrossDomainComboEngine:
    """Open-core stub: accepts events, runs no rules (commercial version only)."""

    _instance: CrossDomainComboEngine | None = None
    _init_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._rules: dict[str, ComboRule] = {}
        self._event_history: deque[ComboEvent] = deque(maxlen=1000)
        self._domain_handlers: dict[ComboDomain, dict[str, Callable[..., Any]]] = {}
        self._lock = threading.RLock()

    @classmethod
    def get_instance(cls) -> CrossDomainComboEngine:
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def fire_event(self, event: ComboEvent) -> ComboResult | None:
        """No-op sink. Full rule evaluation is commercial version only."""
        with self._lock:
            self._event_history.append(event)
        logger.debug("combo engine stub: event %s discarded (commercial version only)", event.event_id)
        return None

    def register_rule(self, rule: ComboRule) -> bool:
        with self._lock:
            self._rules[rule.rule_id] = rule
        return True

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "engine": "stub",
                "mode": "open-core (commercial version only)",
                "rules": len(self._rules),
                "events_received": len(self._event_history),
            }
