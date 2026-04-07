from typing import Optional

import aiosqlite

from ..cache import INVENTORY_CACHE, invalidate_inventory


async def add_inventory(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_id: int,
    item_id: str,
    amount: int,
) -> None:
    if amount <= 0:
        return
    await conn.execute(
        """
        INSERT INTO inventory(guild_id, user_id, item_id, amount)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(guild_id, user_id, item_id)
        DO UPDATE SET amount = amount + excluded.amount
        """,
        (guild_id, user_id, item_id, amount),
    )
    await invalidate_inventory(guild_id, user_id)


async def remove_inventory(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_id: int,
    item_id: str,
    amount: int,
) -> bool:
    if amount <= 0:
        return False
    async with conn.execute(
        "SELECT amount FROM inventory WHERE guild_id = ? AND user_id = ? AND item_id = ?",
        (guild_id, user_id, item_id),
    ) as cur:
        row = await cur.fetchone()
    cur_amount = int(row[0]) if row else 0
    if cur_amount < amount:
        return False
    remain = cur_amount - amount
    if remain == 0:
        await conn.execute(
            "DELETE FROM inventory WHERE guild_id = ? AND user_id = ? AND item_id = ?",
            (guild_id, user_id, item_id),
        )
    else:
        await conn.execute(
            "UPDATE inventory SET amount = ? WHERE guild_id = ? AND user_id = ? AND item_id = ?",
            (remain, guild_id, user_id, item_id),
        )
    await invalidate_inventory(guild_id, user_id)
    return True


async def get_inventory(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_id: int,
) -> list[tuple[str, int]]:
    cached = await INVENTORY_CACHE.get(guild_id, user_id)
    if cached is not None:
        return cached
    
    async with conn.execute(
        """
        SELECT item_id, amount
        FROM inventory
        WHERE guild_id = ? AND user_id = ? AND amount > 0
        ORDER BY amount DESC, item_id ASC
        """,
        (guild_id, user_id),
    ) as cur:
        rows = await cur.fetchall()
    result = [(str(item_id), int(amount)) for item_id, amount in rows]
    await INVENTORY_CACHE.set(result, guild_id, user_id)
    return result


async def get_item_count(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_id: int,
    item_id: str,
) -> int:
    async with conn.execute(
        "SELECT amount FROM inventory WHERE guild_id = ? AND user_id = ? AND item_id = ?",
        (guild_id, user_id, item_id),
    ) as cur:
        row = await cur.fetchone()
    return int(row[0]) if row else 0


async def clear_inventory_slot(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_id: int,
    item_id: str,
) -> None:
    await conn.execute(
        "DELETE FROM inventory WHERE guild_id = ? AND user_id = ? AND item_id = ?",
        (guild_id, user_id, item_id),
    )
    await invalidate_inventory(guild_id, user_id)


async def get_inventory_batch(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_ids: list[int],
) -> dict[int, list[tuple[str, int]]]:
    if not user_ids:
        return {}
    
    placeholders = ", ".join("?" * len(user_ids))
    async with conn.execute(
        f"""
        SELECT user_id, item_id, amount
        FROM inventory
        WHERE guild_id = ? AND user_id IN ({placeholders}) AND amount > 0
        ORDER BY user_id, amount DESC, item_id ASC
        """,
        (guild_id, *user_ids),
    ) as cur:
        rows = await cur.fetchall()
    
    result: dict[int, list[tuple[str, int]]] = {uid: [] for uid in user_ids}
    for row in rows:
        uid = int(row[0])
        result[uid].append((str(row[1]), int(row[2])))
    return result
