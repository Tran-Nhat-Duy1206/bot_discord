import asyncio
import logging
from contextlib import asynccontextmanager
from collections import defaultdict
from typing import AsyncIterator

import aiosqlite

logger = logging.getLogger("rpg.transaction")

_USER_LOCKS: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

_GUILD_WRITE_LOCK = asyncio.Lock()


def get_user_lock(user_id: int) -> asyncio.Lock:
    return _USER_LOCKS[user_id]


def cleanup_user_lock(user_id: int) -> None:
    lock = _USER_LOCKS.get(user_id)
    if lock is not None and not lock.locked():
        del _USER_LOCKS[user_id]


@asynccontextmanager
async def user_transaction(
    conn: aiosqlite.Connection,
    user_id: int,
    savepoint_name: str = "user_tx",
) -> AsyncIterator[aiosqlite.Connection]:
    async with get_user_lock(user_id):
        try:
            await conn.execute(f"SAVEPOINT {savepoint_name}")
            yield conn
            await conn.execute(f"RELEASE {savepoint_name}")
        except Exception:
            await conn.execute(f"ROLLBACK TO {savepoint_name}")
            await conn.execute(f"RELEASE {savepoint_name}")
            raise


@asynccontextmanager
async def guild_transaction(conn: aiosqlite.Connection) -> AsyncIterator[aiosqlite.Connection]:
    async with _GUILD_WRITE_LOCK:
        try:
            await conn.execute("SAVEPOINT guild_tx")
            yield conn
            await conn.execute("RELEASE guild_tx")
        except Exception:
            await conn.execute("ROLLBACK TO guild_tx")
            await conn.execute("RELEASE guild_tx")
            raise


@asynccontextmanager
async def exclusive_user_transaction(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_id: int,
    savepoint_name: str = "exclusive_tx",
) -> AsyncIterator[aiosqlite.Connection]:
    async with get_user_lock(user_id):
        try:
            await conn.execute(f"SAVEPOINT {savepoint_name}")
            yield conn
            await conn.execute(f"RELEASE {savepoint_name}")
        except Exception:
            await conn.execute(f"ROLLBACK TO {savepoint_name}")
            await conn.execute(f"RELEASE {savepoint_name}")
            raise


async def safe_gold_update(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_id: int,
    delta: int,
    reason: str,
) -> tuple[bool, int]:
    if delta == 0:
        return True, 0

    if delta > 0:
        await conn.execute(
            "UPDATE players SET gold = gold + ? WHERE guild_id = ? AND user_id = ?",
            (delta, guild_id, user_id),
        )
        async with conn.execute(
            "SELECT gold FROM players WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ) as cur:
            row = await cur.fetchone()
        new_balance = int(row[0]) if row else 0
        return True, new_balance

    amount = abs(delta)
    async with conn.execute(
        "SELECT gold FROM players WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    ) as cur:
        row = await cur.fetchone()

    current = int(row[0]) if row else 0
    if current < amount:
        return False, current

    await conn.execute(
        "UPDATE players SET gold = gold - ? WHERE guild_id = ? AND user_id = ?",
        (amount, guild_id, user_id),
    )
    return True, current - amount


async def safe_inventory_update(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_id: int,
    item_id: str,
    delta: int,
) -> tuple[bool, int]:
    if delta == 0:
        return True, 0

    if delta > 0:
        await conn.execute(
            """
            INSERT INTO inventory(guild_id, user_id, item_id, amount)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id, item_id)
            DO UPDATE SET amount = amount + excluded.amount
            """,
            (guild_id, user_id, item_id, delta),
        )
        async with conn.execute(
            "SELECT amount FROM inventory WHERE guild_id = ? AND user_id = ? AND item_id = ?",
            (guild_id, user_id, item_id),
        ) as cur:
            row = await cur.fetchone()
        new_amount = int(row[0]) if row else delta
        return True, new_amount

    amount = abs(delta)
    async with conn.execute(
        "SELECT amount FROM inventory WHERE guild_id = ? AND user_id = ? AND item_id = ?",
        (guild_id, user_id, item_id),
    ) as cur:
        row = await cur.fetchone()

    current = int(row[0]) if row else 0
    if current < amount:
        return False, current

    new_amount = current - amount
    if new_amount == 0:
        await conn.execute(
            "DELETE FROM inventory WHERE guild_id = ? AND user_id = ? AND item_id = ?",
            (guild_id, user_id, item_id),
        )
    else:
        await conn.execute(
            "UPDATE inventory SET amount = ? WHERE guild_id = ? AND user_id = ? AND item_id = ?",
            (new_amount, guild_id, user_id, item_id),
        )
    return True, new_amount
