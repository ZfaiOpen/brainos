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
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from brainos.observability.auto_log import logged
from brainos.kernel.safe_execute import safe_execute

logger = logging.getLogger("brainos.api.middleware")


@dataclass
class Request:
    method: str = "GET"
    path: str = "/"
    headers: dict[str, str] = field(default_factory=dict)
    body: dict[str, Any] = field(default_factory=dict)
    request_id: str = ""
    query_params: dict[str, str] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class Response:
    status_code: int = 200
    body: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    @logged()
    @safe_execute
    def ok(cls, data=None, request_id=""):
        pass


    @classmethod
    @logged()
    @safe_execute
    def created(cls, data: str | int | float | bool | dict[str, Any] | list[Any] | None = None, request_id: str = "") -> Response:
        body = data if isinstance(data, dict) else {"data": data}
        return cls(status_code=201, body=body)

    @classmethod
    @logged()
    @safe_execute
    def bad_request(cls, message: str = "Bad Request", request_id: str = "") -> Response:
        return cls(status_code=400, body={"error": message})

    @classmethod
    @logged()
    @safe_execute
    def unauthorized(cls, message: str = "Unauthorized", request_id: str = "") -> Response:
        return cls(status_code=401, body={"error": message})

    @classmethod
    @logged()
    @safe_execute
    def forbidden(cls, message: str = "Forbidden", request_id: str = "") -> Response:
        return cls(status_code=403, body={"error": message})

    @classmethod
    @logged()
    @safe_execute
    def not_found(cls, message: str = "Not Found", request_id: str = "") -> Response:
        return cls(status_code=404, body={"error": message})

    @classmethod
    @logged()
    @safe_execute
    def internal_error(cls, message: str = "Internal Server Error", request_id: str = "") -> Response:
        return cls(status_code=500, body={"error": message})


Middleware = Callable[[Request, Callable[..., Awaitable[Response]]], Awaitable[Response]]


class MiddlewareChain:
    def __init__(self) -> None:
        self._middlewares: list[Middleware] = []

    @logged()
    @safe_execute
    def add(self, middleware: Middleware) -> None:
        self._middlewares.append(middleware)

    @logged()
    @safe_execute
    def remove(self, middleware: Middleware) -> bool:
        if middleware in self._middlewares:
            self._middlewares.remove(middleware)
            return True
        return False

    @logged()
    async def execute(
        self,
        request: Request,
        handler: Callable[..., Awaitable[Response]],
    ) -> Response:
        async def _chain(index: int, req: Request) -> Response:
            if index >= len(self._middlewares):
                return await handler(req)
            middleware = self._middlewares[index]
            return await middleware(req, lambda r: _chain(index + 1, r))

        return await _chain(0, request)

    @property
    def count(self) -> int:
        return len(self._middlewares)


@logged()
async def logging_middleware(request: Request, next_handler: Callable[..., Awaitable[Response]]) -> Response:
    start = time.monotonic()
    response = await next_handler(request)
    duration_ms = (time.monotonic() - start) * 1000.0
    logger.info("%s %s -> %d (%.1fms)", request.method, request.path, response.status_code, duration_ms)
    return response


@logged()
async def cors_middleware(request: Request, next_handler: Callable[..., Awaitable[Response]]) -> Response:
    if request.method == "OPTIONS":
        resp = Response(status_code=204)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Max-Age"] = "86400"
        return resp
    response = await next_handler(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


@logged()
async def auth_middleware(request: Request, next_handler: Callable[..., Awaitable[Response]]) -> Response:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header:
        return Response(status_code=401, body={"error": "Unauthorized"})
    return await next_handler(request)
