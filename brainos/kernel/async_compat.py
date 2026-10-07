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
from __future__ import annotations
import functools
from collections.abc import Callable
from typing import Any


import logging
from typing import Any, Callable
import logging

_logger = logging.getLogger("brainos.kernel.async_compat")

_ASYNC_COMPAT_FLAG = "_is_async_compatible"
_ASYNC_COMPAT_ORIG = "_original_func"

def async_compatible(func):
    """Decorator that marks a sync function as async-compatible.

    The function remains callable synchronously, but is marked
    with _is_async_compatible=True for the async runtime to detect.
    """
    if not callable(func):
        _logger.warning(
            "async_compatible: rejected non-callable target (type=%s), "
            "returning original object unchanged.",
            type(func).__name__,
        )
        return func

    if getattr(func, _ASYNC_COMPAT_FLAG, False):
        _logger.debug(
            "async_compatible: target '%s' already decorated, skipping (idempotent).",
            getattr(func, "__name__", repr(func)),
        )
        return func

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as _exc:
            _logger.warning(
                "async_compatible wrapper: target '%s' raised %s: %s",
                getattr(func, "__name__", "<unknown>"),
                type(_exc).__name__,
                _exc,
                exc_info=False,
            )
            raise

    setattr(wrapper, _ASYNC_COMPAT_FLAG, True)
    setattr(wrapper, _ASYNC_COMPAT_ORIG, func)
    return wrapper



def is_async_compatible(func: Callable[..., Any]) -> bool:
    return getattr(func, "_is_async_compatible", False)
