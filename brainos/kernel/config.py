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
from brainos.observability.auto_log import logged
from brainos.kernel.safe_execute import safe_execute

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import ClassVar, Any, Callable

try:
    import yaml
except ImportError:  # optional dependency: YAML config support needs PyYAML
    yaml = None  # type: ignore[assignment]

from brainos.kernel.errors import ConfigError, ConfigNotFoundError


def _require_yaml() -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is required for YAML config support (pip install pyyaml)")

logger = logging.getLogger("brainos.kernel.config")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@logged()
@safe_execute
def atomic_json_write(path: Path, data: Any) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path)


from typing import Any
MAX_JSON_SIZE: int = 10 * 1024 * 1024

@logged()
@safe_execute
def safe_json_read(path):
    if path is None:
        logger.warning("safe_json_read received None path.")
        return {}
    try:
        if not path.is_file():
            logger.warning("safe_json_read: File not found or not a file: %s", str(path))
            return {}

        file_size = path.stat().st_size
        if file_size > MAX_JSON_SIZE:
            logger.error("safe_json_read: File %s exceeds %d bytes limit.", str(path), MAX_JSON_SIZE)
            return {}

        content = path.read_bytes().decode("utf-8").strip()
        if not content:
            return {}

        return json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as _exc:
        logger.warning("safe_json_read: Failed to parse JSON from %s. Error: %s", str(path), _exc)
        return {}
    except Exception as _exc:
        logger.error("safe_json_read: Unexpected error reading %s. Error: %s", str(path), _exc)
        return {}




