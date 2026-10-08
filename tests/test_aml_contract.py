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
"""AML wire-contract tests: POST /add, POST /search, POST /search/stream, GET /health.

Contract under test (mirrors the deployed adapter semantics, open baseline):
  /add  → 200 {"success": true, <three IDs echoed>}; request_id idempotent;
          extra fields ignored; multimodal degrades honestly.
  /search → 200 {"data": [{"id", "content", "created_at"}]}, ≤ top_k strictly,
          evidence-only (no answer generation), [] on no match.
  /health auth-exempt. Auth: Authorization: Token <KEY> when configured.
Failures honest: malformed → 4xx, never a fabricated 200.
"""

from __future__ import annotations

import asyncio

import pytest

from brainos.api.aml import (
    AMLBadRequest,
    AMLService,
    format_sse,
    wire_memory_surface,
)
from brainos.api.middleware import Request
from brainos.api.server import BrainOSAPI


def make_api(api_key: str | None = None) -> tuple[BrainOSAPI, AMLService]:
    api = BrainOSAPI()
    _, service = wire_memory_surface(
        api, service=(AMLService(api_key=api_key) if api_key is not None else None)
    )
    return api, service


def call(api: BrainOSAPI, method: str, path: str, body=None, headers=None):
    request = Request(method=method, path=path, headers=headers or {}, body=body or {})
    return asyncio.run(api.handle_request(request))


def add_ok(service: AMLService, rid: str, uid: str, text: str, sid: str = "s1") -> dict:
    status, body = service.add(
        {
            "request_id": rid,
            "user_id": uid,
            "session_id": sid,
            "messages": [{"role": "user", "content": text, "timestamp": "2026-10-08T10:00:00Z"}],
        }
    )
    assert status == 200
    return body


# ── /health ─────────────────────────────────────────────────────────────────


def test_health_is_ok_and_auth_exempt() -> None:
    api, service = make_api(api_key="secret")
    response = call(api, "GET", "/health", headers={})  # no Authorization header
    assert response.status_code == 200
    assert response.body["status"] == "ok"
    assert "POST /add" in response.body["memory"]["routes"]


# ── /add ────────────────────────────────────────────────────────────────────


def test_add_contract_shape_and_id_echo() -> None:
    _, service = make_api()
    body = add_ok(service, "req-1", "u1", "Alice chose project Apollo for the Q1 launch.")
    assert body == {
        "success": True,
        "request_id": "req-1",
        "user_id": "u1",
        "session_id": "s1",
    }


def test_add_idempotent_replay_stores_once() -> None:
    _, service = make_api()
    first = add_ok(service, "req-1", "u1", "Apollo kickoff note.")
    total_after_first = service.store.count()["total"]
    second = add_ok(service, "req-1", "u1", "Apollo kickoff note.")
    assert second == first
    assert service.store.count()["total"] == total_after_first  # zero re-store


def test_add_ignores_extra_fields() -> None:
    _, service = make_api()
    status, body = service.add(
        {
            "request_id": "req-x",
            "user_id": "u1",
            "session_id": "s1",
            "messages": [{"role": "user", "content": "hello memory"}],
            "metadata": {"evil": True},
            "app_id": "app-1",
            "agent_id": "agent-1",
            "async_mode": True,
            "options": ["ignored"],
        }
    )
    assert status == 200
    assert body["success"] is True and "metadata" not in body


@pytest.mark.parametrize(
    "payload",
    [
        {},  # everything missing
        {"request_id": "", "user_id": "u", "session_id": "s", "messages": []},  # empty rid
        {"request_id": "r", "user_id": 7, "session_id": "s", "messages": []},  # uid not str
        {"request_id": "r", "user_id": "u", "session_id": None, "messages": []},  # sid not str
        {"request_id": "r", "user_id": "u", "session_id": "s", "messages": "nope"},  # not list
        {"request_id": "r", "user_id": "u", "session_id": "s", "messages": ["nope"]},  # not objects
    ],
)
def test_add_malformed_payloads_rejected_4xx(payload: dict) -> None:
    _, service = make_api()
    with pytest.raises(AMLBadRequest):
        service.add(payload)


def test_add_empty_and_blank_messages_still_succeed_without_storing() -> None:
    _, service = make_api()
    status, body = service.add(
        {
            "request_id": "req-empty",
            "user_id": "u1",
            "session_id": "s1",
            "messages": [
                {"role": "user", "content": ""},
                {"role": "user", "content": None},
                {"role": "assistant"},
            ],
        }
    )
    assert status == 200 and body["success"] is True
    assert service.store.count()["total"] == 0


def test_add_multimodal_degradation_is_honest() -> None:
    _, service = make_api()
    service.add(
        {
            "request_id": "req-mm",
            "user_id": "u1",
            "session_id": "s1",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Look at this chart:"},
                        {"type": "image_url", "image_url": {"url": "data:..."}},
                        {"type": "image_url", "image_url": {"url": "data:..."}},
                        {"type": "mystery_part", "payload": "skip me"},
                    ],
                }
            ],
        }
    )
    entries = service.store.list_all()
    assert len(entries) == 1
    content = entries[0].content
    assert "Look at this chart:" in content
    assert "[image]x2" in content  # honest placeholder, no vision claimed
    assert "mystery_part" not in content  # unknown part type skipped


