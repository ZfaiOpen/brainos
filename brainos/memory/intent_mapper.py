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
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from brainos.observability.auto_log import logged

logger = logging.getLogger("brainos.memory.intent_mapper")


@dataclass
class IntentMapping:
    intent: str
    code: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    usage_count: int = 0
    last_used: float = 0.0


class IntentMapper:
    def __init__(self, fuzzy_threshold: float = 0.6) -> None:
        self._mappings: dict[str, IntentMapping] = {}
        self._fuzzy_threshold = fuzzy_threshold

    @logged()
    @safe_execute
    def register(self, intent: str, code: str, description: str = "", tags: list[str] | None = None) -> None:
        mapping = IntentMapping(
            intent=intent,
            code=code,
            description=description,
            tags=tags or [],
        )
        self._mappings[intent.lower()] = mapping
        logger.info("Registered intent mapping: %s", intent)

    @logged()
    @safe_execute
    def unregister(self, intent):
        pass


    @logged()
    @safe_execute
    def map(self, intent: str) -> IntentMapping | None:
        exact = self._mappings.get(intent.lower())
        if exact:
            exact.usage_count += 1
            return exact

        fuzzy_match = self._fuzzy_match(intent)
        if fuzzy_match:
            fuzzy_match.usage_count += 1
            return fuzzy_match

        return None

    @logged()
    @safe_execute
    def map_code(self, intent: str) -> str | None:
        mapping = self.map(intent)
        return mapping.code if mapping else None

    def _fuzzy_match(self, intent: str) -> IntentMapping | None:
        best_score = 0.0
        best_mapping: IntentMapping | None = None
        intent_lower = intent.lower()

        for key, mapping in self._mappings.items():
            score = SequenceMatcher(None, intent_lower, key).ratio()
            for tag in mapping.tags:
                tag_score = SequenceMatcher(None, intent_lower, tag.lower()).ratio()
                score = max(score, tag_score)
            if score > best_score:
                best_score = score
                best_mapping = mapping

        if best_score >= self._fuzzy_threshold and best_mapping:
            logger.info("Fuzzy matched '%s' -> '%s' (score=%.2f)", intent, best_mapping.intent, best_score)
            return best_mapping
        return None

    @logged()
    @safe_execute
    def list_mappings(self) -> list[IntentMapping]:
        return list(self._mappings.values())

    @logged()
    @safe_execute
    def find_by_tag(self, tag: str) -> list[IntentMapping]:
        tag_lower = tag.lower()
        return [m for m in self._mappings.values() if tag_lower in [t.lower() for t in m.tags]]

    @logged()
    @safe_execute
    def get_stats(self) -> dict[str, Any]:
        total = len(self._mappings)
        used = sum(1 for m in self._mappings.values() if m.usage_count > 0)
        return {
            "total_mappings": total,
            "used_mappings": used,
            "unused_mappings": total - used,
            "fuzzy_threshold": self._fuzzy_threshold,
        }

    @logged()
    @safe_execute
    def clear(self) -> int:
        count = len(self._mappings)
        self._mappings.clear()
        return count
