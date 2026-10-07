# Copyright 2026 zfai-open contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
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
    recall.py          recall
    replay.py          add
    short_term.py      store, retrieve
    snapshot.py        to_dict
    store.py           retrieve
    temporal_awareness.py  is_valid
    temporal_graph.py  has_entity
    trigger.py         evaluate
    working.py         touch, store

These probes assert the INTENDED behavior with ``xfail(strict=True)``:
they xfail today (stub returns None), and the moment someone fills a stub
in they XPASS and FAIL the suite — forcing the marker to be removed and
the method to be covered by a real behavioral test. This is a ratchet:
stubs can only move from "known gap" to "tested behavior", never back.
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


@pytest.mark.xfail(reason="upstream pass-stub: MemoryStore.retrieve", strict=True)
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


@pytest.mark.xfail(reason="upstream pass-stub: RecallEngine.recall", strict=True)
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
