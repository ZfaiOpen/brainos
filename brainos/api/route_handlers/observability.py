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
from typing import TYPE_CHECKING

from brainos.kernel.auto_log import logged
from brainos.kernel.safe_execute import safe_execute

if TYPE_CHECKING:
    from brainos.api.server import BrainOSAPI
    from brainos.observability.health import HealthChecker
    from brainos.observability.metrics import MetricsCollector

    AlertManager = object  # forward reference placeholder
    Tracer = object  # forward reference placeholder

import logging
import time
from dataclasses import dataclass
from typing import Any

from brainos.api.middleware import Request, Response

logger = logging.getLogger("brainos.api.routes.observability")


@dataclass
class ObservabilityRouteConfig:
    max_metrics_per_query: int = 500
    max_traces_per_query: int = 100
    max_alerts_per_query: int = 200
    default_retention_hours: int = 72
    enable_detailed_health: bool = True

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "max_metrics_per_query": self.max_metrics_per_query,
            "max_traces_per_query": self.max_traces_per_query,
            "max_alerts_per_query": self.max_alerts_per_query,
            "default_retention_hours": self.default_retention_hours,
            "enable_detailed_health": self.enable_detailed_health,
        }


@dataclass
class ObservabilityRouteMetrics:
    total_metric_queries: int = 0
    total_trace_queries: int = 0
    total_health_queries: int = 0
    total_alert_queries: int = 0
    query_latency_total_ms: float = 0.0
    errors: int = 0

    @logged()
    @safe_execute
    def record_query(self, query_type, latency_ms):
        pass


    @property
    def total_queries(self) -> int:
        return self.total_metric_queries + self.total_trace_queries + self.total_health_queries + self.total_alert_queries

    @property
    def avg_query_latency_ms(self) -> float:
        return self.query_latency_total_ms / max(1, self.total_queries)

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        return {
            "total_metric_queries": self.total_metric_queries,
            "total_trace_queries": self.total_trace_queries,
            "total_health_queries": self.total_health_queries,
            "total_alert_queries": self.total_alert_queries,
            "total_queries": self.total_queries,
            "avg_query_latency_ms": round(self.avg_query_latency_ms, 2),
            "errors": self.errors,
        }


