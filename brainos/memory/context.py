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
from brainos.kernel.async_compat import async_compatible
from brainos.kernel.safe_execute import safe_execute

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from brainos.observability.auto_log import logged

logger = logging.getLogger("brainos.memory.context")


class ContextLayer(Enum):
    SYSTEM = "system"
    SESSION = "session"
    TASK = "task"
    WORKING = "working"
    SCRATCH = "scratch"


_LAYER_PRIORITY: dict[ContextLayer, float] = {
    ContextLayer.SYSTEM: 1.0,
    ContextLayer.SESSION: 0.8,
    ContextLayer.TASK: 0.6,
    ContextLayer.WORKING: 0.4,
    ContextLayer.SCRATCH: 0.2,
}


@dataclass
class ContextFrame:
    layer: ContextLayer
    content: str = ""
    token_estimate: int = 0
    created_at: float = field(default_factory=time.time)
    priority: float = 0.5
    anchor_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @logged()
    @safe_execute
    def estimate_tokens(self) -> int:
        self.token_estimate = max(1, len(self.content) // 4)
        return self.token_estimate


class ContextEngine:
    def __init__(
        self,
        max_total_tokens: int = 8000,
        compression_threshold: float = 0.8,
        working_window: int = 20,
        scratch_limit: int = 10,
    ) -> None:
        self._stack: dict[ContextLayer, list[ContextFrame]] = {layer: [] for layer in ContextLayer}
        self._max_total_tokens = max_total_tokens
        self._compression_threshold = compression_threshold
        self._working_window = working_window
        self._scratch_limit = scratch_limit
        self._compression_count = 0
        self._anchor_data: dict[str, str] = {}

    @logged()
    @safe_execute
    def push(self, layer, content, priority=None, anchor_key="", metadata=None):
        pass


    @logged()
    @safe_execute
    def pop(self, layer: ContextLayer) -> ContextFrame | None:
        frames = self._stack.get(layer, [])
        if not frames:
            return None
        return frames.pop()

    @logged()
    @safe_execute
    def peek(self, layer: ContextLayer) -> ContextFrame | None:
        frames = self._stack.get(layer, [])
        if not frames:
            return None
        return frames[-1]

    @logged()
    @safe_execute
    def get_layer(self, layer: ContextLayer) -> list[ContextFrame]:
        return list(self._stack.get(layer, []))

    @logged()
    @safe_execute
    def get_all(self) -> dict[ContextLayer, list[ContextFrame]]:
        return {layer: list(frames) for layer, frames in self._stack.items()}

    @logged()
    @safe_execute
    def get_context(self, max_tokens: int | None = None) -> str:
        limit = max_tokens or self._max_total_tokens
        parts: list[str] = []
        tokens = 0
        for layer in ContextLayer:
            for frame in self._stack[layer]:
                if tokens + frame.token_estimate > limit:
                    break
                parts.append(f"[{layer.value}] {frame.content}")
                tokens += frame.token_estimate
        return "\n".join(parts)

    @logged()
    @safe_execute
    def total_tokens(self) -> int:
        total = 0
        for frames in self._stack.values():
            for frame in frames:
                total += frame.token_estimate
        return total

    @logged()
    @safe_execute
    def frame_count(self) -> int:
        return sum(len(frames) for frames in self._stack.values())

    @logged()
    @safe_execute
    def clear_layer(self, layer: ContextLayer) -> int:
        frames = self._stack.get(layer, [])
        count = len(frames)
        frames.clear()
        return count

    @logged()
    @safe_execute
    def clear_all(self) -> int:
        total = self.frame_count()
        for frames in self._stack.values():
            frames.clear()
        return total

    @logged()
    @safe_execute
    def compress(self, target_ratio: float = 0.5) -> dict[str, Any]:
        self._compression_count += 1
        before_tokens = self.total_tokens()
        before_frames = self.frame_count()
        target_tokens = int(before_tokens * target_ratio)

        all_frames: list[tuple[ContextLayer, int, ContextFrame]] = []
        for layer, frames in self._stack.items():
            for i, frame in enumerate(frames):
                all_frames.append((layer, i, frame))

        all_frames.sort(key=lambda x: x[2].priority, reverse=True)

        anchor_saved = 0
        kept_tokens = 0
        keep_set: set[tuple[ContextLayer, int]] = set()

        for layer, idx, frame in all_frames:
            if kept_tokens + frame.token_estimate <= target_tokens:
                keep_set.add((layer, idx))
                kept_tokens += frame.token_estimate
            else:
                if frame.content:
                    self._anchor_data[f"compressed_{layer.value}_{idx}_{self._compression_count}"] = frame.content
                    anchor_saved += 1

        for layer in self._stack:
            new_frames: list[ContextFrame] = []
            for i, frame in enumerate(self._stack[layer]):
                if (layer, i) in keep_set:
                    new_frames.append(frame)
            self._stack[layer] = new_frames

        after_tokens = self.total_tokens()
        after_frames = self.frame_count()
        return {
            "compression_id": self._compression_count,
            "before_tokens": before_tokens,
            "after_tokens": after_tokens,
            "before_frames": before_frames,
            "after_frames": after_frames,
            "removed_frames": before_frames - after_frames,
            "ratio": after_tokens / before_tokens if before_tokens > 0 else 0.0,
            "anchor_saved": anchor_saved,
        }

    @logged()
    @async_compatible
    def save_anchor(self, key: str, content: str) -> None:
        self._anchor_data[key] = content

    @logged()
    @async_compatible
    def load_anchor(self, key: str) -> str | None:
        return self._anchor_data.get(key)

    @logged()
    @safe_execute
    def reinject_from_anchor(self, key: str, layer: ContextLayer = ContextLayer.WORKING) -> ContextFrame | None:
        content = self._anchor_data.get(key)
        if content is None:
            return None
        return self.push(layer, content, priority=0.8, metadata={"reinject": True, "anchor_key": key})

    @logged()
    @safe_execute
    def get_summary(self) -> dict[str, Any]:
        layer_summary: dict[str, Any] = {}
        for layer, frames in self._stack.items():
            layer_summary[layer.value] = {
                "frame_count": len(frames),
                "token_estimate": sum(f.token_estimate for f in frames),
            }
        return {
            "total_tokens": self.total_tokens(),
            "max_tokens": self._max_total_tokens,
            "utilization": self.total_tokens() / self._max_total_tokens if self._max_total_tokens > 0 else 0.0,
            "total_frames": self.frame_count(),
            "layers": layer_summary,
            "anchor_count": len(self._anchor_data),
            "compression_count": self._compression_count,
        }

    def _enforce_limits(self, layer: ContextLayer) -> None:
        if layer == ContextLayer.WORKING:
            while len(self._stack[layer]) > self._working_window:
                removed = self._stack[layer].pop(0)
                if removed.content:
                    self._anchor_data[f"sliding_{layer.value}_{int(removed.created_at)}"] = removed.content
        elif layer == ContextLayer.SCRATCH:
            while len(self._stack[layer]) > self._scratch_limit:
                self._stack[layer].pop(0)

    def _auto_compress(self) -> None:
        if self.total_tokens() > self._max_total_tokens * self._compression_threshold:
            self.compress(target_ratio=0.6)
            logger.info("Auto-compressed context: %d tokens", self.total_tokens())
