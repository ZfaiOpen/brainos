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
from dataclasses import dataclass, field
from typing import Any

from brainos.kernel.auto_log import logged
from brainos.kernel.safe_execute import safe_execute


@dataclass
class AIAnalyzeRequest:
    code: str = ""
    language: str = ""
    analysis_type: str = "full"
    context: dict[str, Any] = field(default_factory=dict)

    @logged()
    @safe_execute
    def to_dict(self):
        pass



@dataclass
class AIAnalyzeResponse:
    analysis_id: str = ""
    issues: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    suggestions: list[str] = field(default_factory=list)
    score: float = 0.0

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "issues": self.issues,
            "metrics": self.metrics,
            "suggestions": self.suggestions,
            "score": round(self.score, 4),
        }


@dataclass
class AIGenerateRequest:
    prompt: str = ""
    language: str = ""
    framework: str = ""
    style: str = "clean"
    context: dict[str, Any] = field(default_factory=dict)

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "language": self.language,
            "framework": self.framework,
            "style": self.style,
            "context": self.context,
        }


@dataclass
class AIGenerateResponse:
    generation_id: str = ""
    code: str = ""
    language: str = ""
    explanation: str = ""
    dependencies: list[str] = field(default_factory=list)

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "generation_id": self.generation_id,
            "code": self.code,
            "language": self.language,
            "explanation": self.explanation,
            "dependencies": self.dependencies,
        }


@dataclass
class AICompleteRequest:
    code: str = ""
    language: str = ""
    cursor_position: int = 0
    max_suggestions: int = 5
    context: dict[str, Any] = field(default_factory=dict)

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "language": self.language,
            "cursor_position": self.cursor_position,
            "max_suggestions": self.max_suggestions,
            "context": self.context,
        }


@dataclass
class AICompleteResponse:
    completion_id: str = ""
    suggestions: list[dict[str, Any]] = field(default_factory=list)
    primary: str = ""

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "completion_id": self.completion_id,
            "suggestions": self.suggestions,
            "primary": self.primary,
        }


@dataclass
class AIExplainRequest:
    code: str = ""
    language: str = ""
    detail_level: str = "normal"
    context: dict[str, Any] = field(default_factory=dict)

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "language": self.language,
            "detail_level": self.detail_level,
            "context": self.context,
        }


@dataclass
class AIExplainResponse:
    explanation_id: str = ""
    summary: str = ""
    details: list[dict[str, Any]] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "explanation_id": self.explanation_id,
            "summary": self.summary,
            "details": self.details,
            "concepts": self.concepts,
        }


@dataclass
class AIFixRequest:
    code: str = ""
    language: str = ""
    error_message: str = ""
    error_type: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "language": self.language,
            "error_message": self.error_message,
            "error_type": self.error_type,
            "context": self.context,
        }


@dataclass
class AIFixResponse:
    fix_id: str = ""
    fixed_code: str = ""
    explanation: str = ""
    changes: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "fix_id": self.fix_id,
            "fixed_code": self.fixed_code,
            "explanation": self.explanation,
            "changes": self.changes,
            "confidence": round(self.confidence, 4),
        }


@dataclass
class AIChatRequest:
    message: str = ""
    conversation_id: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message,
            "conversation_id": self.conversation_id,
            "context": self.context,
        }


@dataclass
class AIChatResponse:
    response_id: str = ""
    reply: str = ""
    conversation_id: str = ""
    suggestions: list[str] = field(default_factory=list)

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "response_id": self.response_id,
            "reply": self.reply,
            "conversation_id": self.conversation_id,
            "suggestions": self.suggestions,
        }


@dataclass
class RefactoringAnalyzeRequest:
    target_path: str = ""
    analysis_depth: str = "standard"
    focus_areas: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "target_path": self.target_path,
            "analysis_depth": self.analysis_depth,
            "focus_areas": self.focus_areas,
            "context": self.context,
        }


@dataclass
class RefactoringAnalyzeResponse:
    analysis_id: str = ""
    problems: list[dict[str, Any]] = field(default_factory=list)
    risk_level: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "problems": self.problems,
            "risk_level": self.risk_level,
            "metrics": self.metrics,
            "recommendations": self.recommendations,
        }


@dataclass
class RefactoringExecuteRequest:
    target_path: str = ""
    layer: str = "L4_CODE"
    approved: bool = False
    dry_run: bool = False
    context: dict[str, Any] = field(default_factory=dict)

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "target_path": self.target_path,
            "layer": self.layer,
            "approved": self.approved,
            "dry_run": self.dry_run,
            "context": self.context,
        }


@dataclass
class RefactoringExecuteResponse:
    execution_id: str = ""
    success: bool = False
    changes: list[dict[str, Any]] = field(default_factory=list)
    fitness_before: float = 0.0
    fitness_after: float = 0.0
    duration_ms: float = 0.0

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "success": self.success,
            "changes": self.changes,
            "fitness_before": round(self.fitness_before, 4),
            "fitness_after": round(self.fitness_after, 4),
            "duration_ms": round(self.duration_ms, 2),
        }


@dataclass
class TrainingCollectRequest:
    source: str = ""
    data_type: str = "task"
    records: list[dict[str, Any]] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "data_type": self.data_type,
            "records": self.records,
            "context": self.context,
        }


@dataclass
class TrainingCollectResponse:
    collection_id: str = ""
    collected_count: int = 0
    valid_count: int = 0
    errors: list[str] = field(default_factory=list)

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "collection_id": self.collection_id,
            "collected_count": self.collected_count,
            "valid_count": self.valid_count,
            "errors": self.errors,
        }


@dataclass
class TrainingStatusResponse:
    engine_active: bool = False
    brain_type: str = ""
    pipeline_entries: int = 0
    repository_stats: dict[str, Any] = field(default_factory=dict)
    last_pipeline_status: str = ""

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_active": self.engine_active,
            "brain_type": self.brain_type,
            "pipeline_entries": self.pipeline_entries,
            "repository_stats": self.repository_stats,
            "last_pipeline_status": self.last_pipeline_status,
        }
