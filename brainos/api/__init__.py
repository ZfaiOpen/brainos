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
"""Minimal HTTP/SDK service surface (open core v0.9).

The evolution API and the full /api/v1 route registry are commercial version
only.
"""

from __future__ import annotations

from brainos.api.aml import (
    AMLRouteHandler,
    AMLService,
    AddLedger,
    format_sse,
    register_aml_routes,
    wire_memory_surface,
)
from brainos.api.auth import AuthManager, AuthMethod, AuthResult, AuthToken
from brainos.api.gateway import APIGateway, GatewayRequest, GatewayResponse, HTTPMethod, Route
from brainos.api.middleware import Middleware, MiddlewareChain
from brainos.api.rate_limiter import LimiterAlgorithm, RateLimitConfig, RateLimiter, RateLimitResult
from brainos.api.routes import Router
from brainos.api.server import BrainOSAPI

__all__ = [
    "AMLRouteHandler",
    "AMLService",
    "APIGateway",
    "AddLedger",
    "AuthManager",
    "AuthMethod",
    "AuthResult",
    "AuthToken",
    "BrainOSAPI",
    "GatewayRequest",
    "GatewayResponse",
    "HTTPMethod",
    "LimiterAlgorithm",
    "Middleware",
    "MiddlewareChain",
    "RateLimitConfig",
    "RateLimitResult",
    "RateLimiter",
    "Route",
    "Router",
    "format_sse",
    "register_aml_routes",
    "wire_memory_surface",
]
