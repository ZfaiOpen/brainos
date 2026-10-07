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
from dataclasses import dataclass, field
from typing import Any

from brainos.memory.recall import RecallEngine, RecallMode
from brainos.memory.store import MemoryEntry, MemoryStore
from brainos.observability.auto_log import logged

logger = logging.getLogger("brainos.memory.semantic_injector")


@dataclass
class InjectionResult:
    injected_count: int = 0
    total_tokens_estimate: int = 0
    deduplicated: int = 0
    sources: list[str] = field(default_factory=list)


class SemanticInjector:
    def __init__(
        self,
        store: MemoryStore | None = None,
        recall_engine: RecallEngine | None = None,
        max_inject_tokens: int = 2000,
        top_k: int = 5,
    ) -> None:
        self._store = store
        self._recall = recall_engine or RecallEngine(store)
        self._max_inject_tokens = max_inject_tokens
        self._top_k = top_k
        self._injection_history: list[InjectionResult] = []

    @logged()
    @safe_execute
    def set_store(self, store: MemoryStore) -> None:
        self._store = store
        self._recall.set_store(store)

    @logged()
    @safe_execute
    def inject(
        self,
        query: str,
        existing_context: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> InjectionResult:
        if self._store is None:
            return InjectionResult()

        results = self._recall.recall(
            query=query,
            mode=RecallMode.HYBRID,
            limit=self._top_k,
            tags=tags,
        )

        existing_set = {c.strip().lower() for c in (existing_context or [])}
        injected: list[MemoryEntry] = []
        total_tokens = 0
        deduped = 0
        sources: list[str] = []

        for result in results:
            content_lower = result.entry.content.strip().lower()
            if content_lower in existing_set:
                deduped += 1
                continue
            token_est = max(1, len(result.entry.content) // 4)
            if total_tokens + token_est > self._max_inject_tokens:
                break
            injected.append(result.entry)
            total_tokens += token_est
            sources.append(result.entry.id)

        injection_result = InjectionResult(
            injected_count=len(injected),
            total_tokens_estimate=total_tokens,
            deduplicated=deduped,
            sources=sources,
        )
        self._injection_history.append(injection_result)
        logger.info("Semantic injection: %d items, %d tokens, %d deduped", len(injected), total_tokens, deduped)
        return injection_result

    @logged()
    @safe_execute
    def get_injection_history(self, limit: int = 10) -> list[InjectionResult]:
        return self._injection_history[-limit:]

    @logged()
    @safe_execute
    def get_stats(self) -> dict[str, Any]:
        total_injections = len(self._injection_history)
        total_items = sum(r.injected_count for r in self._injection_history)
        total_deduped = sum(r.deduplicated for r in self._injection_history)
        return {
            "total_injections": total_injections,
            "total_items_injected": total_items,
            "total_deduplicated": total_deduped,
            "max_inject_tokens": self._max_inject_tokens,
            "top_k": self._top_k,
        }