# ── /search ─────────────────────────────────────────────────────────────────


def test_search_contract_shape_evidence_only() -> None:
    _, service = make_api()
    add_ok(service, "req-1", "u1", "Alice chose project Apollo for the Q1 launch.")
    status, body = service.search({"query": "Which project did Alice choose?", "user_id": "u1", "top_k": 5})
    assert status == 200
    assert set(body.keys()) == {"data"}
    for item in body["data"]:
        assert set(item.keys()) == {"id", "content", "created_at"}
        assert item["id"] and item["content"]
    assert any("Apollo" in item["content"] for item in body["data"])


def test_search_respects_top_k_strictly_and_empty_on_no_match() -> None:
    _, service = make_api()
    for i in range(5):
        add_ok(service, f"req-{i}", "u1", f"Note number {i} about project Apollo logistics.")
    _, body = service.search({"query": "Apollo", "user_id": "u1", "top_k": 2})
    assert len(body["data"]) <= 2
    _, body = service.search({"query": "xylophone quantum zeppelin", "user_id": "u1"})
    assert body["data"] == []


@pytest.mark.parametrize(
    "payload",
    [
        {"query": "", "user_id": "u1"},
        {"query": "hello"},
        {"user_id": "u1"},
        {"query": 42, "user_id": "u1"},
        {"query": "hello", "user_id": "u1", "top_k": "many"},
    ],
)
def test_search_malformed_payloads_rejected_4xx(payload: dict) -> None:
    _, service = make_api()
    with pytest.raises(AMLBadRequest):
        service.search(payload)


def test_search_top_k_is_clamped_not_rejected() -> None:
    _, service = make_api()
    add_ok(service, "req-1", "u1", "Apollo note.")
    status, body = service.search({"query": "Apollo", "user_id": "u1", "top_k": 10_000})
    assert status == 200  # clamped to the contract cap, not an error


# ── auth (configurable Token) ───────────────────────────────────────────────


def test_token_auth_enforced_when_configured() -> None:
    api, _ = make_api(api_key="sekrit")
    body = {"request_id": "r", "user_id": "u1", "session_id": "s", "messages": [{"role": "user", "content": "x"}]}
    assert call(api, "POST", "/add", body).status_code == 401  # missing
    assert call(api, "POST", "/add", body, headers={"Authorization": "Token wrong"}).status_code == 401
    assert call(api, "POST", "/add", body, headers={"Authorization": "Bearer sekrit"}).status_code == 401
    assert call(api, "POST", "/add", body, headers={"Authorization": "Token sekrit"}).status_code == 200
    assert call(api, "POST", "/search", {"query": "x", "user_id": "u1"}, headers={"Authorization": "Token sekrit"}).status_code == 200


def test_auth_disabled_when_no_key_configured() -> None:
    api, _ = make_api()
    body = {"request_id": "r", "user_id": "u1", "session_id": "s", "messages": [{"role": "user", "content": "x"}]}
    assert call(api, "POST", "/add", body).status_code == 200


# ── /search/stream (SSE event sequence) ─────────────────────────────────────


def test_stream_events_order_evidence_before_summary() -> None:
    _, service = make_api()
    add_ok(service, "req-1", "u1", "Apollo kickoff for the launch.")
    add_ok(service, "req-2", "u1", "Mentor note: advisor is Dr. Chen.")
    events = list(service.search_events({"query": "Apollo", "user_id": "u1", "top_k": 5}))
    kinds = [kind for kind, _ in events]
    assert kinds[0] == "meta"
    assert kinds[-1] == "summary"
    assert kinds.count("evidence") >= 1
    assert kinds.index("evidence") < kinds.index("summary")  # evidence strictly before summary


def test_stream_events_error_for_malformed_body() -> None:
    _, service = make_api()
    events = list(service.search_events({"query": "", "user_id": "u1"}))
    assert events == [("error", {"error": events[0][1]["error"], "status": 400})]


def test_format_sse_frame_shape() -> None:
    frame = format_sse("evidence", {"id": "i1"})
    assert frame.startswith("event: evidence\n")
    assert frame.endswith("\n\n")
    assert '"id": "i1"' in frame or '"id":"i1"' in frame


# ── routing integration (the endpoints must actually be registered) ─────────


def test_aml_routes_registered_on_router() -> None:
    api, _ = make_api()
    registered = {(r["method"], r["pattern"]) for r in api.router.list_routes()}
    assert ("POST", "/add") in registered
    assert ("POST", "/search") in registered
    assert ("GET", "/health") in registered


def test_wire_memory_surface_also_registers_legacy_memory_routes() -> None:
    api, service = make_api()
    registered = {(r["method"], r["pattern"]) for r in api.router.list_routes()}
    assert ("GET", "/api/v1/memory/status") in registered
    assert ("POST", "/api/v1/memory/recall") in registered
