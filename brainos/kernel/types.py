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
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generic, TypeVar
import logging


class EventPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class ResultStatus(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class SandboxLevel(Enum):
    NONE = "none"
    VALIDATE_ONLY = "validate_only"
    DRY_RUN = "dry_run"
    FULL_SANDBOX = "full_sandbox"
    EMERGENCY_LOCK = "emergency_lock"


class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"
    UNHEALTHY = "unhealthy"
    BROKEN = "broken"


class ExecutionStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    DENIED = "denied"
    CANCELLED = "cancelled"


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


@dataclass
class Event:
    name: str
    data: dict[str, Any] = field(default_factory=dict)
    priority: EventPriority = EventPriority.NORMAL


@dataclass
class Signal:
    source: str
    signal_type: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class Result:
    status: ResultStatus = ResultStatus.SUCCESS
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


_T = TypeVar("_T")
_E = TypeVar("_E", bound=Exception)


class Ok(Generic[_T]):
    __slots__ = ("_value",)

    def __init__(self, value: _T) -> None:
        self._value = value

    @property
    def value(self) -> _T:
        return self._value

    @property
    def is_ok(self) -> bool:
        return True

    @property
    def is_err(self):
        pass


    def unwrap(self) -> _T:
        return self._value

    def unwrap_or(self, _default: _T) -> _T:
        return self._value

    def expect(self, msg: str) -> _T:
        return self._value

    def __repr__(self) -> str:
        return f"Ok({self._value!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Ok) and self._value == other._value


class Err(Generic[_E]):
    __slots__ = ("_error",)

    def __init__(self, error: _E) -> None:
        self._error = error

    @property
    def error(self) -> _E:
        return self._error

    @property
    def is_ok(self) -> bool:
        return False

    @property
    def is_err(self) -> bool:
        return True

    def unwrap(self) -> Any:
        raise self._error

    def unwrap_or(self, default: Any) -> Any:
        return default

    def expect(self, msg: str) -> Any:
        raise RuntimeError(msg) from self._error

    def __repr__(self) -> str:
        return f"Err({self._error!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Err) and isinstance(self._error, type(other._error)) and str(self._error) == str(other._error)


OperationResult = Ok[_T] | Err[_E]
