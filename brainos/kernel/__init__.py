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
"""Kernel support layer (open-core subset).

Only the generic engineering primitives that the memory engine depends on are
shipped here. The full kernel (DI container, event bus, lifecycle, plugin
system, feature flags) is commercial version only.
"""

from __future__ import annotations

from brainos.kernel.async_compat import (
    async_compatible as async_compatible,
    is_async_compatible as is_async_compatible,
)
from brainos.kernel.auto_log import BufferHandler as BufferHandler
from brainos.kernel.config import (
    PROJECT_ROOT as PROJECT_ROOT,
    RuntimeConfig as RuntimeConfig,
    atomic_json_write as atomic_json_write,
    safe_json_read as safe_json_read,
)
from brainos.kernel.decorators import (
    audit_logged as audit_logged,
    logged as logged,
)
from brainos.kernel.errors import (
    BrainOSError as BrainOSError,
    CircuitBreakerOpenError as CircuitBreakerOpenError,
    ConfigError as ConfigError,
    ConfigNotFoundError as ConfigNotFoundError,
    DICircularDependencyError as DICircularDependencyError,
    DIServiceNotFoundError as DIServiceNotFoundError,
    EventBusError as EventBusError,
    LifecycleError as LifecycleError,
    LifecycleTimeoutError as LifecycleTimeoutError,
    PluginConflictError as PluginConflictError,
    PluginDependencyError as PluginDependencyError,
    PluginError as PluginError,
    PluginLoadError as PluginLoadError,
    ProviderError as ProviderError,
    ProviderHealthError as ProviderHealthError,
    ProviderNotFoundError as ProviderNotFoundError,
    RecoverableError as RecoverableError,
)
from brainos.kernel.safe_execute import (
    clear_swallowed_errors as clear_swallowed_errors,
    get_swallowed_errors as get_swallowed_errors,
    is_safe_executed as is_safe_executed,
    safe_call as safe_call,
    safe_call_v2 as safe_call_v2,
    safe_execute as safe_execute,
    safe_execute_v2 as safe_execute_v2,
)
from brainos.kernel.types import (
    Err as Err,
    Event as Event,
    EventPriority as EventPriority,
    Ok as Ok,
    Result as Result,
    ResultStatus as ResultStatus,
    Signal as Signal,
)

__all__ = [
    "BrainOSError",
    "BufferHandler",
    "CircuitBreakerOpenError",
    "ConfigError",
    "ConfigNotFoundError",
    "DICircularDependencyError",
    "DIServiceNotFoundError",
    "Err",
    "Event",
    "EventBusError",
    "EventPriority",
    "LifecycleError",
    "LifecycleTimeoutError",
    "Ok",
    "PluginConflictError",
    "PluginDependencyError",
    "PluginError",
    "PluginLoadError",
    "PROJECT_ROOT",
    "ProviderError",
    "ProviderHealthError",
    "ProviderNotFoundError",
    "RecoverableError",
    "Result",
    "ResultStatus",
    "RuntimeConfig",
    "Signal",
    "atomic_json_write",
    "audit_logged",
    "async_compatible",
    "clear_swallowed_errors",
    "get_swallowed_errors",
    "is_async_compatible",
    "is_safe_executed",
    "logged",
    "safe_call",
    "safe_call_v2",
    "safe_execute",
    "safe_execute_v2",
    "safe_json_read",
]
