import time
from typing import Optional

import aiosqlite

from ..db.db import ensure_player, get_player as _get_player, gain_xp_and_level as _gain_xp_and_level


async def ensure_player_ready(conn: aiosqlite.Connection, guild_id: int, user_id: int) -> None:
    await ensure_player(conn, guild_id, user_id)


async def get_player_stats(conn: aiosqlite.Connection, guild_id: int, user_id: int) -> Optional[tuple[int, int, int, int, int, int, int]]:
    await ensure_player(conn, guild_id, user_id)
    row = await _get_player(conn, guild_id, user_id)
    return row


async def get_player_level_gold(conn: aiosqlite.Connection, guild_id: int, user_id: int) -> tuple[int, int]:
    await ensure_player(conn, guild_id, user_id)
    async with conn.execute(
        "SELECT level, gold FROM players WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return 1, 0
    return int(row[0]), int(row[1])


async def update_player_hp(conn: aiosqlite.Connection, guild_id: int, user_id: int, hp: int) -> None:
    await conn.execute(
        "UPDATE players SET hp = ? WHERE guild_id = ? AND user_id = ?",
        (max(1, hp), guild_id, user_id),
    )


async def update_player_hp_gold(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_id: int,
    hp: int,
    gold_delta: int,
) -> None:
    await conn.execute(
        "UPDATE players SET hp = ?, gold = gold + ? WHERE guild_id = ? AND user_id = ?",
        (max(1, hp), gold_delta, guild_id, user_id),
    )


async def add_gold(conn: aiosqlite.Connection, guild_id: int, user_id: int, amount: int) -> None:
    if amount == 0:
        return
    await conn.execute(
        "UPDATE players SET gold = gold + ? WHERE guild_id = ? AND user_id = ?",
        (amount, guild_id, user_id),
    )


async def subtract_gold(conn: aiosqlite.Connection, guild_id: int, user_id: int, amount: int) -> bool:
    if amount <= 0:
        return True
    async with conn.execute(
        "SELECT gold FROM players WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    ) as cur:
        row = await cur.fetchone()
    current = int(row[0]) if row else 0
    if current < amount:
        return False
    await conn.execute(
        "UPDATE players SET gold = gold - ? WHERE guild_id = ? AND user_id = ?",
        (amount, guild_id, user_id),
    )
    return True


async def gain_xp_and_level(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_id: int,
    add_xp: int,
) -> tuple[int, int, bool]:
    return await _gain_xp_and_level(conn, guild_id, user_id, add_xp)


async def get_player_level_and_created(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_id: int,
) -> tuple[int, int]:
    await ensure_player(conn, guild_id, user_id)
    async with conn.execute(
        "SELECT level, created_at FROM players WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return 1, 0
    return int(row[0]), int(row[1])


async def get_equipped_items(conn: aiosqlite.Connection, guild_id: int, user_id: int) -> dict[str, str]:
    async with conn.execute(
        "SELECT slot, item_id FROM equipment WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    ) as cur:
        rows = await cur.fetchall()
    return {str(slot): str(item_id) for slot, item_id in rows}


async def equip_item(conn: aiosqlite.Connection, guild_id: int, user_id: int, slot: str, item_id: str) -> None:
    await conn.execute(
        """
        INSERT INTO equipment(guild_id, user_id, slot, item_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(guild_id, user_id, slot)
        DO UPDATE SET item_id = excluded.item_id
        """,
        (guild_id, user_id, slot, item_id),
    )


async def unequip_item(conn: aiosqlite.Connection, guild_id: int, user_id: int, slot: str) -> Optional[str]:
    async with conn.execute(
        "SELECT item_id FROM equipment WHERE guild_id = ? AND user_id = ? AND slot = ?",
        (guild_id, user_id, slot),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    item_id = str(row[0])
    await conn.execute(
        "DELETE FROM equipment WHERE guild_id = ? AND user_id = ? AND slot = ?",
        (guild_id, user_id, slot),
    )
    return item_id


async def get_unlocked_skills(conn: aiosqlite.Connection, guild_id: int, user_id: int) -> set[str]:
    async with conn.execute(
        "SELECT skill_id FROM player_skills WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    ) as cur:
        rows = await cur.fetchall()
    return {str(skill_id) for (skill_id,) in rows}


async def unlock_skill(conn: aiosqlite.Connection, guild_id: int, user_id: int, skill_id: str) -> bool:
    async with conn.execute(
        "SELECT 1 FROM player_skills WHERE guild_id = ? AND user_id = ? AND skill_id = ?",
        (guild_id, user_id, skill_id),
    ) as cur:
        row = await cur.fetchone()
    if row:
        return False
    await conn.execute(
        "INSERT INTO player_skills(guild_id, user_id, skill_id, unlocked_at) VALUES (?, ?, ?, ?)",
        (guild_id, user_id, skill_id, int(time.time())),
    )
    return True


async def get_leaderboard(conn: aiosqlite.Connection, guild_id: int, limit: int = 10) -> list:
    async with conn.execute(
        """
        SELECT user_id, level, gold, xp
        FROM players
        WHERE guild_id = ?
        ORDER BY level DESC, xp DESC
        LIMIT ?
        """,
        (guild_id, max(1, limit)),
    ) as cur:
        return await cur.fetchall()
