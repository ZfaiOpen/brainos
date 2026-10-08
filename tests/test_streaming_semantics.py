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
"""Streaming temporal semantics — the four rules of the Add/Search call stream.

Mirrors the 16-case deployment smoke (serial alternating Add/Search) as pytest:

  R1  Memories are saved strictly in Add-call order: an earlier Add is
      retrievable by later Searches, and interleaved Adds never evict it.
  R2  A Search must never see an Add that has not been committed yet
      (the time arrow — a violation is an evaluation-invalidating bug).
      Once committed, content is searchable even if its message timestamp
      lies in the future: commit order rules, not message timestamps.
  R3  Different user_ids are fully isolated — zero cross-user leakage.
  R4  Every request is an independent transaction: one malformed Add is
      rejected 4xx and never poisons anyone's memory, and the service stays
      alive.
"""

from __future__ import annotations

import asyncio

import pytest

from brainos.api.aml import AMLBadRequest, AMLService
from brainos.api.middleware import Request
from brainos.api.server import BrainOSAPI


@pytest.fixture()
def service() -> AMLService:
    return AMLService()


@pytest.fixture()
def api(service: AMLService) -> BrainOSAPI:
    api = BrainOSAPI()
    from brainos.api.aml import wire_memory_surface

    wire_memory_surface(api, service=service)
    return api


def blob(payload: object) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False).lower()


def add(service: AMLService, uid: str, sid: str, rid: str, text: str, ts: str):
    return service.add(
        {
            "request_id": rid,
            "user_id": uid,
            "session_id": sid,
            "messages": [{"role": "user", "content": text, "timestamp": ts}],
        }
    )


def search(service: AMLService, uid: str, query: str, top_k: int = 5):
    return service.search({"user_id": uid, "query": query, "top_k": top_k})


# ── R1: strict Add-call-order persistence ───────────────────────────────────


def test_r1a_add_first_event_ok(service: AMLService) -> None:
    status, body = add(service, "u1", "s1", "r-a",
                      "Kickoff decision: Alice chose project Apollo for the Q1 product launch.",
                      "2026-10-08T10:00:00Z")
    assert status == 200 and body["success"] is True


def test_r1b_add_second_event_ok(service: AMLService) -> None:
    add(service, "u1", "s1", "r-a",
        "Kickoff decision: Alice chose project Apollo for the Q1 product launch.",
        "2026-10-08T10:00:00Z")
    status, _ = add(service, "u1", "s1", "r-b",
                    "Mentor note: Alice's academic advisor is Dr. Chen from MIT.",
                    "2026-10-08T10:05:00Z")
    assert status == 200


def test_r1c_first_add_retrievable_by_search(service: AMLService) -> None:
    add(service, "u1", "s1", "r-a",
        "Kickoff decision: Alice chose project Apollo for the Q1 product launch.",
        "2026-10-08T10:00:00Z")
    status, body = search(service, "u1", "Which project did Alice choose for the Q1 launch?")
    assert status == 200 and "apollo" in blob(body)


def test_r1d_interleaved_add_across_sessions_ok(service: AMLService) -> None:
    add(service, "u1", "s1", "r-a",
        "Kickoff decision: Alice chose project Apollo for the Q1 product launch.",
        "2026-10-08T10:00:00Z")
    add(service, "u1", "s1", "r-b",
        "Mentor note: Alice's academic advisor is Dr. Chen from MIT.",
        "2026-10-08T10:05:00Z")
    status, _ = add(service, "u1", "s2", "r-c",
                    "Migration note: on 2026-11-01 Alice switched from Apollo to project Borealis.",
                    "2026-11-01T09:00:00Z")
    assert status == 200  # cross-session add accepted


def test_r1e_earlier_add_survives_interleaved_add(service: AMLService) -> None:
    add(service, "u1", "s1", "r-a",
        "Kickoff decision: Alice chose project Apollo for the Q1 product launch.",
        "2026-10-08T10:00:00Z")
    add(service, "u1", "s1", "r-b",
        "Mentor note: Alice's academic advisor is Dr. Chen from MIT.",
        "2026-10-08T10:05:00Z")
    add(service, "u1", "s2", "r-c",
        "Migration note: on 2026-11-01 Alice switched from Apollo to project Borealis.",
        "2026-11-01T09:00:00Z")
    status, body = search(service, "u1", "Who is Alice's academic advisor?")
    assert status == 200 and "chen" in blob(body)


# ── R2: the time arrow ──────────────────────────────────────────────────────


