import time
from dataclasses import dataclass
from typing import Optional

import aiosqlite

from ..db.db import (
    RPG_REST_COOLDOWN, RPG_REST_HP_PERCENT,
    RPG_HP_REGEN_RATE, RPG_HP_REGEN_INTERVAL,
)


@dataclass
class RecoveryStatus:
    can_rest: bool
    rest_remaining: int
    current_hp: int
    max_hp: int
    hp_percent: float
    regen_progress: float
    regen_remaining: int


async def get_recovery_status(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_id: int,
    current_hp: int,
    max_hp: int,
) -> RecoveryStatus:
    now = int(time.time())
    
    async with conn.execute(
        "SELECT rest_ready_at, last_regen_at FROM player_recovery WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    ) as cur:
        row = await cur.fetchone()
    
    if row:
        rest_ready_at = int(row[0]) if row[0] else 0
        last_regen_at = int(row[1]) if row[1] else 0
    else:
        rest_ready_at = 0
        last_regen_at = 0
    
    rest_remaining = max(0, rest_ready_at - now)
    can_rest = rest_remaining == 0
    
    elapsed = now - last_regen_at
    regen_intervals_passed = elapsed // RPG_HP_REGEN_INTERVAL
    regen_amount = int(max_hp * RPG_HP_REGEN_RATE * regen_intervals_passed)
    estimated_hp = min(max_hp, current_hp + regen_amount)
    hp_percent = (estimated_hp / max_hp * 100) if max_hp > 0 else 0
    
    progress_in_interval = elapsed % RPG_HP_REGEN_INTERVAL
    regen_progress = progress_in_interval / RPG_HP_REGEN_INTERVAL
    regen_remaining = RPG_HP_REGEN_INTERVAL - progress_in_interval
    
    return RecoveryStatus(
        can_rest=can_rest,
        rest_remaining=rest_remaining,
        current_hp=estimated_hp,
        max_hp=max_hp,
        hp_percent=hp_percent,
        regen_progress=regen_progress,
        regen_remaining=regen_remaining,
    )


async def use_rest(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_id: int,
    current_hp: int,
    max_hp: int,
) -> tuple[bool, int, int]:
    now = int(time.time())
    
    async with conn.execute(
        "SELECT rest_ready_at FROM player_recovery WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    ) as cur:
        row = await cur.fetchone()
    
    if row and int(row[0]) > now:
        return False, current_hp, int(row[0]) - now
    
    heal_amount = int(max_hp * RPG_REST_HP_PERCENT)
    new_hp = min(max_hp, current_hp + heal_amount)
    
    await conn.execute(
        """
        INSERT INTO player_recovery(guild_id, user_id, rest_ready_at, last_regen_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(guild_id, user_id)
        DO UPDATE SET rest_ready_at = ?, last_regen_at = ?
        """,
        (guild_id, user_id, now + RPG_REST_COOLDOWN, now, now + RPG_REST_COOLDOWN, now),
    )
    
    return True, new_hp, 0


async def update_regen(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_id: int,
) -> Optional[int]:
    now = int(time.time())
    
    async with conn.execute(
        "SELECT last_regen_at FROM player_recovery WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    ) as cur:
        row = await cur.fetchone()
    
    last_regen = int(row[0]) if row and row[0] else 0
    
    if now - last_regen < RPG_HP_REGEN_INTERVAL:
        return None
    
    elapsed = now - last_regen
    intervals = elapsed // RPG_HP_REGEN_INTERVAL
    
    await conn.execute(
        """
        INSERT INTO player_recovery(guild_id, user_id, rest_ready_at, last_regen_at)
        VALUES (?, ?, 0, ?)
        ON CONFLICT(guild_id, user_id)
        DO UPDATE SET last_regen_at = ?
        """,
        (guild_id, user_id, now, now),
    )
    
    return int(intervals)


async def get_hp_regen_amount(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_id: int,
    max_hp: int,
) -> int:
    intervals = await update_regen(conn, guild_id, user_id)
    if intervals is None:
        return 0
    return int(max_hp * RPG_HP_REGEN_RATE * intervals)


def format_recovery_status(status: RecoveryStatus) -> str:
    hp_bar_length = 10
    filled = int(status.hp_percent / 100 * hp_bar_length)
    empty = hp_bar_length - filled
    hp_bar = "█" * filled + "░" * empty
    
    lines = [
        f"**HP:** {status.current_hp}/{status.max_hp} {hp_bar}",
        f"**HP:** {status.hp_percent:.0f}%",
    ]
    
    if status.rest_remaining > 0:
        m, s = divmod(status.rest_remaining, 60)
        lines.append(f"⏱️ Rest cooldown: {m}m {s}s")
    else:
        lines.append("✅ /rest ready!")
    
    regen_m, regen_s = divmod(status.regen_remaining, 60)
    lines.append(f"🔄 Regen: +{RPG_HP_REGEN_RATE*100:.0f}% HP every {RPG_HP_REGEN_INTERVAL}s ({regen_m}m {regen_s}s)")
    
    return "\n".join(lines)
