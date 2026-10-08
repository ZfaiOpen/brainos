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
"""Protocol surface (open-core subset): cross-domain protocols only.

The full protocol registry (concurrency / operations / performance / security
protocol families) is commercial version only.
"""

__all__ = [
    "AdvancedMemoryStoreProtocol",
    "CognitionEngineProtocol",
    "EpisodicStoreProtocol",
    "EvolutionEngineProtocol",
    "ForgettingProtocol",
    "MemoryConsolidatorProtocol",
    "MemoryStoreProtocol",
    "RetrievalBoostProtocol",
    "SecurityEngineProtocol",
    "TemporalKGProtocol",
]

from .cross_domain import (
    AdvancedMemoryStoreProtocol,
    CognitionEngineProtocol,
    EpisodicStoreProtocol,
    EvolutionEngineProtocol,
    ForgettingProtocol,
    MemoryConsolidatorProtocol,
    MemoryStoreProtocol,
    RetrievalBoostProtocol,
    SecurityEngineProtocol,
    TemporalKGProtocol,
)
