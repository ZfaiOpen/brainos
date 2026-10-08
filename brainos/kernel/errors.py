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
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BrainOSError(Exception):
    message: str = ""
    code: str = "UNKNOWN"
    recoverable: bool = False
    context: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


@dataclass
class RecoverableError(BrainOSError):
    recoverable: bool = True
    code: str = "RECOVERABLE"


@dataclass
class DICircularDependencyError(BrainOSError):
    code: str = "DI_CIRCULAR_DEPENDENCY"
    chain: list[str] = field(default_factory=list)


@dataclass
class DIServiceNotFoundError(BrainOSError):
    code: str = "DI_SERVICE_NOT_FOUND"
    service_id: str = ""


@dataclass
class LifecycleError(BrainOSError):
    code: str = "LIFECYCLE_ERROR"


@dataclass
class LifecycleTimeoutError(BrainOSError):
    code: str = "LIFECYCLE_TIMEOUT"
    phase: str = ""


@dataclass
class ConfigError(BrainOSError):
    code: str = "CONFIG_ERROR"
    key: str = ""


@dataclass
class ConfigNotFoundError(BrainOSError):
    code: str = "CONFIG_NOT_FOUND"
    path: str = ""


@dataclass
class PluginError(BrainOSError):
    code: str = "PLUGIN_ERROR"
    plugin_id: str = ""


@dataclass
class PluginLoadError(PluginError):
    code: str = "PLUGIN_LOAD_ERROR"
    path: str = ""


@dataclass
class PluginConflictError(PluginError):
    code: str = "PLUGIN_CONFLICT"


@dataclass
class PluginDependencyError(PluginError):
    code: str = "PLUGIN_DEPENDENCY"
    missing: list[str] = field(default_factory=list)


@dataclass
class EventBusError(BrainOSError):
    code: str = "EVENT_BUS_ERROR"


@dataclass
class CircuitBreakerOpenError(EventBusError):
    code: str = "CIRCUIT_BREAKER_OPEN"
    handler_name: str = ""


@dataclass
class ProviderError(BrainOSError):
    code: str = "PROVIDER_ERROR"
    provider_id: str = ""


@dataclass
class ProviderNotFoundError(ProviderError):
    code: str = "PROVIDER_NOT_FOUND"


@dataclass
class ProviderHealthError(ProviderError):
    code: str = "PROVIDER_HEALTH_ERROR"
