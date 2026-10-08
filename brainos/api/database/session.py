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
from collections.abc import AsyncGenerator, Generator

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from brainos.api.database.engine import get_async_session_factory, get_sync_session_factory


from typing import Generator
import logging
def get_session():
    """同步数据库会话上下文生成器 (生命周期状态机)"""
    logger = logging.getLogger(__name__)
    factory = get_sync_session_factory()

    if factory is None:
        logger.error("get_session: Session factory is None. Cannot create session.")
        return

    session = None
    try:
        session = factory()
        if session is None:
            logger.error("get_session: Factory returned None session.")
            return

        yield session

        try:
            session.commit()
        except Exception as commit_exc:
            logger.error(
                "get_session: Commit failed. Triggering rollback. Error: %s",
                commit_exc,
                exc_info=False
            )
            try:
                session.rollback()
            except Exception as rb_exc:
                logger.warning("get_session: Rollback after commit fail also failed: %s", rb_exc)
            raise

    except Exception as _exc:
        logger.warning(
            "get_session: Session context aborted due to exception: %s",
            _exc,
            exc_info=False
        )
        if session is not None:
            try:
                session.rollback()
            except Exception as rb_exc:
                logger.warning(
                    "get_session: Rollback failed during exception handling: %s",
                    rb_exc
                )
        raise

    finally:
        if session is not None:
            try:
                session.close()
            except Exception as close_exc:
                logger.warning(
                    "get_session: Session close failed (potential connection leak): %s",
                    close_exc
                )



from typing import AsyncGenerator
async def get_async_session():
    """异步数据库会话上下文生成器 (生命周期状态机+降级保护)"""
    logger = logging.getLogger(__name__)
    factory = get_async_session_factory()

    if factory is None:
        logger.error(
            "get_async_session: Async session factory is None. Cannot create session."
        )
        return

    session = None
    try:
        session = factory()
        if session is None:
            logger.error("get_async_session: Factory returned None session.")
            return

        yield session

        try:
            await session.commit()
        except Exception as commit_exc:
            logger.error(
                "get_async_session: Commit failed. Triggering rollback. Error: %s",
                commit_exc,
                exc_info=False
            )
            try:
                await session.rollback()
            except Exception as rb_exc:
                logger.warning(
                    "get_async_session: Rollback after commit fail also failed: %s",
                    rb_exc
                )
            raise

    except Exception as _exc:
        logger.warning(
            "get_async_session: Session context aborted due to exception: %s",
            _exc,
            exc_info=False
        )
        if session is not None:
            try:
                await session.rollback()
            except Exception as rb_exc:
                logger.warning(
                    "get_async_session: Rollback failed during exception handling: %s",
                    rb_exc
                )
        raise

    finally:
        if session is not None:
            try:
                await session.close()
            except Exception as close_exc:
                logger.warning(
                    "get_async_session: Session close failed (potential connection leak): %s",
                    close_exc
                )

