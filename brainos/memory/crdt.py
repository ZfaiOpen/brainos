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
import hashlib
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import logging

logger = logging.getLogger(__name__)


class CRDTOpType(str, Enum):
    ADD = "add"
    REMOVE = "remove"
    UPDATE = "update"
    MERGE = "merge"


@dataclass
class CRDTOperation:
    op_id: str = ""
    op_type: CRDTOpType = CRDTOpType.ADD
    key: str = ""
    value: Any = None
    timestamp: float = 0.0
    vector_clock: dict[str, int] = field(default_factory=dict)
    origin_node: str = ""
    tombstone: bool = False

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = time.time()
        if not self.op_id:
            self.op_id = f"op_{hashlib.sha256(f'{self.key}:{self.timestamp}:{self.origin_node}'.encode()).hexdigest()[:12]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "op_id": self.op_id,
            "op_type": self.op_type.value,
            "key": self.key,
            "value": self.value,
            "timestamp": self.timestamp,
            "vector_clock": dict(self.vector_clock),
            "origin_node": self.origin_node,
            "tombstone": self.tombstone,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CRDTOperation:
        return cls(
            op_id=data.get("op_id", ""),
            op_type=CRDTOpType(data.get("op_type", "add")),
            key=data.get("key", ""),
            value=data.get("value"),
            timestamp=data.get("timestamp", 0.0),
            vector_clock=data.get("vector_clock", {}),
            origin_node=data.get("origin_node", ""),
            tombstone=data.get("tombstone", False),
        )


@dataclass
class CRDTNode:
    node_id: str = ""
    address: str = ""
    is_active: bool = True
    last_sync: float = 0.0
    sync_count: int = 0


@dataclass
class CRDTValue:
    key: str = ""
    value: Any = None
    version: int = 0
    vector_clock: dict[str, int] = field(default_factory=dict)
    last_modified: float = 0.0
    last_modified_by: str = ""
    is_tombstone: bool = False

    def __post_init__(self) -> None:
        if not self.last_modified:
            self.last_modified = time.time()


