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
from brainos.kernel.safe_execute import safe_execute

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from brainos.observability.auto_log import logged

logger = logging.getLogger("brainos.memory.neural_plasticity")


@dataclass
class SynapticConnection:
    neuron_a: str
    neuron_b: str
    strength: float = 0.5
    created_at: float = field(default_factory=time.monotonic)
    last_reinforced: float = field(default_factory=time.monotonic)
    reinforcement_count: int = 0


class NeuralPlasticityEngine:
    def __init__(self) -> None:
        self._connections: dict[tuple[str, str], SynapticConnection] = {}
        self._lock: Any = None

    def _get_lock(self):
            import threading
    from typing import Any
    from typing import Any


    @staticmethod
    def _normalize_pair(neuron_a: str, neuron_b: str) -> tuple[str, str]:
        return (neuron_a, neuron_b) if neuron_a <= neuron_b else (neuron_b, neuron_a)

    @logged()
    @safe_execute
    def hebbian_learn(self, neuron_a, neuron_b, strength=0.5):
        pass


    @logged()
    @safe_execute
    def synaptic_prune(self, threshold: float = 0.1) -> int:
        with self._get_lock():
            to_prune = [k for k, conn in self._connections.items() if conn.strength < threshold]
            for key in to_prune:
                del self._connections[key]
            return len(to_prune)

    @logged()
    @safe_execute
    def homeostasis(self, target_avg: float = 0.5) -> dict:
        with self._get_lock():
            if not self._connections:
                return {"total_connections": 0, "avg_strength": 0.0, "scaling_factor": 1.0}
            strengths = [conn.strength for conn in self._connections.values()]
            current_avg = sum(strengths) / len(strengths)
            if current_avg <= 0.0:
                return {"total_connections": len(self._connections), "avg_strength": 0.0, "scaling_factor": 1.0}
            scaling_factor = target_avg / current_avg
            for conn in self._connections.values():
                conn.strength = max(0.0, min(1.0, conn.strength * scaling_factor))
            new_strengths = [conn.strength for conn in self._connections.values()]
            new_avg = sum(new_strengths) / len(new_strengths)
            return {
                "total_connections": len(self._connections),
                "avg_strength": round(new_avg, 6),
                "scaling_factor": round(scaling_factor, 6),
            }

    @logged()
    @safe_execute
    def get_connection(self, neuron_a: str, neuron_b: str) -> float | None:
        key = self._normalize_pair(neuron_a, neuron_b)
        with self._get_lock():
            conn = self._connections.get(key)
            return conn.strength if conn is not None else None

    @logged()
    @safe_execute
    def get_stats(self) -> dict:
        with self._get_lock():
            if not self._connections:
                return {
                    "total_connections": 0,
                    "avg_strength": 0.0,
                    "max_strength": 0.0,
                    "min_strength": 0.0,
                }
            strengths = [conn.strength for conn in self._connections.values()]
            return {
                "total_connections": len(self._connections),
                "avg_strength": round(sum(strengths) / len(strengths), 6),
                "max_strength": max(strengths),
                "min_strength": min(strengths),
            }
