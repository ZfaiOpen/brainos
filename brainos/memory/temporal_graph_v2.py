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
# ═══════════════════════════════════════════════════════════════════════════
# FROZEN AT v0.9.0
# This file is version-anchored to the open-source v0.9.0 baseline: its
# evolution is frozen in the open repository and v1.x improvements live in
# the commercial version only. Do not evolve this file here.
# ═══════════════════════════════════════════════════════════════════════════
from __future__ import annotations
import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from brainos.kernel.auto_log import logged
from brainos.kernel.safe_execute import safe_execute


class _EdgeType(str, Enum):
    RELATED_TO = "related_to"
    DEPENDS_ON = "depends_on"
    SUPERSEDES = "supersedes"
    DERIVED_FROM = "derived_from"
    CONTRADICTS = "contradicts"


logger = logging.getLogger("brainos.memory.temporal_graph_v2")


class FactStatus(Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"


class EntityType(Enum):
    PERSON = "person"
    ORGANIZATION = "organization"
    CONCEPT = "concept"
    PROJECT = "project"
    TOOL = "tool"
    DECISION = "decision"
    CUSTOM = "custom"


class EdgeType(Enum):
    WORKS_ON = "works_on"
    BELONGS_TO = "belongs_to"
    DEPENDS_ON = "depends_on"
    PREFERRED = "preferred"
    DECIDED = "decided"
    RELATED_TO = "related_to"
    SUPERSEDES = "supersedes"
    CUSTOM = "custom"


@dataclass
class TemporalFact:
    fact_id: str = ""
    subject: str = ""
    predicate: str = ""
    obj: str = ""
    valid_from: float = field(default_factory=time.time)
    valid_to: float = 0.0
    invalidated_at: float = 0.0
    recorded_at: float = field(default_factory=time.time)
    status: FactStatus = FactStatus.ACTIVE
    confidence: float = 1.0
    source: str = ""
    ttl_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.fact_id:
            self.fact_id = f"fact_{uuid.uuid4().hex[:8]}"

    @property
    def is_active(self) -> bool:
        if self.status != FactStatus.ACTIVE:
            return False
        now = time.time()
        if self.valid_to > 0 and now > self.valid_to:
            return False
        if self.ttl_seconds > 0 and (now - self.recorded_at) > self.ttl_seconds:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.obj,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "invalidated_at": self.invalidated_at,
            "recorded_at": self.recorded_at,
            "status": self.status.value,
            "confidence": self.confidence,
            "source": self.source,
            "ttl_seconds": self.ttl_seconds,
        }


@dataclass
class GraphEntity:
    entity_id: str = ""
    entity_type: EntityType = EntityType.CUSTOM
    name: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    access_count: int = 0

    def __post_init__(self) -> None:
        if not self.entity_id:
            self.entity_id = f"ent_{uuid.uuid4().hex[:8]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type.value,
            "name": self.name,
            "attributes": self.attributes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "access_count": self.access_count,
        }


@dataclass
class MemoryGraphEdge:
    edge_id: str = ""
    source_id: str = ""
    edge_type: EdgeType = EdgeType.RELATED_TO
    target_id: str = ""
    fact: TemporalFact | None = None
    strength: float = 1.0
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.edge_id:
            self.edge_id = f"edge_{uuid.uuid4().hex[:8]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_id": self.source_id,
            "edge_type": self.edge_type.value,
            "target_id": self.target_id,
            "strength": self.strength,
            "fact": self.fact.to_dict() if self.fact else None,
        }


class SearchMode(Enum):
    SEMANTIC = "semantic"
    KEYWORD = "keyword"
    GRAPH_TRAVERSAL = "graph_traversal"
    HYBRID = "hybrid"