def test_r2a_search_before_commit_cannot_see_future_add(service: AMLService) -> None:
    add(service, "u1", "s1", "r-a",
        "Kickoff decision: Alice chose project Apollo for the Q1 product launch.",
        "2026-10-08T10:00:00Z")
    status, body = search(service, "u1", "Borealis project migration")
    assert status == 200
    assert "borealis" not in blob(body), "search read an Add that was never committed"


def test_r2b_after_commit_content_is_visible_even_with_future_timestamp(service: AMLService) -> None:
    add(service, "u1", "s1", "r-a",
        "Kickoff decision: Alice chose project Apollo for the Q1 product launch.",
        "2026-10-08T10:00:00Z")
    _, pre = search(service, "u1", "Borealis project migration")
    assert "borealis" not in blob(pre)
    # committed now — its message timestamp (2026-11-01) is in the future,
    # but commit order is what governs visibility:
    add(service, "u1", "s2", "r-c",
        "Migration note: on 2026-11-01 Alice switched from Apollo to project Borealis.",
        "2026-11-01T09:00:00Z")
    status, post = search(service, "u1", "Borealis project migration")
    assert status == 200 and "borealis" in blob(post)


# ── R3: multi-tenant isolation ──────────────────────────────────────────────


def test_r3_isolation_matrix(service: AMLService) -> None:
    add(service, "u1", "s1", "r-a",
        "Kickoff decision: Alice chose project Apollo for the Q1 product launch.",
        "2026-10-08T10:00:00Z")
    status, _ = add(service, "u2", "s1", "r-d",
                    "Team note: Bob's team adopted project Calypso for the billing module.",
                    "2026-10-08T11:00:00Z")
    assert status == 200

    _, leak_u1 = search(service, "u1", "Calypso billing module")
    assert "calypso" not in blob(leak_u1), "u2 memory leaked into u1"

    _, leak_u2 = search(service, "u2", "Apollo Q1 launch")
    assert "apollo" not in blob(leak_u2), "u1 memory leaked into u2"

    _, own_u2 = search(service, "u2", "Calypso billing module")
    assert "calypso" in blob(own_u2), "u2 cannot retrieve its own memory"


def test_r3_isolation_holds_through_recall_engine_scope_too(service: AMLService) -> None:
    add(service, "u1", "s1", "r-a", "Apollo secret of user one.", "2026-10-08T10:00:00Z")
    results = service.recall_engine.recall("Apollo secret", scope={"user_id": "u2"})
    assert results == []


# ── R4: per-request transaction independence ────────────────────────────────


def test_r4a_malformed_add_rejected_via_http_mapping(api: BrainOSAPI, service: AMLService) -> None:
    request = Request(method="POST", path="/add", body={})  # no request_id/user_id
    response = asyncio.run(api.handle_request(request))
    assert response.status_code == 400


def test_r4a2_malformed_message_shape_rejected(service: AMLService) -> None:
    with pytest.raises(AMLBadRequest):
        service.add({"request_id": "r", "user_id": "u1", "session_id": "s", "messages": [42]})


def test_r4bc_service_alive_and_other_users_unaffected_after_malformed(service: AMLService) -> None:
    add(service, "u1", "s1", "r-a",
        "Kickoff decision: Alice chose project Apollo for the Q1 product launch.",
        "2026-10-08T10:00:00Z")
    with pytest.raises(AMLBadRequest):
        service.add({"request_id": "bad", "user_id": "u2", "session_id": "s", "messages": [["not", "an", "object"]]})
    with pytest.raises(AMLBadRequest):
        service.add({"request_id": "bad2", "user_id": "u2", "session_id": "s", "messages": None})

    # service alive: u2 can still add afterwards...
    status, _ = add(service, "u2", "s2", "r-e",
                    "Follow-up: Bob's Calypso rollout review is scheduled for Friday.",
                    "2026-10-08T12:00:00Z")
    assert status == 200
    # ...and retrieve normally
    status, body = search(service, "u2", "Calypso rollout review Friday")
    assert status == 200 and "friday" in blob(body)
    # u1's memory store was not polluted by the failed requests
    status, body = search(service, "u1", "Which project did Alice choose for the Q1 launch?")
    assert status == 200 and "apollo" in blob(body)


def test_r4d_failed_request_leaves_zero_partial_entries(service: AMLService) -> None:
    """Validate-then-commit: a request that fails validation never half-stores."""
    before = service.store.count()["total"]
    with pytest.raises(AMLBadRequest):
        service.add({"request_id": "r", "user_id": "u", "session_id": "s", "messages": [42]})
    assert service.store.count()["total"] == before
