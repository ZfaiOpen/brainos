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
from enum import Enum

from brainos.memory.store import MemoryEntry, MemoryStore
from brainos.observability.auto_log import logged

logger = logging.getLogger("brainos.memory.recall")


class RecallMode(Enum):
    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


@dataclass
class RecallResult:
    entry: MemoryEntry
    score: float = 0.0
    match_type: str = ""
    highlights: list[str] = field(default_factory=list)


class RecallEngine:
    def __init__(self, store: MemoryStore | None = None) -> None:
        self._store = store

    @logged()
    @safe_execute
    def set_store(self, store: MemoryStore) -> None:
        self._store = store

    @logged()
    @safe_execute
    def recall(self, query, mode=RecallMode.HYBRID, limit=10, tags=None, min_importance=0.0):
        pass


    def _keyword_recall(
        self,
        query: str,
        limit: int,
        tags: list[str] | None = None,
        min_importance: float = 0.0,
    ) -> list[RecallResult]:
        entries = self._store.search(query, limit=limit * 3)
        results: list[RecallResult] = []
        q_lower = query.lower()
        for entry in entries:
            if entry.importance < min_importance:
                continue
            if tags and not any(t in entry.tags for t in tags):
                continue
            score = self._keyword_score(entry, q_lower)
            highlights = self._extract_highlights(entry.content, q_lower)
            results.append(
                RecallResult(
                    entry=entry,
                    score=score,
                    match_type="keyword",
                    highlights=highlights,
                )
            )
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def _semantic_recall(
        self,
        query: str,
        limit: int,
        tags: list[str] | None = None,
        min_importance: float = 0.0,
    ) -> list[RecallResult]:
        entries = self._store.search(query, limit=limit * 3)
        results: list[RecallResult] = []
        query_words = set(query.lower().split())
        for entry in entries:
            if entry.importance < min_importance:
                continue
            if tags and not any(t in entry.tags for t in tags):
                continue
            score = self._semantic_score(entry, query_words)
            results.append(
                RecallResult(
                    entry=entry,
                    score=score,
                    match_type="semantic",
                )
            )
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def _hybrid_recall(
        self,
        query: str,
        limit: int,
        tags: list[str] | None = None,
        min_importance: float = 0.0,
    ) -> list[RecallResult]:
        keyword_results = self._keyword_recall(query, limit * 2, tags, min_importance)
        semantic_results = self._semantic_recall(query, limit * 2, tags, min_importance)

        merged: dict[str, RecallResult] = {}
        for r in keyword_results:
            merged[r.entry.id] = RecallResult(
                entry=r.entry,
                score=r.score * 0.6,
                match_type="hybrid",
                highlights=r.highlights,
            )
        for r in semantic_results:
            if r.entry.id in merged:
                merged[r.entry.id].score += r.score * 0.4
            else:
                merged[r.entry.id] = RecallResult(
                    entry=r.entry,
                    score=r.score * 0.4,
                    match_type="hybrid",
                )

        results = list(merged.values())
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def _keyword_score(self, entry: MemoryEntry, q_lower: str) -> float:
        content_lower = entry.content.lower()
        count = content_lower.count(q_lower)
        base_score = min(1.0, count * 0.2)
        importance_boost = entry.importance * 0.3
        access_boost = min(0.2, entry.access_count * 0.02)
        return base_score + importance_boost + access_boost

    def _semantic_score(self, entry: MemoryEntry, query_words: set[str]) -> float:
        content_words = set(entry.content.lower().split())
        if not query_words or not content_words:
            return 0.0
        intersection = query_words & content_words
        union = query_words | content_words
        jaccard = len(intersection) / len(union) if union else 0.0
        importance_boost = entry.importance * 0.3
        return jaccard + importance_boost

    def _extract_highlights(self, content: str, q_lower: str) -> list[str]:
        highlights: list[str] = []
        content_lower = content.lower()
        idx = content_lower.find(q_lower)
        while idx != -1 and len(highlights) < 3:
            start = max(0, idx - 20)
            end = min(len(content), idx + len(q_lower) + 20)
            highlights.append(content[start:end])
            idx = content_lower.find(q_lower, idx + 1)
        return highlights
