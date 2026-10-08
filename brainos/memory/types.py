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
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class MemoryTier(Enum):
    CRITICAL = "critical"
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"
    ARCHIVE = "archive"


class MemoryType(Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    ANCHOR = "anchor"
    CONVERSATION = "conversation"
    DECISION = "decision"
    LESSON = "lesson"
    PATTERN = "pattern"
    CONTEXT = "context"
    SKILL = "skill"
    BUG_FIX = "bug_fix"
    ARCHITECTURE = "architecture"


_TIER_ORDER = [MemoryTier.ARCHIVE, MemoryTier.COLD, MemoryTier.WARM, MemoryTier.HOT, MemoryTier.CRITICAL]


@dataclass
class MemoryEntry:
    id: str = ""
    content: str = ""
    memory_type: MemoryType = MemoryType.SEMANTIC
    tier: MemoryTier = MemoryTier.WARM
    importance: float = 0.5
    confidence: float = 1.0
    created_at: float = field(default_factory=time.time)
    accessed_at: float = field(default_factory=time.time)
    access_count: int = 0
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    relevance_score: float = 0.5
    source: str = ""
    project: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = f"mem_{uuid.uuid4().hex[:12]}"
        if not self.created_at:
            self.created_at = time.time()
        if not self.accessed_at:
            self.accessed_at = self.created_at

    def touch(self) -> bool:
            """更新访问时间与频次，并基于启发式算法评估是否需要层级晋升。

            时间复杂度: O(1), 空间复杂度: O(1)
            对接: SSGM漂移治理与Weibull衰减模型(L4层)
            """
            try:
                current_time = time.time()
                self.accessed_at = current_time
                # 防御: 防止并发场景下计数器回退或溢出
                self.access_count = max(0, self.access_count) + 1

                # 算法: 启发式重要性增量评估 (Weibull衰减启发)
                # 访问次数越多,单次重要性增益越小 (边际递减效应)
                gain = 0.05 / (1.0 + (self.access_count - 1) * 0.1)
                self.importance = min(1.0, max(0.0, self.importance + gain))

                # 机制: 惰性层级提升 (达到热度阈值且未在最高层时触发)
                if self.importance >= 0.85 and self.tier != MemoryTier.CRITICAL:
                    return self.promote()
                return True
            except Exception as _exc:
                # 降级: 仅记录时间,保证核心touch语义成功
                self.accessed_at = time.time()
                return False

    def promote(self):
            """将记忆条目提升至更高优先级层级 (O(1)复杂度)。

            基于层级有序序列进行状态跃迁，同步刷新访问时间戳。
            """
            try:
                # 防御: 拦截非法tier状态或并发状态损坏
                if self.tier not in _TIER_ORDER:
                    return False

                idx = _TIER_ORDER.index(self.tier)
                # 幂等性: 已处于最高层级视为成功,避免上层无效重试
                if idx >= len(_TIER_ORDER) - 1:
                    return True

                # 算法: 有序层级状态机跃迁
                self.tier = _TIER_ORDER[idx + 1]
                # 联动: 刷新时间戳以重置L4层Weibull衰减时钟
                self.accessed_at = time.time()
                return True
            except Exception as _exc:
                # 降级: 保持原层级状态不变,阻断异常向L1内核层传播
                return False


    def demote(self) -> bool:
        idx = _TIER_ORDER.index(self.tier)
        if idx > 0:
            self.tier = _TIER_ORDER[idx - 1]
            return True
        return False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # JSON-safe projection: enums → their string values
        if isinstance(data.get("memory_type"), MemoryType):
            data["memory_type"] = data["memory_type"].value
        if isinstance(data.get("tier"), MemoryTier):
            data["tier"] = data["tier"].value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryEntry:
        d = dict(data)
        if "memory_type" in d and isinstance(d["memory_type"], str):
            try:
                d["memory_type"] = MemoryType(d["memory_type"])
            except ValueError:
                d["memory_type"] = MemoryType.SEMANTIC
        if "tier" in d and isinstance(d["tier"], str):
            try:
                d["tier"] = MemoryTier(d["tier"])
            except ValueError:
                d["tier"] = MemoryTier.WARM
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class MemorySearchResult:
    entry: MemoryEntry
    score: float
    match_reason: str = ""