class TemporalKnowledgeGraphV2:
    def __init__(
        self,
        db_path: str = "",
        enable_fts: bool = True,
    ) -> None:
        if not db_path:
            try:
                from brainos.core.paths import paths as _paths  # commercial version only

                db_path = str(_paths.data_dir / "temporal_graph.db")
            except ImportError:
                # open-source build: brainos.core is commercial-only; fall back
                # to a repository-local data directory.
                db_path = str(Path(__file__).resolve().parent.parent.parent / "data" / "temporal_graph.db")
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._entities: dict[str, GraphEntity] = {}
        self._edges: dict[str, GraphEdge] = {}
        self._facts: dict[str, TemporalFact] = {}
        self._enable_fts = enable_fts
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self) -> None:
        try:
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    entity_id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    attributes TEXT DEFAULT '{}',
                    created_at REAL,
                    updated_at REAL,
                    access_count INTEGER DEFAULT 0
                )
            """)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS edges (
                    edge_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    edge_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    strength REAL DEFAULT 1.0,
                    created_at REAL,
                    fact_id TEXT
                )
            """)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS facts (
                    fact_id TEXT PRIMARY KEY,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object TEXT NOT NULL,
                    valid_from REAL,
                    valid_to REAL DEFAULT 0,
                    invalidated_at REAL DEFAULT 0,
                    status TEXT DEFAULT 'active',
                    confidence REAL DEFAULT 1.0,
                    source TEXT DEFAULT ''
                )
            """)
            if self._enable_fts:
                self._conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
                        fact_id, subject, predicate, object, source,
                        content=facts, content_rowid=rowid
                    )
                """)
            self._conn.commit()
            self._load_from_db()
        except Exception as _exc:
            logger.exception("Failed to initialize temporal graph database")

    def _load_from_db(self) -> None:
        try:
            for row in self._conn.execute("SELECT * FROM entities"):
                entity = GraphEntity(
                    entity_id=row[0],
                    entity_type=EntityType(row[1]),
                    name=row[2],
                    attributes=json.loads(row[3]),
                    created_at=row[4],
                    updated_at=row[5],
                    access_count=row[6],
                )
                self._entities[entity.entity_id] = entity

            for row in self._conn.execute("SELECT * FROM facts"):
                fact = TemporalFact(
                    fact_id=row[0],
                    subject=row[1],
                    predicate=row[2],
                    obj=row[3],
                    valid_from=row[4],
                    valid_to=row[5],
                    invalidated_at=row[6],
                    status=FactStatus(row[7]),
                    confidence=row[8],
                    source=row[9],
                )
                self._facts[fact.fact_id] = fact
        except Exception as _exc:
            logger.exception("Failed to load from database")

    @logged()
    @safe_execute
    def add_entity(
        self,
        name: str,
        entity_type: EntityType | int | str = EntityType.CUSTOM,
        attributes: dict[str, Any] | None = None,
    ) -> GraphEntity:
        if isinstance(entity_type, int):
            try:
                entity_type = EntityType(entity_type)
            except ValueError:
                entity_type = EntityType.CUSTOM
        elif isinstance(entity_type, str):
            try:
                entity_type = EntityType(entity_type)
            except ValueError:
                entity_type = EntityType.CUSTOM
        existing = self._find_entity_by_name(name)
        if existing:
            existing.access_count += 1
            existing.updated_at = time.time()
            if attributes:
                existing.attributes.update(attributes)
            self._persist_entity(existing)
            return existing

        entity = GraphEntity(
            entity_type=entity_type,
            name=name,
            attributes=attributes or {},
        )
        self._entities[entity.entity_id] = entity
        self._persist_entity(entity)
        return entity

    @logged()
    @safe_execute
    def add_fact(
        self,
        subject: str,
        predicate: str,
        obj: str,
        valid_from: float | None = None,
        valid_to: float = 0.0,
        confidence: float = 1.0,
        source: str = "",
        ttl_seconds: float = 0.0,
    ) -> TemporalFact:
        active = self._find_active_fact(subject, predicate)
        if active:
            active.status = FactStatus.SUPERSEDED
            active.invalidated_at = time.time()
            self._persist_fact(active)

            supersede_edge = GraphEdge(
                source_id=active.fact_id,
                edge_type=EdgeType.SUPERSEDES,
                target_id="",
            )
            self._edges[supersede_edge.edge_id] = supersede_edge

        fact = TemporalFact(
            subject=subject,
            predicate=predicate,
            obj=obj,
            valid_from=valid_from or time.time(),
            valid_to=valid_to,
            confidence=confidence,
            source=source,
            ttl_seconds=ttl_seconds,
        )
        self._facts[fact.fact_id] = fact
        self._persist_fact(fact)
        return fact

    @logged()
    @safe_execute
    def add_edge(
        self,
        source_id: str,
        edge_type: EdgeType,
        target_id: str,
        fact: TemporalFact | None = None,
        strength: float = 1.0,
    ) -> GraphEdge:
        edge = GraphEdge(
            source_id=source_id,
            edge_type=edge_type,
            target_id=target_id,
            fact=fact,
            strength=strength,
        )
        self._edges[edge.edge_id] = edge
        self._persist_edge(edge)
        return edge

    @logged()
    @safe_execute
    def search(
        self,
        query: str,
        mode: SearchMode = SearchMode.HYBRID,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        if mode in (SearchMode.KEYWORD, SearchMode.HYBRID):
            results.extend(self._keyword_search(query, limit))

        if mode in (SearchMode.GRAPH_TRAVERSAL, SearchMode.HYBRID):
            results.extend(self._graph_search(query, limit))

        if mode == SearchMode.SEMANTIC:
            results.extend(self._keyword_search(query, limit))

        seen_ids: set[str] = set()
        unique_results: list[dict[str, Any]] = []
        for r in results:
            rid = r.get("fact_id", r.get("entity_id", ""))
            if rid not in seen_ids:
                seen_ids.add(rid)
                unique_results.append(r)

        return unique_results[:limit]

    @logged()
    @safe_execute
    def get_active_facts(self, subject: str = "") -> list[TemporalFact]:
        facts = [f for f in self._facts.values() if f.is_active]
        if subject:
            facts = [f for f in facts if f.subject == subject]
        return facts

    @logged()
    @safe_execute
    def get_entity_relations(self, entity_id: str, depth: int = 1) -> list[GraphEdge]:
        direct = [e for e in self._edges.values() if e.source_id == entity_id or e.target_id == entity_id]
        if depth <= 1:
            return direct

        visited: set[str] = {entity_id}
        all_edges: list[GraphEdge] = list(direct)
        frontier = direct

        for _ in range(depth - 1):
            next_frontier: list[GraphEdge] = []
            for edge in frontier:
                for nid in (edge.source_id, edge.target_id):
                    if nid not in visited:
                        visited.add(nid)
                        neighbor_edges = [e for e in self._edges.values() if e.source_id == nid or e.target_id == nid]
                        next_frontier.extend(neighbor_edges)
                        all_edges.extend(neighbor_edges)
            frontier = next_frontier
            if not frontier:
                break

        return all_edges

    @logged()
    @safe_execute
    def invalidate_fact(self, fact_id: str) -> bool:
        fact = self._facts.get(fact_id)
        if not fact:
            return False
        fact.status = FactStatus.INVALIDATED
        fact.invalidated_at = time.time()
        self._persist_fact(fact)
        return True

    @logged()
    @safe_execute
    def get_context_block(self, subject: str = "", max_facts: int = 20) -> str:
        facts = self.get_active_facts(subject)
        facts.sort(key=lambda f: f.confidence, reverse=True)
        facts = facts[:max_facts]

        lines: list[str] = []
        for fact in facts:
            status_str = "active" if fact.is_active else fact.status.value
            lines.append(f"- {fact.subject} {fact.predicate} {fact.obj} [{status_str}, confidence={fact.confidence:.1f}]")

        return "\n".join(lines) if lines else "No active facts found."

    @logged()
    @safe_execute
    def get_stats(self) -> dict[str, Any]:
        active_facts = sum(1 for f in self._facts.values() if f.is_active)
        return {
            "total_entities": len(self._entities),
            "total_edges": len(self._edges),
            "total_facts": len(self._facts),
            "active_facts": active_facts,
            "superseded_facts": sum(1 for f in self._facts.values() if f.status == FactStatus.SUPERSEDED),
            "invalidated_facts": sum(1 for f in self._facts.values() if f.status == FactStatus.INVALIDATED),
            "entity_type_counts": self._count_entity_types(),
            "edge_type_counts": self._count_edge_types(),
            "db_path": str(self._db_path),
            "communities": len(self.detect_communities()),
        }

    @logged()
    @safe_execute
    def detect_communities(self, min_size: int = 2) -> list[dict[str, Any]]:
        adjacency: dict[str, set[str]] = {}
        for edge in self._edges.values():
            adjacency.setdefault(edge.source_id, set()).add(edge.target_id)
            adjacency.setdefault(edge.target_id, set()).add(edge.source_id)

        visited: set[str] = set()
        communities: list[dict[str, Any]] = []

        for entity_id in self._entities:
            if entity_id in visited:
                continue
            community: set[str] = set()
            queue = [entity_id]
            while queue:
                node = queue.pop(0)
                if node in visited:
                    continue
                visited.add(node)
                community.add(node)
                for neighbor in adjacency.get(node, set()):
                    if neighbor not in visited:
                        queue.append(neighbor)

            if len(community) >= min_size:
                entities = [self._entities[eid] for eid in community if eid in self._entities]
                community_facts = [f for f in self._facts.values() if f.subject in {e.name for e in entities} and f.is_active]
                communities.append(
                    {
                        "size": len(community),
                        "entity_ids": list(community),
                        "entity_names": [e.name for e in entities],
                        "active_fact_count": len(community_facts),
                        "types": list({e.entity_type.value for e in entities}),
                    }
                )

        return sorted(communities, key=lambda c: c["size"], reverse=True)

    @logged()
    @safe_execute
    def search_dual_layer(self, query: str, limit: int = 10) -> dict[str, Any]:
        low_level = self._keyword_search(query, limit)
        communities = self.detect_communities(min_size=2)
        high_level: list[dict[str, Any]] = []
        query_lower = query.lower()

        for community in communities:
            entity_names = community.get("entity_names", [])
            if any(query_lower in name.lower() for name in entity_names):
                high_level.append(
                    {
                        "type": "community",
                        "community_size": community["size"],
                        "entity_names": entity_names[:5],
                        "active_fact_count": community["active_fact_count"],
                    }
                )

        return {
            "query": query,
            "low_level_results": low_level[:limit],
            "high_level_communities": high_level[:5],
            "total_low": len(low_level),
            "total_high": len(high_level),
        }

    def _find_entity_by_name(self, name: str) -> GraphEntity | None:
            if not isinstance(name, str) or not name.strip():
                return None
            try:
                if not hasattr(self, "_entity_name_index"):
                    self._entity_name_index = {
                        ent.name: ent for ent in self._entities.values()
                    }
                found = self._entity_name_index.get(name)
                if found is not None:
                    return found
                for entity in self._entities.values():
                    if entity.name == name:
                        self._entity_name_index[entity.name] = entity
                        return entity
                return None
            except Exception as _exc:
                logger.warning(
                    "KnowledgeGraph._find_entity_by_name index lookup failed, "
                    "falling back to linear scan. Error: %s",
                    _exc,
                    exc_info=False
                )
                try:
                    for entity in self._entities.values():
                        if entity.name == name:
                            return entity
                except Exception as _fallback_exc:
                    logger.error(
                        "KnowledgeGraph._find_entity_by_name fallback scan critically failed: %s",
                        _fallback_exc
                    )
                return None

    def _find_active_fact(self, subject: str, predicate: str) -> TemporalFact | None:
        for fact in self._facts.values():
            if fact.subject == subject and fact.predicate == predicate and fact.is_active:
                return fact
        return None

    def _keyword_search(self, query: str, limit: int) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        query_lower = query.lower()
        for fact in self._facts.values():
            if not fact.is_active:
                continue
            searchable = f"{fact.subject} {fact.predicate} {fact.obj}".lower()
            if query_lower in searchable:
                results.append({"fact_id": fact.fact_id, "subject": fact.subject, "predicate": fact.predicate, "object": fact.obj, "confidence": fact.confidence, "type": "fact"})
        for entity in self._entities.values():
            if query_lower in entity.name.lower():
                results.append({"entity_id": entity.entity_id, "name": entity.name, "entity_type": entity.entity_type.value, "type": "entity"})
        return results[:limit]

    def _graph_search(self, query: str, limit: int) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        seed_entities = [e for e in self._entities.values() if query.lower() in e.name.lower()]
        for entity in seed_entities[:3]:
            edges = self.get_entity_relations(entity.entity_id, depth=2)
            for edge in edges[:5]:
                target = self._entities.get(edge.target_id)
                if target:
                    results.append({"entity_id": target.entity_id, "name": target.name, "edge_type": edge.edge_type.value, "type": "related_entity"})
                if edge.fact and edge.fact.is_active:
                    results.append({"fact_id": edge.fact.fact_id, "subject": edge.fact.subject, "predicate": edge.fact.predicate, "object": edge.fact.obj, "type": "related_fact"})
        return results[:limit]

    def _persist_entity(self, entity: GraphEntity) -> None:
        if self._conn is None:
            return
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO entities VALUES (?,?,?,?,?,?,?)",
                (entity.entity_id, entity.entity_type.value, entity.name, json.dumps(entity.attributes), entity.created_at, entity.updated_at, entity.access_count),
            )
            self._conn.commit()
        except Exception as _exc:
            logger.exception("Failed to persist entity")

    def _persist_fact(self, fact: TemporalFact) -> None:
        if self._conn is None:
            return
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO facts VALUES (?,?,?,?,?,?,?,?,?,?)",
                (fact.fact_id, fact.subject, fact.predicate, fact.obj, fact.valid_from, fact.valid_to, fact.invalidated_at, fact.status.value, fact.confidence, fact.source),
            )
            self._conn.commit()
        except Exception as _exc:
            logger.exception("Failed to persist fact")

    def _persist_edge(self, edge: GraphEdge) -> None:
        if self._conn is None:
            return
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO edges VALUES (?,?,?,?,?,?,?)",
                (edge.edge_id, edge.source_id, edge.edge_type.value, edge.target_id, edge.strength, edge.created_at, edge.fact.fact_id if edge.fact else None),
            )
            self._conn.commit()
        except Exception as _exc:
            logger.exception("Failed to persist edge")

    def _count_entity_types(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self._entities.values():
            key = e.entity_type.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _count_edge_types(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self._edges.values():
            key = e.edge_type.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @logged()
    @safe_execute
    def expire_ttl_facts(self) -> list[str]:
        now = time.time()
        expired_ids: list[str] = []
        for fact_id, fact in list(self._facts.items()):
            if fact.status == FactStatus.ACTIVE:
                if fact.ttl_seconds > 0 and (now - fact.recorded_at) > fact.ttl_seconds:
                    fact.status = FactStatus.EXPIRED
                    fact.invalidated_at = now
                    self._persist_fact(fact)
                    expired_ids.append(fact_id)
                elif fact.valid_to > 0 and now > fact.valid_to:
                    fact.status = FactStatus.EXPIRED
                    fact.invalidated_at = now
                    self._persist_fact(fact)
                    expired_ids.append(fact_id)
        return expired_ids

    @logged()
    @safe_execute
    def apply_hebbian_reinforcement(self, decay_rate: float = 0.01, boost_rate: float = 0.05) -> dict[str, Any]:
        now = time.time()
        boosted_entities = 0
        decayed_edges = 0

        for entity in self._entities.values():
            if entity.access_count > 0:
                recency = 1.0 / (1.0 + (now - entity.updated_at) / 86400.0)
                frequency = min(1.0, entity.access_count / 10.0)
                boost_rate * recency * frequency
                entity.access_count += 1
                entity.updated_at = now
                self._persist_entity(entity)
                boosted_entities += 1

        for edge in self._edges.values():
            edge.strength *= 1.0 - decay_rate
            if edge.strength < 0.01:
                edge.strength = 0.01
            self._persist_edge(edge)
            decayed_edges += 1

        return {
            "boosted_entities": boosted_entities,
            "decayed_edges": decayed_edges,
            "total_entities": len(self._entities),
            "total_edges": len(self._edges),
        }

    @logged()
    @safe_execute
    def deduplicate_entities(self, similarity_threshold: float = 0.8) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        entity_list = list(self._entities.values())
        consumed: set[str] = set()

        for i, entity_a in enumerate(entity_list):
            if entity_a.entity_id in consumed:
                continue
            for j in range(i + 1, len(entity_list)):
                entity_b = entity_list[j]
                if entity_b.entity_id in consumed:
                    continue
                if entity_a.entity_type != entity_b.entity_type:
                    continue
                name_sim = self._compute_name_similarity(entity_a.name, entity_b.name)
                if name_sim >= similarity_threshold:
                    entity_a.access_count += entity_b.access_count
                    entity_a.attributes.update(entity_b.attributes)
                    entity_a.updated_at = time.time()
                    self._persist_entity(entity_a)

                    for edge in self._edges.values():
                        if edge.source_id == entity_b.entity_id:
                            edge.source_id = entity_a.entity_id
                            self._persist_edge(edge)
                        if edge.target_id == entity_b.entity_id:
                            edge.target_id = entity_a.entity_id
                            self._persist_edge(edge)

                    del self._entities[entity_b.entity_id]
                    consumed.add(entity_b.entity_id)
                    merged.append(
                        {
                            "kept": entity_a.name,
                            "merged": entity_b.name,
                            "similarity": round(name_sim, 3),
                        }
                    )

        return merged

    @logged()
    @safe_execute
    def extract_from_text(self, text: str, source: str = "") -> dict[str, Any]:
        entities_found: list[dict[str, str]] = []
        facts_found: list[dict[str, str]] = []

        patterns = [
            ("uses", "tool"),
            ("depends_on", "dependency"),
            ("belongs_to", "membership"),
            ("manages", "authority"),
            ("creates", "creation"),
            ("integrates_with", "integration"),
            ("synergizes_with", "synergy"),
        ]

        text_lower = text.lower()
        words = set(text_lower.split())

        for entity_name in words:
            if len(entity_name) > 3 and entity_name.isalpha():
                existing = self._find_entity_by_name(entity_name)
                if existing is None:
                    entity = self.add_entity(
                        name=entity_name,
                        entity_type=EntityType.CONCEPT,
                        attributes={"auto_extracted": True, "source": source},
                    )
                    if entity:
                        entities_found.append({"name": entity_name, "type": "concept"})

        for predicate, category in patterns:
            if predicate in text_lower:
                parts = text_lower.split(predicate, 1)
                if len(parts) == 2:
                    subject = parts[0].strip().split()[-1] if parts[0].strip() else ""
                    obj = parts[1].strip().split()[0] if parts[1].strip() else ""
                    if subject and obj:
                        fact = self.add_fact(
                            subject=subject,
                            predicate=predicate,
                            obj=obj,
                            confidence=0.6,
                            source=source or "auto_extract",
                        )
                        if fact:
                            facts_found.append(
                                {
                                    "subject": subject,
                                    "predicate": predicate,
                                    "object": obj,
                                }
                            )

        return {
            "entities_found": entities_found,
            "facts_found": facts_found,
            "total_entities": len(entities_found),
            "total_facts": len(facts_found),
        }

    @staticmethod
    def _compute_name_similarity(name_a: str, name_b: str) -> float:
        if name_a == name_b:
            return 1.0
        a_lower = name_a.lower()
        b_lower = name_b.lower()
        if a_lower == b_lower:
            return 0.95
        set_a = set(a_lower)
        set_b = set(b_lower)
        if not set_a or not set_b:
            return 0.0
        intersection = set_a & set_b
        union = set_a | set_b
        jaccard = len(intersection) / len(union)
        prefix_len = 0
        for ca, cb in zip(a_lower, b_lower):
            if ca == cb:
                prefix_len += 1
            else:
                break
        prefix_sim = prefix_len / max(len(a_lower), len(b_lower))
        return 0.5 * jaccard + 0.5 * prefix_sim


GraphEdge = MemoryGraphEdge
