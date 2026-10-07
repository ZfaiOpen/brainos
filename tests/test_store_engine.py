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
"""Behavioral tests for the MemoryStore engine, MemoryEntry lifecycle and
the Deduplicator.

Single-entry retrieval (``MemoryStore.retrieve``) is an upstream pass-stub
and is probed in ``test_known_gaps.py``; this module exercises the working
paths: substring search, tag/type indexes, update, delete, persistence,
backup/restore, consolidation.
"""

from __future__ import annotations

import time

from brainos.memory import (
    Deduplicator,
    MemoryEntry,
    MemoryStore,
    MemoryType,
)


def _entry(content: str, **kw) -> MemoryEntry:
    return MemoryEntry(content=content, **kw)


class TestMemoryStoreSearch:
    def test_store_returns_generated_id(self) -> None:
        store = MemoryStore()
        mid = store.store(_entry("alpha report"))
        assert isinstance(mid, str) and mid

    def test_substring_search_ranks_by_importance(self) -> None:
        store = MemoryStore()
        store.store(_entry("alpha report low", importance=0.2))
        store.store(_entry("alpha report high", importance=0.9))
        hits = store.search("alpha")
        assert len(hits) == 2
        # importance-sorted descending (invariant; no tuned constants)
        imps = [e.importance for e in hits]
        assert imps == sorted(imps, reverse=True)
        assert {e.content for e in hits} == {"alpha report low", "alpha report high"}

    def test_search_limit_respected(self) -> None:
        store = MemoryStore()
        for i in range(5):
            store.store(_entry(f"widget item {i}"))
        assert len(store.search("widget", limit=3)) == 3

    def test_search_case_insensitive(self) -> None:
        store = MemoryStore()
        store.store(_entry("CamelCase Content"))
        assert store.search("camelcase") != []

    def test_search_no_match_empty(self) -> None:
        store = MemoryStore()
        store.store(_entry("apples"))
        assert store.search("oranges") == []

    def test_search_by_tag(self) -> None:
        store = MemoryStore()
        store.store(_entry("tagged one", tags=["red"]))
        store.store(_entry("tagged two", tags=["blue"]))
        store.store(_entry("untagged"))
        reds = store.search_by_tag("red")
        assert len(reds) == 1
        assert reds[0].content == "tagged one"

    def test_search_by_type(self) -> None:
        store = MemoryStore()
        store.store(_entry("an episode", memory_type=MemoryType.EPISODIC))
        store.store(_entry("a fact", memory_type=MemoryType.SEMANTIC))
        eps = store.search_by_type(MemoryType.EPISODIC)
        assert len(eps) == 1
        assert eps[0].content == "an episode"


class TestMemoryStoreMutation:
    def test_update_changes_content_and_search_sees_it(self) -> None:
        store = MemoryStore()
        mid = store.store(_entry("old content"))
        updated = store.update(mid, content="brand new content")
        assert updated is not None
        assert updated.content == "brand new content"
        assert store.search("brand new") != []
        assert store.search("old content") == []

    def test_update_missing_returns_none(self) -> None:
        store = MemoryStore()
        assert store.update("mem_missing", content="x") is None

    def test_update_tags_reindexes(self) -> None:
        store = MemoryStore()
        mid = store.store(_entry("doc", tags=["old"]))
        store.update(mid, tags=["fresh"])
        assert store.search_by_tag("old") == []
        assert len(store.search_by_tag("fresh")) == 1

    def test_delete_removes_from_indexes_and_count(self) -> None:
        store = MemoryStore()
        mid = store.store(_entry("doomed", tags=["doom"], memory_type=MemoryType.EPISODIC))
        assert store.delete(mid) is True
        assert store.delete(mid) is False
        assert store.search("doomed") == []
        assert store.search_by_tag("doom") == []
        assert store.search_by_type(MemoryType.EPISODIC) == []
        assert store.count()["total"] == 0

    def test_count_partitions_by_tier(self) -> None:
        store = MemoryStore()
        store.store(_entry("one"))
        store.store(_entry("two"))
        counts = store.count()
        assert counts["total"] == 2
        tier_sum = sum(v for k, v in counts.items() if k != "total")
        assert tier_sum == 2

    def test_list_all_roundtrip(self) -> None:
        store = MemoryStore()
        store.store(_entry("a"))
        store.store(_entry("b"))
        assert len(store.list_all()) == 2


