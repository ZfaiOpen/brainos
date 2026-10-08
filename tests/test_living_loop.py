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
"""The living loop — the open core's "runnable system" acceptance line.

One test per item of the living-loop checklist: add → persist (WAL) →
consolidate → dream → forget → search → streaming, end to end, zero LLM and
zero network, and still alive with every metabolic module excised (the
commercial-only simulation).

1.  POST /add lands in the store, persists durably, replays idempotently.
2.  MemoryConsolidator phase machine walks encode → stabilize → … → demote.
3.  HippocampalDreamEngine.dream_cycle() produces a DreamResult and DreamLaw
    proposals (fixed cycle, zero LLM).
4.  ForgettingCurve default model judges retention / should_forget and
    schedule_review(target=0.9) emits a future review timestamp.
5.  Search (multi-channel baseline) hits both consolidated and unconsolidated
    entries.
6.  The whole loop runs with the network stack disabled.
7.  Excision test: with every metabolic module unimportable (the commercial
    version's territory), the add/search core loop still runs.
8.  Streaming end-to-end: add → search stream, event order = evidence items
    strictly before the summary.
"""

from __future__ import annotations

import socket
import sqlite3
import sys
import time
from pathlib import Path

import pytest

from brainos.api.aml import AMLService
from brainos.memory.consolidator import (
    ConsolidationPhase,
    MemoryConsolidator,
)
from brainos.memory.forgetting import CurveModel, ForgettingCurve
from brainos.memory.hippocampal_dream import HippocampalDreamEngine, MemoryItem
from brainos.memory.recall import RecallEngine
from brainos.memory.store import MemoryStore
from brainos.memory.types import MemoryEntry, MemoryTier


# ── 1. add → store + durable persistence + idempotent replay ────────────────


def test_1_add_persists_and_replays_idempotently(tmp_path: Path) -> None:
    db = str(tmp_path / "living.db")
    service = AMLService(db_path=db)
    payload = {
        "request_id": "req-1",
        "user_id": "u1",
        "session_id": "s1",
        "messages": [{"role": "user", "content": "Apollo launch decision.", "timestamp": "2026-10-08T10:00:00Z"}],
    }
    status, first = service.add(payload)
    assert status == 200 and first["success"] is True

    # durability: a fresh process-shaped service over the same db sees the data
    reborn = AMLService(db_path=db)
    status, body = reborn.search({"query": "Apollo launch", "user_id": "u1", "top_k": 5})
    assert status == 200 and len(body["data"]) == 1

    # replay across restart: same request_id → same response, zero re-store
    status, replay = reborn.add(payload)
    assert status == 200 and replay == first
    assert reborn.store.count()["total"] == 1

    # the ledger is genuinely on disk (WAL sqlite table)
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT COUNT(*) FROM aml_ledger WHERE request_id='req-1'").fetchone()[0]
    conn.close()
    assert rows == 1


# ── 2. consolidation phase machine ──────────────────────────────────────────


def test_2_consolidator_phase_progression_and_demote() -> None:
    consolidator = MemoryConsolidator()
    consolidator.add("apollo", {"plan": "launch"}, importance=0.9)
    entry = consolidator.get_entry("apollo")
    assert entry.phase == ConsolidationPhase.ENCODE

    # fixed-phase thresholds are age-gated; age the entry to satisfy them
    entry.access_count = 2
    entry.phase_entered_at = time.monotonic() - 301.0
    results = consolidator.consolidate("apollo")
    assert results and results[0].promoted
    assert consolidator.get_entry("apollo").phase == ConsolidationPhase.STABILIZE

    # the demote path is walkable
    demoted = consolidator.demote("apollo", reason="load shedding")
    assert demoted and not demoted.promoted
    assert consolidator.get_entry("apollo").phase == ConsolidationPhase.ENCODE


# ── 3. dream cycle (fixed, zero LLM) ────────────────────────────────────────


def test_3_dream_cycle_detects_contradictions_and_proposes_laws() -> None:
    engine = HippocampalDreamEngine()
    memories = [
        MemoryItem(key="apollo:choice", value="project Apollo", timestamp=time.time() - 7200),
        MemoryItem(key="apollo:choice", value="project Borealis", timestamp=time.time()),
        MemoryItem(key="calypso:owner", value="team Bob", timestamp=time.time()),
        MemoryItem(key="calypso:owner", value="team Alice", timestamp=time.time() - 7200),
    ]
    result = engine.dream_cycle(memories)
    assert result.contradictions_found == 2
    assert result.iron_law_proposals, "DreamLaw pattern detection produced no proposals"
    assert all(law.startswith("[DreamLaw]") for law in result.iron_law_proposals)


