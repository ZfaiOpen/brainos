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
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from brainos.observability.auto_log import logged
from brainos.kernel.safe_execute import safe_execute

logger = logging.getLogger("brainos.api.gateway")


class HTTPMethod(Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


@dataclass
class Route:
    path: str
    method: HTTPMethod
    handler: Callable[[dict[str, object]], dict[str, object]] | None = None
    middleware: list[str] = field(default_factory=list)
    rate_limit: int = 0
    auth_required: bool = True

    @logged()
    @safe_execute
    def to_dict(self):
        pass



@dataclass
class GatewayRequest:
    method: HTTPMethod
    path: str
    headers: dict[str, str] = field(default_factory=dict)
    body: dict[str, object] = field(default_factory=dict)
    query_params: dict[str, str] = field(default_factory=dict)
    client_id: str = ""

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, object]:
        return {
            "method": self.method.value,
            "path": self.path,
            "headers": dict(self.headers),
            "body": dict(self.body),
            "query_params": dict(self.query_params),
            "client_id": self.client_id,
        }


@dataclass
class GatewayResponse:
    status_code: int
    body: dict[str, object] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    duration_ms: float = 0.0

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, object]:
        return {
            "status_code": self.status_code,
            "body": dict(self.body),
            "headers": dict(self.headers),
            "duration_ms": self.duration_ms,
        }


class APIGateway:
    def __init__(self) -> None:
        self._routes: dict[str, Route] = {}
        self._middleware: dict[str, Callable] = {}
        self._request_count: int = 0
        self._error_count: int = 0
        self._route_stats: dict[str, dict[str, int]] = {}
        self._path_params_pattern = re.compile(r"\{(\w+)\}")

    @logged()
    @safe_execute
    def add_route(self, route: Route) -> None:
        key = self._route_key(route.path, route.method)
        self._routes[key] = route
        self._route_stats.setdefault(key, {"count": 0, "errors": 0})
        logger.debug("Added route: %s %s", route.method.value, route.path)

    @logged()
    @safe_execute
    def remove_route(self, path: str, method: HTTPMethod) -> bool:
        key = self._route_key(path, method)
        if key not in self._routes:
            return False
        del self._routes[key]
        self._route_stats.pop(key, None)
        return True

    @logged()
    @safe_execute
    def handle(self, request: GatewayRequest) -> GatewayResponse:
        start = time.monotonic()
        self._request_count += 1
        route = self._match_route(request)
        if route is None:
            duration_ms = (time.monotonic() - start) * 1000.0
            self._error_count += 1
            return GatewayResponse(
                status_code=404,
                body={"error": "Not Found", "path": request.path},
                duration_ms=duration_ms,
            )
        try:
            processed = self._apply_middleware(request, route)
            path_params = self._extract_path_params(request.path, route.path)
            if path_params:
                processed.body["path_params"] = path_params
            if route.handler is None:
                duration_ms = (time.monotonic() - start) * 1000.0
                return GatewayResponse(
                    status_code=501,
                    body={"error": "No handler for route"},
                    duration_ms=duration_ms,
                )
            result = route.handler(processed.body)
            duration_ms = (time.monotonic() - start) * 1000.0
            status_code = 200
            response_body: dict[str, object] = {}
            if isinstance(result, dict):
                status_code = int(result.pop("_status_code", 200))
                response_body = result
            else:
                response_body = {"result": result}
            key = self._route_key(route.path, route.method)
            stats = self._route_stats.setdefault(key, {"count": 0, "errors": 0})
            stats["count"] += 1
            return GatewayResponse(
                status_code=status_code,
                body=response_body,
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = (time.monotonic() - start) * 1000.0
            self._error_count += 1
            key = self._route_key(route.path, route.method)
            stats = self._route_stats.setdefault(key, {"count": 0, "errors": 0})
            stats["errors"] += 1
            logger.exception("Route handler failed: %s %s", request.method.value, request.path)
            return GatewayResponse(
                status_code=500,
                body={"error": str(e)},
                duration_ms=duration_ms,
            )

    @logged()
    @safe_execute
    def add_middleware(self, name: str, middleware_fn: Callable) -> None:
        self._middleware[name] = middleware_fn
        logger.debug("Added middleware: %s", name)

    @logged()
    @safe_execute
    def get_routes(self) -> list[Route]:
        return list(self._routes.values())

    @logged()
    @safe_execute
    def get_stats(self) -> dict[str, object]:
        return {
            "total_requests": self._request_count,
            "total_errors": self._error_count,
            "total_routes": len(self._routes),
            "total_middleware": len(self._middleware),
            "error_rate": (round(self._error_count / max(1, self._request_count), 4)),
            "route_stats": dict(self._route_stats),
        }

    def _match_route(self, request: GatewayRequest) -> Route | None:
        for route in self._routes.values():
            if route.method != request.method:
                continue
            if self._path_matches(request.path, route.path):
                return route
        return None

    def _apply_middleware(self, request: GatewayRequest, route: Route) -> GatewayRequest:
        current = request
        for mw_name in route.middleware:
            mw_fn = self._middleware.get(mw_name)
            if mw_fn is None:
                logger.warning("Middleware not found: %s", mw_name)
                continue
            try:
                result = mw_fn(current)
                if isinstance(result, GatewayRequest):
                    current = result
            except Exception as _exc:
                logger.exception("Middleware '%s' failed", mw_name)
        return current

    def _path_matches(self, request_path: str, route_path: str) -> bool:
        route_parts = route_path.strip("/").split("/")
        request_parts = request_path.strip("/").split("/")
        if len(route_parts) != len(request_parts):
            return False
        for rp, reqp in zip(route_parts, request_parts, strict=False):
            if self._path_params_pattern.match(rp):
                continue
            if rp != reqp:
                return False
        return True

    def _extract_path_params(self, request_path: str, route_path: str) -> dict[str, str]:
        params: dict[str, str] = {}
        route_parts = route_path.strip("/").split("/")
        request_parts = request_path.strip("/").split("/")
        for rp, reqp in zip(route_parts, request_parts, strict=False):
            match = self._path_params_pattern.match(rp)
            if match:
                params[match.group(1)] = reqp
        return params

    def _route_key(self, path: str, method: HTTPMethod) -> str:
        return f"{method.value}:{path}"
