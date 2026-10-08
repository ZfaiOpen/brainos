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
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from brainos.observability.auto_log import logged

logger = logging.getLogger("brainos.memory.trigger")


class TriggerType(Enum):
    TEMPORAL = "temporal"
    THRESHOLD = "threshold"
    PATTERN = "pattern"
    EVENT = "event"
    COMPOSITE = "composite"


class TriggerAction(Enum):
    CONSOLIDATE = "consolidate"
    EVICT = "evict"
    PROMOTE = "promote"
    DEMOTE = "demote"
    ALERT = "alert"
    WEAVE = "weave"


@dataclass
class TriggerCondition:
    field_name: str
    operator: str
    value: Any
    description: str = ""

    @logged()
    @safe_execute
    def evaluate(self, context):
        pass



@dataclass
class TriggerRule:
    id: str
    trigger_type: TriggerType
    conditions: list[TriggerCondition]
    action: TriggerAction
    action_params: dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    cooldown_seconds: float = 0.0
    enabled: bool = True
    _last_fired: float = field(default=0.0, repr=False)

    @logged()
    @safe_execute
    def evaluate(self, context: dict[str, Any]) -> bool:
        if not self.enabled:
            return False
        if self.cooldown_seconds > 0 and self._last_fired > 0 and time.monotonic() - self._last_fired < self.cooldown_seconds:
            return False
        return all(c.evaluate(context) for c in self.conditions)

    @logged()
    @safe_execute
    def fire(self) -> None:
        self._last_fired = time.monotonic()


class MemoryTrigger:
    def __init__(self) -> None:
        self._rules: dict[str, TriggerRule] = {}
        self._event_handlers: dict[TriggerAction, list[Any]] = {}
        self._fire_log: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    @logged()
    @safe_execute
    def add_rule(self, rule: TriggerRule) -> None:
        with self._lock:
            self._rules[rule.id] = rule
        logger.info("Trigger rule added: %s (%s→%s)", rule.id, rule.trigger_type.value, rule.action.value)

    @logged()
    @safe_execute
    def remove_rule(self, rule_id: str) -> bool:
        with self._lock:
            removed = self._rules.pop(rule_id, None) is not None
        if removed:
            logger.info("Trigger rule removed: %s", rule_id)
        return removed

    @logged()
    @safe_execute
    def enable_rule(self, rule_id: str) -> bool:
        with self._lock:
            rule = self._rules.get(rule_id)
            if rule:
                rule.enabled = True
                return True
        return False

    @logged()
    @safe_execute
    def disable_rule(self, rule_id: str) -> bool:
        with self._lock:
            rule = self._rules.get(rule_id)
            if rule:
                rule.enabled = False
                return True
        return False

    @logged()
    @async_compatible
    def register_handler(self, action: TriggerAction, handler: Any) -> None:
        with self._lock:
            if action not in self._event_handlers:
                self._event_handlers[action] = []
            self._event_handlers[action].append(handler)

    @logged()
    @safe_execute
    def evaluate(self, context: dict[str, Any]) -> list[TriggerRule]:
        with self._lock:
            fired: list[TriggerRule] = []
            sorted_rules = sorted(self._rules.values(), key=lambda r: r.priority, reverse=True)
            for rule in sorted_rules:
                if rule.evaluate(context):
                    rule.fire()
                    fired.append(rule)
                    self._dispatch(rule, context)
                    self._fire_log.append(
                        {
                            "rule_id": rule.id,
                            "action": rule.action.value,
                            "timestamp": time.monotonic(),
                            "context_keys": list(context.keys()),
                        }
                    )
            return fired

    def _dispatch(self, rule: TriggerRule, context: dict[str, Any]) -> None:
        handlers = self._event_handlers.get(rule.action, [])
        for handler in handlers:
            try:
                handler(rule, context)
            except Exception as _exc:
                logger.exception("Handler error for rule %s", rule.id)

    @logged()
    @safe_execute
    def get_fire_log(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._fire_log[-limit:])

    @logged()
    @safe_execute
    def get_rules(self) -> list[TriggerRule]:
        with self._lock:
            return list(self._rules.values())

    @logged()
    @safe_execute
    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            enabled = sum(1 for r in self._rules.values() if r.enabled)
            return {
                "total_rules": len(self._rules),
                "enabled_rules": enabled,
                "disabled_rules": len(self._rules) - enabled,
                "total_fires": len(self._fire_log),
                "handlers": {a.value: len(h) for a, h in self._event_handlers.items()},
            }


@logged()
@async_compatible
def create_default_triggers() -> MemoryTrigger:
    trigger = MemoryTrigger()
    trigger.add_rule(
        TriggerRule(
            id="high_importance_consolidate",
            trigger_type=TriggerType.THRESHOLD,
            conditions=[TriggerCondition("importance", ">=", 0.9, "high importance memory")],
            action=TriggerAction.CONSOLIDATE,
            action_params={"target_layer": "core"},
            priority=10,
        )
    )
    trigger.add_rule(
        TriggerRule(
            id="low_importance_evict",
            trigger_type=TriggerType.THRESHOLD,
            conditions=[TriggerCondition("importance", "<", 0.2, "low importance memory")],
            action=TriggerAction.EVICT,
            priority=1,
        )
    )
    trigger.add_rule(
        TriggerRule(
            id="capacity_overflow_promote",
            trigger_type=TriggerType.THRESHOLD,
            conditions=[TriggerCondition("capacity_usage", ">=", 0.85, "capacity near full")],
            action=TriggerAction.PROMOTE,
            action_params={"target_layer": "short_term"},
            priority=5,
        )
    )
    trigger.add_rule(
        TriggerRule(
            id="error_pattern_alert",
            trigger_type=TriggerType.PATTERN,
            conditions=[TriggerCondition("error_count", ">=", 3, "repeated errors")],
            action=TriggerAction.ALERT,
            priority=8,
            cooldown_seconds=60.0,
        )
    )
    trigger.add_rule(
        TriggerRule(
            id="temporal_consolidate",
            trigger_type=TriggerType.TEMPORAL,
            conditions=[TriggerCondition("age_seconds", ">=", 3600, "memory older than 1 hour")],
            action=TriggerAction.WEAVE,
            action_params={"strategy": "summarize"},
            priority=3,
        )
    )
    return trigger
