import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import aiosqlite

from ..db.db import DB_WRITE_LOCK, open_db as _open_db, ensure_db_ready


class ConcurrentUserLock:
    _locks: dict[int, asyncio.Lock] = {}
    _meta_lock = asyncio.Lock()

    @classmethod
    async def get_user_lock(cls, user_id: int) -> asyncio.Lock:
        async with cls._meta_lock:
            if user_id not in cls._locks:
                cls._locks[user_id] = asyncio.Lock()
            return cls._locks[user_id]


@asynccontextmanager
async def user_transaction(
    guild_id: int,
    user_id: int,
    action: str,
) -> AsyncGenerator[aiosqlite.Connection, None]:
    await ensure_db_ready()
    user_lock = await ConcurrentUserLock.get_user_lock(user_id)

    async with user_lock:
        async with _open_db() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                await conn.commit()
            except:
                await conn.rollback()
                raise


@asynccontextmanager
async def user_transaction_with_lock(
    guild_id: int,
    user_id: int,
    action: str,
) -> AsyncGenerator[aiosqlite.Connection, None]:
    await ensure_db_ready()
    user_lock = await ConcurrentUserLock.get_user_lock(user_id)

    async with user_lock:
        async with DB_WRITE_LOCK:
            async with _open_db() as conn:
                await conn.execute("BEGIN IMMEDIATE")
                try:
                    yield conn
                    await conn.commit()
                except:
                    await conn.rollback()
                    raise


@asynccontextmanager
async def multi_user_transaction(
    guild_id: int,
    user_ids: list[int],
    action: str,
) -> AsyncGenerator[aiosqlite.Connection, None]:
    await ensure_db_ready()
    sorted_ids = sorted(set(user_ids))
    locks = [await ConcurrentUserLock.get_user_lock(uid) for uid in sorted_ids]

    async with asyncio.TaskGroup() as tg:
        for lock in locks:
            tg.create_task(lock.acquire())
        try:
            pass
        except:
            for lock in locks:
                lock.release()
            raise

    try:
        async with DB_WRITE_LOCK:
            async with _open_db() as conn:
                await conn.execute("BEGIN IMMEDIATE")
                try:
                    yield conn
                    await conn.commit()
                except:
                    await conn.rollback()
                    raise
    finally:
        for lock in locks:
            try:
                lock.release()
            except:
                pass


class BaseService:
    @staticmethod
    def with_user_transaction(
        guild_id: int,
        user_id: int,
        action: str,
    ):
        return user_transaction_with_lock(guild_id, user_id, action)

    @staticmethod
    def with_multi_user_transaction(
        guild_id: int,
        user_ids: list[int],
        action: str,
    ):
        return multi_user_transaction(guild_id, user_ids, action)
