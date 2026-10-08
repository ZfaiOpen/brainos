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
import asyncio
import functools
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar

from brainos.observability.auto_log import logged
from brainos.kernel.safe_execute import safe_execute

logger = logging.getLogger("brainos.kernel.resilience")

T = TypeVar("T")


class RetryStrategy(Enum):
    FIXED = "fixed"
    EXPONENTIAL = "exponential"
    LINEAR = "linear"


@dataclass
class ResilienceConfig:
    max_retries: int = 3
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL
    base_delay: float = 0.5
    max_delay: float = 30.0
    fallback: Any = None
    log_level: str = "WARNING"
    circuit_breaker: bool = True
    failure_threshold: int = 5
    recovery_timeout: float = 60.0


@dataclass
class CircuitState:
    failures: int = 0
    last_failure_time: float = 0.0
    state: str = "closed"

    @logged()
    @safe_execute
    def record_failure(self) -> None:
        self.failures += 1
        self.last_failure_time = time.monotonic()

    @logged()
    @safe_execute
    def record_success(self) -> None:
        self.failures = 0
        self.state = "closed"

    @logged()
    @safe_execute
    def is_open(self, threshold: int, recovery_timeout: float) -> bool:
        if self.state == "open":
            if time.monotonic() - self.last_failure_time > recovery_timeout:
                self.state = "half-open"
                return False
            return True
        if self.failures >= threshold:
            self.state = "open"
            return True
        return False


_circuits: dict[str, CircuitState] = {}


def _get_circuit(name: str) -> CircuitState:
    if name not in _circuits:
        _circuits[name] = CircuitState()
    return _circuits[name]


def _calculate_delay(attempt: int, config: ResilienceConfig) -> float:
    if config.strategy == RetryStrategy.FIXED:
        return config.base_delay
    if config.strategy == RetryStrategy.LINEAR:
        return min(config.base_delay * attempt, config.max_delay)
    delay = config.base_delay * (2**attempt)
    return min(delay, config.max_delay)


from typing import Any
_LEVEL_MAP = {
    "DEBUG": logging.DEBUG, "INFO": logging.INFO,
    "WARNING": logging.WARNING, "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _log(config, msg, *args):
    if config is None or not hasattr(config, "log_level"):
        logger.log(logging.WARNING, msg, *args)
        return
    try:
        level = _LEVEL_MAP.get(
            str(config.log_level).upper(), logging.WARNING
        )
        if logger.isEnabledFor(level):
            logger.log(level, msg, *args)
    except Exception as _exc:
        logger.warning(
            "Resilience._log failed to dispatch level '%s'. Fallback to WARNING. Error: %s",
            getattr(config, "log_level", "unknown"),
            _exc,
            exc_info=False
        )
        try:
            logger.log(logging.WARNING, msg, *args)
        except Exception:
            pass



@logged()
@safe_execute
def resilient(
    max_retries: int = 3,
    strategy: str = "exponential",
    base_delay: float = 0.5,
    max_delay: float = 30.0,
    fallback: Any = None,
    log_level: str = "WARNING",
    circuit_breaker: bool = True,
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
) -> Callable:
    strategy_enum = RetryStrategy(strategy)
    config = ResilienceConfig(
        max_retries=max_retries,
        strategy=strategy_enum,
        base_delay=base_delay,
        max_delay=max_delay,
        fallback=fallback,
        log_level=log_level,
        circuit_breaker=circuit_breaker,
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout,
    )

    def decorator(func: Callable) -> Callable:
        circuit_name = f"{func.__module__}.{func.__qualname__}"

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            circuit = _get_circuit(circuit_name)
            if config.circuit_breaker and circuit.is_open(config.failure_threshold, config.recovery_timeout):
                _log(config, "Circuit open for %s, using fallback", circuit_name)
                if config.fallback is not None:
                    if asyncio.iscoroutinefunction(config.fallback):
                        return await config.fallback(*args, **kwargs)
                    return config.fallback
                msg = f"Circuit open for {circuit_name}"
                raise RuntimeError(msg)

            last_error: Exception | None = None
            for attempt in range(config.max_retries + 1):
                try:
                    result = await func(*args, **kwargs)
                    circuit.record_success()
                    return result
                except Exception as e:
                    last_error = e
                    circuit.record_failure()
                    if attempt < config.max_retries:
                        delay = _calculate_delay(attempt, config)
                        _log(
                            config,
                            "Retry %d/%d for %s after %.1fs",
                            attempt + 1,
                            config.max_retries,
                            circuit_name,
                            delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        _log(
                            config,
                            "All %d retries exhausted for %s",
                            config.max_retries,
                            circuit_name,
                        )

            if config.fallback is not None:
                _log(config, "Using fallback for %s", circuit_name)
                if asyncio.iscoroutinefunction(config.fallback):
                    return await config.fallback(*args, **kwargs)
                return config.fallback
            raise last_error  # type: ignore[misc]

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            circuit = _get_circuit(circuit_name)
            if config.circuit_breaker and circuit.is_open(config.failure_threshold, config.recovery_timeout):
                _log(config, "Circuit open for %s, using fallback", circuit_name)
                if config.fallback is not None:
                    if callable(config.fallback):
                        return config.fallback(*args, **kwargs)
                    return config.fallback
                msg = f"Circuit open for {circuit_name}"
                raise RuntimeError(msg)

            last_error: Exception | None = None
            for attempt in range(config.max_retries + 1):
                try:
                    result = func(*args, **kwargs)
                    circuit.record_success()
                    return result
                except Exception as e:
                    last_error = e
                    circuit.record_failure()
                    if attempt < config.max_retries:
                        delay = _calculate_delay(attempt, config)
                        _log(
                            config,
                            "Retry %d/%d for %s after %.1fs",
                            attempt + 1,
                            config.max_retries,
                            circuit_name,
                            delay,
                        )
                        time.sleep(delay)
                    else:
                        _log(
                            config,
                            "All %d retries exhausted for %s",
                            config.max_retries,
                            circuit_name,
                        )

            if config.fallback is not None:
                _log(config, "Using fallback for %s", circuit_name)
                if callable(config.fallback):
                    return config.fallback(*args, **kwargs)
                return config.fallback
            raise last_error  # type: ignore[misc]

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
