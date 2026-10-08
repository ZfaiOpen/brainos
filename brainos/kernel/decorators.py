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
import functools
import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("brainos.kernel.decorators")


from typing import Any, Callable
def logged(func=None):
    if func is None:
        return logged

    _SLOW_THRESHOLD_MS = 1000.0

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        func_name = getattr(func, "__qualname__", getattr(func, "__name__", "unknown"))
        logger.debug("→ %s", func_name)
        start = time.monotonic()
        try:
            result = func(*args, **kwargs)
            duration = (time.monotonic() - start) * 1000
            if duration > _SLOW_THRESHOLD_MS:
                logger.warning("⚠ %s slow-call (%.1fms)", func_name, duration)
            else:
                logger.debug("← %s (%.1fms)", func_name, duration)
            return result
        except Exception as _exc:
            duration = (time.monotonic() - start) * 1000
            logger.exception("✗ %s (%.1fms)", func_name, duration)
            raise

    wrapper.__isabstractmethod__ = getattr(func, "__isabstractmethod__", False)
    return wrapper



def audit_logged(func: Callable[..., Any]) -> Callable[..., Any]:
    _audit_logger = logging.getLogger("brainos.audit")

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        func_name = func.__qualname__
        _audit_logger.info("AUDIT CALL: %s args=%s kwargs_keys=%s", func_name, len(args), list(kwargs.keys()))
        start = time.monotonic()
        try:
            result = func(*args, **kwargs)
            duration = (time.monotonic() - start) * 1000
            _audit_logger.info("AUDIT OK: %s duration=%.1fms", func_name, duration)
            return result
        except Exception as _exc:
            duration = (time.monotonic() - start) * 1000
            _audit_logger.exception("AUDIT FAIL: %s duration=%.1fms", func_name, duration)
            raise

    return wrapper