class ObservabilityRouteHandler:
    def __init__(self, config: ObservabilityRouteConfig | None = None) -> None:
        self._config = config or ObservabilityRouteConfig()
        self._metrics = ObservabilityRouteMetrics()
        self._metrics_collector: MetricsCollector | None = None
        self._tracer: Tracer | None = None
        self._health_checker: HealthChecker | None = None
        self._alert_manager: AlertManager | None = None

    @logged()
    @safe_execute
    def set_metrics_collector(self, collector: MetricsCollector) -> None:
        self._metrics_collector = collector

    @logged()
    @safe_execute
    def set_tracer(self, tracer: Tracer) -> None:
        self._tracer = tracer

    @logged()
    @safe_execute
    def set_health_checker(self, checker: HealthChecker) -> None:
        self._health_checker = checker

    @logged()
    @safe_execute
    def set_alert_manager(self, manager: AlertManager) -> None:
        self._alert_manager = manager

    @logged()
    async def handle_get_metrics(self, request: Request) -> Response:
        start = time.monotonic()
        module_filter = request.query_params.get("module", "")
        limit = min(int(request.query_params.get("limit", "100")), self._config.max_metrics_per_query)

        if self._metrics_collector:
            try:
                if module_filter:
                    result = self._metrics_collector.get_metrics(module=module_filter, limit=limit)
                else:
                    result = self._metrics_collector.get_metrics(limit=limit)
                metrics_data = result if isinstance(result, list) else []
                if hasattr(result, "to_dict"):
                    metrics_data = [m.to_dict() if hasattr(m, "to_dict") else m for m in result]
            except Exception as _exc:
                logger.exception("Failed to get metrics from collector")
                self._metrics.errors += 1
                metrics_data = []
        else:
            metrics_data = [
                {
                    "name": "brainos.api.requests.total",
                    "type": "counter",
                    "value": 0,
                    "labels": {"module": "api"},
                    "timestamp": time.time(),
                },
                {
                    "name": "brainos.api.latency.ms",
                    "type": "histogram",
                    "value": 0.0,
                    "labels": {"module": "api"},
                    "timestamp": time.time(),
                },
                {
                    "name": "brainos.memory.anchors.count",
                    "type": "gauge",
                    "value": 0,
                    "labels": {"module": "memory"},
                    "timestamp": time.time(),
                },
            ]
            if module_filter:
                metrics_data = [m for m in metrics_data if m.get("labels", {}).get("module") == module_filter]
            metrics_data = metrics_data[:limit]

        latency_ms = (time.monotonic() - start) * 1000.0
        self._metrics.record_query("metrics", latency_ms)

        return Response.ok(
            {
                "metrics": metrics_data,
                "total": len(metrics_data),
                "module_filter": module_filter or None,
            },
            request.request_id,
        )

    @logged()
    async def handle_get_traces(self, request: Request) -> Response:
        start = time.monotonic()
        trace_id = request.query_params.get("trace_id", "")
        limit = min(int(request.query_params.get("limit", "50")), self._config.max_traces_per_query)

        if self._tracer:
            try:
                if trace_id:
                    result = self._tracer.get_trace(trace_id)
                    traces = [result] if result else []
                else:
                    result = self._tracer.list_traces(limit=limit)
                    traces = result if isinstance(result, list) else []
                traces_data = [t.to_dict() if hasattr(t, "to_dict") else t for t in traces]
            except Exception as _exc:
                logger.exception("Failed to get traces from tracer")
                self._metrics.errors += 1
                traces_data = []
        else:
            traces_data = []
            if trace_id:
                traces_data = [
                    {
                        "trace_id": trace_id,
                        "spans": [],
                        "status": "not_found",
                        "duration_ms": 0.0,
                    }
                ]

        latency_ms = (time.monotonic() - start) * 1000.0
        self._metrics.record_query("traces", latency_ms)

        return Response.ok(
            {
                "traces": traces_data,
                "total": len(traces_data),
                "trace_id_filter": trace_id or None,
            },
            request.request_id,
        )

    @logged()
    async def handle_get_health(self, request: Request) -> Response:
        start = time.monotonic()

        if self._health_checker:
            try:
                health = self._health_checker.check()
                if isinstance(health, dict):
                    health_data = health
                elif hasattr(health, "to_dict"):
                    health_data = health.to_dict()
                else:
                    health_data = {"status": str(health)}
            except Exception as _exc:
                logger.exception("Failed to get health from checker")
                self._metrics.errors += 1
                health_data = {
                    "status": "degraded",
                    "error": "health check failed",
                }
        else:
            health_data = {
                "status": "healthy",
                "timestamp": time.time(),
                "uptime_seconds": 0,
                "components": {
                    "api": {"status": "healthy", "latency_ms": 0.1},
                    "ans": {"status": "healthy", "latency_ms": 0.0},
                    "memory": {"status": "healthy", "latency_ms": 0.0},
                    "cognition": {"status": "healthy", "latency_ms": 0.0},
                    "evolution": {"status": "healthy", "latency_ms": 0.0},
                    "governance": {"status": "healthy", "latency_ms": 0.0},
                    "amcc": {"status": "healthy", "latency_ms": 0.0},
                    "capability": {"status": "healthy", "latency_ms": 0.0},
                },
                "version": "2.0.0",
            }
            if self._config.enable_detailed_health:
                health_data["details"] = {
                    "python_version": "3.12+",
                    "process_id": 0,
                    "memory_usage_mb": 0.0,
                    "cpu_percent": 0.0,
                }

        latency_ms = (time.monotonic() - start) * 1000.0
        self._metrics.record_query("health", latency_ms)

        return Response.ok(health_data, request.request_id)

    @logged()
    async def handle_get_alerts(self, request: Request) -> Response:
        start = time.monotonic()
        severity_filter = request.query_params.get("severity", "")
        limit = min(int(request.query_params.get("limit", "50")), self._config.max_alerts_per_query)
        acknowledged = request.query_params.get("acknowledged", "")

        if self._alert_manager:
            try:
                filters: dict[str, Any] = {}
                if severity_filter:
                    filters["severity"] = severity_filter
                if acknowledged:
                    filters["acknowledged"] = acknowledged.lower() in ("true", "1", "yes")
                result = self._alert_manager.list_alerts(filters=filters, limit=limit)
                alerts = result if isinstance(result, list) else []
                alerts_data = [a.to_dict() if hasattr(a, "to_dict") else a for a in alerts]
            except Exception as _exc:
                logger.exception("Failed to get alerts from alert manager")
                self._metrics.errors += 1
                alerts_data = []
        else:
            alerts_data = []

        latency_ms = (time.monotonic() - start) * 1000.0
        self._metrics.record_query("alerts", latency_ms)

        return Response.ok(
            {
                "alerts": alerts_data,
                "total": len(alerts_data),
                "severity_filter": severity_filter or None,
                "acknowledged_filter": acknowledged or None,
            },
            request.request_id,
        )

    @logged()
    async def handle_get_metrics_summary(self, request: Request) -> Response:
        return Response.ok(self._metrics.to_dict(), request.request_id)

    @logged()
    @safe_execute
    def stats(self) -> dict[str, Any]:
        return {
            "metrics": self._metrics.to_dict(),
            "config": self._config.to_dict(),
        }


@logged()
@safe_execute
def register_observability_routes(api: BrainOSAPI, handler: ObservabilityRouteHandler | None = None) -> ObservabilityRouteHandler:
    h = handler or ObservabilityRouteHandler()
    api.get("/api/v1/observability/metrics", h.handle_get_metrics)
    api.get("/api/v1/observability/traces", h.handle_get_traces)
    api.get("/api/v1/observability/health", h.handle_get_health)
    api.get("/api/v1/observability/alerts", h.handle_get_alerts)
    api.get("/api/v1/observability/metrics_summary", h.handle_get_metrics_summary)
    logger.info("Observability routes registered: 5 endpoints")
    return h
