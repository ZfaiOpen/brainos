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
