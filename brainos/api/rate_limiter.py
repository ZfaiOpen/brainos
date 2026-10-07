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
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from enum import Enum

from brainos.observability.auto_log import logged
from brainos.kernel.safe_execute import safe_execute

logger = logging.getLogger("brainos.api.rate_limiter")


class LimiterAlgorithm(Enum):
    TOKEN_BUCKET = "token_bucket"
    SLIDING_WINDOW = "sliding_window"
    FIXED_WINDOW = "fixed_window"


@dataclass
class RateLimitConfig:
    algorithm: LimiterAlgorithm = LimiterAlgorithm.TOKEN_BUCKET
    max_requests: int = 100
    window_seconds: float = 60.0
    burst_size: int = 10

    @logged()
    @safe_execute
    def to_dict(self):
        pass



@dataclass
class RateLimitResult:
    allowed: bool
    remaining: int
    reset_at: float
    retry_after: float = 0.0

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "remaining": self.remaining,
            "reset_at": self.reset_at,
            "retry_after": self.retry_after,
        }


@dataclass
class _TokenBucketState:
    tokens: float = 0.0
    last_refill: float = field(default_factory=time.time)


@dataclass
class _SlidingWindowState:
    timestamps: list[float] = field(default_factory=list)


@dataclass
class _FixedWindowState:
    count: int = 0
    window_start: float = field(default_factory=time.time)


