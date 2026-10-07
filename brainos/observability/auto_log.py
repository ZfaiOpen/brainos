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
import asyncio
import functools
import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

logger = logging.getLogger("brainos.observability.auto_log")

T = TypeVar("T")


def logged(
    level: str = "INFO",
    include_args: bool = False,
    include_result: bool = False,
    include_duration: bool = True,
    max_arg_length: int = 200,
    max_result_length: int = 200,
    logger_name: str | None = None,
) -> Callable:
    _logger = logging.getLogger(logger_name) if logger_name else logger
    log_level = getattr(logging, level.upper(), logging.INFO)

    from typing import Any, Callable
    def decorator(func):
            func_name = f"{func.__module__}.{func.__qualname__}"

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                start = time.monotonic()
                parts: list[str] = [func_name]
                if include_args:
                    arg_str = _safe_repr(args[1:] if len(args) > 1 else args, max_arg_length)
                    kwarg_str = _safe_repr(kwargs, max_arg_length)
                    parts.append(f"args={arg_str} kwargs={kwarg_str}")
                _logger.log(log_level, "→ %s", " | ".join(parts))
                try:
                    result = await func(*args, **kwargs)
                    duration = time.monotonic() - start
                    result_parts: list[str] = [func_name]
                    if include_result:
                        result_parts.append(f"result={_safe_repr(result, max_result_length)}")
                    if include_duration:
                        result_parts.append(f"duration={duration:.3f}s")
                    _logger.log(log_level, "← %s ✓", " | ".join(result_parts))
                    return result
                except Exception as _exc:
                    duration = time.monotonic() - start
                    _logger.log(logging.ERROR, "← %s ✗ %s (%.3fs)", func_name, str(_exc)[:100], duration)
                    raise

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                start = time.monotonic()
                parts: list[str] = [func_name]
                if include_args:
                    arg_str = _safe_repr(args[1:] if len(args) > 1 else args, max_arg_length)
                    kwarg_str = _safe_repr(kwargs, max_arg_length)
                    parts.append(f"args={arg_str} kwargs={kwarg_str}")
                _logger.log(log_level, "→ %s", " | ".join(parts))
                try:
                    result = func(*args, **kwargs)
                    duration = time.monotonic() - start
                    result_parts: list[str] = [func_name]
                    if include_result:
                        result_parts.append(f"result={_safe_repr(result, max_result_length)}")
                    if include_duration:
                        result_parts.append(f"duration={duration:.3f}s")
                    _logger.log(log_level, "← %s ✓", " | ".join(result_parts))
                    return result
                except Exception as _exc:
                    duration = time.monotonic() - start
                    _logger.log(logging.ERROR, "← %s ✗ %s (%.3fs)", func_name, str(_exc)[:100], duration)
                    raise

            if asyncio.iscoroutinefunction(func) or hasattr(func, "_is_async"):
                return async_wrapper
            return sync_wrapper

    def _safe_repr(obj, max_len):
        try:
            return repr(obj)[:max_len]
        except Exception as _exc:
            return f"<unreprable {type(obj).__name__}: {str(_exc)[:50]}>"


    return decorator


def audit_logged(
    action: str,
    include_args: bool = True,
    max_arg_length: int = 500,
) -> Callable:
    def decorator(func: Callable) -> Callable:
        func_name = f"{func.__module__}.{func.__qualname__}"

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.monotonic()
            arg_str = ""
            if include_args:
                arg_str = repr(kwargs)[:max_arg_length]
            logger.info("AUDIT ▶ action=%s method=%s args=%s", action, func_name, arg_str)
            try:
                result = await func(*args, **kwargs)
                duration = time.monotonic() - start
                logger.info("AUDIT ◀ action=%s method=%s duration=%.3fs status=success", action, func_name, duration)
                return result
            except Exception as _exc:
                duration = time.monotonic() - start
                logger.warning(
                    "AUDIT ◀ action=%s method=%s duration=%.3fs status=failed error=%s",
                    action,
                    func_name,
                    duration,
                )
                raise

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.monotonic()
            arg_str = ""
            if include_args:
                arg_str = repr(kwargs)[:max_arg_length]
            logger.info("AUDIT ▶ action=%s method=%s args=%s", action, func_name, arg_str)
            try:
                result = func(*args, **kwargs)
                duration = time.monotonic() - start
                logger.info("AUDIT ◀ action=%s method=%s duration=%.3fs status=success", action, func_name, duration)
                return result
            except Exception as _exc:
                duration = time.monotonic() - start
                logger.warning(
                    "AUDIT ◀ action=%s method=%s duration=%.3fs status=failed error=%s",
                    action,
                    func_name,
                    duration,
                )
                raise

        if asyncio.iscoroutinefunction(func) or hasattr(func, "_is_async"):
            return async_wrapper
        return sync_wrapper

    return decorator
