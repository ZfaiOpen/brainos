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
"""Known upstream gaps: pass-stub methods inherited from the source baseline.

ATTRIBUTION (AST sweep, source vs staging, keyed by file+function):
all 24 pass-only methods in the open memory core exist identically upstream
(/opt/brainos_new) — the v0.9 carve introduced ZERO stubs. The only source
stub not carried over lives in the private file fidelity.py.

FULL INVENTORY (brainos/memory only):
    active_recall.py   recall
    consolidator.py    age_seconds
    context.py         push
    dedup.py           scan, _build_similarity_calculator
    distiller.py       submit, approve
    episode.py         from_dict
    forgetting.py      model (property getter)
    intent_mapper.py   unregister
    manager.py         get_instance
    neural_plasticity.py  hebbian_learn
    procedural.py      record_success
    replay.py          add
    short_term.py      store, retrieve
    snapshot.py        to_dict
    temporal_awareness.py  is_valid
    temporal_graph.py  has_entity
    trigger.py         evaluate
    working.py         touch, store

CLOSED in v0.9.1 (ratchet retired, probes below are now real behavioral
tests): MemoryStore.retrieve, RecallEngine.recall — filled to make the AML
contract surface (POST /add, POST /search) live on a real multi-channel
retrieval engine.

These probes assert the INTENDED behavior with ``xfail(strict=True)``:
they xfail today (stub returns None), and the moment someone fills a stub
in they XPASS and FAIL the suite — forcing the marker to be removed and
the method to be covered by a real behavioral test. This is a ratchet:
stubs can only move from "known gap" to "tested behavior", never back.

Carve batch 2: coverage extended from 9 probes (10 stubs) to the FULL
inventory — every one of the 24 memory stubs now has a strict-xfail probe.
"""

from __future__ import annotations

import pytest

from brainos.memory import (
    Deduplicator,
    MemoryEntry,
    MemoryStore,
)
from brainos.memory.episode import Episode, EpisodeStore
from brainos.memory.short_term import ShortTermMemory
from brainos.memory.working import WorkingMemory


def test_store_single_entry_retrieve() -> None:
    store = MemoryStore()
    mid = store.store(MemoryEntry(content="find me"))
    assert store.retrieve(mid) is not None


@pytest.mark.xfail(reason="upstream pass-stub: WorkingMemory.store", strict=True)
def test_working_memory_store_roundtrip() -> None:
    wm = WorkingMemory()
    wm.store("k", "v")
    assert wm.retrieve("k") == "v"


@pytest.mark.xfail(reason="upstream pass-stub: ShortTermMemory.store/retrieve", strict=True)
def test_short_term_store_roundtrip() -> None:
    stm = ShortTermMemory()
    stm.store("k", "v", session_id="s1")
    assert stm.retrieve("k") == "v"


@pytest.mark.xfail(reason="upstream pass-stub: Episode.from_dict", strict=True)
def test_episode_from_dict_roundtrip() -> None:
    ep = Episode(events=[{"a": 1}], tags=["t"])
    clone = Episode.from_dict(ep.to_dict())
    assert clone.episode_id == ep.episode_id


@pytest.mark.xfail(reason="upstream pass-stub: Deduplicator.scan", strict=True)
def test_dedup_scan_returns_result() -> None:
    store = MemoryStore()
    store.store(MemoryEntry(content="one"))
    result = Deduplicator(store).scan()
    assert result is not None


@pytest.mark.xfail(reason="upstream pass-stub: ExperienceReplay.add", strict=True)
def test_replay_add_grows_buffer() -> None:
    from brainos.memory.replay import ExperienceReplay

    replay = ExperienceReplay()
    replay.add("task-1", {"step": 1})
    assert len(replay) == 1


def test_recall_engine_returns_results() -> None:
    from brainos.memory import RecallEngine, RecallMode

    store = MemoryStore()
    store.store(MemoryEntry(content="quantum flux theory", importance=0.9))
    hits = RecallEngine(store).recall("quantum", mode=RecallMode.HYBRID)
    assert hits, "recall returned nothing for a stored keyword"


@pytest.mark.xfail(reason="upstream pass-stub: MemoryManager.get_instance singleton", strict=True)
def test_manager_get_instance_singleton() -> None:
    from brainos.memory.manager import MemoryManager

    assert MemoryManager.get_instance() is not None


@pytest.mark.xfail(reason="upstream pass-stub: ForgettingCurve.model getter", strict=True)
def test_forgetting_curve_model_getter() -> None:
    from brainos.memory import CurveModel, ForgettingCurve

    fc = ForgettingCurve(model=CurveModel.EBBINGHAUS)
    assert fc.model is not None


def test_episode_store_writes_are_durable(tmp_path) -> None:
    """Companion (non-xfail) regression proving the harness detects real
    persistence, so the xfail probes above cannot lull anyone."""
    db = str(tmp_path / "durability.db")
    ep = Episode(events=[{"n": 1}], tags=["durable"])
    EpisodeStore(db_path=db).append(ep)
    again = EpisodeStore(db_path=db)
    loaded = again.get_episode(ep.episode_id)
    assert loaded is not None and loaded.tags == ["durable"]


# --------------------------------------------------------------------------
# Batch 2: probes for the remaining 14 memory stubs (full 24/24 coverage).
# --------------------------------------------------------------------------


