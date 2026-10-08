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
"""Minimal smoke suite for the brainos open core (v0.9).

Scope: package import integrity, public symbol surface, per-module import of
every carved memory module, and a zero-network guarantee check.

Desensitization discipline: assertions are structural/invariant only — no
battle-tuned constant values are asserted anywhere in this suite.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import ROOT

import brainos
import brainos.memory as memory_pkg

# Symbols that must stay importable from the package facade: the public API
# surface of the memory core. If a carve change removes one of these, this
# test is the tripwire.
# Facade decision (carve batch 2): the five consumer-facing layer types
# (Episode/EpisodeStore/SemanticMemory/WorkingMemory/ShortTermMemory) are
# re-exported from brainos.memory so consumers do not need submodule imports.
EXPECTED_EXPORTS = (
    "CoreBelief",
    "CoreMemory",
    "MemoryEntry",
    "MemoryStore",
    "MemoryTier",
    "MemoryType",
    "MemoryManager",
    "MemoryWeaver",
    "MemoryTrigger",
    "CurveModel",
    "Deduplicator",
    "DedupResult",
    "RecallEngine",
    "RecallResult",
    "RecallMode",
    "RecallTier",
    "RetentionEstimate",
    "ForgettingCurve",
    "ForgettingStats",
    "MemoryConsolidator",
    "ConsolidationPhase",
    "ContextEngine",
    "Distiller",
    "DistillationStatus",
    "IntentMapper",
    "SemanticInjector",
    "StateSnapshot",
    "Snapshot",
    "Anchor",
    "MemoryAnchor",
    "Episode",
    "EpisodeStore",
    "SemanticMemory",
    "ShortTermMemory",
    "WorkingMemory",
)


def test_package_import_and_version() -> None:
    assert brainos.__version__ == "0.9.0"


@pytest.mark.parametrize("symbol", EXPECTED_EXPORTS)
def test_public_symbol_importable(symbol: str) -> None:
    obj = getattr(memory_pkg, symbol, None)
    assert obj is not None, f"brainos.memory.{symbol} missing from package facade"


@pytest.mark.parametrize(
    ("facade_name", "module_name"),
    [
        ("Episode", "brainos.memory.episode.Episode"),
        ("EpisodeStore", "brainos.memory.episode.EpisodeStore"),
        ("SemanticMemory", "brainos.memory.semantic.SemanticMemory"),
        ("ShortTermMemory", "brainos.memory.short_term.ShortTermMemory"),
        ("WorkingMemory", "brainos.memory.working.WorkingMemory"),
    ],
)
def test_facade_reexports_are_the_canonical_classes(facade_name: str, module_name: str) -> None:
    """Facade exports must be identity-re-exports, not wrapper copies."""
    from importlib import import_module

    mod_path, cls_name = module_name.rsplit(".", 1)
    canonical = getattr(import_module(mod_path), cls_name)
    assert getattr(memory_pkg, facade_name) is canonical


def test_all_memory_modules_import() -> None:
    """Every carved module under brainos/memory must import cleanly."""
    mem_dir = ROOT / "brainos" / "memory"
    modules = sorted(
        p.stem for p in mem_dir.glob("*.py") if p.stem != "__init__"
    )
    assert modules, "no modules discovered — carve layout changed?"
    failures: dict[str, str] = {}
    for name in modules:
        try:
            importlib.import_module(f"brainos.memory.{name}")
        except Exception as exc:  # noqa: BLE001 — smoke must report any import failure
            failures[name] = repr(exc)
    assert not failures, f"modules failed to import: {failures}"


def test_import_pulls_no_http_clients() -> None:
    """Fresh interpreter: importing the memory core must not load HTTP client
    libraries (zero-dependency + zero-network guarantee of the open core)."""
    code = (
        "import sys; import brainos.memory;"
        "bad = [m for m in ('requests','httpx','aiohttp','urllib3','pycurl')"
        " if m in sys.modules]; print(','.join(bad))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "", (
        f"HTTP client modules loaded on import: {proc.stdout.strip()}"
    )


def test_memory_client_facade_constructs_offline() -> None:
    """The SDK facade must construct without any network activity
    (default base_url is localhost; constructor stores state only)."""
    from brainos.memory.sdk import MemoryClient

    client = MemoryClient(api_key="smoke-test-key")
    assert client is not None


def test_core_defaults_initialized() -> None:
    from brainos.memory import CoreMemory

    core = CoreMemory()
    assert core.size >= 9  # declarative defaults block
    name = core.retrieve("identity.name")
    assert isinstance(name, str) and name  # present, value not pinned here


def test_forgetting_curve_models_enumerated() -> None:
    from brainos.memory import CurveModel

    names = {m.name for m in CurveModel}
    assert {"EBBINGHAUS", "EXPONENTIAL", "POWER_LAW"} <= names
