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

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SemanticEntry:
    key: str
    value: Any
    keywords: set[str] = field(default_factory=set)
    category: str = ""
    confidence: float = 1.0
    source: str = ""
    access_count: int = 0
    created_at: float = field(default_factory=time.monotonic)
    updated_at: float = field(default_factory=time.monotonic)


def _tokenize(text):
    if not text or not isinstance(text, str):
        return set()
    try:
        tokens = re.findall(
            r"[a-zA-Z\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]*",
            text.lower()
        )
        return set(tokens) if tokens else set()
    except Exception as _exc:
        logger.warning(
            "Tokenization failed, returning empty set: %s",
            _exc,
            exc_info=True
        )
        return set()



def _keyword_overlap_score(query_tokens: set[str], entry_tokens: set[str]) -> float:
    if not query_tokens or not entry_tokens:
        return 0.0
    overlap = query_tokens & entry_tokens
    return len(overlap) / len(query_tokens)


class SemanticMemory:
    def __init__(self) -> None:
        self._memory_store: dict[str, Any] = {}
        self._entries: dict[str, SemanticEntry] = {}
        self._index: dict[str, set[str]] = {}

    def read(self, key: str) -> Any:
        entry = self._entries.get(key)
        if entry is not None:
            entry.access_count += 1
            return entry.value
        return self._memory_store.get(key, None)

    def write(self, key: str, value: Any) -> None:
        self.store(key, value)

    def store(self, key: str, value: Any, category: str = "", confidence: float = 1.0, source: str = "") -> bool:
        text = self._extract_text(value)
        keywords = _tokenize(text)
        now = time.monotonic()
        if key in self._entries:
            old_entry = self._entries[key]
            for kw in old_entry.keywords:
                bucket = self._index.get(kw)
                if bucket is not None:
                    bucket.discard(key)
                    if not bucket:
                        self._index.pop(kw, None)
        entry = SemanticEntry(
            key=key,
            value=value,
            keywords=keywords,
            category=category,
            confidence=confidence,
            source=source,
            created_at=self._entries[key].created_at if key in self._entries else now,
            updated_at=now,
        )
        self._entries[key] = entry
        self._memory_store[key] = value
        for kw in keywords:
            self._index.setdefault(kw, set()).add(key)
        return True

    def retrieve(self, key: str) -> Any:
        return self.read(key)

    def search(self, query: str, top_k: int = 10, min_score: float = 0.1, category: str | None = None) -> list[tuple[str, Any, float]]:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []
        candidate_keys: set[str] = set()
        for token in query_tokens:
            bucket = self._index.get(token)
            if bucket:
                candidate_keys.update(bucket)
        if not candidate_keys:
            return []
        scored: list[tuple[str, Any, float]] = []
        for key in candidate_keys:
            entry = self._entries.get(key)
            if entry is None:
                continue
            if category is not None and entry.category != category:
                continue
            score = _keyword_overlap_score(query_tokens, entry.keywords)
            if entry.access_count > 0:
                score = min(1.0, score + 0.05 * min(entry.access_count, 5))
            if score >= min_score:
                scored.append((key, entry.value, round(score, 4)))
        scored.sort(key=lambda x: x[2], reverse=True)
        return scored[:top_k]

    def search_by_category(self, category: str, limit: int = 50) -> list[tuple[str, Any]]:
        results: list[tuple[str, Any]] = []
        for key, entry in self._entries.items():
            if entry.category == category:
                results.append((key, entry.value))
            if len(results) >= limit:
                break
        return results

    def delete(self, key: str) -> bool:
        entry = self._entries.pop(key, None)
        if entry is None:
            self._memory_store.pop(key, None)
            return False
        for kw in entry.keywords:
            bucket = self._index.get(kw)
            if bucket is not None:
                bucket.discard(key)
                if not bucket:
                    self._index.pop(kw, None)
        self._memory_store.pop(key, None)
        return True

    def clear(self) -> None:
        self._memory_store.clear()
        self._entries.clear()
        self._index.clear()

    def get_stats(self) -> dict[str, Any]:
        categories: dict[str, int] = {}
        for entry in self._entries.values():
            cat = entry.category or "uncategorized"
            categories[cat] = categories.get(cat, 0) + 1
        return {
            "total_entries": len(self._entries),
            "index_size": len(self._index),
            "categories": categories,
        }

    def _extract_text(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            parts: list[str] = []
            for v in value.values():
                if isinstance(v, str):
                    parts.append(v)
                elif isinstance(v, (list, tuple)):
                    for item in v:
                        if isinstance(item, str):
                            parts.append(item)
            return " ".join(parts)
        return str(value)