class TestMemoryStorePersistence:
    def test_sqlite_reopen_reloads_entries(self, tmp_path) -> None:
        db = tmp_path / "memories.db"
        s1 = MemoryStore(db_path=db)
        s1.store(_entry("persist me"))
        s1.store(_entry("and me", tags=["keep"]))
        s1.close()

        s2 = MemoryStore(db_path=db)
        assert s2.count()["total"] == 2
        assert s2.search("persist me") != []
        assert len(s2.search_by_tag("keep")) == 1
        s2.close()

    def test_backup_and_restore_roundtrip(self, tmp_path) -> None:
        src = MemoryStore()
        mid = src.store(_entry("precious memory", importance=0.8))
        backup_file = tmp_path / "backup.json"
        assert src.backup(backup_file) == 1

        dst = MemoryStore()
        assert dst.restore(backup_file) == 1
        entries = dst.list_all()
        assert len(entries) == 1
        assert entries[0].id == mid
        assert entries[0].content == "precious memory"

    def test_consolidate_returns_int(self) -> None:
        store = MemoryStore()
        store.store(_entry("hot memory", access_count=10))
        promoted = store.consolidate(threshold_access=5, threshold_time=1e18)
        assert isinstance(promoted, int)
        assert promoted >= 0


class TestMemoryEntryLifecycle:
    def test_auto_id_and_timestamps(self) -> None:
        entry = MemoryEntry(content="x")
        assert entry.id.startswith("mem_")
        assert entry.created_at > 0
        # created_at/accessed_at default from two independent time.time()
        # calls — assert they coincide within clock-tick tolerance, not exactly
        assert abs(entry.accessed_at - entry.created_at) < 0.01

    def test_touch_increments_access_count(self) -> None:
        entry = MemoryEntry(content="x")
        before = entry.access_count
        assert entry.touch() is True
        assert entry.access_count == before + 1

    def test_touch_importance_stays_bounded(self) -> None:
        entry = MemoryEntry(content="x", importance=0.99)
        for _ in range(50):
            entry.touch()
            assert 0.0 <= entry.importance <= 1.0
            assert entry.importance >= 0.99  # never decreases on access

    def test_to_dict_from_dict_roundtrip(self) -> None:
        entry = MemoryEntry(content="round trip", tags=["t"], importance=0.7)
        d = entry.to_dict()
        clone = MemoryEntry.from_dict(d)
        assert clone.id == entry.id
        assert clone.content == entry.content
        assert clone.tags == ["t"]


class TestDeduplicator:
    def test_exact_duplicate_detected(self) -> None:
        store = MemoryStore()
        text = "the quick brown fox jumps over the lazy dog"
        store.store(_entry(text))
        d = Deduplicator(store)
        hit = d.is_duplicate(text.upper())
        assert hit is not None
        assert hit.content == text

    def test_near_duplicate_detected(self) -> None:
        store = MemoryStore()
        store.store(_entry("deploy the service to production cluster"))
        d = Deduplicator(store)
        assert d.is_duplicate("deploy the service to production cluster!") is not None

    def test_distinct_content_not_flagged(self) -> None:
        store = MemoryStore()
        store.store(_entry("whales migrate across oceans"))
        d = Deduplicator(store)
        assert d.is_duplicate("quantum flux capacitor repair manual") is None

    def test_no_store_attached_returns_none(self) -> None:
        assert Deduplicator().is_duplicate("anything") is None

    def test_time_heuristic_sanity(self) -> None:
        # store timestamps move forward monotonically per entry creation
        e1 = MemoryEntry(content="a")
        e2 = MemoryEntry(content="b")
        assert e2.created_at >= e1.created_at - 1e-6
