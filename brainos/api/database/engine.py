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
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from brainos.kernel.config import PROJECT_ROOT

_async_engine: AsyncEngine | None = None


def get_async_database_url() -> str:
    return f"sqlite+aiosqlite:///{PROJECT_ROOT}/data/brainos.db"


def get_async_engine() -> AsyncEngine:
    global _async_engine
    if _async_engine is None:
        _async_engine = create_async_engine(get_async_database_url(), echo=False)
    return _async_engine


def get_database_url() -> str:
    return f"sqlite:///{PROJECT_ROOT}/data/brainos.db"


def get_sync_engine():
    from sqlalchemy import create_engine as _create_engine

    return _create_engine(get_database_url(), echo=False)


def get_sync_session_factory():
    from sqlalchemy import create_engine as _create_engine

    sync_url = f"sqlite:///{PROJECT_ROOT}/data/brainos.db"
    engine = _create_engine(sync_url, echo=False)
    return sessionmaker(bind=engine, class_=Session)


def get_async_session_factory():
    from sqlalchemy.ext.asyncio import async_sessionmaker

    return async_sessionmaker(get_async_engine(), class_=AsyncSession, expire_on_commit=False)


def close_async_engine() -> None:
    global _async_engine
    if _async_engine is not None:
        _async_engine.dispose()
        _async_engine = None
