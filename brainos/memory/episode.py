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
import json
import logging
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from brainos.kernel.safe_execute import safe_execute
from brainos.observability.auto_log import logged

logger = logging.getLogger("brainos.memory.episode")


@dataclass
class Episode:
    episode_id: str = ""
    timestamp: float = 0.0
    events: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.episode_id:
            self.episode_id = f"ep_{uuid.uuid4().hex[:12]}"
        if not self.timestamp:
            self.timestamp = time.time()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        pass



class EpisodeStore:
    def __init__(self, db_path: str = "knowledge/episodes.db") -> None:
        self._db_path = db_path
        self._initialized = False
        self._init_db()

    def _init_db(self) -> None:
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute("CREATE TABLE IF NOT EXISTS episodes (episode_id TEXT PRIMARY KEY,timestamp REAL NOT NULL,events_json TEXT NOT NULL,metadata_json TEXT NOT NULL,tags_json TEXT NOT NULL)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_timestamp ON episodes(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_tags ON episodes(tags_json)")
            conn.commit()
            conn.close()
            self._initialized = True
        except Exception as exc:
            logger.warning("EpisodeStore init failed: %s", exc)
            self._initialized = False

    @logged()
    @safe_execute
    def append(self, episode: Episode) -> bool:
        if not self._initialized:
            self._init_db()
            if not self._initialized:
                return False
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                "INSERT OR REPLACE INTO episodes (episode_id, timestamp, events_json, metadata_json, tags_json) VALUES (?, ?, ?, ?, ?)",
                (
                    episode.episode_id,
                    episode.timestamp,
                    json.dumps(episode.events, default=str),
                    json.dumps(episode.metadata, default=str),
                    json.dumps(episode.tags),
                ),
            )
            conn.commit()
            conn.close()
            return True
        except Exception as exc:
            logger.warning("EpisodeStore append failed: %s", exc)
            return False

    @logged()
    @safe_execute
    def query(self, since: float = 0, tags: list[str] | None = None, limit: int = 100) -> list[Episode]:
        if not self._initialized:
            self._init_db()
            if not self._initialized:
                return []
        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            sql = "SELECT * FROM episodes WHERE timestamp >= ?"
            params: list[Any] = [since]
            if tags:
                for tag in tags:
                    sql += " AND tags_json LIKE ?"
                    params.append(f'%"{tag}"%')
            sql += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            conn.close()
            return [self._row_to_episode(row) for row in rows]
        except Exception as exc:
            logger.warning("EpisodeStore query failed: %s", exc)
            return []

    @logged()
    @safe_execute
    def get_episode(self, episode_id: str) -> Episode | None:
        if not self._initialized:
            self._init_db()
            if not self._initialized:
                return None
        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM episodes WHERE episode_id = ?", (episode_id,)).fetchone()
            conn.close()
            if row is None:
                return None
            return self._row_to_episode(row)
        except Exception as exc:
            logger.warning("EpisodeStore get_episode failed: %s", exc)
            return None

    @logged()
    @safe_execute
    def get_stats(self) -> dict[str, Any]:
        if not self._initialized:
            self._init_db()
            if not self._initialized:
                return {"total_episodes": 0, "total_events": 0, "oldest_episode_age": 0, "initialized": False}
        try:
            conn = sqlite3.connect(self._db_path)
            total = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
            oldest_ts = conn.execute("SELECT MIN(timestamp) FROM episodes").fetchone()[0]
            conn.close()
            oldest_age = (time.time() - oldest_ts) if oldest_ts else 0
            return {
                "total_episodes": total,
                "total_events": total,
                "oldest_episode_age": round(oldest_age, 2),
                "initialized": True,
            }
        except Exception as exc:
            logger.warning("EpisodeStore get_stats failed: %s", exc)
            return {"total_episodes": 0, "total_events": 0, "oldest_episode_age": 0, "initialized": False}

    def store(self, key: str, value: Any) -> bool:
        ep = Episode(episode_id=key, timestamp=time.time(), events=[value] if not isinstance(value, list) else value, metadata={}, tags=[])
        return self.append(ep)

    def retrieve(self, key: str) -> Any:
        if not self._initialized:
            self._init_db()
            if not self._initialized:
                return None
        try:
            conn = sqlite3.connect(self._db_path)
            row = conn.execute("SELECT * FROM episodes WHERE episode_id = ?", (key,)).fetchone()
            conn.close()
            if row:
                return self._row_to_episode(row)
            return None
        except Exception as _exc:
            return None

    @staticmethod
    def _row_to_episode(row: sqlite3.Row) -> Episode:
        return Episode(
            episode_id=row["episode_id"],
            timestamp=row["timestamp"],
            events=json.loads(row["events_json"]),
            metadata=json.loads(row["metadata_json"]),
            tags=json.loads(row["tags_json"]),
        )
