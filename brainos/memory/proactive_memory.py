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
"""
import heapq
Proactive Memory v1.0

Inspired by Cognitive Workspace (arXiv 2025.08) — 主动记忆管理
系统自动根据当前任务上下文推送相关记忆，不等用户问

核心能力:
  1. 上下文感知: 基于当前任务关键词匹配相关记忆
  2. 主动推送: 检测到相似场景时自动提醒历史经验
  3. 过期清理: 定期清理过期/冲突记忆
"""
from __future__ import annotations


import time
import logging
import threading
from dataclasses import dataclass
from typing import Any
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ProactiveSuggestion:
    key: str
    value: Any
    relevance: float
    reason: str
    timestamp: float = 0.0


class ProactiveMemory:
    def __init__(self) -> None:
        self._memory: dict[str, dict[str, Any]] = {}
        self._tag_index: dict[str, list[str]] = {}
        self._suggestions_fired: int = 0
        self._lock = threading.Lock()

    def store(self, key: str, value: Any, tags: list[str] | None = None) -> None:
        with self._lock:
            self._memory[key] = {
                "value": value,
                "tags": tags or [],
                "timestamp": time.time(),
                "access_count": 0,
            }
            for tag in (tags or []):
                self._tag_index.setdefault(tag, []).append(key)

    def suggest(self, context_tags: list[str], top_k: int = 3) -> list[ProactiveSuggestion]:
            if not context_tags or top_k <= 0:
                return []

            suggestions: list[ProactiveSuggestion] = []
            seen_keys: set[str] = set()
            context_set = set(context_tags)
            ctx_len = max(len(context_tags), 1)

            try:
                with self._lock:
                    for tag in context_set:
                        for key in self._tag_index.get(tag, []):
                            if key in seen_keys:
                                continue
                            seen_keys.add(key)
                            entry = self._memory.get(key)
                            if not entry:
                                continue

                            entry_tags = set(entry.get("tags", []))
                            overlap = len(entry_tags & context_set)
                            if overlap == 0:
                                continue

                            relevance = overlap / ctx_len
                            suggestions.append(ProactiveSuggestion(
                                key=key, value=entry.get("value"),
                                relevance=relevance,
                                reason=f"tags overlap: {overlap}/{len(context_tags)}",
                                timestamp=time.time(),
                            ))
            except Exception as _exc:
                logger.warning("ProactiveMemory suggest failed: %s", _exc)
                return []

            top_suggestions = heapq.nlargest(top_k, suggestions, key=lambda s: s.relevance)
            self._suggestions_fired += len(top_suggestions)
            return top_suggestions

    def cleanup_expired(self, max_age_seconds: float = 86400 * 30) -> int:
        now = time.time()
        expired_keys: list[str] = []
        with self._lock:
            for key, entry in self._memory.items():
                if now - entry["timestamp"] > max_age_seconds:
                    expired_keys.append(key)
            for key in expired_keys:
                entry = self._memory.pop(key)
                for tag in entry.get("tags", []):
                    if tag in self._tag_index:
                        self._tag_index[tag] = [k for k in self._tag_index[tag] if k != key]
        return len(expired_keys)

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "stored_memories": len(self._memory),
                "tags_indexed": len(self._tag_index),
                "suggestions_fired": self._suggestions_fired,
            }
