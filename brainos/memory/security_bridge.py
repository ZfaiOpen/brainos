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
import threading
from dataclasses import dataclass, field
from typing import Any

from brainos.kernel.protocols.cross_domain import SecurityEngineProtocol
from brainos.kernel.safe_execute import safe_call

logger = logging.getLogger(__name__)


@dataclass
class MemorySecurityBridgeStats:
    total_checks: int = 0
    tampering_detected: int = 0
    integrity_verified: int = 0
    by_layer: dict[str, int] = field(default_factory=dict)
    bridge_errors: int = 0


class MemorySecurityBridge:
    _instance: MemorySecurityBridge | None = None
    _init_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._immune: SecurityEngineProtocol | None = None
        self._stats = MemorySecurityBridgeStats()
        self._lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> MemorySecurityBridge:
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def bind_immune(self, immune: SecurityEngineProtocol) -> None:
        self._immune = immune

    def check_memory_integrity(self, key: str, value: Any, layer: str = "short_term") -> bool:
            if not key or not layer:
                return True

            with self._lock:
                self._stats.total_checks += 1
                self._stats.by_layer[layer] = self._stats.by_layer.get(layer, 0) + 1

            is_tampered = False
            if isinstance(value, dict):
                try:
                    checksum = value.get("_checksum")
                    if checksum and isinstance(checksum, str):
                        import hashlib
                        content_str = str({k: v for k, v in value.items() if k != "_checksum"})
                        expected = hashlib.sha256(content_str.encode("utf-8", errors="ignore")).hexdigest()[:16]
                        is_tampered = (checksum != expected)

                    if not is_tampered and layer in ("core", "semantic"):
                        confidence = value.get("confidence", 0)
                        if not isinstance(confidence, (int, float)) or confidence > 1.0 or confidence < 0.0:
                            is_tampered = True
                except Exception as _exc:
                    logger.warning("Memory integrity check failed: key=%s err=%s", key, _exc)
                    with self._lock:
                        self._stats.bridge_errors += 1
                    return False

            if is_tampered and self._immune is not None:
                safe_call(
                    lambda: self._immune.detect_threat(
                        threat_type="memory_tampering",
                        source=key,
                        details={"layer": layer, "value_type": type(value).__name__},
                    ),
                    default=None,
                )
                with self._lock:
                    self._stats.tampering_detected += 1
                logger.warning("Memory tampering detected: key=%s layer=%s", key, layer)
            else:
                with self._lock:
                    self._stats.integrity_verified += 1

            return not is_tampered

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "total_checks": self._stats.total_checks,
                "tampering_detected": self._stats.tampering_detected,
                "integrity_verified": self._stats.integrity_verified,
                "by_layer": dict(self._stats.by_layer),
                "bridge_errors": self._stats.bridge_errors,
            }
