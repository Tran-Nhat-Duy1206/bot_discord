import time
from typing import Optional

import aiosqlite

from ..data.data import QUEST_DEFINITIONS


async def ensure_default_quests(conn: aiosqlite.Connection, guild_id: int, user_id: int) -> None:
    now = int(time.time())
    for q in QUEST_DEFINITIONS:
        qid = str(q["quest_id"])
        objective = str(q["objective"])
        target = int(q["target"])
        reward_gold = int(q["reward_gold"])
        reward_xp = int(q["reward_xp"])
        period = str(q.get("period", "none"))
        prereq = str(q.get("prereq_quest_id", ""))
        
        if period == "daily":
            reset_after = now + 86400
        elif period == "weekly":
            reset_after = now + 86400 * 7
        else:
            reset_after = 0

        await conn.execute(
            """
            INSERT OR IGNORE INTO quests(
                guild_id, user_id, quest_id, objective, target, progress,
                reward_gold, reward_xp, period, prereq_quest_id, reset_after, claimed, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, 0, ?)
            """,
            (guild_id, user_id, qid, objective, target, reward_gold, reward_xp, period, prereq, reset_after, now),
        )


async def refresh_quests_if_needed(conn: aiosqlite.Connection, guild_id: int, user_id: int) -> None:
    now = int(time.time())
    async with conn.execute(
        "SELECT quest_id, period, reset_after FROM quests WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    ) as cur:
        rows = await cur.fetchall()

    for quest_id, period, reset_after in rows:
        period = str(period or "none")
        ra = int(reset_after or 0)
        if period == "none":
            continue
        if ra > now:
            continue

        if period == "daily":
            new_reset = now + 86400
        elif period == "weekly":
            new_reset = now + 86400 * 7
        else:
            new_reset = 0

        await conn.execute(
            """
            UPDATE quests
            SET progress = 0, claimed = 0, reset_after = ?, updated_at = ?
            WHERE guild_id = ? AND user_id = ? AND quest_id = ?
            """,
            (new_reset, now, guild_id, user_id, quest_id),
        )


async def get_quests(conn: aiosqlite.Connection, guild_id: int, user_id: int) -> list:
    await ensure_default_quests(conn, guild_id, user_id)
    await refresh_quests_if_needed(conn, guild_id, user_id)
    async with conn.execute(
        """
        SELECT quest_id, objective, target, progress, reward_gold, reward_xp, 
               period, reset_after, prereq_quest_id, claimed
        FROM quests
        WHERE guild_id = ? AND user_id = ?
        ORDER BY quest_id ASC
        """,
        (guild_id, user_id),
    ) as cur:
        return await cur.fetchall()


async def get_quest(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_id: int,
    quest_id: str,
) -> Optional[tuple]:
    async with conn.execute(
        """
        SELECT target, progress, reward_gold, reward_xp, prereq_quest_id, claimed
        FROM quests
        WHERE guild_id = ? AND user_id = ? AND quest_id = ?
        """,
        (guild_id, user_id, quest_id),
    ) as cur:
        return await cur.fetchone()


async def add_quest_progress(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_id: int,
    objective: str,
    amount: int = 1,
) -> None:
    if amount <= 0:
        return
    await conn.execute(
        """
        UPDATE quests
        SET progress = progress + ?, updated_at = ?
        WHERE guild_id = ? AND user_id = ? AND objective = ? AND claimed = 0
        """,
        (amount, int(time.time()), guild_id, user_id, objective),
    )


async def claim_quest(conn: aiosqlite.Connection, guild_id: int, user_id: int, quest_id: str) -> bool:
    await conn.execute(
        """
        UPDATE quests SET claimed = 1, updated_at = ?
        WHERE guild_id = ? AND user_id = ? AND quest_id = ?
        """,
        (int(time.time()), guild_id, user_id, quest_id),
    )
    return True
