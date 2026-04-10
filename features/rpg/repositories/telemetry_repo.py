import time

import aiosqlite


async def set_cooldown(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_id: int,
    key: str,
    seconds: int,
) -> None:
    ready_at = int(time.time()) + seconds
    await conn.execute(
        """
        INSERT INTO cooldowns(guild_id, user_id, key, ready_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(guild_id, user_id, key)
        DO UPDATE SET ready_at = excluded.ready_at
        """,
        (guild_id, user_id, key, ready_at),
    )


async def cooldown_remain(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_id: int,
    key: str,
) -> int:
    async with conn.execute(
        "SELECT ready_at FROM cooldowns WHERE guild_id = ? AND user_id = ? AND key = ?",
        (guild_id, user_id, key),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return 0
    return max(0, int(row[0]) - int(time.time()))


async def record_gold_flow(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_id: int,
    delta: int,
    source: str,
) -> None:
    amount = int(delta)
    if amount == 0:
        return
    flow_type = "source" if amount > 0 else "sink"
    await conn.execute(
        """
        INSERT INTO rpg_gold_ledger(guild_id, user_id, delta, flow_type, source, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (guild_id, user_id, amount, flow_type, str(source), int(time.time())),
    )


async def record_combat_telemetry(
    conn: aiosqlite.Connection,
    guild_id: int,
    mode: str,
    player_level: int,
    win: bool,
    gold: int = 0,
    xp: int = 0,
    turns: int = 0,
    damage_dealt: int = 0,
    damage_taken: int = 0,
    drop_qty: int = 0,
) -> None:
    lvl = max(1, int(player_level))
    bracket = f"{((lvl - 1) // 10) * 10 + 1}-{(lvl - 1) // 10 * 10 + 10}"
    now = int(time.time())

    await conn.execute(
        """
        INSERT INTO combat_telemetry(
            guild_id, mode, level_bracket,
            wins, losses, total_gold, total_xp,
            total_turns, total_damage_dealt, total_damage_taken, total_drop_qty,
            samples, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        ON CONFLICT(guild_id, mode, level_bracket)
        DO UPDATE SET
            wins = wins + excluded.wins,
            losses = losses + excluded.losses,
            total_gold = total_gold + excluded.total_gold,
            total_xp = total_xp + excluded.total_xp,
            total_turns = total_turns + excluded.total_turns,
            total_damage_dealt = total_damage_dealt + excluded.total_damage_dealt,
            total_damage_taken = total_damage_taken + excluded.total_damage_taken,
            total_drop_qty = total_drop_qty + excluded.total_drop_qty,
            samples = samples + 1,
            updated_at = excluded.updated_at
        """,
        (
            guild_id, str(mode), bracket,
            1 if win else 0, 0 if win else 1,
            max(0, gold), max(0, xp),
            max(0, turns), max(0, damage_dealt), max(0, damage_taken), max(0, drop_qty),
            now,
        ),
    )


async def update_player_streak(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_id: int,
    mode: str,
    win: bool,
) -> tuple[int, int]:
    now = int(time.time())
    async with conn.execute(
        """
        SELECT current_streak, best_streak
        FROM player_combat_streaks
        WHERE guild_id = ? AND user_id = ? AND mode = ?
        """,
        (guild_id, user_id, str(mode)),
    ) as cur:
        row = await cur.fetchone()

    prev_current = int(row[0]) if row else 0
    prev_best = int(row[1]) if row else 0
    current = (prev_current + 1) if bool(win) else 0
    best = max(prev_best, current)

    await conn.execute(
        """
        INSERT INTO player_combat_streaks(
            guild_id, user_id, mode, current_streak, best_streak, last_result_win, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(guild_id, user_id, mode)
        DO UPDATE SET
            current_streak = excluded.current_streak,
            best_streak = excluded.best_streak,
            last_result_win = excluded.last_result_win,
            updated_at = excluded.updated_at
        """,
        (guild_id, user_id, str(mode), current, best, 1 if win else 0, now),
    )
    return current, best


async def record_slime_jackpot(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_id: int,
    gold_bonus: int,
) -> None:
    now = int(time.time())
    await conn.execute(
        """
        INSERT INTO slime_jackpot_stats(
            guild_id, user_id, jackpot_hits, total_jackpot_gold, best_jackpot_gold, last_jackpot_ts
        )
        VALUES (?, ?, 1, ?, ?, ?)
        ON CONFLICT(guild_id, user_id)
        DO UPDATE SET
            jackpot_hits = jackpot_hits + 1,
            total_jackpot_gold = total_jackpot_gold + excluded.total_jackpot_gold,
            best_jackpot_gold = MAX(best_jackpot_gold, excluded.best_jackpot_gold),
            last_jackpot_ts = excluded.last_jackpot_ts
        """,
        (guild_id, user_id, gold_bonus, gold_bonus, now),
    )


async def get_jackpot_stats(conn: aiosqlite.Connection, guild_id: int, user_id: int) -> tuple[int, int, int, int]:
    async with conn.execute(
        """
        SELECT jackpot_hits, total_jackpot_gold, best_jackpot_gold, last_jackpot_ts
        FROM slime_jackpot_stats
        WHERE guild_id = ? AND user_id = ?
        """,
        (guild_id, user_id),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return (0, 0, 0, 0)
    return tuple(int(x or 0) for x in row)


async def consume_lootbox_limit(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_id: int,
    amount: int,
    daily_limit: int,
) -> tuple[bool, int]:
    if amount <= 0:
        return False, 0
    
    import datetime
    now = datetime.datetime.utcnow()
    day_key = now.strftime("%Y-%m-%d")

    async with conn.execute(
        "SELECT opened_count FROM lootbox_daily_limit WHERE guild_id = ? AND user_id = ? AND day_key = ?",
        (guild_id, user_id, day_key),
    ) as cur:
        row = await cur.fetchone()
    opened = int(row[0]) if row else 0
    remain = max(0, daily_limit - opened)
    
    if amount > remain:
        return False, remain

    await conn.execute(
        """
        INSERT INTO lootbox_daily_limit(guild_id, user_id, day_key, opened_count)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(guild_id, user_id, day_key)
        DO UPDATE SET opened_count = opened_count + excluded.opened_count
        """,
        (guild_id, user_id, day_key, amount),
    )
    return True, remain - amount


async def record_monster_kill(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_id: int,
    monster_name: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO monsters_killed(guild_id, user_id, monster_name, kills)
        VALUES (?, ?, ?, 1)
        ON CONFLICT(guild_id, user_id, monster_name)
        DO UPDATE SET kills = kills + 1
        """,
        (guild_id, user_id, monster_name),
    )


async def record_guild_boss_damage(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_id: int,
    boss_id: str,
    damage: int,
    win: bool,
) -> None:
    now = int(time.time())
    dealt = max(0, int(damage))
    await conn.execute(
        """
        INSERT INTO guild_boss_damage(
            guild_id, user_id, boss_id, total_damage, last_damage, battles, wins, updated_at
        )
        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(guild_id, user_id)
        DO UPDATE SET
            boss_id = excluded.boss_id,
            total_damage = total_damage + excluded.total_damage,
            last_damage = excluded.last_damage,
            battles = battles + 1,
            wins = wins + excluded.wins,
            updated_at = excluded.updated_at
        """,
        (guild_id, user_id, str(boss_id or ""), dealt, dealt, 1 if win else 0, now),
    )


async def get_top_guild_boss_damage(
    conn: aiosqlite.Connection,
    guild_id: int,
    limit: int = 10,
) -> list[tuple[int, int, int, int, int]]:
    async with conn.execute(
        """
        SELECT user_id, total_damage, battles, wins, last_damage
        FROM guild_boss_damage
        WHERE guild_id = ?
        ORDER BY total_damage DESC, wins DESC, updated_at ASC
        LIMIT ?
        """,
        (guild_id, max(1, int(limit))),
    ) as cur:
        rows = await cur.fetchall()
    return [
        (int(r[0]), int(r[1]), int(r[2]), int(r[3]), int(r[4]))
        for r in rows
    ]


async def get_guild_boss_summary(conn: aiosqlite.Connection, guild_id: int) -> tuple[int, int]:
    async with conn.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(wins), 0)
        FROM guild_boss_damage
        WHERE guild_id = ?
        """,
        (guild_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return 0, 0
    return int(row[0] or 0), int(row[1] or 0)
