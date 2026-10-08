# Copyright 2026 zfai-open contributors
#
# Copyright (C) 2026 Zfai Open
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See the LICENSE file for details.
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""brainos/memory/recall.py — open baseline: fixed-strategy retrieval.

This module is the retrieval organ of the open core. It ships a *fixed
strategy* multi-channel ranker — pure stdlib, zero network, zero LLM, and no
battle-tuned private parameters (learned channel weights, full-union query
expansion, and window-protection schemes are commercial-version territory and
are deliberately NOT implemented here).

Channels (all computed over the live store):
  1. ``lexical`` — inverted-index BM25 (classical k1/b defaults, idf-weighted,
     document-length normalized so long entries do not dominate short ones).
  2. ``ngram``   — padded character-trigram overlap scored with the overlap
     coefficient; a distributional stand-in for embeddings that makes recall
     robust to morphological variants ("running" vs "run"). An optional
     embedding adapter is future work; until then this channel is the honest
     open-baseline "semantic-ish" arm — it is never presented as an LLM or
     neural embedding.
  3. ``recency`` — a mild exponential time-decay boost applied to the fused
     ranking (newer evidence ranks slightly higher, all else equal).

Fusion: reciprocal rank fusion (RRF, classical k=60) across the channels,
followed by the recency boost. Tokenization normalizes number words to digits
("three" ≡ "3") — plain classical IR normalization.

Scope: ``recall(..., scope={"user_id": ...})`` restricts candidates to entries
whose ``metadata`` contains all given key/value pairs — this is how the AML
contract layer enforces per-user isolation without duplicating ranking logic.
"""
from __future__ import annotations

import logging
import math
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from brainos.kernel.safe_execute import safe_execute
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
    channels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable projection for the HTTP surface (evidence fields)."""
        return {
            "id": self.entry.id,
            "content": self.entry.content,
            "created_at": self.entry.created_at,
            "score": self.score,
            "match_type": self.match_type,
            "channels": list(self.channels),
        }


# ── tokenization / normalization (classical IR, fixed strategy) ─────────────

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Small closed-class number words mapped to digit form so "three apples" and
# "3 apples" share postings. Deliberately minimal — this is normalization, not
# a numeric-understanding feature.
_NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12",
}


def tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumerics, normalize number words to digits."""
    raw = _TOKEN_RE.findall(str(text).lower())
    return [_NUMBER_WORDS.get(tok, tok) for tok in raw]


def char_trigrams(text: str) -> set[str]:
    """Space-padded character trigrams over the normalized token stream.

    Padding guarantees that short tokens ("run") contribute boundary trigrams
    that also occur inside their inflected forms ("running").
    """
    norm = " ".join(tokenize(text))
    padded = f"  {norm} "
    if len(padded) < 3:
        return {padded} if padded else set()
    return {padded[i : i + 3] for i in range(len(padded) - 2)}


# ── inverted index (term -> {entry_id: term_frequency}) ─────────────────────


class _InvertedIndex:
    """Minimal in-memory inverted index maintained incrementally."""

    def __init__(self) -> None:
        self._postings: dict[str, dict[str, int]] = {}
        self._doc_len: dict[str, int] = {}

    def add(self, entry_id: str, tokens: list[str]) -> None:
        self.remove(entry_id)
        counts = Counter(tokens)
        for term, tf in counts.items():
            self._postings.setdefault(term, {})[entry_id] = tf
        self._doc_len[entry_id] = len(tokens)

    def remove(self, entry_id: str) -> None:
        if entry_id not in self._doc_len:
            # still sweep postings: the id may exist without a length record
            for postings in self._postings.values():
                postings.pop(entry_id, None)
            return
        for term in list(self._postings):
            postings = self._postings[term]
            if entry_id in postings:
                del postings[entry_id]
                if not postings:
                    del self._postings[term]
        del self._doc_len[entry_id]

    def postings_for(self, term: str) -> dict[str, int]:
        return self._postings.get(term, {})

    def doc_len(self, entry_id: str) -> int:
        return self._doc_len.get(entry_id, 0)

    @property
    def doc_count(self) -> int:
        return len(self._doc_len)

    def total_doc_len(self) -> int:
        return sum(self._doc_len.values())


# ── channel scorers (fixed defaults — not tuned parameters) ─────────────────

_K1 = 1.2          # BM25 term-frequency saturation (classical default)
_B = 0.75          # BM25 document-length normalization (classical default)
_RRF_K = 60        # reciprocal rank fusion constant (classical default)
_RECENCY_BOOST = 0.25   # max multiplicative boost for brand-new entries
_RECENCY_HALFLIFE_S = 7 * 86400.0  # recency boost halves weekly
_POOL = 50         # per-channel candidate pool depth before fusion


def _recency_factor(entry: MemoryEntry, now: float) -> float:
    age = max(0.0, now - entry.created_at)
    return 1.0 + _RECENCY_BOOST * math.exp(-age / _RECENCY_HALFLIFE_S)


class RecallEngine:
    def __init__(self, store: MemoryStore | None = None) -> None:
        self._store = store
        self._index = _InvertedIndex()
        self._indexed_ids: set[str] = set()
        self._index_lock = threading.Lock()

    @logged()
    @safe_execute
    def set_store(self, store: MemoryStore) -> None:
        with self._index_lock:
            self._store = store
            self._index = _InvertedIndex()
            self._indexed_ids = set()

    # ── public API ──────────────────────────────────────────────────────

    @logged()
    @safe_execute
    def recall(
        self,
        query: str,
        mode: RecallMode = RecallMode.HYBRID,
        limit: int = 10,
        tags: list[str] | None = None,
        min_importance: float = 0.0,
        scope: dict[str, Any] | None = None,
    ) -> list[RecallResult]:
        """Multi-channel recall. Returns up to ``limit`` results, best first.

        ``scope`` filters candidates by exact ``metadata`` key/value matches
        (e.g. ``{"user_id": "u1"}`` for per-tenant isolation).
        """
        if self._store is None or not str(query or "").strip():
            return []
        entries = self._visible_entries(scope)
        if not entries:
            return []
        self._sync_index(entries)

        now = time.time()
        if mode == RecallMode.KEYWORD:
            fused, channel_hits = self._lexical_scores(query, entries), {"lexical"}
        elif mode == RecallMode.SEMANTIC:
            fused, channel_hits = self._ngram_scores(query, entries), {"ngram"}
        else:
            lexical_ranked = self._ranked(self._lexical_scores(query, entries))
            ngram_ranked = self._ranked(self._ngram_scores(query, entries))
            fused = self._fuse(lexical_ranked, ngram_ranked)
            channel_hits = {"lexical": set(lexical_ranked), "ngram": set(ngram_ranked)}

        scored: list[tuple[str, float]] = []
        for entry_id, score in fused.items():
            entry = entries.get(entry_id)
            if entry is None:
                continue
            if entry.importance < min_importance:
                continue
            if tags and not any(t in entry.tags for t in tags):
                continue
            final = score * (_recency_factor(entry, now) if mode == RecallMode.HYBRID else 1.0)
            scored.append((entry_id, final))

        scored.sort(key=lambda pair: pair[1], reverse=True)
        max_score = scored[0][1] if scored else 0.0

        results: list[RecallResult] = []
        for entry_id, score in scored[: max(0, int(limit))]:
            entry = entries[entry_id]
            norm = score / max_score if max_score > 0 else 0.0
            if mode == RecallMode.HYBRID:
                hit_channels = sorted(c for c, ids in channel_hits.items() if entry_id in ids)
            else:
                hit_channels = sorted(channel_hits)
            results.append(
                RecallResult(
                    entry=entry,
                    score=round(norm, 6),
                    match_type=mode.value,
                    highlights=self._extract_highlights(entry.content, str(query)),
                    channels=hit_channels,
                )
            )
        return results

    # thin wrappers used by the HTTP route handlers (brainos.api style)
    def keyword_search(self, query: str, top_k: int = 10, **kw: Any) -> list[RecallResult]:
        return self.recall(query, mode=RecallMode.KEYWORD, limit=top_k, **kw)

    def semantic_search(self, query: str, top_k: int = 10, **kw: Any) -> list[RecallResult]:
        return self.recall(query, mode=RecallMode.SEMANTIC, limit=top_k, **kw)

    def hybrid_search(self, query: str, top_k: int = 10, **kw: Any) -> list[RecallResult]:
        return self.recall(query, mode=RecallMode.HYBRID, limit=top_k, **kw)

    # ── candidate visibility / index sync ───────────────────────────────

    def _visible_entries(self, scope: dict[str, Any] | None) -> dict[str, MemoryEntry]:
        if self._store is None:
            return {}
        all_entries = self._store.list_all()
        if not scope:
            return {e.id: e for e in all_entries}
        want = {str(k): v for k, v in scope.items()}
        out: dict[str, MemoryEntry] = {}
        for e in all_entries:
            meta = e.metadata if isinstance(e.metadata, dict) else {}
            if all(str(k) in meta and meta[str(k)] == v for k, v in want.items()):
                out[e.id] = e
        return out

    def _sync_index(self, entries: dict[str, MemoryEntry]) -> None:
        with self._index_lock:
            live_ids = set(entries)
            for gone in self._indexed_ids - live_ids:
                self._index.remove(gone)
                self._indexed_ids.discard(gone)
            for entry_id, entry in entries.items():
                if entry_id not in self._indexed_ids:
                    self._index.add(entry_id, tokenize(entry.content))
                    self._indexed_ids.add(entry_id)

    # ── channels ────────────────────────────────────────────────────────

    def _lexical_scores(self, query: str, entries: dict[str, MemoryEntry]) -> dict[str, float]:
        """BM25 over the inverted index (length-normalized, idf-weighted)."""
        with self._index_lock:
            n_docs = max(1, self._index.doc_count)
            total_len = self._index.total_doc_len()
            avgdl = (total_len / n_docs) if n_docs else 1.0
            q_tokens = [t for t in tokenize(query) if t]
            scores: dict[str, float] = {}
            for term in set(q_tokens):
                postings = dict(self._index.postings_for(term))
                df = len(postings)
                if df == 0:
                    continue
                idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
                for entry_id, tf in postings.items():
                    if entry_id not in entries:
                        continue  # scoped-out candidate: never contributes
                    dl = max(1, self._index.doc_len(entry_id))
                    denom = tf + _K1 * (1.0 - _B + _B * dl / avgdl)
                    scores[entry_id] = scores.get(entry_id, 0.0) + idf * tf * (_K1 + 1.0) / denom
            return scores

    def _ngram_scores(self, query: str, entries: dict[str, MemoryEntry]) -> dict[str, float]:
        """Character-trigram overlap coefficient (length-robust, fuzzy arm)."""
        q_grams = char_trigrams(query)
        if not q_grams:
            return {}
        scores: dict[str, float] = {}
        for entry_id, entry in entries.items():
            d_grams = char_trigrams(entry.content)
            if not d_grams:
                continue
            overlap = len(q_grams & d_grams) / min(len(q_grams), len(d_grams))
            if overlap > 0.0:
                scores[entry_id] = overlap
        return scores

    # ── fusion ──────────────────────────────────────────────────────────

    @staticmethod
    def _ranked(scores: dict[str, float]) -> list[str]:
        return [eid for eid, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:_POOL]]

    @staticmethod
    def _fuse(*rankings: list[str]) -> dict[str, float]:
        fused: dict[str, float] = {}
        for ranking in rankings:
            for rank, entry_id in enumerate(ranking):
                fused[entry_id] = fused.get(entry_id, 0.0) + 1.0 / (_RRF_K + rank + 1)
        return fused

    # ── highlight helper ────────────────────────────────────────────────

    @staticmethod
    def _extract_highlights(content: str, query: str) -> list[str]:
        highlights: list[str] = []
        q_tokens = [t for t in tokenize(query) if len(t) > 2]
        if not q_tokens:
            return highlights
        content_lower = content.lower()
        for tok in q_tokens:
            idx = content_lower.find(tok)
            while idx != -1 and len(highlights) < 3:
                start = max(0, idx - 20)
                end = min(len(content), idx + len(tok) + 20)
                highlights.append(content[start:end])
                idx = content_lower.find(tok, idx + 1)
            if len(highlights) >= 3:
                break
        return highlights
