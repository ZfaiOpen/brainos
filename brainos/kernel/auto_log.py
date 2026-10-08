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
import threading

import logging
from typing import TypeVar

logger = logging.getLogger("brainos.kernel.auto_log")

T = TypeVar("T")

from brainos.kernel.decorators import logged as logged  # noqa: E402,F401


class BufferHandler(logging.Handler):
    def __init__(self, capacity: int = 10000) -> None:
        self._lock = threading.RLock()
