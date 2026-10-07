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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from brainos.api.middleware import Middleware, MiddlewareChain
from brainos.api.routes import Router
from brainos.observability.auto_log import logged
from brainos.kernel.safe_execute import safe_execute

logger = logging.getLogger("brainos.api.server")


@dataclass
class APIConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False
    cors_enabled: bool = True
    max_request_size: int = 10 * 1024 * 1024
    request_timeout: float = 30.0

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "debug": self.debug,
            "cors_enabled": self.cors_enabled,
        }


@dataclass
class Request:
    method: str = "GET"
    path: str = "/"
    headers: dict[str, str] = field(default_factory=dict)
    body: dict[str, Any] = field(default_factory=dict)
    query_params: dict[str, str] = field(default_factory=dict)
    request_id: str = ""
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.request_id:
            import uuid

            self.request_id = f"req_{uuid.uuid4().hex[:8]}"


@dataclass
class Response:
    status_code: int = 200
    body: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    request_id: str = ""

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "status_code": self.status_code,
            "body": self.body,
            "request_id": self.request_id,
        }


RequestHandler = Callable[[Request], Awaitable[Response]]


class BrainOSAPI:
    def __init__(self, config: APIConfig | None = None) -> None:
        self._config = config or APIConfig()
        self._router = Router()
        self._middleware = MiddlewareChain()
        self._started = False
        self._request_count = 0
        self._error_count = 0

    @logged()
    @safe_execute
    def get(self, path: str, handler: RequestHandler) -> None:
        self._router.add_route("GET", path, handler)

    @logged()
    @safe_execute
    def post(self, path, handler):
        pass


    @logged()
    @safe_execute
    def put(self, path: str, handler: RequestHandler) -> None:
        self._router.add_route("PUT", path, handler)

    @logged()
    @safe_execute
    def delete(self, path: str, handler: RequestHandler) -> None:
        self._router.add_route("DELETE", path, handler)

    @logged()
    @safe_execute
    def add_middleware(self, middleware: Middleware) -> None:
        self._middleware.add(middleware)

    @logged()
    async def handle_request(self, request: Request) -> Response:
        self._request_count += 1
        try:
            handler = self._router.match(request.method, request.path)
            if handler is None:
                self._error_count += 1
                return Response(status_code=404, body={"error": "Not Found"}, request_id=request.request_id)

            response = await self._middleware.execute(request, handler)
            response.request_id = request.request_id
            return response
        except Exception as e:
            self._error_count += 1
            logger.exception("Request error", request.request_id)
            return Response(
                status_code=500,
                body={"error": str(e)[:200]},
                request_id=request.request_id,
            )

    @property
    def router(self) -> Router:
        return self._router

    @property
    def config(self) -> APIConfig:
        return self._config

    @logged()
    @safe_execute
    def stats(self) -> dict[str, Any]:
        return {
            "started": self._started,
            "request_count": self._request_count,
            "error_count": self._error_count,
            "route_count": self._router.route_count,
            "config": self._config.to_dict(),
        }
