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
"""Route handlers (open-core subset): memory + observability only.

The other 23 handlers (ans / cognition / evolution / rag / knowledge /
training / ...) are commercial version only.
"""

from __future__ import annotations

from brainos.api.route_handlers.memory import register_memory_routes
from brainos.api.route_handlers.observability import register_observability_routes

__all__ = [
    "register_memory_routes",
    "register_observability_routes",
]