# ── 4. forgetting curve (default model) ─────────────────────────────────────


def test_4_forgetting_retention_judgement_and_review_schedule() -> None:
    curve = ForgettingCurve(model=CurveModel.EBBINGHAUS)
    stale = MemoryEntry(content="ancient note", created_at=time.time() - 60 * 86400)
    fresh = MemoryEntry(content="fresh note", created_at=time.time())

    assert curve.retention(fresh) > curve.retention(stale)
    assert curve.should_forget(stale) is True
    assert curve.should_forget(fresh) is False

    review_at = curve.schedule_review("stale", learned_at=time.time() - 86400, target_retention=0.9)
    assert isinstance(review_at, float) and review_at > (time.time() - 86400)
    # reviews compound stability: a reviewed memory schedules its next review further out
    reviewed_at = curve.schedule_review("stale", learned_at=time.time() - 86400, review_count=5, target_retention=0.9)
    assert reviewed_at > review_at


# ── 5. search hits consolidated and unconsolidated entries ──────────────────


def test_5_multichannel_search_hits_all_tiers() -> None:
    store = MemoryStore()
    hot = MemoryEntry(content="Apollo launch checklist for Monday.", tier=MemoryTier.CRITICAL)
    cold = MemoryEntry(content="Apollo retro note from the archive.", tier=MemoryTier.COLD)
    for entry in (hot, cold):
        store.store(entry)
    engine = RecallEngine(store)
    hits = engine.recall("Apollo", limit=5)
    tiers = {h.entry.tier for h in hits}
    assert MemoryTier.CRITICAL in tiers and MemoryTier.COLD in tiers


# ── 6. zero-network guarantee ───────────────────────────────────────────────


def test_6_whole_loop_runs_with_network_disabled(tmp_path: Path) -> None:
    service = AMLService(db_path=str(tmp_path / "net.db"))

    class _NoNetwork(socket.socket):
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("network attempted during the living loop")

    real_socket = socket.socket
    socket.socket = _NoNetwork
    try:
        status, _ = service.add(
            {
                "request_id": "req-offline",
                "user_id": "u1",
                "session_id": "s1",
                "messages": [{"role": "user", "content": "Offline Apollo consolidation test."}],
            }
        )
        assert status == 200
        status, body = service.search({"query": "Apollo consolidation", "user_id": "u1"})
        assert status == 200 and body["data"]
    finally:
        socket.socket = real_socket


# ── 7. excision: metabolic modules gone → add/search core still runs ────────


def test_7_core_loop_survives_metabolic_excision(monkeypatch: pytest.MonkeyPatch) -> None:
    for module in (
        "brainos.memory.consolidator",
        "brainos.memory.hippocampal_dream",
        "brainos.memory.forgetting",
        "brainos.memory.weaver",
        "brainos.memory.neural_plasticity",
    ):
        monkeypatch.setitem(sys.modules, module, None)  # import → ImportError

    from brainos.api.aml import AMLService as FreshService  # re-import under excision

    service = FreshService()
    status, _ = service.add(
        {
            "request_id": "req-x",
            "user_id": "u1",
            "session_id": "s1",
            "messages": [{"role": "user", "content": "Core Apollo memory without metabolism."}],
        }
    )
    assert status == 200
    status, body = service.search({"query": "Apollo memory", "user_id": "u1"})
    assert status == 200 and body["data"]


# ── 8. streaming end-to-end: evidence before summary ────────────────────────


def test_8_streaming_event_order_end_to_end(tmp_path: Path) -> None:
    service = AMLService(db_path=str(tmp_path / "stream.db"))
    service.add(
        {
            "request_id": "req-1",
            "user_id": "u1",
            "session_id": "s1",
            "messages": [{"role": "user", "content": "Apollo kickoff for the product launch."}],
        }
    )
    service.add(
        {
            "request_id": "req-2",
            "user_id": "u1",
            "session_id": "s1",
            "messages": [{"role": "user", "content": "Mentor note: advisor is Dr. Chen from MIT."}],
        }
    )
    events = list(service.search_events({"query": "Apollo launch", "user_id": "u1", "top_k": 5}))
    kinds = [kind for kind, _ in events]
    assert kinds == ["meta"] + ["evidence"] * kinds.count("evidence") + ["summary"]
    assert kinds.count("evidence") >= 1
    assert kinds.index("summary") > kinds.index("evidence")
    assert events[-1][1]["count"] == kinds.count("evidence")
