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
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from collections import deque
logger = logging.getLogger("brainos.memory.temporal_kg")

# Stopwords for the rule-based entity fallback (open-core; no llm module).
_RULE_STOPWORDS = {
    "the", "this", "that", "from", "with", "return", "import", "class",
    "def", "true", "false", "none", "and", "for", "not", "are", "you",
    "can", "all", "new", "self", "str", "int", "dict", "list", "type",
}


class EdgeType(Enum):
    DERIVES_FROM = "derives_from"
    DEPENDS_ON = "depends_on"
    EVOLVED_TO = "evolved_to"
    SUPERSEDES = "supersedes"
    RELATES_TO = "relates_to"
    CAUSES = "causes"
    PREVENTS = "prevents"


@dataclass(slots=True)
class KGEntity:
    entity_id: str = ""
    name: str = ""
    entity_type: str = ""
    properties: dict[str, Any] = field(default_factory=dict)
    valid_from: float = 0.0
    valid_to: float = float("inf")
    system_time: float = field(default_factory=time.monotonic)


@dataclass(slots=True)
class KGEdge:
    edge_id: str = ""
    source_id: str = ""
    target_id: str = ""
    edge_type: EdgeType = EdgeType.RELATES_TO
    weight: float = 1.0
    properties: dict[str, Any] = field(default_factory=dict)
    valid_from: float = 0.0
    valid_to: float = float("inf")


@dataclass(slots=True)
class TemporalQuery:
    query_text: str = ""
    as_of_time: float | None = None
    max_depth: int = 3
    entity_types: list[str] = field(default_factory=list)


