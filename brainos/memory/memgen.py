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
from dataclasses import dataclass
import re
import hashlib
import logging


@dataclass
class GenRule:
    rule_id: str
    template: str
    params: dict[str, str]
    associated_raw_size: int = 0


class MemGenStore:
    def __init__(self) -> None:
        self._rules: dict[str, GenRule] = {}
        self._counter: int = 0

    def create_rule(self, name: str, template: str, params: dict[str, str]) -> str:
        self._counter += 1
        rule_id = f"rule_{name}_{self._counter}"
        self._rules[rule_id] = GenRule(rule_id=rule_id, template=template, params=params)
        return rule_id

    def has_rule(self, rule_id: str) -> bool:
        return rule_id in self._rules

    def generate(self, rule_id: str, values: dict[str, str]) -> str:
        rule = self._rules[rule_id]
        result = rule.template
        for key, val in values.items():
            result = result.replace(f"{{{key}}}", str(val))
        return result

    def associate(self, rule_id: str, raw_data: str) -> None:
        if rule_id in self._rules:
            self._rules[rule_id].associated_raw_size = len(raw_data)

    def compression_ratio(self, rule_id: str) -> float:
        rule = self._rules.get(rule_id)
        if rule is None or rule.associated_raw_size == 0:
            return 1.0
        rule_size = len(rule.template) + sum(len(k) + len(v) for k, v in rule.params.items())
        return rule.associated_raw_size / max(rule_size, 1)
