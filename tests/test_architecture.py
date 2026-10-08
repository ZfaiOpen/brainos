# Copyright 2026 zfai-open contributors
#
# Copyright (C) 2026 Zfai Open
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Behavioral tests for the five architecture-grade memory components.

Carve batch 2, second phase: the smoke suite only proved these modules
import; this suite pins their actual behavior.

Components covered:
    MemoryConsolidator      multi-phase promotion/demotion pipeline
    MemoryWeaver            N→1 memory fusion with strategies
    Anchor / MemoryAnchor   content-addressed immutable anchors
    HippocampalDreamEngine  offline contradiction detection
    TemporalKnowledgeGraphV2  bi-temporal facts with sqlite persistence

Desensitization discipline: structural/invariant assertions only; no
tuning constants are pinned.
"""

from __future__ import annotations

import time

import pytest

from brainos.memory import (
    Anchor,
    AnchorStrength,
    AnchorType,
    ConsolidationPhase,
    MemoryAnchor,
    MemoryConsolidator,
    MemoryEntry,
    MemoryStore,
    MemoryWeaver,
    WeaveStrategy,
)
from brainos.memory.hippocampal_dream import HippocampalDreamEngine, MemoryItem


class TestMemoryConsolidator:
    def test_add_and_access_roundtrip(self) -> None:
        consol = MemoryConsolidator(store=MemoryStore())
        consol.add("k1", {"payload": 1}, importance=0.8)
        assert consol.access("k1") == {"payload": 1}
        assert consol.access("missing") is None

    def test_entry_promotes_after_thresholds_met(self) -> None:
        consol = MemoryConsolidator(store=MemoryStore())
        consol.add("k2", "v", importance=0.9)
        # ENCODE→STABILIZE thresholds are those of the NEXT phase:
        # min_age 300s, min_access 2, min_importance 0.4.
        consol.access("k2")
        consol.access("k2")
        entry = consol.get_entry("k2")
        entry.phase_entered_at -= 400.0

        results = consol.consolidate("k2")
        assert results, "expected a promotion result"
        assert results[0].promoted is True
        assert results[0].to_phase == ConsolidationPhase.STABILIZE
        assert consol.get_entry("k2").phase == ConsolidationPhase.STABILIZE

    def test_fresh_entry_does_not_promote(self) -> None:
        consol = MemoryConsolidator(store=MemoryStore())
        consol.add("k3", "v", importance=0.9)
        consol.access("k3")
        assert consol.consolidate("k3") == []  # below STABILIZE thresholds

    def test_demote_returns_entry_to_previous_phase(self) -> None:
        consol = MemoryConsolidator(store=MemoryStore())
        consol.add("k4", "v", importance=0.9)
        consol.access("k4")
        consol.access("k4")
        consol.get_entry("k4").phase_entered_at -= 400.0
        consol.consolidate("k4")

        demotion = consol.demote("k4", reason="test-demote")
        assert demotion is not None
        assert consol.get_entry("k4").phase == ConsolidationPhase.ENCODE

    def test_get_by_phase_partition_and_remove(self) -> None:
        consol = MemoryConsolidator(store=MemoryStore())
        consol.add("a", 1)
        consol.add("b", 2)
        encoded = consol.get_by_phase(ConsolidationPhase.ENCODE)
        assert {e.key for e in encoded} == {"a", "b"}
        assert consol.remove("a") is True
        assert consol.remove("a") is False
        assert consol.get_entry("a") is None


class TestMemoryWeaver:
    def test_weave_merges_keys_into_single_output(self) -> None:
        weaver = MemoryWeaver(store=MemoryStore())
        result = weaver.weave(["alpha", "beta"], strategy=WeaveStrategy.MERGE)
        assert result.success is True
        assert result.input_keys == ["alpha", "beta"]
        assert result.output_key  # non-empty target key
        assert result.tokens_saved >= 0
        assert result.duration_ms >= 0.0

    def test_weave_results_are_recorded_in_stats(self) -> None:
        weaver = MemoryWeaver(store=MemoryStore())
        weaver.weave(["a", "b"], strategy=WeaveStrategy.SUMMARIZE)
        stats = weaver.get_stats()
        assert stats["weave_count"] == 1
        assert stats["successful"] == 1
        assert len(weaver.get_results(limit=10)) == 1

    def test_every_strategy_returns_successful_result(self) -> None:
        for strategy in WeaveStrategy:
            weaver = MemoryWeaver(store=MemoryStore())
            result = weaver.weave(["x", "y"], strategy=strategy)
            assert result.success is True, f"strategy {strategy} failed"
            assert result.output_value is not None


class TestAnchor:
    def test_fingerprint_is_deterministic_and_content_addressed(self) -> None:
        a1 = Anchor(
            content="rule text",
            anchor_type=AnchorType.RULE,
            strength=AnchorStrength.STRONG,
            source="governance",
        )
        a2 = Anchor(
            content="rule text",
            anchor_type=AnchorType.RULE,
            strength=AnchorStrength.STRONG,
            source="governance",
        )
        assert a1.fingerprint == a2.fingerprint
        assert len(a1.fingerprint) == 16

    def test_verify_passes_for_unmodified_anchor(self) -> None:
        anchor = Anchor(
            content="decision record",
            anchor_type=AnchorType.DECISION,
            strength=AnchorStrength.PERMANENT,
        )
        assert anchor.verify() is True
        assert anchor.verify_immutability() is True

    def test_modified_permanent_anchor_fails_verification(self) -> None:
        anchor = Anchor(
            content="original law",
            anchor_type=AnchorType.RULE,
            strength=AnchorStrength.PERMANENT,
        )
        anchor.content = "tampered law"
        assert anchor.verify() is False
        assert anchor.verify_immutability() is False

    def test_derive_extends_lineage(self) -> None:
        parent = Anchor(
            content="parent",
            anchor_type=AnchorType.KNOWLEDGE,
            strength=AnchorStrength.STRONG,
        )
        child = parent.derive("child observation")
        assert parent.id in child.lineage
        assert child.strength == AnchorStrength.MEDIUM


class TestMemoryAnchor:
    def test_create_find_roundtrip(self) -> None:
        registry = MemoryAnchor()
        created = registry.create_anchor(
            content="unique content xyz",
            anchor_type=AnchorType.EVENT,
            strength=AnchorStrength.MEDIUM,
            source="tester",
        )
        assert registry.get(created.id) is not None
        assert registry.find_by_content("unique content xyz") is not None
        assert registry.find_by_fingerprint(created.fingerprint) is not None
        assert registry.find_by_type(AnchorType.EVENT) != []

    def test_verify_all_reports_intact_registry(self) -> None:
        registry = MemoryAnchor()
        registry.create_anchor(content="a", anchor_type=AnchorType.RULE, strength=AnchorStrength.PERMANENT)
        registry.create_anchor(content="b", anchor_type=AnchorType.RULE, strength=AnchorStrength.STRONG)
        report = registry.verify_all()
        assert report["total"] == 2
        assert report["corrupted"] == 0
        assert report["intact"] == 2

    def test_lineage_connects_derived_anchor(self) -> None:
        registry = MemoryAnchor()
        root = registry.create_anchor(content="root", anchor_type=AnchorType.DECISION)
        child = root.derive("child note")
        registry._anchors[child.id] = child  # register derived anchor
        lineage = registry.get_lineage(child.id)
        assert root.id in [a.id for a in lineage]


class TestHippocampalDreamEngine:
    def test_empty_cycle_is_a_noop_counted_cycle(self) -> None:
        engine = HippocampalDreamEngine(memory_store=None)
        result = engine.dream_cycle([])
        assert result.contradictions_found == 0
        assert result.memories_merged == 0
        assert engine.get_dream_stats()["dream_count"] >= 1

    def test_contradiction_detected_and_iron_law_proposed(self) -> None:
        now = time.time()
        engine = HippocampalDreamEngine(memory_store=None)
        result = engine.dream_cycle(
            [
                MemoryItem(key="fact:1", value="value-A", timestamp=now, domain="d1"),
                MemoryItem(key="fact:2", value="value-B", timestamp=now - 7200, domain="d1"),
            ]
        )
        assert result.contradictions_found == 1
        assert isinstance(result.iron_law_proposals, list)
        assert result.duration_ms >= 0.0

    def test_agreeing_memories_produce_no_contradiction(self) -> None:
        now = time.time()
        engine = HippocampalDreamEngine(memory_store=None)
        result = engine.dream_cycle(
            [
                MemoryItem(key="fact:1", value="same", timestamp=now, domain="d1"),
                MemoryItem(key="fact:2", value="same", timestamp=now, domain="d1"),
            ]
        )
        assert result.contradictions_found == 0


class TestTemporalKnowledgeGraphV2:
    @pytest.fixture()
    def kg(self, tmp_path):
        from brainos.memory.temporal_graph_v2 import TemporalKnowledgeGraphV2

        graph = TemporalKnowledgeGraphV2(db_path=str(tmp_path / "tg2.db"))
        yield graph
        graph.close()

    def test_entity_and_fact_roundtrip(self, kg) -> None:
        from brainos.memory.temporal_graph_v2 import EntityType, FactStatus

        entity = kg.add_entity("Alice", entity_type=EntityType.PERSON)
        assert entity.name == "Alice"

        fact = kg.add_fact("Alice", "works_at", "Acme", confidence=0.95)
        assert fact.is_active is True
        assert fact.status == FactStatus.ACTIVE

        active = kg.get_active_facts("Alice")
        assert len(active) == 1
        assert active[0].obj == "Acme"

    def test_new_fact_supersedes_active_one(self, kg) -> None:
        from brainos.memory.temporal_graph_v2 import FactStatus

        first = kg.add_fact("Bob", "role", "engineer")
        kg.add_fact("Bob", "role", "architect")

        active = kg.get_active_facts("Bob")
        assert len(active) == 1
        assert active[0].obj == "architect"
        assert first.status == FactStatus.SUPERSEDED

    def test_invalidate_fact_removes_it_from_active_set(self, kg) -> None:
        fact = kg.add_fact("Carol", "likes", "tea")
        assert kg.invalidate_fact(fact.fact_id) is True
        assert kg.invalidate_fact("fact_missing0") is False
        assert kg.get_active_facts("Carol") == []

    def test_stats_reflect_population(self, kg) -> None:
        kg.add_entity("Dave")
        kg.add_fact("Dave", "uses", "vim")
        stats = kg.get_stats()
        assert stats["total_entities"] >= 1
        assert stats["active_facts"] >= 1

    def test_facts_persist_across_sqlite_reopen(self, tmp_path) -> None:
        from brainos.memory.temporal_graph_v2 import TemporalKnowledgeGraphV2

        db = str(tmp_path / "tg2-durable.db")
        g1 = TemporalKnowledgeGraphV2(db_path=db)
        g1.add_fact("Eve", " speaks ", "esperanto".strip())
        g1.close()

        g2 = TemporalKnowledgeGraphV2(db_path=db)
        try:
            active = g2.get_active_facts("Eve")
            assert len(active) == 1
            assert active[0].obj == "esperanto"
        finally:
            g2.close()
