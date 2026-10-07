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

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from brainos.memory.trigger import MemoryTrigger, TriggerAction, TriggerCondition, TriggerRule, TriggerType
from brainos.observability.auto_log import logged

logger = logging.getLogger("brainos.memory.weaver")


class WeaveStrategy(Enum):
    SUMMARIZE = "summarize"
    MERGE = "merge"
    DISTILL = "distill"
    CROSS_REFERENCE = "cross_reference"
    CHAIN = "chain"


@dataclass
class WeaveResult:
    success: bool
    strategy: WeaveStrategy
    input_keys: list[str]
    output_key: str
    output_value: Any
    tokens_saved: int = 0
    duration_ms: float = 0.0


@dataclass
class WeavePlan:
    strategy: WeaveStrategy
    source_keys: list[str]
    target_key: str
    params: dict[str, Any] = field(default_factory=dict)
    priority: int = 0


class MemoryWeaver:
    def __init__(self, store: Any = None, trigger: MemoryTrigger | None = None) -> None:
        self._store = store
        self._trigger = trigger or MemoryTrigger()
        self._weave_count: int = 0
        self._results: list[WeaveResult] = []
        self._lock = threading.RLock()
        self._setup_triggers()

    def _setup_triggers(self) -> None:
        self._trigger.add_rule(
            TriggerRule(
                id="auto_weave_high_importance",
                trigger_type=TriggerType.THRESHOLD,
                conditions=[TriggerCondition("importance", ">=", 0.8, "auto-weave high importance")],
                action=TriggerAction.WEAVE,
                action_params={"strategy": "summarize"},
                priority=7,
            )
        )
        self._trigger.register_handler(TriggerAction.WEAVE, self._on_weave_trigger)

    def _on_weave_trigger(self, rule: TriggerRule, context: dict[str, Any]) -> None:
        strategy_name = rule.action_params.get("strategy", "summarize")
        strategy = WeaveStrategy(strategy_name)
        keys = context.get("memory_keys", [])
        if keys:
            self.weave(keys, strategy=strategy)

    @logged()
    @safe_execute
    def plan(self, memory_keys: list[str], strategy: WeaveStrategy = WeaveStrategy.SUMMARIZE) -> WeavePlan:
        target_key = self._generate_target_key(memory_keys, strategy)
        return WeavePlan(
            strategy=strategy,
            source_keys=memory_keys,
            target_key=target_key,
            params={},
            priority=self._estimate_priority(memory_keys),
        )

    @logged()
    @safe_execute
    def weave(self, memory_keys: list[str], strategy: WeaveStrategy = WeaveStrategy.SUMMARIZE, **kwargs: Any) -> WeaveResult:
        start = time.monotonic()
        self._weave_count += 1
        plan = self.plan(memory_keys, strategy)
        values = self._fetch_values(memory_keys)
        if not values:
            values = list(memory_keys)
        output = self._apply_strategy(strategy, values, kwargs)
        tokens_saved = self._estimate_tokens_saved(values, output)
        self._store_result(plan.target_key, output)
        duration = (time.monotonic() - start) * 1000
        result = WeaveResult(
            success=True,
            strategy=strategy,
            input_keys=memory_keys,
            output_key=plan.target_key,
            output_value=output,
            tokens_saved=tokens_saved,
            duration_ms=duration,
        )
        self._results.append(result)
        logger.info("Weave completed: %s %d→1 keys, saved %d tokens", strategy.value, len(memory_keys), tokens_saved)
        return result

    def _fetch_values(self, keys: list[str]) -> list[Any]:
        values: list[Any] = []
        if self._store is None:
            return values
        for key in keys:
            try:
                val = self._store.retrieve(key)
                if val is not None:
                    values.append(val)
            except Exception as _exc:
                logger.warning("Weaver retrieval failed for key: %s")
        return values

    def _apply_strategy(self, strategy: WeaveStrategy, values: list[Any], _params: dict[str, Any]) -> Any:
        if strategy == WeaveStrategy.SUMMARIZE:
            return self._summarize(values)
        if strategy == WeaveStrategy.MERGE:
            return self._merge(values)
        if strategy == WeaveStrategy.DISTILL:
            return self._distill(values)
        if strategy == WeaveStrategy.CROSS_REFERENCE:
            return self._cross_reference(values)
        if strategy == WeaveStrategy.CHAIN:
            return self._chain(values)
        return self._summarize(values)

    def _summarize(self, values: list[Any]) -> dict[str, Any]:
        combined = " ".join(str(v) for v in values)
        return {
            "type": "summary",
            "source_count": len(values),
            "content_hash": hashlib.sha256(combined.encode()).hexdigest()[:12],
            "preview": combined[:200],
            "created_at": time.monotonic(),
        }

    def _merge(self, values: list[Any]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for v in values:
            if isinstance(v, dict):
                merged.update(v)
            else:
                key = f"item_{len(merged)}"
                merged[key] = v
        merged["_merged_count"] = len(values)
        merged["_merged_at"] = time.monotonic()
        return merged

    def _distill(self, values: list[Any]) -> dict[str, Any]:
        distilled: list[Any] = []
        for v in values:
            if isinstance(v, dict):
                essential = {k: v2 for k, v2 in v.items() if k.startswith("_") or k in ("type", "name", "id")}
                distilled.append(essential if essential else {"ref": str(v)[:50]})
            else:
                distilled.append({"ref": str(v)[:50]})
        return {"type": "distilled", "items": distilled, "source_count": len(values)}

    def _cross_reference(self, values: list[Any]) -> dict[str, Any]:
        refs: list[dict[str, str]] = []
        for i, v in enumerate(values):
            for j, v2 in enumerate(values):
                if i != j:
                    similarity = self._estimate_similarity(v, v2)
                    if similarity > 0.3:
                        refs.append({"from": f"item_{i}", "to": f"item_{j}", "similarity": f"{similarity:.2f}"})
        return {"type": "cross_reference", "references": refs, "source_count": len(values)}

    def _chain(self, values: list[Any]) -> dict[str, Any]:
        return {
            "type": "chain",
            "items": [{"index": i, "value": str(v)[:100]} for i, v in enumerate(values)],
            "source_count": len(values),
            "chained_at": time.monotonic(),
        }

    def _estimate_similarity(self, a: Any, b: Any) -> float:
        sa, sb = str(a), str(b)
        if sa == sb:
            return 1.0
        common = len(set(sa.split()) & set(sb.split()))
        total = len(set(sa.split()) | set(sb.split()))
        return common / total if total > 0 else 0.0

    from typing import Any
    from typing import Any
    def _estimate_tokens_saved(self, inputs, output):
                """估算Token节省量 (启发式压缩率评估算法)

                采用非线性分段映射评估上下文压缩的经济价值，
                并引入去重惩罚机制识别无效合并，确保指标真实性。
                """
                if not inputs:
                    return 0

                safe_inputs = inputs if isinstance(inputs, list) else []
                max_chars_per_item = getattr(self, '_max_estimation_chars', 10000)

                try:
                    # 1. 计算输入总字符数 (带异常隔离与长度截断)
                    input_chars = 0
                    for item in safe_inputs:
                        try:
                            item_str = str(item) if item is not None else ""
                            input_chars += min(len(item_str), max_chars_per_item)
                        except Exception as _inner_exc:
                            logger.warning(
                                "Token estimation skipped an unstringifiable input item: %s",
                                _inner_exc
                            )

                    # 2. 计算输出字符数
                    output_str = str(output) if output is not None else ""
                    output_chars = min(len(output_str), max_chars_per_item)

                    if input_chars == 0:
                        return 0

                    # 3. 核心算法: 基础Token估算 (4字符约等于1Token)
                    base_saved = (input_chars - output_chars) // 4

                    # 4. 上下文工程优化: 非线性压缩率自适应奖励/惩罚
                    compression_ratio = output_chars / input_chars

                    if compression_ratio < 0.3:
                        # 高度压缩 (如 _distill): 非线性奖励
                        base_saved = int(base_saved * 1.2)
                    elif compression_ratio > 0.8:
                        # 低度压缩 (如简单的 _merge): 惩罚,避免高估价值
                        base_saved = int(base_saved * 0.8)

                    # 5. 信息论优化: 去重惩罚机制
                    # 如果输出包含了大量重复的输入前缀,说明是无效拼接,施加额外惩罚
                    if output_chars > 0:
                        repeat_prefix_len = 0
                        for item in safe_inputs:
                            try:
                                item_str = str(item) if item is not None else ""
                                if item_str and output_str.startswith(item_str):
                                    repeat_prefix_len += len(item_str)
                            except Exception:
                                continue

                        # 如果重复率过高,说明合并策略劣化
                        repeat_ratio = repeat_prefix_len / output_chars
                        if repeat_ratio > 0.7:
                            base_saved = int(base_saved * 0.5)

                    return max(0, base_saved)

                except Exception as _exc:
                    logger.error(
                        "Token estimation critically failed, falling back to naive calculation: %s",
                        _exc,
                        exc_info=False
                    )
                    # 优雅降级: 返回粗略的绝对值计算,确保系统流不中断
                    try:
                        fallback_saved = (sum(len(str(v)) for v in safe_inputs if v) - len(str(output_str))) // 4
                        return max(0, fallback_saved)
                    except Exception:
                        return 0



    def _generate_target_key(self, keys: list[str], strategy: WeaveStrategy) -> str:
        combined = "|".join(sorted(keys)) + strategy.value
        hash_part = hashlib.sha256(combined.encode()).hexdigest()[:8]
        return f"weave:{strategy.value}:{hash_part}"

    def _estimate_priority(self, keys: list[str]) -> int:
        return min(len(keys) * 2, 10)

    def _store_result(self, key: str, value: Any) -> None:
        if self._store is not None:
            try:
                self._store.store(key, value)
            except Exception as _exc:
                logger.exception("Failed to store weave result")

    @logged()
    @safe_execute
    def get_results(self, limit: int = 20) -> list[WeaveResult]:
        with self._lock:
            return list(self._results[-limit:])

    @logged()
    @safe_execute
    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            successful = sum(1 for r in self._results if r.success)
            total_tokens = sum(r.tokens_saved for r in self._results)
            return {
                "weave_count": self._weave_count,
                "successful": successful,
                "failed": len(self._results) - successful,
                "total_tokens_saved": total_tokens,
                "strategies_used": list({r.strategy.value for r in self._results}),
            }
