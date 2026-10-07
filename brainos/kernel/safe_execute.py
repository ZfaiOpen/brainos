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
import logging
import threading
from collections.abc import Callable
from typing import Any

from brainos.kernel.types import Err, Ok

logger = logging.getLogger("brainos.kernel.safe_execute")

_swallowed_errors: list[dict[str, Any]] = []
_swallowed_lock = threading.Lock()
_MAX_SWALLOWED = 1000


def get_swallowed_errors() -> list[dict[str, Any]]:
    with _swallowed_lock:
        return list(_swallowed_errors)


def clear_swallowed_errors() -> int:
    with _swallowed_lock:
        count = len(_swallowed_errors)
        _swallowed_errors.clear()
        return count


def safe_execute(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that wraps a function with try/except and logs exceptions.

    Exceptions are logged and re-raised, ensuring no silent failures.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception as _exc:
            logger.exception("%s failed", func.__qualname__)
            raise

    wrapper._is_safe_executed = True
    wrapper._original_func = func
    return wrapper


def is_safe_executed(func: Callable[..., Any]) -> bool:
    return getattr(func, "_is_safe_executed", False)


_SENTINEL = object()


def safe_call(func: Callable[..., Any], *args: Any, default: Any = _SENTINEL, **kwargs: Any) -> Any:
    try:
        return func(*args, **kwargs)
    except Exception as _exc:
        func_name = getattr(func, "__qualname__", str(func))
        logger.exception("%s failed", func_name)
        if default is not _SENTINEL:
            with _swallowed_lock:
                if len(_swallowed_errors) < _MAX_SWALLOWED:
                    _swallowed_errors.append({
                        "function": func_name,
                        "error": repr(_exc),
                        "default_returned": repr(default),
                    })
            return default
        raise


def safe_execute_v2(func: Callable[..., Any]) -> Callable[..., Ok[Any] | Err[Exception]]:
    """Decorator that wraps a function and returns Ok(value) or Err(exception).

    Unlike safe_execute which re-raises, this ALWAYS returns a Result type.
    Callers MUST explicitly check .is_ok / .is_err or use .unwrap() / .unwrap_or().
    This eliminates the silent-failure pattern where safe_call(default=None) hides errors.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Ok[Any] | Err[Exception]:
        try:
            result = func(*args, **kwargs)
            return Ok(result)
        except Exception as exc:
            logger.exception("%s failed (captured as Err)", func.__qualname__)
            return Err(exc)

    wrapper._is_safe_executed_v2 = True
    wrapper._original_func = func
    return wrapper


from typing import Any, Callable
def safe_call_v2(func, *args, **kwargs):
    """Call a function and return Ok(result) or Err(exception).

    Unlike safe_call which may silently return a default value,
    this always returns an explicit Result type that the caller must handle.
    Includes pre-execution callable validation and tiered exception logging
    to prevent log storms in kernel hot paths.
    """
    if not callable(func):
        func_name = getattr(func, "__qualname__", repr(func))
        logger.warning("safe_call_v2 rejected non-callable target: %s", func_name)
        return Err(TypeError(f"Target is not callable: {func_name}"))

    func_name = getattr(func, "__qualname__", str(func))
    try:
        result = func(*args, **kwargs)
        return Ok(result)
    except TypeError as _exc:
        logger.warning(
            "%s failed with TypeError (captured as Err): %s",
            func_name, _exc, exc_info=False
        )
        return Err(_exc)
    except Exception as _exc:
        logger.exception("%s failed (captured as Err)", func_name)
        return Err(_exc)

