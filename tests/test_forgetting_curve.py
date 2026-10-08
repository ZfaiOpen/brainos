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
"""Forgetting-curve engine tests.

DESSENSITIZATION DISCIPLINE (carve EXTRA batch rule): every assertion here is
a range / monotonicity / boundary invariant. No curve parameter value, decay
coefficient or tuning constant is asserted exactly — the model skeleton is
open source, the battle-tuned parameters are not, and these tests must never
become a channel that pins them.
"""

from __future__ import annotations

import time

import pytest

from brainos.memory import CurveModel, ForgettingCurve, MemoryEntry, MemoryStore

DAY = 86400.0


def _aged(days: float, access_count: int = 0) -> MemoryEntry:
    return MemoryEntry(
        content="aged memory",
        created_at=time.time() - days * DAY,
        accessed_at=time.time() - days * DAY,
        access_count=access_count,
    )


class TestRetentionInvariants:
    def test_retention_bounded_in_unit_interval(self) -> None:
        fc = ForgettingCurve()
        for days in (0.01, 1, 7, 30, 365):
            r = fc.retention(_aged(days))
            assert 0.0 <= r <= 1.0

    def test_retention_decays_monotonically_with_age(self) -> None:
        fc = ForgettingCurve()
        fresh = fc.retention(_aged(1))
        week = fc.retention(_aged(7))
        month = fc.retention(_aged(30))
        assert fresh > week > month

    def test_recent_memory_is_fully_retained(self) -> None:
        fc = ForgettingCurve()
        assert fc.retention(_aged(-1)) == 1.0  # elapsed <= 0 branch
        assert fc.retention(_aged(0.0001)) > 0.99

    def test_reviews_improve_retention(self) -> None:
        fc = ForgettingCurve()
        unreviewed = fc.retention(_aged(30, access_count=0))
        reviewed = fc.retention(_aged(30, access_count=5))
        assert reviewed >= unreviewed

    def test_heavily_reviewed_retention_bounded(self) -> None:
        fc = ForgettingCurve()
        for count in (0, 10, 100):
            assert 0.0 <= fc.retention(_aged(30, access_count=count)) <= 1.0


class TestForgettingDecision:
    def test_threshold_boundary_semantics(self) -> None:
        # test-local threshold values (not engine tuning): pick a threshold so
        # extreme that the decision is unambiguous either way.
        aggressive = ForgettingCurve(retention_threshold=0.999999)
        assert aggressive.should_forget(_aged(30)) is True
        lenient = ForgettingCurve(retention_threshold=0.0)
        assert lenient.should_forget(_aged(30)) is False

    def test_fresher_memory_forgotten_later(self) -> None:
        fc = ForgettingCurve(retention_threshold=0.5)
        assert fc.should_forget(_aged(365)) is True
        assert fc.should_forget(_aged(0.0001)) is False


class TestDecayRate:
    def test_decay_rate_positive_and_bounded(self) -> None:
        fc = ForgettingCurve()
        for reviews in range(0, 20):
            rate = fc.get_decay_rate(reviews)
            assert 0.0 < rate <= 1.0

    def test_decay_rate_non_increasing_with_reviews(self) -> None:
        fc = ForgettingCurve()
        rates = [fc.get_decay_rate(n) for n in range(10)]
        assert rates == sorted(rates, reverse=True)


class TestEstimateRetention:
    @pytest.mark.parametrize("model", list(CurveModel))
    def test_estimate_bounded_and_schedules_review_after_learning(self, model) -> None:
        fc = ForgettingCurve(model=model)
        learned_at = time.time() - 5 * DAY
        est = fc.estimate_retention("k", learned_at=learned_at, review_count=2)
        assert 0.0 <= est.retention_probability <= 1.0
        assert est.next_review_at > learned_at  # review always after learning
        assert est.model == model

    def test_future_learned_at_is_fully_retained(self) -> None:
        # elapsed <= 0 branch: retention is exactly 1.0 by contract
        fc = ForgettingCurve()
        est = fc.estimate_retention("k", learned_at=time.time() + 60)
        assert est.retention_probability == 1.0

    def test_older_estimate_never_exceeds_fresher(self) -> None:
        fc = ForgettingCurve()
        fresh = fc.estimate_retention("k", learned_at=time.time() - DAY)
        old = fc.estimate_retention("k", learned_at=time.time() - 60 * DAY)
        assert old.retention_probability <= fresh.retention_probability


class TestApplyForgetting:
    def test_dry_run_never_deletes(self) -> None:
        store = MemoryStore()
        for i in range(4):
            entry = MemoryEntry(content=f"old {i}", created_at=time.time() - 400 * DAY)
            store.store(entry)
        fc = ForgettingCurve(store=store, retention_threshold=0.5)
        stats = fc.apply_forgetting(dry_run=True)
        assert stats.total_evaluated == 4
        assert store.count()["total"] == 4  # dry run: nothing removed

    def test_real_delete_removes_weak_entries_and_keeps_strong(self) -> None:
        """Non-dry-run path: entries below the threshold are really removed,
        entries above it survive, and the stats reflect both populations."""
        store = MemoryStore()
        old = MemoryEntry(content="ancient", created_at=time.time() - 400 * DAY)
        fresh = MemoryEntry(content="fresh", created_at=time.time())
        old_id = store.store(old)
        store.store(fresh)

        fc = ForgettingCurve(store=store, retention_threshold=0.5)
        stats = fc.apply_forgetting(dry_run=False)

        assert stats.forgotten == 1
        assert stats.retained == 1
        assert stats.forgotten_ids == [old_id]
        assert store.retrieve(old_id) is None  # really deleted
        assert store.count()["total"] == 1  # fresh entry survives
        assert fc.get_last_stats() is stats

    def test_real_delete_is_durable_across_sqlite_reopen(self, tmp_path) -> None:
        """The deletion must persist: a fresh store bound to the same sqlite
        file must not resurrect forgotten entries (pattern reused from the
        store-engine durability regression)."""
        import tempfile
        from pathlib import Path

        db = str(Path(tmp_path) / "forget.db")
        store = MemoryStore(db_path=db)
        for i in range(3):
            store.store(MemoryEntry(content=f"old {i}", created_at=time.time() - 400 * DAY))
        ForgettingCurve(store=store, retention_threshold=0.5).apply_forgetting(dry_run=False)
        store.close() if hasattr(store, "close") else None

        reopened = MemoryStore(db_path=db)
        assert reopened.count()["total"] == 0

    def test_stats_object_shape(self) -> None:
        fc = ForgettingCurve(store=MemoryStore())
        stats = fc.apply_forgetting(dry_run=True)
        assert stats.forgotten == 0
        assert stats.retained == 0