class RateLimiter:
    def __init__(self, config: RateLimitConfig | None = None) -> None:
        self._config = config or RateLimitConfig()
        self._token_buckets: dict[str, _TokenBucketState] = {}
        self._sliding_windows: dict[str, _SlidingWindowState] = {}
        self._fixed_windows: dict[str, _FixedWindowState] = {}
        self._total_allowed: int = 0
        self._total_denied: int = 0

    @logged()
    @safe_execute
    def check(self, client_id: str) -> RateLimitResult:
        algo = self._config.algorithm
        if algo == LimiterAlgorithm.TOKEN_BUCKET:
            result = self._token_bucket_check(client_id)
        elif algo == LimiterAlgorithm.SLIDING_WINDOW:
            result = self._sliding_window_check(client_id)
        elif algo == LimiterAlgorithm.FIXED_WINDOW:
            result = self._fixed_window_check(client_id)
        else:
            result = self._token_bucket_check(client_id)
        if result.allowed:
            self._total_allowed += 1
        else:
            self._total_denied += 1
        return result

    @logged()
    @safe_execute
    def reset(self, client_id: str) -> dict:
        """重置指定客户端的所有限流状态 (并发安全)
        
        Returns:
            dict: 包含重置操作的状态及受影响的算法列表
        """
        if not client_id or not isinstance(client_id, str):
            logger.warning("RateLimiter.reset rejected invalid client_id")
            return {"status": "error", "affected": []}
            
        affected = []
        lock = getattr(self, '_lock', None)
        
        def _do_reset():
            nonlocal affected
            if self._token_buckets.pop(client_id, None) is not None:
                affected.append("token_bucket")
            if self._sliding_windows.pop(client_id, None) is not None:
                affected.append("sliding_window")
            if self._fixed_windows.pop(client_id, None) is not None:
                affected.append("fixed_window")

        try:
            if lock and hasattr(lock, '__enter__'):
                with lock:
                    _do_reset()
            else:
                _do_reset()
                
            logger.debug(
                "Rate limit reset for client: %s, affected algorithms: %s",
                client_id, affected
            )
            return {"status": "success", "affected": affected}
        except Exception as _exc:
            logger.warning(
                "RateLimiter.reset failed for client %s: %s",
                client_id, _exc, exc_info=False
            )
            return {"status": "degraded", "affected": affected}

    @logged()
    @safe_execute
    def get_status(self, client_id: str) -> dict[str, object]:
        algo = self._config.algorithm
        if algo == LimiterAlgorithm.TOKEN_BUCKET:
            state = self._token_buckets.get(client_id)
            if state is None:
                return {"remaining": self._config.max_requests, "algorithm": algo.value}
            refill_rate = self._config.max_requests / self._config.window_seconds
            now = time.monotonic()
            elapsed = now - state.last_refill
            current_tokens = min(
                self._config.max_requests,
                state.tokens + elapsed * refill_rate,
            )
            return {
                "remaining": int(current_tokens),
                "algorithm": algo.value,
                "max_requests": self._config.max_requests,
            }
        if algo == LimiterAlgorithm.SLIDING_WINDOW:
            state = self._sliding_windows.get(client_id)
            now = time.monotonic()
            cutoff = now - self._config.window_seconds
            if state is None:
                return {"remaining": self._config.max_requests, "algorithm": algo.value}
            valid = [t for t in state.timestamps if t > cutoff]
            return {
                "remaining": max(0, self._config.max_requests - len(valid)),
                "algorithm": algo.value,
                "max_requests": self._config.max_requests,
            }
        if algo == LimiterAlgorithm.FIXED_WINDOW:
            state = self._fixed_windows.get(client_id)
            if state is None:
                return {"remaining": self._config.max_requests, "algorithm": algo.value}
            now = time.monotonic()
            if now - state.window_start >= self._config.window_seconds:
                return {"remaining": self._config.max_requests, "algorithm": algo.value}
            return {
                "remaining": max(0, self._config.max_requests - state.count),
                "algorithm": algo.value,
                "max_requests": self._config.max_requests,
            }
        return {"remaining": 0, "algorithm": algo.value}

    @logged()
    @safe_execute
    def get_stats(self) -> dict[str, object]:
        return {
            "total_allowed": self._total_allowed,
            "total_denied": self._total_denied,
            "active_clients": (len(self._token_buckets) + len(self._sliding_windows) + len(self._fixed_windows)),
            "config": self._config.to_dict(),
        }

    def _token_bucket_check(self, client_id: str) -> RateLimitResult:
        now = time.monotonic()
        state = self._token_buckets.get(client_id)
        if state is None:
            state = _TokenBucketState(
                tokens=float(self._config.max_requests),
                last_refill=now,
            )
            self._token_buckets[client_id] = state
        refill_rate = self._config.max_requests / self._config.window_seconds
        elapsed = now - state.last_refill
        state.tokens = min(self._config.max_requests, state.tokens + elapsed * refill_rate)
        state.last_refill = now
        if state.tokens >= 1.0:
            state.tokens -= 1.0
            reset_at = now + (1.0 - state.tokens) / refill_rate
            return RateLimitResult(
                allowed=True,
                remaining=int(state.tokens),
                reset_at=reset_at,
            )
        retry_after = (1.0 - state.tokens) / refill_rate
        reset_at = now + retry_after
        return RateLimitResult(
            allowed=False,
            remaining=0,
            reset_at=reset_at,
            retry_after=retry_after,
        )

    def _sliding_window_check(self, client_id: str) -> RateLimitResult:
        now = time.monotonic()
        state = self._sliding_windows.get(client_id)
        if state is None:
            state = _SlidingWindowState()
            self._sliding_windows[client_id] = state
        cutoff = now - self._config.window_seconds
        state.timestamps = [t for t in state.timestamps if t > cutoff]
        if len(state.timestamps) < self._config.max_requests:
            state.timestamps.append(now)
            reset_at = state.timestamps[0] + self._config.window_seconds
            return RateLimitResult(
                allowed=True,
                remaining=self._config.max_requests - len(state.timestamps),
                reset_at=reset_at,
            )
        oldest = state.timestamps[0]
        reset_at = oldest + self._config.window_seconds
        retry_after = reset_at - now
        return RateLimitResult(
            allowed=False,
            remaining=0,
            reset_at=reset_at,
            retry_after=max(0.0, retry_after),
        )

    def _fixed_window_check(self, client_id: str) -> RateLimitResult:
        now = time.monotonic()
        state = self._fixed_windows.get(client_id)
        if state is None:
            state = _FixedWindowState(count=0, window_start=now)
            self._fixed_windows[client_id] = state
        if now - state.window_start >= self._config.window_seconds:
            state.count = 0
            state.window_start = now
        if state.count < self._config.max_requests:
            state.count += 1
            reset_at = state.window_start + self._config.window_seconds
            return RateLimitResult(
                allowed=True,
                remaining=self._config.max_requests - state.count,
                reset_at=reset_at,
            )
        reset_at = state.window_start + self._config.window_seconds
        retry_after = reset_at - now
        return RateLimitResult(
            allowed=False,
            remaining=0,
            reset_at=reset_at,
            retry_after=max(0.0, retry_after),
        )
