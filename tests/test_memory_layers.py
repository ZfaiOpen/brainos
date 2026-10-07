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
"""Behavioral tests for memory layers: semantic store, episode store,
working/short-term shells, in-process manager.

Working paths only: methods that are upstream pass-stubs are probed in
``test_known_gaps.py`` (strict xfail), never asserted as working here.
"""

from __future__ import annotations

from brainos.memory.manager import MemoryManager
from brainos.memory.episode import Episode, EpisodeStore
from brainos.memory.semantic import SemanticMemory
from brainos.memory.working import WorkingMemory


class TestSemanticMemory:
    def test_write_read_roundtrip(self) -> None:
        mem = SemanticMemory()
        mem.write("greeting", "hello world")
        assert mem.read("greeting") == "hello world"
        assert mem.retrieve("greeting") == "hello world"

    def test_store_returns_true_and_search_ranks_keyword_hits(self) -> None:
        mem = SemanticMemory()
        assert mem.store("doc.a", "the quick brown fox jumps", category="docs") is True
        assert mem.store("doc.b", "lazy dogs sleep all day", category="docs") is True
        hits = mem.search("quick fox")
        assert hits, "keyword search returned no hits"
        keys = [k for k, _, _ in hits]
        assert "doc.a" in keys
        # scores sorted descending and within (0, 1]
        scores = [s for _, _, s in hits]
        assert scores == sorted(scores, reverse=True)
        assert all(0.0 < s <= 1.0 for s in scores)

    def test_search_min_score_filters_weak_hits(self) -> None:
        mem = SemanticMemory()
        mem.store("doc.a", "quantum entanglement basics")
        assert mem.search("quantum entanglement basics", min_score=0.1)
        assert mem.search("zzz", min_score=0.1) == []

    def test_search_empty_query_returns_empty(self) -> None:
        mem = SemanticMemory()
        mem.store("doc.a", "some content")
        assert mem.search("") == []

    def test_delete_removes_entry(self) -> None:
        mem = SemanticMemory()
        mem.store("k1", "unique widget content")
        assert mem.delete("k1") is True
        assert mem.delete("k1") is False  # second delete is a no-op
        assert mem.search("unique widget") == []
        assert mem.read("k1") is None

    def test_search_by_category(self) -> None:
        mem = SemanticMemory()
        mem.store("a", "alpha content", category="cat1")
        mem.store("b", "beta content", category="cat2")
        hits = mem.search_by_category("cat1")
        assert [k for k, _ in hits] == ["a"]

    def test_get_stats_shape(self) -> None:
        mem = SemanticMemory()
        mem.store("a", "alpha")
        stats = mem.get_stats()
        assert isinstance(stats, dict)


class TestEpisodeStore:
    def test_append_and_get_roundtrip(self, tmp_path) -> None:
        store = EpisodeStore(db_path=str(tmp_path / "episodes.db"))
        ep = Episode(events=[{"action": "test"}], tags=["t1"])
        assert store.append(ep) is True
        loaded = store.get_episode(ep.episode_id)
        assert loaded is not None
        assert loaded.episode_id == ep.episode_id
        assert loaded.events == [{"action": "test"}]

    def test_query_filters_by_tag(self, tmp_path) -> None:
        store = EpisodeStore(db_path=str(tmp_path / "episodes.db"))
        store.append(Episode(events=[], tags=["red"]))
        store.append(Episode(events=[], tags=["blue"]))
        reds = store.query(tags=["red"])
        assert len(reds) == 1
        assert reds[0].tags == ["red"]

    def test_query_since_future_is_empty(self, tmp_path) -> None:
        import time

        store = EpisodeStore(db_path=str(tmp_path / "episodes.db"))
        store.append(Episode(events=[], tags=[]))
        assert store.query(since=time.time() + 3600) == []

    def test_get_episode_missing_returns_none(self, tmp_path) -> None:
        store = EpisodeStore(db_path=str(tmp_path / "episodes.db"))
        assert store.get_episode("ep_missing") is None

    def test_episode_to_dict_fields(self) -> None:
        ep = Episode(events=[{"a": 1}], tags=["x"], metadata={"k": "v"})
        d = ep.to_dict()
        assert d["episode_id"] == ep.episode_id
        assert d["tags"] == ["x"]
        assert d["metadata"] == {"k": "v"}
        assert d["events"] == [{"a": 1}]
        assert d["timestamp"] > 0


class TestWorkingMemoryShell:
    def test_empty_retrieve_returns_none(self) -> None:
        wm = WorkingMemory()
        assert wm.retrieve("nothing") is None

    def test_capacity_and_size_properties(self) -> None:
        wm = WorkingMemory(capacity=3)
        assert wm.capacity == 3
        assert wm.size == 0
        assert wm.items() == {}

    def test_clear_is_safe_on_empty(self) -> None:
        wm = WorkingMemory()
        wm.clear()
        assert wm.size == 0


class TestMemoryManager:
    def test_put_get_roundtrip(self) -> None:
        mgr = MemoryManager()
        mgr.put("k", {"v": 1})
        assert mgr.get("k") == {"v": 1}

    def test_get_missing_returns_default(self) -> None:
        mgr = MemoryManager()
        assert mgr.get("missing") is None
        assert mgr.get("missing", default=42) == 42
