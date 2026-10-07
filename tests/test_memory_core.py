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
"""Behavioral tests for the CoreMemory identity/value belief store.

All assertions are invariant-level (roundtrip, immutability protection,
category partitioning, thread safety). No tuned-constant values asserted.
"""

from __future__ import annotations

import threading

from brainos.memory import CoreBelief, CoreMemory


def test_store_retrieve_roundtrip() -> None:
    core = CoreMemory()
    baseline = core.size
    assert core.store("user.language", "zh-CN", category="preference") is True
    assert core.size == baseline + 1
    assert core.retrieve("user.language") == "zh-CN"


def test_retrieve_missing_returns_none() -> None:
    core = CoreMemory()
    assert core.retrieve("no.such.key") is None
    assert core.retrieve_belief("no.such.key") is None


def test_immutable_belief_cannot_be_overwritten_or_deleted() -> None:
    core = CoreMemory()
    assert core.store("pin.color", "blue", immutable=True) is True
    # overwrite refused, original preserved
    assert core.store("pin.color", "red") is False
    assert core.retrieve("pin.color") == "blue"
    # delete refused
    assert core.delete("pin.color") is False
    assert core.retrieve("pin.color") == "blue"


def test_mutable_belief_overwrite_and_delete() -> None:
    core = CoreMemory()
    core.store("note.text", "v1")
    assert core.store("note.text", "v2") is True
    assert core.retrieve("note.text") == "v2"
    assert core.delete("note.text") is True
    assert core.retrieve("note.text") is None
    assert core.delete("note.text") is False  # second delete is a no-op


def test_get_by_category_partitions() -> None:
    core = CoreMemory()
    identity = core.get_by_category("identity")
    assert len(identity) >= 3
    assert all(isinstance(b, CoreBelief) for b in identity)
    assert all(b.category == "identity" for b in identity)


def test_get_identity_and_values_are_mappings() -> None:
    core = CoreMemory()
    identity = core.get_identity()
    values = core.get_values()
    assert isinstance(identity, dict) and identity
    assert isinstance(values, dict) and values
    # constraints land in get_values, not get_identity
    assert "constraints.no_harm" in values
    assert "constraints.no_harm" not in identity


def test_check_constraint_semantics() -> None:
    core = CoreMemory()
    assert core.check_constraint("constraints.no_harm") is True
    # absent constraint does not block by design
    assert core.check_constraint("constraints.not_defined") is True
    core.store("constraints.custom_gate", False, category="constraints")
    assert core.check_constraint("constraints.custom_gate") is False


def test_retrieve_belief_returns_full_record() -> None:
    core = CoreMemory()
    belief = core.retrieve_belief("values.transparency")
    assert isinstance(belief, CoreBelief)
    assert belief.key == "values.transparency"
    assert 0.0 <= belief.confidence <= 1.0


def test_concurrent_store_thread_safety() -> None:
    core = CoreMemory()
    baseline = core.size
    n_threads, per_thread = 8, 25
    errors: list[BaseException] = []

    def worker(tid: int) -> None:
        try:
            for i in range(per_thread):
                core.store(f"thread.{tid}.{i}", i)
        except BaseException as exc:  # noqa: BLE001 — surfaced via assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert core.size == baseline + n_threads * per_thread