@pytest.mark.xfail(reason="upstream pass-stub: ActiveRecallEngine.recall", strict=True)
def test_active_recall_returns_result_for_stored_content() -> None:
    from brainos.memory import ActiveRecallEngine

    store = MemoryStore()
    store.store(MemoryEntry(content="ferromagnetic domains align"))
    result = ActiveRecallEngine(store).recall("ferromagnetic")
    assert result is not None


@pytest.mark.xfail(reason="upstream pass-stub: ConsolidationEntry.age_seconds", strict=True)
def test_consolidation_entry_age_seconds_non_negative() -> None:
    from brainos.memory.consolidator import ConsolidationEntry

    entry = ConsolidationEntry(key="k", value="v")
    assert entry.age_seconds >= 0.0


@pytest.mark.xfail(reason="upstream pass-stub: ContextEngine.push", strict=True)
def test_context_push_grows_layer_stack() -> None:
    from brainos.memory import ContextEngine, ContextLayer

    engine = ContextEngine()
    engine.push(ContextLayer.WORKING, "scratch note")
    assert engine.frame_count() == 1
    assert engine.peek(ContextLayer.WORKING) is not None


@pytest.mark.xfail(reason="upstream pass-stub: Deduplicator._build_similarity_calculator", strict=True)
def test_dedup_builds_similarity_calculator() -> None:
    dedup = Deduplicator(MemoryStore())
    assert dedup._build_similarity_calculator() is not None


@pytest.mark.xfail(reason="upstream pass-stub: Distiller.submit + Distiller.approve", strict=True)
def test_distiller_submit_then_approve_request() -> None:
    from brainos.memory import DistillationStatus, Distiller

    distiller = Distiller(MemoryStore())
    distiller.submit("src-1", "long source text", "distilled summary", confidence=0.5)
    pending = distiller.get_pending()
    assert len(pending) == 1
    approved = distiller.approve(pending[0].id, reviewer="reviewer-1")
    assert approved is not None
    assert approved.status == DistillationStatus.APPROVED


@pytest.mark.xfail(reason="upstream pass-stub: IntentMapper.unregister", strict=True)
def test_intent_mapper_unregister_removes_mapping() -> None:
    from brainos.memory import IntentMapper

    mapper = IntentMapper()
    mapper.register("summarize_doc", "fn_summarize")
    mapper.unregister("summarize_doc")
    assert mapper.map("summarize_doc") is None


@pytest.mark.xfail(reason="upstream pass-stub: NeuralPlasticityEngine.hebbian_learn", strict=True)
def test_hebbian_learn_creates_synaptic_connection() -> None:
    from brainos.memory.neural_plasticity import NeuralPlasticityEngine

    engine = NeuralPlasticityEngine()
    engine.hebbian_learn("neuron-a", "neuron-b", strength=0.5)
    stats = engine.get_stats()
    assert stats["total_connections"] == 1


@pytest.mark.xfail(reason="upstream pass-stub: Procedure.record_success", strict=True)
def test_procedure_record_success_increments_counter() -> None:
    from brainos.memory.procedural import Procedure

    proc = Procedure(name="deploy", steps=[{"action": "build"}])
    proc.record_success(duration=1.5)
    assert proc.success_count == 1
    assert proc.success_rate == pytest.approx(1.0)


@pytest.mark.xfail(reason="upstream pass-stub: Snapshot.to_dict", strict=True)
def test_snapshot_to_dict_preserves_checksum() -> None:
    from brainos.memory import Snapshot

    snap = Snapshot(id="snap-1", label="before-clean", state={"depth": 3})
    data = snap.to_dict()
    assert data["id"] == "snap-1"
    assert data["checksum"] == snap.checksum


@pytest.mark.xfail(reason="upstream pass-stub: TemporalEntry.is_valid", strict=True)
def test_temporal_entry_without_expiry_is_valid() -> None:
    from brainos.memory.temporal_awareness import TemporalEntry

    entry = TemporalEntry(key="fact", value=1)  # valid_from=0, valid_until=0
    assert entry.is_valid is True


@pytest.mark.xfail(reason="upstream pass-stub: LegacyTemporalKnowledgeGraph.has_entity", strict=True)
def test_temporal_graph_has_entity_membership() -> None:
    from brainos.memory.temporal_graph import LegacyTemporalKnowledgeGraph

    graph = LegacyTemporalKnowledgeGraph()
    graph.add_entity("entity-1")
    assert graph.has_entity("entity-1") is True
    assert graph.has_entity("missing") is False


@pytest.mark.xfail(reason="upstream pass-stub: TriggerCondition.evaluate", strict=True)
def test_trigger_condition_evaluates_field_against_threshold() -> None:
    from brainos.memory import TriggerCondition

    cond = TriggerCondition(field_name="importance", operator=">=", value=0.5)
    assert cond.evaluate({"importance": 0.9}) is True
    assert cond.evaluate({"importance": 0.1}) is False


@pytest.mark.xfail(reason="upstream pass-stub: WorkingItem.touch", strict=True)
def test_working_item_touch_bumps_access_stats() -> None:
    from brainos.memory.working import WorkingItem

    item = WorkingItem(key="k", value="v")
    before = item.accessed_at
    item.touch()
    assert item.access_count == 1
    assert item.accessed_at >= before
