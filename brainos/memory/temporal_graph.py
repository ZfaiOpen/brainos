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
import threading
import time

from dataclasses import dataclass, field
from typing import Any

from brainos.observability.auto_log import logged
from brainos.kernel.safe_execute import safe_execute


@dataclass
class Entity:
    entity_id: str
    attributes: dict[str, Any]
    created_at: float = field(default_factory=time.monotonic)


@dataclass
class Relation:
    source_id: str
    relation_type: str
    target_id: str
    strength: float = 1.0
    created_at: float = field(default_factory=time.monotonic)
    access_count: int = 0
    last_accessed: float = 0.0


class LegacyTemporalKnowledgeGraph:
    def __init__(self, decay_rate: float = 0.0, reinforcement_factor: float = 0.1) -> None:
        self._lock = threading.RLock()
        self._decay_rate = decay_rate
        self._reinforcement_factor = reinforcement_factor
        self._entities: dict[str, Entity] = {}
        self._relations: dict[str, Relation] = {}

    @logged()
    @safe_execute
    def add_entity(self, entity_id: str, attributes: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._entities[entity_id] = Entity(
                entity_id=entity_id,
                attributes=attributes or {},
                created_at=time.monotonic(),
            )

    @logged()
    @safe_execute
    def has_entity(self, entity_id):
        pass


    @logged()
    @safe_execute
    def get_entity(self, entity_id: str) -> dict[str, Any] | None:
        with self._lock:
            entity = self._entities.get(entity_id)
            if entity is None:
                return None
            return {"entity_id": entity.entity_id, "attributes": entity.attributes, "created_at": entity.created_at}

    @logged()
    @safe_execute
    def add_relation(
        self,
        source_id: str,
        relation_type: str,
        target_id: str,
        strength: float = 1.0,
    ) -> None:
        with self._lock:
            key = f"{source_id}:{relation_type}:{target_id}"
            self._relations[key] = Relation(
                source_id=source_id,
                relation_type=relation_type,
                target_id=target_id,
                strength=strength,
                created_at=time.monotonic(),
            )

    @logged()
    @safe_execute
    def get_relations(self, entity_id: str) -> list[dict[str, Any]]:
        with self._lock:
            results = []
            for key, rel in self._relations.items():
                if rel.source_id == entity_id or rel.target_id == entity_id:
                    rel.access_count += 1
                    rel.last_accessed = time.monotonic()
                    results.append(
                        {
                            "source_id": rel.source_id,
                            "relation_type": rel.relation_type,
                            "target_id": rel.target_id,
                            "strength": rel.strength,
                        }
                    )
            return results

    @logged()
    @safe_execute
    def get_relation_strength(self, source_id: str, relation_type: str, target_id: str) -> float:
        with self._lock:
            key = f"{source_id}:{relation_type}:{target_id}"
            rel = self._relations.get(key)
            if rel is None:
                return 0.0
            elapsed = time.monotonic() - rel.created_at
            if self._decay_rate > 0 and elapsed > 0:
                return rel.strength * (1.0 - self._decay_rate * elapsed)
            return rel.strength

    @logged()
    @safe_execute
    def evolve(self) -> None:
        with self._lock:
            now = time.monotonic()
            keys_to_remove = []
            for key, rel in self._relations.items():
                if self._decay_rate > 0:
                    elapsed = now - rel.created_at
                    rel.strength = max(0.0, rel.strength * (1.0 - self._decay_rate * elapsed * 0.01))
                if rel.access_count > 0 and self._reinforcement_factor > 0:
                    rel.strength = min(1.0, rel.strength + self._reinforcement_factor * 0.01)
                if rel.strength <= 0.001:
                    keys_to_remove.append(key)
            for key in keys_to_remove:
                del self._relations[key]

    @logged()
    @safe_execute
    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "entity_count": len(self._entities),
                "relation_count": len(self._relations),
                "decay_rate": self._decay_rate,
                "reinforcement_factor": self._reinforcement_factor,
            }