class MemoryCRDT:
    _MAX_OPS = 10000
    _MAX_VALUES = 5000

    def __init__(self, node_id: str = "local") -> None:
        self._node_id = node_id
        self._values: dict[str, CRDTValue] = {}
        self._ops_log: list[CRDTOperation] = []
        self._vector_clock: dict[str, int] = {node_id: 0}
        self._nodes: dict[str, CRDTNode] = {}
        self._lock = threading.RLock()
        self._op_count: int = 0
        self._merge_count: int = 0
        self._conflict_count: int = 0

        self._nodes[node_id] = CRDTNode(node_id=node_id, is_active=True)

    def add(self, key: str, value: Any) -> CRDTOperation:
        with self._lock:
            self._vector_clock[self._node_id] = self._vector_clock.get(self._node_id, 0) + 1

            op = CRDTOperation(
                op_type=CRDTOpType.ADD,
                key=key,
                value=value,
                vector_clock=dict(self._vector_clock),
                origin_node=self._node_id,
            )

            self._apply_operation(op)
            self._ops_log.append(op)
            self._op_count += 1

            if len(self._ops_log) > self._MAX_OPS:
                self._ops_log = self._ops_log[-self._MAX_OPS // 2 :]

        return op

    def remove(self, key: str) -> CRDTOperation:
        with self._lock:
            self._vector_clock[self._node_id] = self._vector_clock.get(self._node_id, 0) + 1

            op = CRDTOperation(
                op_type=CRDTOpType.REMOVE,
                key=key,
                vector_clock=dict(self._vector_clock),
                origin_node=self._node_id,
                tombstone=True,
            )

            self._apply_operation(op)
            self._ops_log.append(op)
            self._op_count += 1

        return op

    def update(self, key: str, value: Any) -> CRDTOperation:
        with self._lock:
            self._vector_clock[self._node_id] = self._vector_clock.get(self._node_id, 0) + 1

            op = CRDTOperation(
                op_type=CRDTOpType.UPDATE,
                key=key,
                value=value,
                vector_clock=dict(self._vector_clock),
                origin_node=self._node_id,
            )

            self._apply_operation(op)
            self._ops_log.append(op)
            self._op_count += 1

        return op

    def get(self, key: str) -> Any:
        with self._lock:
            val = self._values.get(key)
            if val is None or val.is_tombstone:
                return None
            return val.value

    def get_all(self) -> dict[str, Any]:
        with self._lock:
            return {k: v.value for k, v in self._values.items() if not v.is_tombstone}

    def merge(self, other_ops: list[CRDTOperation]) -> int:
        merged = 0
        with self._lock:
            for op in other_ops:
                if self._should_apply(op):
                    self._apply_operation(op)
                    self._merge_vector_clock(op.vector_clock)
                    merged += 1
                self._ops_log.append(op)

            if len(self._ops_log) > self._MAX_OPS:
                self._ops_log = self._ops_log[-self._MAX_OPS // 2 :]

            self._merge_count += 1

        logger.info("CRDT merge: %d/%d ops applied from %s", merged, len(other_ops), other_ops[0].origin_node if other_ops else "unknown")
        return merged

    def merge_from_node(self, other: MemoryCRDT) -> int:
        with other._lock:
            other_ops = list(other._ops_log)
        merged = self.merge(other_ops)
        if merged > 0:
            self._fire_combo_event(merged, other._node_id)
        return merged

    def _should_apply(self, op: CRDTOperation) -> bool:
        current = self._values.get(op.key)
        if current is None:
            return True

        if self._happened_before(current.vector_clock, op.vector_clock):
            return True

        if self._is_concurrent(current.vector_clock, op.vector_clock):
            self._conflict_count += 1
            if op.timestamp > current.last_modified:
                return True
            if op.timestamp == current.last_modified and op.origin_node > current.last_modified_by:
                return True
            return False

        return False

    def _apply_operation(self, op: CRDTOperation) -> None:
        current = self._values.get(op.key)

        if op.op_type == CRDTOpType.ADD:
            if current is None or current.is_tombstone:
                self._values[op.key] = CRDTValue(
                    key=op.key,
                    value=op.value,
                    version=1,
                    vector_clock=op.vector_clock,
                    last_modified_by=op.origin_node,
                )
            elif current is not None and not current.is_tombstone:
                self._conflict_count += 1
                if op.timestamp > current.last_modified:
                    self._values[op.key] = CRDTValue(
                        key=op.key,
                        value=op.value,
                        version=current.version + 1,
                        vector_clock=op.vector_clock,
                        last_modified_by=op.origin_node,
                    )

        elif op.op_type == CRDTOpType.UPDATE:
            if current is not None and not current.is_tombstone:
                self._values[op.key] = CRDTValue(
                    key=op.key,
                    value=op.value,
                    version=current.version + 1,
                    vector_clock=op.vector_clock,
                    last_modified_by=op.origin_node,
                )
            elif current is None:
                self._values[op.key] = CRDTValue(
                    key=op.key,
                    value=op.value,
                    version=1,
                    vector_clock=op.vector_clock,
                    last_modified_by=op.origin_node,
                )

        elif op.op_type == CRDTOpType.REMOVE:
            if current is not None:
                self._values[op.key] = CRDTValue(
                    key=op.key,
                    value=None,
                    version=current.version + 1,
                    vector_clock=op.vector_clock,
                    last_modified_by=op.origin_node,
                    is_tombstone=True,
                )

        if len(self._values) > self._MAX_VALUES:
            tombstoned = [k for k, v in self._values.items() if v.is_tombstone]
            for k in tombstoned[: len(self._values) - self._MAX_VALUES]:
                del self._values[k]

    def _merge_vector_clock(self, other_clock: dict[str, int]) -> None:
        for node, counter in other_clock.items():
            self._vector_clock[node] = max(self._vector_clock.get(node, 0), counter)

    def _happened_before(self, clock_a: dict[str, int], clock_b: dict[str, int]) -> bool:
        all_keys = set(clock_a.keys()) | set(clock_b.keys())
        at_least_one_less = False
        for key in all_keys:
            a_val = clock_a.get(key, 0)
            b_val = clock_b.get(key, 0)
            if a_val > b_val:
                return False
            if a_val < b_val:
                at_least_one_less = True
        return at_least_one_less

    def _is_concurrent(self, clock_a: dict[str, int], clock_b: dict[str, int]) -> bool:
        return not self._happened_before(clock_a, clock_b) and not self._happened_before(clock_b, clock_a)

    def register_node(self, node_id, address=""):
            """注册或更新集群节点，采用幂等状态机算法保证分布式一致性。
            Time: O(1) Space: O(1)
            """
            # 1. 输入防御:拦截非法类型与超长字符串(防内存/哈希DoS)
            if not isinstance(node_id, str) or not node_id.strip():
                logger.warning("CRDT: register_node rejected invalid node_id type or empty.")
                return False

            clean_id = node_id.strip()
            clean_addr = address if isinstance(address, str) else ""

            max_node_id_len = getattr(self, "_MAX_NODE_ID_LEN", 256)
            if len(clean_id) > max_node_id_len:
                clean_id = clean_id[:max_node_id_len]

            max_addr_len = getattr(self, "_MAX_ADDR_LEN", 1024)
            if len(clean_addr) > max_addr_len:
                clean_addr = clean_addr[:max_addr_len]

            is_new_node = False
            try:
                with self._lock:
                    # 2. 状态自愈: 确保核心数据结构存在且类型正确,防止崩溃
                    if not isinstance(getattr(self, '_nodes', None), dict):
                        self._nodes = {}
                    if not isinstance(getattr(self, '_vector_clock', None), dict):
                        self._vector_clock = {}

                    nodes = self._nodes
                    v_clock = self._vector_clock

                    # 3. 容量治理:防止无限制节点注册耗尽内存
                    max_nodes = getattr(self, "_MAX_NODES", 1024)
                    is_new_node = clean_id not in nodes
                    if is_new_node and len(nodes) >= max_nodes:
                        logger.error("CRDT: Node registration rejected, capacity limit %d reached.", max_nodes)
                        return False

                    # 4. 幂等状态机:保留已存在节点的状态,仅更新必要字段(避免CRDT状态重置)
                    if not is_new_node:
                        existing_node = nodes[clean_id]
                        if hasattr(existing_node, 'address'):
                            existing_node.address = clean_addr
                        logger.debug("CRDT: Node '%s' re-registered, state preserved.", clean_id)
                    else:
                        nodes[clean_id] = CRDTNode(node_id=clean_id, address=clean_addr)

                    # 5. 向量时钟初始化:确保新节点参与分布式偏序关系
                    if clean_id not in v_clock:
                        v_clock[clean_id] = 0

                # 6. 跨域协同通知:触发拓扑变更事件(L4->L2/L7),必须在锁外执行防死锁
                if is_new_node and hasattr(self, "_fire_combo_event"):
                    try:
                        self._fire_combo_event(merged_count=0, source_node=clean_id)
                    except Exception as _inner_exc:
                        logger.debug("CRDT: Combo event suppressed for node registration: %s", _inner_exc)

                return True

            except Exception as _exc:
                logger.error("CRDT: Failed to register node '%s': %s", clean_id, _exc, exc_info=False)
                return False


    def export_ops(self, since_version: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            return [op.to_dict() for op in self._ops_log]

    def import_ops(self, ops_dicts: list[dict[str, Any]]) -> int:
        ops = [CRDTOperation.from_dict(d) for d in ops_dicts]
        return self.merge(ops)

    def _fire_combo_event(self, merged_count: int, source_node: str) -> None:
        try:
            from brainos.kernel.cross_domain_combo_engine import CrossDomainComboEngine, ComboTrigger, ComboDomain, ComboEvent

            engine = CrossDomainComboEngine.get_instance()
            event = ComboEvent(
                trigger=ComboTrigger.MEMORY_SYNC,
                source_domain=ComboDomain.MEMORY,
                payload={"merged_count": merged_count, "source_node": source_node},
            )
            engine.fire_event(event)
        except Exception as e:
            logger.warning(f"silently handled: {e}")

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            active_values = sum(1 for v in self._values.values() if not v.is_tombstone)
            tombstoned = sum(1 for v in self._values.values() if v.is_tombstone)
            return {
                "node_id": self._node_id,
                "active_values": active_values,
                "tombstoned_values": tombstoned,
                "total_values": len(self._values),
                "ops_log_size": len(self._ops_log),
                "op_count": self._op_count,
                "merge_count": self._merge_count,
                "conflict_count": self._conflict_count,
                "vector_clock": dict(self._vector_clock),
                "nodes": len(self._nodes),
            }
