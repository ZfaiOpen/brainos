# Copyright 2026 zfai-open contributors
#
# Copyright (C) 2026 Zfai Open
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Known upstream gaps in brainos/api: pass-stub methods (carve batch 2).

ATTRIBUTION (AST sweep, source vs staging, keyed by file+function): all 12
pass-only methods under brainos/api exist identically upstream (/opt/brainos_new)
— the v0.9 carve introduced ZERO api stubs.

FULL INVENTORY (brainos/api):
    auth.py                     AuthToken.to_dict
    gateway.py                  Route.to_dict
    rate_limiter.py             RateLimitConfig.to_dict
    route_handlers/observability.py  ObservabilityRouteMetrics.record_query
    route_handlers/schemas.py   AIAnalyzeRequest.to_dict
    websocket.py                WSMessage.to_json, WSMessage._json_default

CLOSED in v0.9.1 (ratchet retired, probes below are now real behavioral
tests): Response.ok, AuthToken.is_expired, MemoryRouteMetrics.record_query,
Route._compile_pattern, BrainOSAPI.post — filled to make the AML contract
surface (POST /add, POST /search, GET /health) live.

Same ratchet as test_known_gaps.py: every probe asserts the INTENDED behavior
with ``xfail(strict=True)`` — it xfails today (stub returns None / unpacking
fails) and XPASSes the moment a stub is filled, forcing the marker to be
replaced by a real behavioral test. Stubs can only move forward.
"""

from __future__ import annotations

import json

import pytest


# --- auth.py ---------------------------------------------------------------


@pytest.mark.xfail(reason="upstream pass-stub: AuthToken.to_dict", strict=True)
def test_auth_token_to_dict_roundtrip_fields() -> None:
    from brainos.api.auth import AuthMethod, AuthToken

    token = AuthToken(
        token_id="tok-1",
        method=AuthMethod.JWT,
        client_id="client-a",
        scopes=["read"],
    )
    data = token.to_dict()
    assert data["token_id"] == "tok-1"
    assert data["client_id"] == "client-a"


def test_auth_token_is_expired_for_past_expiry() -> None:
    from brainos.api.auth import AuthMethod, AuthToken

    token = AuthToken(
        token_id="tok-2",
        method=AuthMethod.API_KEY,
        client_id="client-b",
        expires_at=0.0,  # epoch is always in the past
    )
    assert token.is_expired is True


# --- gateway.py ------------------------------------------------------------


@pytest.mark.xfail(reason="upstream pass-stub: gateway.Route.to_dict", strict=True)
def test_gateway_route_to_dict() -> None:
    from brainos.api.gateway import HTTPMethod, Route

    route = Route(path="/memories", method=HTTPMethod.GET, rate_limit=10)
    data = route.to_dict()
    assert data["path"] == "/memories"
    assert data["rate_limit"] == 10


# --- middleware.py ----------------------------------------------------------


def test_response_ok_classmethod_shape() -> None:
    from brainos.api.middleware import Response

    resp = Response.ok({"answer": 42}, request_id="req-1")
    assert resp.status_code == 200
    assert resp.body == {"answer": 42}
    assert resp.headers.get("X-Request-ID") == "req-1"


# --- rate_limiter.py --------------------------------------------------------


@pytest.mark.xfail(reason="upstream pass-stub: RateLimitConfig.to_dict", strict=True)
def test_rate_limit_config_to_dict() -> None:
    from brainos.api.rate_limiter import LimiterAlgorithm, RateLimitConfig

    cfg = RateLimitConfig(max_requests=5, window_seconds=30.0)
    data = cfg.to_dict()
    assert data["algorithm"] == LimiterAlgorithm.TOKEN_BUCKET.value
    assert data["max_requests"] == 5


# --- route_handlers/memory.py ----------------------------------------------


def test_memory_route_metrics_record_query() -> None:
    from brainos.api.route_handlers.memory import MemoryRouteMetrics

    metrics = MemoryRouteMetrics()
    metrics.record_query(12.5)
    assert metrics.total_queries == 1
    assert metrics.query_latency_total_ms == pytest.approx(12.5)


# --- route_handlers/observability.py ----------------------------------------


@pytest.mark.xfail(reason="upstream pass-stub: ObservabilityRouteMetrics.record_query", strict=True)
def test_observability_route_metrics_record_query() -> None:
    from brainos.api.route_handlers.observability import (
        ObservabilityRouteMetrics,
    )

    metrics = ObservabilityRouteMetrics()
    metrics.record_query("metric", 4.0)
    assert metrics.total_metric_queries == 1
    assert metrics.total_queries == 1


# --- route_handlers/schemas.py ----------------------------------------------


@pytest.mark.xfail(reason="upstream pass-stub: AIAnalyzeRequest.to_dict", strict=True)
def test_ai_analyze_request_to_dict() -> None:
    from brainos.api.route_handlers.schemas import AIAnalyzeRequest

    req = AIAnalyzeRequest(code="print(1)", language="python")
    data = req.to_dict()
    assert data["code"] == "print(1)"
    assert data["language"] == "python"


# --- routes.py ----------------------------------------------------------------


def test_router_route_compiles_pattern_and_extracts_params() -> None:
    from brainos.api.routes import Route

    route = Route(method="GET", pattern="/memories/{memory_id}")
    assert route.match("/memories/abc-123") == {"memory_id": "abc-123"}
    assert route.match("/other") is None


# --- server.py -----------------------------------------------------------------


def test_api_post_registers_route() -> None:
    from brainos.api.server import BrainOSAPI

    api = BrainOSAPI()
    api.post("/query", lambda req: {"ok": True})
    assert api._router.route_count == 1
    assert api._router.match("POST", "/query") is not None


# --- websocket.py ----------------------------------------------------------------


@pytest.mark.xfail(reason="upstream pass-stub: WSMessage.to_json", strict=True)
def test_ws_message_to_json_roundtrip() -> None:
    from brainos.api.websocket import WSMessage

    msg = WSMessage(payload="hello", source="client-1")
    parsed = json.loads(msg.to_json())
    assert parsed["payload"] == "hello"
    assert parsed["source"] == "client-1"


@pytest.mark.xfail(reason="upstream pass-stub: WSMessage._json_default", strict=True)
def test_ws_message_json_default_serializes_non_native_types() -> None:
    from datetime import datetime

    from brainos.api.websocket import WSMessage

    value = datetime(2026, 1, 1, 12, 0, 0)
    assert WSMessage._json_default(value) is not None
    json.dumps({"when": value}, default=WSMessage._json_default)
