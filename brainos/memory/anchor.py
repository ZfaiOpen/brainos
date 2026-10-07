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
from brainos.kernel.async_compat import async_compatible
from brainos.kernel.safe_execute import safe_execute

import hashlib
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from brainos.observability.auto_log import logged

logger = logging.getLogger("brainos.memory.anchor")


class AnchorType(Enum):
    DECISION = "decision"
    RULE = "rule"
    PATTERN = "pattern"
    EVENT = "event"
    KNOWLEDGE = "knowledge"


class AnchorStrength(Enum):
    WEAK = "weak"
    MEDIUM = "medium"
    STRONG = "strong"
    PERMANENT = "permanent"


_STRENGTH_ORDER = [AnchorStrength.WEAK, AnchorStrength.MEDIUM, AnchorStrength.STRONG, AnchorStrength.PERMANENT]

_CONFIDENCE_BASE = {
    AnchorStrength.PERMANENT: 1.0,
    AnchorStrength.STRONG: 0.9,
    AnchorStrength.MEDIUM: 0.7,
    AnchorStrength.WEAK: 0.5,
}


@dataclass
class Anchor:
    id: str = ""
    content: str = ""
    anchor_type: AnchorType = AnchorType.KNOWLEDGE
    strength: AnchorStrength = AnchorStrength.MEDIUM
    created_at: float = field(default_factory=time.time)
    verified_at: float = field(default_factory=time.time)
    verification_count: int = 0
    source: str = ""
    lineage: list[str] = field(default_factory=list)
    negative_constraints: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    _fingerprint: str = field(default="", repr=False)
    _original_content: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = f"anc_{uuid.uuid4().hex[:12]}"
        if not self._fingerprint:
            self._fingerprint = self._compute_fingerprint()
        if not self._original_content:
            self._original_content = self.content

    def _compute_fingerprint(self) -> str:
        payload = f"{self.content}:{self.anchor_type.value}:{self.source}"
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    @logged()
    @safe_execute
    def verify(self) -> bool:
        if self.strength == AnchorStrength.PERMANENT and self.content != self._original_content:
            logger.error("Permanent anchor %s has been modified!", self.id)
            return False
        self.verified_at = time.time()
        self.verification_count += 1
        return True

    @logged()
    @async_compatible
    def verify_immutability(self) -> bool:
        if self.strength != AnchorStrength.PERMANENT:
            return True
        return self.content == self._original_content

    @logged()
    @safe_execute
    def is_expired(self, ttl: float = 2592000.0) -> bool:
        if self.strength == AnchorStrength.PERMANENT:
            return False
        return (time.time() - self.verified_at) > ttl

    @logged()
    @safe_execute
    def derive(
        self,
        new_content: str,
        anchor_type: AnchorType | None = None,
        source: str = "",
    ) -> Anchor:
        return Anchor(
            content=new_content,
            anchor_type=anchor_type or self.anchor_type,
            strength=AnchorStrength.MEDIUM,
            source=source or f"derived_from:{self.id}",
            lineage=self.lineage + [self.id],
            negative_constraints=list(self.negative_constraints),
        )

    @logged()
    @safe_execute
    def get_confidence(self) -> float:
        base = _CONFIDENCE_BASE.get(self.strength, 0.5)
        decay = max(0.0, 1.0 - (time.time() - self.verified_at) / 7776000.0)
        verification_bonus = min(0.1, self.verification_count * 0.02)
        return min(1.0, base * decay + verification_bonus)

    @logged()
    @safe_execute
    def add_negative_constraint(self, constraint: str) -> None:
        if constraint and constraint not in self.negative_constraints:
            self.negative_constraints.append(constraint)

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["anchor_type"] = self.anchor_type.value
        d["strength"] = self.strength.value
        d["fingerprint"] = self.fingerprint
        d.pop("_fingerprint", None)
        d.pop("_original_content", None)
        return d

    @classmethod
    @logged()
    @safe_execute
    def from_dict(cls, data: dict[str, Any]) -> Anchor:
        data = dict(data)
        data["anchor_type"] = AnchorType(data["anchor_type"])
        data["strength"] = AnchorStrength(data["strength"])
        fingerprint = data.pop("fingerprint", "")
        anchor = cls(**data)
        if fingerprint:
            anchor._fingerprint = fingerprint
        return anchor