class RuntimeConfig:
    DEFAULTS: ClassVar[dict[str, Any]] = {
        "zmq_enabled": True,
        "strict_approval": False,
        "ollama_url": "http://localhost:11434",
        "budget_limit": 100.0,
        "max_retries": 3,
        "retry_delay": 1.0,
        "circuit_breaker_threshold": 5,
        "circuit_breaker_recovery": 30.0,
        "event_log_size": 10000,
        "health_check_interval": 300.0,
        "provider_timeout": 30.0,
        "max_concurrent_requests": 10,
        "debug_mode": False,
        "log_level": "INFO",
        "data_dir": "./data",
    }

    def __init__(self, prefix: str = "BRAINOS") -> None:
        self._data: dict[str, Any] = dict(self.DEFAULTS)
        self._watchers: dict[str, list[Callable[[str, Any, Any], None]]] = {}
        self._env_prefix = prefix
        self._env_overrides: dict[str, Any] = {}
        self._file_path: Path | None = None
        self._file_mtime: float = 0.0
        self._polling: bool = False
        self._poll_thread: threading.Thread | None = None
        self._poll_interval: float = 2.0
        self._lock = threading.Lock()

    @logged()
    @safe_execute
    def load_from_yaml(self, path: str | Path) -> None:
        p = Path(path)
        if not p.exists():
            raise ConfigNotFoundError(message=f"Config file not found: {p}", path=str(p))
        _require_yaml()
        try:
            content = p.read_text(encoding="utf-8")
            data = yaml.safe_load(content) or {}
        except yaml.YAMLError as e:
            raise ConfigError(message=f"Invalid YAML in {p}: {e}", key=str(p)) from e
        with self._lock:
            self._data.update(data)
            self._file_path = p
            self._file_mtime = p.stat().st_mtime
        self._notify_all_watchers(data)

    @logged()
    @safe_execute
    def load_from_env(self, prefix: str | None = None) -> dict[str, str]:
        env_prefix = f"{prefix or self._env_prefix}_"
        overrides: dict[str, str] = {}
        for env_key, env_value in os.environ.items():
            if env_key.startswith(env_prefix):
                config_key = env_key[len(env_prefix) :].lower().replace("__", ".")
                parsed = self._parse_env_value(env_value)
                with self._lock:
                    self._data[config_key] = parsed
                    self._env_overrides[config_key] = parsed
                overrides[config_key] = env_value
        return overrides

    @logged()
    @safe_execute
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if key in self._env_overrides:
                return self._env_overrides[key]
            if key in self._data:
                return self._data[key]
        return default

    @logged()
    @safe_execute
    def set(self, key: str, value: Any) -> None:
        old_value: Any
        with self._lock:
            old_value = self._data.get(key)
            self._data[key] = value
        callbacks = self._watchers.get(key, [])
        for cb in callbacks:
            try:
                cb(key, old_value, value)
            except Exception as _exc:
                logger.warning("Config callback error: %s")

    @logged()
    @safe_execute
    def watch(self, key: str, callback: Callable[[str, Any, Any], None]) -> Callable[[], None]:
        if key not in self._watchers:
            self._watchers[key] = []
        self._watchers[key].append(callback)

        @logged()
        @safe_execute
        def unwatch() -> None:
            if key in self._watchers:
                self._watchers[key] = [cb for cb in self._watchers[key] if cb is not callback]

        return unwatch

    @logged()
    @safe_execute
    def unwatch(self, key: str, callback: Callable[[str, Any, Any], None]) -> None:
        if key in self._watchers:
            self._watchers[key] = [cb for cb in self._watchers[key] if cb is not callback]

    @logged()
    @safe_execute
    def start_hot_reload(self, interval: float = 2.0) -> None:
        if self._polling:
            return
        self._polling = True
        self._poll_interval = interval
        self._poll_thread = threading.Thread(target=self._poll_file_changes, daemon=True)
        self._poll_thread.start()
        logger.info(f"Hot reload started, polling every {interval}s")

    @logged()
    @safe_execute
    def stop_hot_reload(self) -> None:
        self._polling = False
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=5.0)
            self._poll_thread = None
        logger.info("Hot reload stopped")

    @logged()
    @safe_execute
    def save_to_yaml(self, path: str | Path | None = None) -> None:
        p = Path(path) if path else self._file_path
        if p is None:
            raise ConfigError(message="No file path specified for save")
        _require_yaml()
        p.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            data = dict(self._data)
        content = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        p.write_text(content, encoding="utf-8")
        self._file_path = p
        self._file_mtime = p.stat().st_mtime

    @logged()
    @safe_execute
    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)

    @logged()
    @safe_execute
    def keys(self) -> list[str]:
        with self._lock:
            return list(self._data.keys())

    @logged()
    @safe_execute
    def has(self, key: str) -> bool:
        with self._lock:
            return key in self._data

    @logged()
    @safe_execute
    def reset(self) -> None:
        with self._lock:
            self._data = dict(self.DEFAULTS)
            self._env_overrides.clear()
        self._notify_all_watchers(self._data)

    def _poll_file_changes(self) -> None:
        while self._polling:
            try:
                if self._file_path and self._file_path.exists():
                    mtime = self._file_path.stat().st_mtime
                    if mtime > self._file_mtime:
                        self._file_mtime = mtime
                        self.load_from_yaml(self._file_path)
                        logger.info("Config reloaded from file change")
            except Exception as e:
                logger.warning(f"Hot reload error: {e}")
            time.sleep(self._poll_interval)

    def _notify_all_watchers(self, data: dict[str, Any]) -> None:
        flat: dict[str, Any] = {}
        self._flatten(data, flat)
        for key, callbacks in self._watchers.items():
            if key in flat:
                for cb in callbacks:
                    try:
                        cb(key, flat[key], flat[key])
                    except Exception as _exc:
                        logger.warning("Config callback error: %s")

    @staticmethod
    def _flatten(d: dict[str, Any], out: dict[str, Any], prefix: str = "") -> None:
        for k, v in d.items():
            full_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                RuntimeConfig._flatten(v, out, full_key)
            else:
                out[full_key] = v

    @staticmethod
    def _parse_env_value(value: str) -> Any:
        if value.lower() in ("true", "1", "yes"):
            return True
        if value.lower() in ("false", "0", "no"):
            return False
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass
        try:
            return json.loads(value)
        except (ValueError, Exception):
            return value
