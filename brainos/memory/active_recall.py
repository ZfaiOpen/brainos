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
from __future__ import annotations
from brainos.kernel.safe_execute import safe_execute

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from brainos.observability.auto_log import logged

logger = logging.getLogger("brainos.memory.active_recall")


class RecallTier(Enum):
    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    CHUNK = "chunk"


@dataclass
class ActiveRecallResult:
    tier: RecallTier
    results: list[dict[str, Any]]
    confidence: float
    cost_ms: float


class ActiveRecallEngine:
    def __init__(self, store: Any = None, vector_engine: Any = None) -> None:
        self._store = store
        self._vector_engine = vector_engine
        self._stats: dict[str, int] = {"keyword": 0, "semantic": 0, "chunk": 0}

    @logged()
    @safe_execute
    def recall(self, query, max_tier=RecallTier.CHUNK):
        pass


    def _keyword_search(self, query: str) -> ActiveRecallResult:
        results: list[dict[str, Any]] = []
        if self._store:
            try:
                results = self._store.search(query, limit=5)
            except Exception as _exc:
                logger.warning("Keyword recall search failed: %s")
        confidence = 0.9 if results else 0.1
        return ActiveRecallResult(tier=RecallTier.KEYWORD, results=results, confidence=confidence, cost_ms=0)

    def _semantic_search(self, query: str) -> ActiveRecallResult:
        results: list[dict[str, Any]] = []
        if self._vector_engine:
            try:
                results = self._vector_engine.search(query, top_k=5)
            except Exception as _exc:
                logger.warning("Semantic recall search failed: %s")
        confidence = 0.85 if results else 0.3
        return ActiveRecallResult(tier=RecallTier.SEMANTIC, results=results, confidence=confidence, cost_ms=0)

    def _chunk_read(self, _query: str, _doc_id: str) -> ActiveRecallResult:
        return ActiveRecallResult(tier=RecallTier.CHUNK, results=[], confidence=0.5, cost_ms=0)

    @logged()
    @safe_execute
    def get_stats(self) -> dict[str, int]:
        return dict(self._stats)
