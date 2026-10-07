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

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MemoryStoreProtocol(Protocol):
    def store(self, key: str, value: Any, layer: str = "short_term", **kwargs: Any) -> bool: ...

    def retrieve(self, key: str, layer: str | None = None, **kwargs: Any) -> Any | None: ...

    def link(self, source_key: str, target_key: str, strength: float = 0.1) -> None: ...

    def get_related(self, key: str, min_strength: float = 0.3) -> list[tuple[str, float]]: ...

    def stats(self) -> dict[str, Any]: ...


@runtime_checkable
class AdvancedMemoryStoreProtocol(MemoryStoreProtocol, Protocol):
    def sleep_consolidate(self) -> dict[str, int]: ...


@runtime_checkable
class EpisodicStoreProtocol(Protocol):
    def store_episode(self, episode: dict[str, Any]) -> str: ...

    def retrieve_episode(self, episode_id: str) -> dict[str, Any] | None: ...


@runtime_checkable
class TemporalKGProtocol(Protocol):
    def add_fact(self, fact: dict[str, Any]) -> str: ...

    def query(self, q: str) -> list[dict[str, Any]]: ...


@runtime_checkable
class MemoryConsolidatorProtocol(Protocol):
    def consolidate(self, memories: list[Any]) -> bool: ...


@runtime_checkable
class ForgettingProtocol(Protocol):
    def apply(self, memories: list[Any]) -> list[Any]: ...


@runtime_checkable
class RetrievalBoostProtocol(Protocol):
    def boost(self, key: str) -> bool: ...

    def get_boosted(self) -> list[tuple[str, float]]: ...


@runtime_checkable
class CognitionEngineProtocol(Protocol):
    def process(self, input_data: str | dict[str, Any], **kwargs: Any) -> dict[str, Any]: ...


@runtime_checkable
class EvolutionEngineProtocol(Protocol):
    def evolve(self, feedback: dict[str, Any]) -> dict[str, Any]: ...


@runtime_checkable
class SecurityEngineProtocol(Protocol):
    def scan(self, content: str, source: str = "") -> Any: ...


CROSS_DOMAIN_PROTOCOLS = {
    "DM-01": MemoryStoreProtocol,
    "DM-01a": AdvancedMemoryStoreProtocol,
    "DM-02": EpisodicStoreProtocol,
    "DM-03": TemporalKGProtocol,
    "DM-04": MemoryConsolidatorProtocol,
    "DM-05": ForgettingProtocol,
    "DM-06": RetrievalBoostProtocol,
    "DC-01": CognitionEngineProtocol,
    "DE-01": EvolutionEngineProtocol,
    "DS-01": SecurityEngineProtocol,
}
