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
"""Minimal HTTP/SDK service surface (open core v0.9).

The evolution API and the full /api/v1 route registry are commercial version
only.
"""

from __future__ import annotations

from brainos.api.auth import AuthManager, AuthMethod, AuthResult, AuthToken
from brainos.api.gateway import APIGateway, GatewayRequest, GatewayResponse, HTTPMethod, Route
from brainos.api.middleware import Middleware, MiddlewareChain
from brainos.api.rate_limiter import LimiterAlgorithm, RateLimitConfig, RateLimiter, RateLimitResult
from brainos.api.routes import Router
from brainos.api.server import BrainOSAPI

__all__ = [
    "APIGateway",
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
]
