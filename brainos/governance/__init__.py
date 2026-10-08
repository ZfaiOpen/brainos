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
"""Governance surface (open-core subset): constitution stub only.

Compliance, explainability and policy-engine modules are commercial version
only; the constitution engine ships as a NoopConstitution stub.
"""

from __future__ import annotations

from brainos.governance.constitution import (
    ConstitutionEngine as ConstitutionEngine,
    ConstitutionRule as ConstitutionRule,
    GovernanceAction as GovernanceAction,
    GovernanceDecision as GovernanceDecision,
    PrincipleCategory as PrincipleCategory,
    Violation as Violation,
    ViolationSeverity as ViolationSeverity,
)

__all__ = [
    "ConstitutionEngine",
    "ConstitutionRule",
    "GovernanceAction",
    "GovernanceDecision",
    "PrincipleCategory",
    "Violation",
    "ViolationSeverity",
]
