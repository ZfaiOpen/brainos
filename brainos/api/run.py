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
import asyncio
import logging
import os
import signal
import time
from typing import Any, Optional

from brainos.api.server import BrainOSAPI, APIConfig, Request, Response

try:  # commercial version only (the /api/v1 registry is excluded from open core)
    from brainos.api.v1_routes import V1RouteRegistry
except ImportError:  # open-core degradation
    V1RouteRegistry = None  # type: ignore[assignment,misc]

try:  # commercial version only (full process bootstrap is excluded from open core)
    from brainos.bootstrap import BrainOSBootstrap
except ImportError:  # open-core degradation
    BrainOSBootstrap = None  # type: ignore[assignment,misc]

logger = logging.getLogger("brainos.api.run")

try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    import uvicorn

    _HAS_UVICORN = True
except ImportError:
    _HAS_UVICORN = False


class BrainOSAPIServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8080, workers: int = 1) -> None:
        self._host = host
        self._port = port
        self._workers = workers
        self._api = BrainOSAPI(APIConfig(host=host, port=port))
        self._v1_routes = V1RouteRegistry(self._api) if V1RouteRegistry is not None else None
        self._bootstrap_status: dict[str, Any] = {}
        self._start_time = 0.0
        self._running = False

    def bootstrap(self) -> dict[str, Any]:
        if BrainOSBootstrap is None:
            logger.info("Bootstrap skipped: full bootstrap is commercial version only")
            self._bootstrap_status = {"modules": 0, "capabilities": 0, "channels": 0, "mode": "open-core"}
            return self._bootstrap_status
        self._bootstrap_status = BrainOSBootstrap.get_instance().bootstrap()
        logger.info(
            "Bootstrap: %d modules, %d capabilities, %d channels",
            self._bootstrap_status.get("modules", 0),
            self._bootstrap_status.get("capabilities", 0),
            self._bootstrap_status.get("channels", 0),
        )
        return self._bootstrap_status

    async def start(self) -> None:
        self._start_time = time.monotonic()
        self._running = True
        logger.info("BrainOS API starting on %s:%d", self._host, self._port)
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._handle_shutdown, sig)
        await self._serve()

    async def _serve(self) -> None:
        if _HAS_UVICORN:
            app = self._create_fastapi_app()
            config = uvicorn.Config(
                app,
                host=self._host,
                port=self._port,
                workers=1,
                log_level="info",
                access_log=False,
            )
            server = uvicorn.Server(config)
            await server.serve()
        else:
            while self._running:
                await asyncio.sleep(1)

    def _create_fastapi_app(self) -> FastAPI:
        app = FastAPI(
            title="BrainOS API",
            version="0.1.0",
            description="BrainOS - The AI Operating System that Thinks",
        )
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        self._register_routes(app)
        return app

    def _register_routes(self, app: FastAPI) -> None:
        router = self._api.router

        for method, path, handler in router.all_routes():

            def _make_handler(h=handler, m=method, p=path):
                async def _handler():
                    req = Request(method=m, path=p)
                    resp: Response = await self._api.handle_request(req)
                    return JSONResponse(content=resp.body, status_code=resp.status_code)

                return _handler

            route_name = f"{method.lower()}_{path.replace('/', '_').strip('_')}"
            fn = _make_handler()

            if method == "GET":
                app.get(path, name=route_name)(fn)
            elif method == "POST":
                app.post(path, name=route_name)(fn)
            elif method == "PUT":
                app.put(path, name=route_name)(fn)
            elif method == "DELETE":
                app.delete(path, name=route_name)(fn)

    def _handle_shutdown(self, sig: signal.Signals) -> None:
        logger.info("Received signal %s, shutting down...", sig.name)
        self._running = False

    def stop(self) -> None:
        self._running = False

    @property
    def api(self) -> BrainOSAPI:
        return self._api

    def get_status(self) -> dict[str, Any]:
        uptime = time.monotonic() - self._start_time if self._start_time else 0
        return {
            "running": self._running,
            "host": self._host,
            "port": self._port,
            "uptime_seconds": round(uptime, 1),
            "bootstrap": self._bootstrap_status,
            "api_stats": self._api.stats(),
            "v1_routes": self._v1_routes.stats() if self._v1_routes is not None else None,
        }


from typing import Optional
def create_app(host=None, port=None, workers=None):
    # Upstream referenced an undefined global ``config`` here (NameError on
    # every no-arg call). The open-core build reads the same values from
    # environment variables instead.
    _host = host or os.getenv("BRAINOS_API_HOST", "0.0.0.0")
    _port = int(port or os.getenv("BRAINOS_API_PORT", "8080"))
    _workers = int(workers or os.getenv("BRAINOS_API_WORKERS", "1"))
    server = BrainOSAPIServer(host=_host, port=_port, workers=_workers)
    try:
        server.bootstrap()
    except Exception as _exc:
        logger.error("Bootstrap failed, starting in degraded mode: %s", _exc)
    if not getattr(server, "_api", None) or not hasattr(server._api, "router"):
        raise RuntimeError("Core API dependency missing")
    logger.info(
        "App created: host=%s port=%d workers=%d uvicorn=%s",
        _host, _port, _workers, _HAS_UVICORN,
    )
    return server



def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    server = create_app()
    logger.info("BrainOS API Server status: %s", server.get_status())
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        server.stop()
        logger.info("BrainOS API Server stopped")


if __name__ == "__main__":
    main()
