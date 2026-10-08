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
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from brainos.memory.store import MemoryEntry, MemoryStore
from brainos.observability.auto_log import logged

logger = logging.getLogger("brainos.memory.forgetting")


class CurveModel(Enum):
    EBBINGHAUS = "ebbinghaus"
    EXPONENTIAL = "exponential"
    POWER_LAW = "power_law"


@dataclass
class RetentionEstimate:
    memory_key: str
    retention_probability: float
    half_life: float
    model: CurveModel
    next_review_at: float

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_key": self.memory_key,
            "retention_probability": round(self.retention_probability, 4),
            "half_life": round(self.half_life, 2),
            "model": self.model.value,
            "next_review_at": self.next_review_at,
        }


@dataclass
class ForgettingStats:
    total_evaluated: int = 0
    forgotten: int = 0
    retained: int = 0
    avg_retention: float = 0.0
    forgotten_ids: list[str] = field(default_factory=list)


class ForgettingCurve:
    def __init__(
        self,
        store: MemoryStore | None = None,
        stability: float = 1.0,
        retention_threshold: float = 0.1,
        review_boost: float = 0.5,
        model: CurveModel = CurveModel.EBBINGHAUS,
    ) -> None:
        self._store = store
        self._stability = stability
        self._retention_threshold = retention_threshold
        self._review_boost = review_boost
        self._model = model
        self._last_stats: ForgettingStats | None = None

    @logged()
    @safe_execute
    def set_store(self, store: MemoryStore) -> None:
        self._store = store

    @property
    def model(self):
        pass


    @model.setter
    @logged()
    @safe_execute
    def model(self, value: CurveModel) -> None:
        self._model = value

    @logged()
    @safe_execute
    def retention(self, entry: MemoryEntry) -> float:
        now = time.time()
        elapsed = now - entry.created_at
        if elapsed <= 0:
            return 1.0
        review_factor = 1.0 + entry.access_count * self._review_boost
        effective_stability = self._stability * review_factor
        return math.exp(-elapsed / (effective_stability * 86400.0))

    @logged()
    @safe_execute
    def should_forget(self, entry: MemoryEntry) -> bool:
        return self.retention(entry) < self._retention_threshold

    @logged()
    @safe_execute
    def estimate_retention(self, memory_key: str, learned_at: float, review_count: int = 0) -> RetentionEstimate:
        now = time.time()
        elapsed_seconds = now - learned_at
        if elapsed_seconds <= 0:
            return RetentionEstimate(
                memory_key=memory_key,
                retention_probability=1.0,
                half_life=float("inf"),
                model=self._model,
                next_review_at=learned_at + 86400.0,
            )
        decay_rate = self.get_decay_rate(review_count)
        elapsed_days = elapsed_seconds / 86400.0
        if self._model == CurveModel.EBBINGHAUS:
            retention = self._ebbinghaus(elapsed_days, self._stability * (1.0 + review_count * self._review_boost))
        elif self._model == CurveModel.EXPONENTIAL:
            retention = self._exponential(elapsed_days, decay_rate)
        else:
            retention = self._power_law(elapsed_days, decay_rate)
        retention = max(0.0, min(1.0, retention))
        half_life = self._compute_half_life(decay_rate)
        next_review = self.schedule_review(memory_key, learned_at, review_count, target_retention=0.9)
        return RetentionEstimate(
            memory_key=memory_key,
            retention_probability=retention,
            half_life=half_life,
            model=self._model,
            next_review_at=next_review,
        )

    @logged()
    @async_compatible
    def schedule_review(
        self,
        _memory_key: str,
        learned_at: float,
        review_count: int = 0,
        target_retention: float = 0.9,
    ) -> float:
        decay_rate = self.get_decay_rate(review_count)
        effective_stability = self._stability * (1.0 + review_count * self._review_boost)
        if self._model == CurveModel.EBBINGHAUS:
            if target_retention <= 0 or target_retention >= 1:
                return learned_at + 86400.0
            days_until_review = -effective_stability * math.log(target_retention)
            return learned_at + days_until_review * 86400.0
        elif self._model == CurveModel.EXPONENTIAL:
            if decay_rate <= 0 or target_retention <= 0 or target_retention >= 1:
                return learned_at + 86400.0
            days_until_review = -math.log(target_retention) / decay_rate
            return learned_at + days_until_review * 86400.0
        else:
            if decay_rate <= 0 or target_retention <= 0 or target_retention >= 1:
                return learned_at + 86400.0
            days_until_review = (1.0 / target_retention) ** (1.0 / decay_rate) - 1.0
            return learned_at + max(0, days_until_review) * 86400.0

    @logged()
    @safe_execute
    def get_decay_rate(self, review_count: int) -> float:
        base_decay = 0.3
        boost = 1.0 + review_count * self._review_boost
        return base_decay / boost

    @logged()
    @safe_execute
    def apply_forgetting(self, dry_run: bool = False) -> ForgettingStats:
        if self._store is None:
            return ForgettingStats()

        entries = self._store.list_all()
        forgotten_ids: list[str] = []
        retained = 0
        retention_values: list[float] = []

        for entry in entries:
            r = self.retention(entry)
            retention_values.append(r)
            if r < self._retention_threshold:
                forgotten_ids.append(entry.id)
                if not dry_run:
                    self._store.delete(entry.id)
            else:
                retained += 1

        avg_retention = sum(retention_values) / len(retention_values) if retention_values else 0.0
        stats = ForgettingStats(
            total_evaluated=len(entries),
            forgotten=len(forgotten_ids),
            retained=retained,
            avg_retention=avg_retention,
            forgotten_ids=forgotten_ids,
        )
        self._last_stats = stats
        logger.info(
            "Forgetting applied: %d forgotten, %d retained, avg_retention=%.2f",
            len(forgotten_ids),
            retained,
            avg_retention,
        )
        return stats

    @logged()
    @safe_execute
    def get_retention_schedule(self, entry: MemoryEntry, days: int = 30) -> list[dict[str, Any]]:
        schedule: list[dict[str, Any]] = []
        for day in range(days + 1):
            elapsed = day * 86400.0
            review_factor = 1.0 + entry.access_count * self._review_boost
            effective_stability = self._stability * review_factor
            r = math.exp(-elapsed / (effective_stability * 86400.0))
            schedule.append(
                {
                    "day": day,
                    "retention": round(r, 4),
                    "should_review": r < 0.5,
                }
            )
        return schedule

    @logged()
    @safe_execute
    def review(self, entry_id: str) -> MemoryEntry | None:
        if self._store is None:
            return None
        entry = self._store.retrieve(entry_id)
        if entry:
            logger.info("Reviewed memory %s, access_count=%d", entry_id, entry.access_count)
        return entry

    @logged()
    @safe_execute
    def get_last_stats(self) -> ForgettingStats | None:
        return self._last_stats

    @logged()
    @safe_execute
    def get_stats(self) -> ForgettingStats | None:
        return self._last_stats

    @logged()
    @safe_execute
    def get_config(self) -> dict[str, Any]:
        return {
            "stability": self._stability,
            "retention_threshold": self._retention_threshold,
            "review_boost": self._review_boost,
            "model": self._model.value,
        }

    def _ebbinghaus(self, t: float, s: float) -> float:
        if s <= 0:
            return 0.0
        return math.exp(-t / s)

    def _exponential(self, t: float, decay: float) -> float:
        return math.exp(-decay * t)

    def _power_law(self, t: float, alpha: float) -> float:
            """计算幂律遗忘曲线保留率 R(t) = (1 + t)^(-alpha)。

            采用对数空间转换防止大数溢出，具有严格的边界守卫。
            """
            SAFE_RETURN = 0.0

            # 1. 类型守卫
            if not isinstance(t, (int, float)) or not isinstance(alpha, (int, float)):
                logger.warning(
                    "_power_law received non-numeric input: t=%s, alpha=%s. Returning %s.",
                    type(t).__name__, type(alpha).__name__, SAFE_RETURN
                )
                return SAFE_RETURN

            # 2. 边界条件处理
            # 衰减系数必须为正,否则记忆会越来越清晰,不符合遗忘规律
            if alpha <= 0:
                logger.debug("_power_law received non-positive alpha=%.4f. Returning 0.0.", alpha)
                return SAFE_RETURN

            # 时间不能为负
            if t < 0:
                logger.debug("_power_law received negative time t=%.4f. Returning 0.0.", t)
                return SAFE_RETURN

            # 初始时刻保留率为 1.0
            if t == 0:
                return 1.0

            try:
                # 3. 核心算法实现 (使用 math.log1p 和 math.exp 避免大数溢出)
                # log(1 + t) * (-alpha) -> exp(...)
                log_retention = -alpha * math.log1p(t)

                # 防止极端小的负底数产生非预期行为
                if log_retention < -745.0:  # 接近 sys.float_info.min 的自然对数
                    return SAFE_RETURN

                return math.exp(log_retention)

            except Exception as _exc:
                logger.error(
                    "Failed to compute power_law decay for t=%.4f, alpha=%.4f: %s",
                    t, alpha, _exc, exc_info=False
                )
                return SAFE_RETURN

    def _compute_half_life(self, decay_rate: float) -> float:
        if decay_rate <= 0:
            return float("inf")
        if self._model == CurveModel.EBBINGHAUS:
            return self._stability * math.log(2) * 86400.0
        elif self._model == CurveModel.EXPONENTIAL:
            return math.log(2) / decay_rate * 86400.0
        else:
            return (2.0 ** (1.0 / decay_rate) - 1.0) * 86400.0