class TemporalKnowledgeGraph:
    _instance: TemporalKnowledgeGraph | None = None

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entities: dict[str, list[KGEntity]] = {}
        self._edges: list[KGEdge] = []
        self._entity_index: dict[str, str] = {}
        self._stats = {
            "entities_added": 0,
            "edges_added": 0,
            "queries_executed": 0,
            "llm_extractions": 0,
        }

    @classmethod
    def get_instance(cls) -> TemporalKnowledgeGraph:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def add_entity(self, name: str, entity_type: str, properties: dict[str, Any] | None = None, valid_from: float | None = None) -> str:
        now = time.monotonic()
        entity_id = f"ent_{hash(name + entity_type) % 100000:05d}"
        entity = KGEntity(
            entity_id=entity_id,
            name=name,
            entity_type=entity_type,
            properties=properties or {},
            valid_from=valid_from or now,
            system_time=now,
        )
        with self._lock:
            if name not in self._entities:
                self._entities[name] = []
            old_versions = self._entities[name]
            if old_versions:
                latest = old_versions[-1]
                latest.valid_to = now
            self._entities[name].append(entity)
            self._entity_index[entity_id] = name
            self._stats["entities_added"] += 1
        return entity_id

    def add_edge(self, source_name: str, target_name: str, edge_type: EdgeType, weight: float = 1.0, properties: dict[str, Any] | None = None) -> str:
        now = time.monotonic()
        edge_id = f"edge_{len(self._edges):06d}"
        source_id = self._entity_index.get(source_name, source_name)
        target_id = self._entity_index.get(target_name, target_name)
        edge = KGEdge(
            edge_id=edge_id,
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            weight=weight,
            properties=properties or {},
            valid_from=now,
        )
        with self._lock:
            self._edges.append(edge)
            self._stats["edges_added"] += 1
        return edge_id

    def extract_from_text(self, text: str, source: str = "") -> list[str]:
        try:
            from brainos.llm import llm_chat_sync  # commercial version only

            messages = [
                {
                    "role": "system",
                    "content": (
                        'Extract entities and relationships from text. Return JSON: '
                        '{"entities": [{"name": "...", "type": "...", "props": {...}}], '
                        '"relations": [{"source": "...", "target": "...", '
                        '"type": "derives_from|depends_on|evolved_to|supersedes|relates_to|causes|prevents"}]}. '
                        'Types: module, concept, error, decision, rule, domain.'
                    ),
                },
                {"role": "user", "content": text[:1000]},
            ]
            result = llm_chat_sync(messages, max_tokens=512, temperature=0.2, priority="low", caller="temporal_kg")
            if result:
                import json

                data = json.loads(result)
                ids = []
                for ent in data.get("entities", []):
                    eid = self.add_entity(ent["name"], ent.get("type", "concept"), ent.get("props"))
                    ids.append(eid)
                for rel in data.get("relations", []):
                    et = EdgeType.RELATES_TO
                    for e in EdgeType:
                        if e.value == rel.get("type", "relates_to"):
                            et = e
                            break
                    self.add_edge(rel["source"], rel["target"], et)
                self._stats["llm_extractions"] += 1
                return ids
        except ImportError:
            # v0.9 open-source build ships no llm module (commercial version
            # only). Rule-based fallback: register capitalized / CamelCase
            # tokens as concept entities so callers still get a useful graph.
            import re as _re

            ids: list[str] = []
            for token in dict.fromkeys(_re.findall(r"\b[A-Z][A-Za-z0-9_]{2,}\b", text)):
                if token.lower() in _RULE_STOPWORDS:
                    continue
                ids.append(self.add_entity(token, "concept"))
            return ids
        except Exception as _exc:
            logger.warning("LLM extraction failed: %s", _exc)
        return []

    def query(self, query: TemporalQuery) -> list[dict[str, Any]]:
        with self._lock:
            self._stats["queries_executed"] += 1
        results: list[dict[str, Any]] = []
        query_lower = query.query_text.lower()
        with self._lock:
            for name, versions in self._entities.items():
                if query_lower in name.lower() or any(query_lower in str(v.properties).lower() for v in versions):
                    valid = versions[-1]
                    if query.as_of_time and (valid.valid_from > query.as_of_time or valid.valid_to < query.as_of_time):
                        continue
                    connected = [e for e in self._edges if e.source_id == valid.entity_id or e.target_id == valid.entity_id]
                    results.append(
                        {
                            "entity": {"name": valid.name, "type": valid.entity_type, "properties": valid.properties},
                            "connections": [{"to": e.target_id if e.source_id == valid.entity_id else e.source_id, "type": e.edge_type.value, "weight": e.weight} for e in connected[:10]],
                        }
                    )
        return results[:20]

    def get_temporal_evolution(self, entity_name: str) -> list[dict]:
            """获取实体属性的时间演化轨迹及Weibull生存权重 (SSGM漂移治理)"""
            # 1. 边界守卫与防御编程
            if not entity_name or not isinstance(entity_name, str):
                logger.warning("Temporal evolution rejected invalid entity_name: %r", entity_name)
                return []

            try:
                # 并发安全读取:拷贝引用后释放锁,避免长时间持锁导致并发瓶颈
                with self._lock:
                    versions = list(getattr(self, '_entities', {}).get(entity_name, []))

                if not versions:
                    return []

                # 2. 初始化算法状态机
                evolution = []
                # 使用 deque 维护滑动窗口,支持计算演化加速度 (一阶差分)
                window = deque(maxlen=2) 
                prev_delta_size = 0
                now = time.monotonic()

                # SSGM 漂移治理参数 (Weibull衰减 Eq.4)
                # lambda: 特征寿命(默认1天), k: 形状参数(<1早期快速衰减, >1后期衰减)
                half_life = getattr(self, '_temporal_half_life', 86400.0)
                weibull_lambda = max(half_life, 1e-6)
                weibull_k = getattr(self, '_temporal_weibull_k', 1.5)

                for v in versions:
                    # 脏数据隔离:防御非字典属性或损坏的实体
                    curr_props = getattr(v, 'properties', None)
                    if not isinstance(curr_props, dict):
                        curr_props = {}

                    # 3. 核心算法:基于集合操作的 O(1) 差分提取
                    curr_keys = set(curr_props.keys())
                    prev_keys = set(window[-1].keys()) if window else set()

                    added = {k: curr_props[k] for k in (curr_keys - prev_keys)}
                    removed = {k: window[-1][k] for k in (prev_keys - curr_keys)} if window else {}
                    modified = {
                        k: {"from": window[-1][k], "to": curr_props[k]}
                        for k in (curr_keys & prev_keys) if window[-1][k] != curr_props[k]
                    } if window else {}

                    # 计算演化动力学指标 (变化量及加速度)
                    curr_delta_size = len(added) + len(removed) + len(modified)
                    acceleration = curr_delta_size - prev_delta_size

                    # 4. 核心算法:SSGM Weibull 生存函数计算时序权重
                    weight = 1.0
                    v_from = getattr(v, 'valid_from', 0.0)
                    if v_from and now > v_from:
                        age = now - v_from
                        # S(t) = exp(-(t/lambda)^k)
                        try:
                            ratio = age / weibull_lambda
                            weight = pow(2.718281828459045, -pow(ratio, weibull_k))
                        except OverflowError:
                            weight = 0.0 # 极端古老的记忆权重归零

                    evolution.append({
                        "name": getattr(v, 'name', ''),
                        "type": getattr(v, 'entity_type', ''),
                        "valid_from": getattr(v, 'valid_from', 0.0),
                        "valid_to": getattr(v, 'valid_to', float('inf')),
                        "props": curr_props,
                        "diff": {
                            "added": added,
                            "removed": removed,
                            "modified": modified,
                            "velocity": curr_delta_size,     # 变化速率
                            "acceleration": acceleration     # 演化加速度
                        },
                        "temporal_weight": round(weight, 6)
                    })

                    # 状态机滚动推进
                    window.append(curr_props)
                    prev_delta_size = curr_delta_size

                logger.debug("Extracted temporal evolution for '%s' (versions: %d)", entity_name, len(evolution))
                return evolution

            except Exception as _exc:
                # 优雅降级:记录详细上下文,防止调用链断裂
                logger.error(
                    "Failed to get temporal evolution for entity '%s': %s",
                    entity_name,
                    _exc,
                    exc_info=False
                )
                return []


    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                **self._stats,
                "total_entities": sum(len(v) for v in self._entities.values()),
                "unique_entity_names": len(self._entities),
                "total_edges": len(self._edges),
            }
