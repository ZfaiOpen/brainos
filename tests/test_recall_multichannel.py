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
"""Multi-channel retrieval (open baseline: fixed-strategy) behavioral tests.

Proves the recall engine is a real multi-channel ranker — not the old
double-lexical pseudo-HYBRID where both "channels" called the same substring
search:

  lexical channel — inverted-index BM25: exact term match with idf weighting
  n-gram channel  — padded char-trigram overlap: morphological variants hit
                    even with zero lexical overlap
  recency         — newer entries rank above equally-relevant older ones
  length norm     — long entries do not drown short, precise ones
  number forms    — "three" ≡ "3" via token normalization (classical IR)
"""

from __future__ import annotations

import time

from brainos.memory.recall import RecallEngine, RecallMode, char_trigrams, tokenize
from brainos.memory.store import MemoryStore
from brainos.memory.types import MemoryEntry


def make_engine(*entries: MemoryEntry) -> tuple[MemoryStore, RecallEngine]:
    store = MemoryStore()
    for entry in entries:
        store.store(entry)
    return store, RecallEngine(store)


def test_tokenize_normalizes_number_words_to_digits() -> None:
    assert tokenize("She bought THREE apples") == ["she", "bought", "3", "apples"]


def test_char_trigrams_share_boundary_grams_with_inflections() -> None:
    base = char_trigrams("run")
    inflected = char_trigrams("running")
    assert base & inflected, "padding must produce shared boundary trigrams"


def test_lexical_channel_hits_exact_terms() -> None:
    _, engine = make_engine(MemoryEntry(content="quantum flux theory of the halo array"))
    hits = engine.recall("quantum flux", mode=RecallMode.HYBRID)
    assert hits
    assert "lexical" in hits[0].channels
    assert hits[0].entry.content.startswith("quantum flux")


def test_ngram_channel_hits_morphological_variant_with_zero_lexical_overlap() -> None:
    # query token "running" appears nowhere in the document ("run"): the
    # lexical channel must miss, the trigram channel must hit.
    _, engine = make_engine(MemoryEntry(content="Morning run around the park."))
    hits = engine.recall("running pace", mode=RecallMode.HYBRID)
    assert hits, "variant query retrieved nothing"
    top = hits[0]
    assert top.entry.content.startswith("Morning run")
    assert "ngram" in top.channels


def test_number_form_variant_hits_lexical_channel() -> None:
    _, engine = make_engine(MemoryEntry(content="She bought three apples at the market."))
    hits = engine.recall("3 apples", mode=RecallMode.HYBRID)
    assert hits and "apples" in hits[0].entry.content
    assert "lexical" in hits[0].channels


def test_recency_boosts_newer_entry_on_equal_relevance() -> None:
    old = MemoryEntry(
        content="board meeting scheduling protocol",
        created_at=time.time() - 60 * 86400,  # two months old
    )
    new = MemoryEntry(content="board meeting scheduling protocol", created_at=time.time())
    _, engine = make_engine(old, new)
    hits = engine.recall("board meeting scheduling", mode=RecallMode.HYBRID, limit=2)
    assert len(hits) == 2
    assert hits[0].entry.created_at > hits[1].entry.created_at, "recency channel had no effect"


def test_length_normalization_keeps_short_precise_entry_on_top() -> None:
    filler = " ".join(["filler"] * 400)
    short = MemoryEntry(content="cuda kernel tuning guide")
    long = MemoryEntry(content=f"{filler} cuda")
    _, engine = make_engine(short, long)
    hits = engine.recall("cuda", mode=RecallMode.HYBRID, limit=2)
    assert hits[0].entry.id == short.id, "long document drowned the precise short one"


def test_hybrid_fuses_both_channels_into_one_ranking() -> None:
    _, engine = make_engine(
        MemoryEntry(content="Kickoff decision: project Apollo launch."),
        MemoryEntry(content="Launch logistics runbook for the running of the pad."),
    )
    hits = engine.recall("project Apollo launch", mode=RecallMode.HYBRID)
    assert hits[0].channels == ["lexical", "ngram"]  # ranked by RRF fusion


def test_keyword_and_semantic_modes_rank_single_channel() -> None:
    store, engine = make_engine(MemoryEntry(content="hippocampal consolidation loop"))
    kw = engine.recall("hippocampal", mode=RecallMode.KEYWORD)
    assert kw and kw[0].match_type == "keyword" and kw[0].channels == ["lexical"]
    sem = engine.recall("hippocampus consolidation loop", mode=RecallMode.SEMANTIC)
    assert sem and sem[0].match_type == "semantic" and sem[0].channels == ["ngram"]


def test_scope_restricts_candidates() -> None:
    store = MemoryStore()
    store.store(MemoryEntry(content="u1 apollo secret", metadata={"user_id": "u1"}))
    store.store(MemoryEntry(content="u2 apollo secret", metadata={"user_id": "u2"}))
    engine = RecallEngine(store)
    hits_u1 = engine.recall("apollo", scope={"user_id": "u1"})
    assert {h.entry.metadata["user_id"] for h in hits_u1} == {"u1"}
    hits_missing = engine.recall("apollo", scope={"user_id": "ghost"})
    assert hits_missing == []


def test_tags_and_min_importance_filters_still_apply() -> None:
    store = MemoryStore()
    store.store(MemoryEntry(content="tagged apollo note", tags=["project"], importance=0.9))
    store.store(MemoryEntry(content="plain apollo note", importance=0.1))
    engine = RecallEngine(store)
    tagged = engine.recall("apollo", tags=["project"])
    assert {h.entry.tags[0] for h in tagged} == {"project"}
    important = engine.recall("apollo", min_importance=0.5)
    assert all(h.entry.importance >= 0.5 for h in important)


def test_route_handler_wrappers_exist_and_rank() -> None:
    """The HTTP route layer calls keyword_search/semantic_search/hybrid_search."""
    _, engine = make_engine(MemoryEntry(content="apollo onboarding memo"))
    assert engine.keyword_search("apollo")
    assert engine.semantic_search("apollo onboarding")
    assert engine.hybrid_search("apollo", top_k=3)


def test_empty_query_and_empty_store_return_empty() -> None:
    _, engine = make_engine(MemoryEntry(content="something"))
    assert engine.recall("") == []
    assert RecallEngine(MemoryStore()).recall("anything") == []
