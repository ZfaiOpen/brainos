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
from brainos.kernel.config import PROJECT_ROOT
import hashlib
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from brainos.kernel.auto_log import logged
from brainos.kernel.safe_execute import safe_execute
from brainos.memory.types import MemoryEntry, MemorySearchResult, MemoryTier, MemoryType

logger = logging.getLogger("brainos.memory.persistence")


class MemoryPersistence:
    def __init__(self, db_path: str = str(PROJECT_ROOT / "data/memory.db")) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self) -> None:
        conn = self._conn
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                tier TEXT NOT NULL DEFAULT 'warm',
                tags TEXT DEFAULT '[]',
                metadata TEXT DEFAULT '{}',
                created_at REAL NOT NULL,
                accessed_at REAL NOT NULL,
                access_count INTEGER DEFAULT 0,
                relevance_score REAL DEFAULT 0.5,
                source TEXT DEFAULT '',
                project TEXT DEFAULT '',
                content_hash TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_type ON memories(memory_type)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tier ON memories(tier)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_project ON memories(project)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_accessed ON memories(accessed_at)
        """)
        conn.commit()

    @logged()
    @safe_execute
    def store(self, entry: MemoryEntry) -> str:
        content_hash = hashlib.sha256(entry.content.encode()).hexdigest()[:16]
        existing = self._conn.execute("SELECT id FROM memories WHERE content_hash = ?", (content_hash,)).fetchone()
        if existing:
            self._conn.execute(
                "UPDATE memories SET access_count = access_count + 1, accessed_at = ? WHERE id = ?",
                (time.time(), existing[0]),
            )
            self._conn.commit()
            return existing[0]

        self._conn.execute(
            """
            INSERT OR REPLACE INTO memories (id, content, memory_type, tier, tags, metadata,
                created_at, accessed_at, access_count, relevance_score, source, project, content_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                entry.id,
                entry.content,
                entry.memory_type.value,
                entry.tier.value,
                json.dumps(entry.tags),
                json.dumps(entry.metadata),
                entry.created_at,
                entry.accessed_at,
                entry.access_count,
                entry.relevance_score,
                entry.source,
                entry.project,
                content_hash,
            ),
        )
        self._conn.commit()
        return entry.id

    @logged()
    @safe_execute
    def retrieve(self, entry_id: str) -> MemoryEntry | None:
        row = self._conn.execute("SELECT * FROM memories WHERE id = ?", (entry_id,)).fetchone()
        if not row:
            return None
        self._conn.execute(
            "UPDATE memories SET access_count = access_count + 1, accessed_at = ? WHERE id = ?",
            (time.time(), entry_id),
        )
        self._conn.commit()
        return self._row_to_entry(row)

    @logged()
    @safe_execute
    def search(self, query: str, limit: int = 10, memory_type: MemoryType | None = None, project: str | None = None, tier: MemoryTier | None = None) -> list[MemorySearchResult]:
        conditions: list[str] = []
        params: list[Any] = []

        if memory_type:
            conditions.append("memory_type = ?")
            params.append(memory_type.value)
        if project:
            conditions.append("project = ?")
            params.append(project)
        if tier:
            conditions.append("tier = ?")
            params.append(tier.value)

        query_terms = query.lower().split()
        content_conditions = " OR ".join(["content LIKE ?" for _ in query_terms])
        tag_conditions = " OR ".join(["tags LIKE ?" for _ in query_terms])
        full_text_condition = f"({content_conditions} OR {tag_conditions})"

        where = " AND ".join(conditions + [full_text_condition]) if conditions else full_text_condition
        for term in query_terms:
            params.append(f"%{term}%")
        for term in query_terms:
            params.append(f"%{term}%")

        sql = f"SELECT * FROM memories WHERE {where} ORDER BY relevance_score DESC, accessed_at DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(sql, params).fetchall()
        results: list[MemorySearchResult] = []
        for row in rows:
            entry = self._row_to_entry(row)
            score = self._compute_relevance(query, entry)
            results.append(MemorySearchResult(entry=entry, score=score, match_reason=f"keyword match for '{query}'"))
        return sorted(results, key=lambda r: r.score, reverse=True)

    @logged()
    @safe_execute
    def search_by_type(self, memory_type: MemoryType, limit: int = 20, project: str | None = None) -> list[MemoryEntry]:
        conditions = ["memory_type = ?"]
        params: list[Any] = [memory_type.value]
        if project:
            conditions.append("project = ?")
            params.append(project)
        sql = f"SELECT * FROM memories WHERE {' AND '.join(conditions)} ORDER BY accessed_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_entry(r) for r in rows]

    @logged()
    @safe_execute
    def promote(self, entry_id: str) -> bool:
        entry = self.retrieve(entry_id)
        if not entry:
            return False
        tier_order = {MemoryTier.COLD: MemoryTier.WARM, MemoryTier.WARM: MemoryTier.HOT, MemoryTier.HOT: MemoryTier.CRITICAL}
        new_tier = tier_order.get(entry.tier)
        if new_tier:
            self._conn.execute("UPDATE memories SET tier = ? WHERE id = ?", (new_tier.value, entry_id))
            self._conn.commit()
            return True
        return False

    @logged()
    @safe_execute
    def demote(self, entry_id: str) -> bool:
        entry = self.retrieve(entry_id)
        if not entry:
            return False
        tier_order = {MemoryTier.CRITICAL: MemoryTier.HOT, MemoryTier.HOT: MemoryTier.WARM, MemoryTier.WARM: MemoryTier.COLD, MemoryTier.COLD: MemoryTier.ARCHIVE}
        new_tier = tier_order.get(entry.tier)
        if new_tier:
            self._conn.execute("UPDATE memories SET tier = ? WHERE id = ?", (new_tier.value, entry_id))
            self._conn.commit()
            return True
        return False

    @logged()
    @safe_execute
    def auto_tier(self) -> dict[str, int]:
        now = time.time()
        day = 86400.0
        stats = {"promoted": 0, "demoted": 0, "deleted": 0, "archived": 0}

        critical_candidates = self._conn.execute(
            "SELECT id, access_count, accessed_at FROM memories WHERE tier = 'hot' AND access_count >= 20 AND accessed_at > ?",
            (now - 3 * day,),
        ).fetchall()
        for row in critical_candidates:
            self.promote(row[0])
            stats["promoted"] += 1

        hot_candidates = self._conn.execute(
            "SELECT id, access_count, accessed_at FROM memories WHERE tier = 'warm' AND access_count >= 5 AND accessed_at > ?",
            (now - 7 * day,),
        ).fetchall()
        for row in hot_candidates:
            self.promote(row[0])
            stats["promoted"] += 1

        cold_candidates = self._conn.execute(
            "SELECT id, accessed_at FROM memories WHERE tier = 'warm' AND accessed_at < ?",
            (now - 30 * day,),
        ).fetchall()
        for row in cold_candidates:
            self.demote(row[0])
            stats["demoted"] += 1

        archive_candidates = self._conn.execute(
            "SELECT id, accessed_at FROM memories WHERE tier = 'cold' AND accessed_at < ?",
            (now - 90 * day,),
        ).fetchall()
        for row in archive_candidates:
            self.demote(row[0])
            stats["archived"] += 1

        stale = self._conn.execute(
            "SELECT id FROM memories WHERE tier = 'archive' AND accessed_at < ?",
            (now - 365 * day,),
        ).fetchall()
        for row in stale:
            self._conn.execute("DELETE FROM memories WHERE id = ?", (row[0],))
            stats["deleted"] += 1

        self._conn.commit()
        return stats

    @logged()
    @safe_execute
    def get_stats(self) -> dict[str, Any]:
        total = self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        by_type = dict(self._conn.execute("SELECT memory_type, COUNT(*) FROM memories GROUP BY memory_type").fetchall())
        by_tier = dict(self._conn.execute("SELECT tier, COUNT(*) FROM memories GROUP BY tier").fetchall())
        by_project = dict(self._conn.execute("SELECT project, COUNT(*) FROM memories GROUP BY project").fetchall())
        return {
            "total_entries": total,
            "by_type": by_type,
            "by_tier": by_tier,
            "by_project": by_project,
            "db_path": str(self._db_path),
        }

    def _row_to_entry(self, row: tuple) -> MemoryEntry:
        return MemoryEntry(
            id=row[0],
            content=row[1],
            memory_type=MemoryType(row[2]),
            tier=MemoryTier(row[3]),
            tags=json.loads(row[4]),
            metadata=json.loads(row[5]),
            created_at=row[6],
            accessed_at=row[7],
            access_count=row[8],
            relevance_score=row[9],
            source=row[10],
            project=row[11],
        )

    def _compute_relevance(self, query: str, entry: MemoryEntry) -> float:
        query_lower = query.lower()
        terms = query_lower.split()
        content_lower = entry.content.lower()
        tag_text = " ".join(entry.tags).lower()

        term_hits = sum(1 for t in terms if t in content_lower or t in tag_text)
        term_score = term_hits / max(len(terms), 1)

        recency = max(0, 1.0 - (time.time() - entry.accessed_at) / (30 * 86400))
        frequency = min(entry.access_count / 10.0, 1.0)

        return term_score * 0.6 + recency * 0.2 + frequency * 0.2

    def close(self):
            """安全关闭数据库连接，确保事务提交与资源释放。

            采用防御性编程，处理异常状态、并发冲突，并保证关闭操作的绝对幂等性。
            时间复杂度: O(1), 空间复杂度: O(1)
            """
            # 1. 幂等性守卫:防止重复关闭引发的异常
            if getattr(self, '_closed', False):
                return
            self._closed = True

            _local = getattr(self, '_local', None)
            if _local is None:
                return

            conn = getattr(_local, 'conn', None)
            if conn is None:
                return

            # 2. 并发死锁守卫:非阻塞获取锁,防止并发关闭造成死锁
            _lock = getattr(self, '_lock', None)
            _lock_acquired = False
            if _lock is not None and hasattr(_lock, 'acquire'):
                try:
                    _lock_acquired = _lock.acquire(timeout=0.1)
                    if not _lock_acquired:
                        logger.warning("Memory close: Lock acquisition timed out. Proceeding with teardown unsynchronized.")
                except Exception as _exc_lock:
                    logger.warning("Memory close: Failed to acquire lock safely: %s", _exc_lock)

            try:
                # 3. 尽力提交未完成的事务 (Weibull衰减对账等异步任务可能刚写入)
                try:
                    if hasattr(conn, 'commit'):
                        conn.commit()
                except Exception as _exc_commit:
                    logger.warning(
                        "Memory close: Failed to commit pending transaction (potential data loss): %s", 
                        _exc_commit
                    )

                # 4. 释放数据库连接
                try:
                    if hasattr(conn, 'close'):
                        conn.close()
                except Exception as _exc_close:
                    logger.warning("Memory close: Failed to close sqlite connection safely: %s", _exc_close)

                # 5. 清理引用,防止内存泄漏与 GC 悬挂
                _local.conn = None
                if hasattr(_local, 'cursor') and _local.cursor is not None:
                    _local.cursor = None

            except Exception as _exc:
                logger.error(
                    "Memory close: Unexpected error during connection teardown: %s", 
                    _exc, 
                    exc_info=True
                )
                # 强制兜底置空
                _local.conn = None
            finally:
                # 6. 严谨的锁释放逻辑
                if _lock_acquired and _lock is not None and hasattr(_lock, 'release'):
                    try:
                        _lock.release()
                    except Exception as _exc_release:
                        # 捕获过度释放异常,原代码此处违反了零裸异常铁律
                        logger.debug(
                            "Memory close: Lock release failed (possibly already released): %s", 
                            _exc_release
                        )



    def _try_commit(self, conn):
            try:
                if hasattr(conn, 'commit'):
                    conn.commit()
            except Exception as _exc_commit:
                # 如果是 "no transaction is active" 或底层损坏,记录但不中断关闭流程
                logger.warning(
                    "Memory close: Failed to commit pending transaction (data might be lost): %s",
                    _exc_commit
                )
            # 清理可能的缓存游标
            _local = getattr(self, '_local', None)
            if _local is not None and hasattr(_local, 'cursor') and _local.cursor is not None:
                _local.cursor = None
            try:
                if hasattr(conn, 'close'):
                    conn.close()
            except Exception as _exc_close:
                logger.warning(
                    "Memory close: Failed to close sqlite connection safely: %s",
                    _exc_close
                )
            finally:
                # 无论 close() 是否抛出异常,必须切断引用防止 GC 悬挂
                if _local is not None:
                    _local.conn = None