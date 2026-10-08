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
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from brainos.observability.auto_log import logged
from brainos.kernel.safe_execute import safe_execute

logger = logging.getLogger("brainos.api.routes")


@dataclass
class Route:
    method: str = "GET"
    pattern: str = "/"
    handler: Callable[..., Any] = None
    param_names: list[str] = field(default_factory=list)
    compiled_pattern: re.Pattern[str] | None = None

    def __post_init__(self) -> None:
        self.compiled_pattern, self.param_names = self._compile_pattern(self.pattern)

    @staticmethod
    def _compile_pattern(pattern: str) -> tuple[re.Pattern[str], list[str]]:
        """Compile ``/path/{param}`` into a regex plus the parameter names."""
        param_names: list[str] = []

        def _sub(match: re.Match[str]) -> str:
            param_names.append(match.group(1))
            return f"(?P<{match.group(1)}>[^/]+)"

        regex = "^" + re.sub(r"\{([A-Za-z_]\w*)\}", _sub, pattern) + "$"
        return re.compile(regex), param_names

    @logged()
    @safe_execute
    def match(self, path: str) -> dict[str, str] | None:
        if self.compiled_pattern is None:
            return None
        m = self.compiled_pattern.match(path)
        if m:
            return m.groupdict()
        return None


class Router:
    def __init__(self) -> None:
        self._routes: list[Route] = []

    @logged()
    @safe_execute
    def add_route(self, method: str, pattern: str, handler: Callable[..., Any]) -> None:
        route = Route(method=method, pattern=pattern, handler=handler)
        self._routes.append(route)
        logger.debug("Added route: %s %s", method, pattern)

    @logged()
    @safe_execute
    def match(self, method: str, path: str) -> Callable[..., Any] | None:
        for route in self._routes:
            if route.method != method:
                continue
            params = route.match(path)
            if params is not None:
                return route.handler
        return None

    @logged()
    @safe_execute
    def match_with_params(self, method: str, path: str) -> tuple[Callable[..., Any] | None, dict[str, str]]:
        for route in self._routes:
            if route.method != method:
                continue
            params = route.match(path)
            if params is not None:
                return route.handler, params
        return None, {}

    @property
    def route_count(self) -> int:
        return len(self._routes)

    def all_routes(self) -> list[tuple[str, str, Callable[..., Any]]]:
        """All registered routes as (method, pattern, handler) tuples."""
        return [(r.method, r.pattern, r.handler) for r in self._routes]

    @logged()
    @safe_execute
    def list_routes(self) -> list[dict[str, str]]:
        return [{"method": r.method, "pattern": r.pattern} for r in self._routes]