class MemoryAnchor:
    def __init__(self) -> None:
        self._anchors: dict[str, Anchor] = {}
        self._fingerprint_index: dict[str, str] = {}

    @logged()
    @async_compatible
    def create_anchor(
        self,
        content: str,
        anchor_type: AnchorType,
        strength: AnchorStrength = AnchorStrength.MEDIUM,
        source: str = "",
        lineage: list[str] | None = None,
        negative_constraints: list[str] | None = None,
    ) -> Anchor:
        anchor = Anchor(
            content=content,
            anchor_type=anchor_type,
            strength=strength,
            source=source,
            lineage=lineage or [],
            negative_constraints=negative_constraints or [],
        )
        self._anchors[anchor.id] = anchor
        self._fingerprint_index[anchor.fingerprint] = anchor.id
        logger.info("Created anchor %s type=%s strength=%s", anchor.id, anchor_type.value, strength.value)
        return anchor

    @logged()
    @safe_execute
    def get(self, anchor_id: str) -> Anchor | None:
        anchor = self._anchors.get(anchor_id)
        if anchor:
            anchor.verify()
        return anchor

    @logged()
    @safe_execute
    def update(self, anchor_id: str, content: str) -> Anchor | None:
        anchor = self._anchors.get(anchor_id)
        if anchor is None:
            return None
        if anchor.strength == AnchorStrength.PERMANENT:
            logger.warning("Cannot update permanent anchor %s", anchor_id)
            return None
        old_fp = anchor.fingerprint
        anchor.content = content
        anchor._fingerprint = anchor._compute_fingerprint()
        self._fingerprint_index.pop(old_fp, None)
        self._fingerprint_index[anchor.fingerprint] = anchor.id
        return anchor

    @logged()
    @safe_execute
    def delete(self, anchor_id: str) -> bool:
        anchor = self._anchors.pop(anchor_id, None)
        if anchor is None:
            return False
        self._fingerprint_index.pop(anchor.fingerprint, None)
        return True

    @logged()
    @safe_execute
    def find_by_fingerprint(self, fingerprint: str) -> Anchor | None:
        aid = self._fingerprint_index.get(fingerprint)
        if aid:
            return self._anchors.get(aid)
        return None

    @logged()
    @safe_execute
    def find_by_content(self, content: str) -> Anchor | None:
        for anchor in self._anchors.values():
            if anchor.content == content:
                return anchor
        return None

    @logged()
    @safe_execute
    def find_by_type(self, anchor_type: AnchorType) -> list[Anchor]:
        return [a for a in self._anchors.values() if a.anchor_type == anchor_type]

    @logged()
    @safe_execute
    def find_by_source(self, source: str) -> list[Anchor]:
        return [a for a in self._anchors.values() if a.source == source]

    @logged()
    @safe_execute
    def find_by_strength(self, strength: AnchorStrength) -> list[Anchor]:
        return [a for a in self._anchors.values() if a.strength == strength]

    @logged()
    @safe_execute
    def get_lineage(self, anchor_id: str) -> list[Anchor]:
        anchor = self._anchors.get(anchor_id)
        if not anchor:
            return []
        return [self._anchors[aid] for aid in anchor.lineage if aid in self._anchors]

    @logged()
    @async_compatible
    def verify_all(self) -> dict[str, Any]:
        total = len(self._anchors)
        corrupted = [a.id for a in self._anchors.values() if not a.verify_immutability()]
        return {
            "total": total,
            "corrupted": len(corrupted),
            "corrupted_ids": corrupted,
            "intact": total - len(corrupted),
        }

    @logged()
    @safe_execute
    def get_negative_constraints(self) -> list[str]:
        constraints: list[str] = []
        for anchor in self._anchors.values():
            constraints.extend(anchor.negative_constraints)
        return list(set(constraints))

    @logged()
    @safe_execute
    def check_constraints(self, action: str) -> list[Anchor]:
        action_lower = action.lower()
        return [a for a in self._anchors.values() if any(c.lower() in action_lower for c in a.negative_constraints)]

    @logged()
    @safe_execute
    def merge(self, anchor_id_a: str, anchor_id_b: str, strategy: str = "strongest") -> Anchor | None:
        a = self._anchors.get(anchor_id_a)
        b = self._anchors.get(anchor_id_b)
        if a is None or b is None:
            return None
        merged = merge_anchors(a, b, strategy=strategy)
        self._anchors[merged.id] = merged
        self._fingerprint_index[merged.fingerprint] = merged.id
        return merged

    @logged()
    @safe_execute
    def list_all(self) -> list[Anchor]:
        return list(self._anchors.values())

    @logged()
    @safe_execute
    def count(self) -> int:
        return len(self._anchors)

    @logged()
    @safe_execute
    def count_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for a in self._anchors.values():
            counts[a.anchor_type.value] = counts.get(a.anchor_type.value, 0) + 1
        return counts

    @logged()
    @safe_execute
    def count_by_strength(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for a in self._anchors.values():
            counts[a.strength.value] = counts.get(a.strength.value, 0) + 1
        return counts

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {aid: a.to_dict() for aid, a in self._anchors.items()}

    @classmethod
    @logged()
    @safe_execute
    def from_dict(cls, data: dict[str, Any]) -> MemoryAnchor:
        ma = cls()
        for aid, anchor_data in data.items():
            anchor = Anchor.from_dict(anchor_data)
            ma._anchors[aid] = anchor
            ma._fingerprint_index[anchor.fingerprint] = aid
        return ma


@logged()
@async_compatible
def create_anchor(
    content: str,
    anchor_type: AnchorType,
    strength: AnchorStrength = AnchorStrength.MEDIUM,
    source: str = "",
    lineage: list[str] | None = None,
    negative_constraints: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Anchor:
    return Anchor(
        content=content,
        anchor_type=anchor_type,
        strength=strength,
        source=source,
        lineage=lineage or [],
        negative_constraints=negative_constraints or [],
        metadata=metadata or {},
    )


@logged()
@async_compatible
def validate_anchor(anchor: Anchor) -> dict[str, Any]:
    issues: list[str] = []
    if not anchor.content.strip():
        issues.append("empty_content")
    if not anchor.id.startswith("anc_"):
        issues.append("invalid_id_format")
    current_fp = anchor._compute_fingerprint()
    if current_fp != anchor._fingerprint:
        issues.append("fingerprint_mismatch")
    if anchor.strength == AnchorStrength.PERMANENT and anchor.content != anchor._original_content:
        issues.append("permanent_tampered")
    return {"valid": len(issues) == 0, "anchor_id": anchor.id, "issues": issues}


@logged()
@safe_execute
def merge_anchors(a, b, strategy="strongest"):
    if a is None or b is None:
        logger.warning("merge_anchors received None input: a=%s b=%s", a is None, b is None)
        return a if a is not None else b
    try:
        _priority = {s: i for i, s in enumerate(_STRENGTH_ORDER)}
        pa, pb = _priority.get(a.strength, -1), _priority.get(b.strength, -1)
        if strategy == "weakest":
            strength = a.strength if pa <= pb else b.strength
        elif strategy in ("strongest", "latest", "union"):
            strength = a.strength if pa >= pb else b.strength
        else:
            logger.warning("Unknown merge strategy '%s', defaulting to 'a'", strategy)
            strength = a.strength
        merged_constraints = list(dict.fromkeys(a.negative_constraints + b.negative_constraints))
        merged_lineage = list(dict.fromkeys(a.lineage + b.lineage))
        meta_a = a.metadata if hasattr(a, 'metadata') and isinstance(a.metadata, dict) else {}
        meta_b = b.metadata if hasattr(b, 'metadata') and isinstance(b.metadata, dict) else {}
        return Anchor(
            content=a.content,
            anchor_type=a.anchor_type,
            strength=strength,
            source=f"merged:{a.id}+{b.id}",
            lineage=merged_lineage,
            negative_constraints=merged_constraints,
            metadata={**meta_b, **meta_a},
        )
    except Exception as _exc:
        logger.error("Anchor merge failed, degrading to anchor 'a': %s", _exc)
        return a

