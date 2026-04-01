import os
import time
import asyncio

import aiosqlite

from .data import QUEST_DEFINITIONS, xp_need_for_next


DB_PATH = os.getenv("RPG_DB", "data/rpg.db")
RPG_HUNT_COOLDOWN = int(os.getenv("RPG_HUNT_COOLDOWN", "45"))
RPG_DAILY_COOLDOWN = int(os.getenv("RPG_DAILY_COOLDOWN", "86400"))
RPG_DAILY_GOLD = int(os.getenv("RPG_DAILY_GOLD", "120"))
RPG_BOSS_COOLDOWN = int(os.getenv("RPG_BOSS_COOLDOWN", "1800"))
RPG_DUNGEON_COOLDOWN = int(os.getenv("RPG_DUNGEON_COOLDOWN", "3600"))
RPG_PARTY_HUNT_COOLDOWN = int(os.getenv("RPG_PARTY_HUNT_COOLDOWN", "1200"))
RPG_LOOTBOX_DAILY_LIMIT = int(os.getenv("RPG_LOOTBOX_DAILY_LIMIT", "25"))
RPG_PAY_MIN_LEVEL = int(os.getenv("RPG_PAY_MIN_LEVEL", "5"))
RPG_PAY_MIN_ACCOUNT_AGE_SECS = int(os.getenv("RPG_PAY_MIN_ACCOUNT_AGE_SECS", "259200"))
RPG_PAY_DAILY_SEND_LIMIT = int(os.getenv("RPG_PAY_DAILY_SEND_LIMIT", "5000"))
RPG_PAY_DAILY_PAIR_LIMIT = int(os.getenv("RPG_PAY_DAILY_PAIR_LIMIT", "2000"))

DB_WRITE_LOCK = asyncio.Lock()
_DB_READY = False
_DB_INIT_LOCK = asyncio.Lock()


def open_db():
    return aiosqlite.connect(DB_PATH, timeout=30)


def fmt_secs(secs: int) -> str:
    h, rem = divmod(max(0, int(secs)), 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def _ensure_db_dir():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)


async def _db_init():
    _ensure_db_dir()
    async with open_db() as conn:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute("PRAGMA busy_timeout=5000")

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS players (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                level INTEGER NOT NULL DEFAULT 1,
                xp INTEGER NOT NULL DEFAULT 0,
                hp INTEGER NOT NULL DEFAULT 100,
                max_hp INTEGER NOT NULL DEFAULT 100,
                attack INTEGER NOT NULL DEFAULT 12,
                defense INTEGER NOT NULL DEFAULT 6,
                gold INTEGER NOT NULL DEFAULT 150,
                created_at INTEGER NOT NULL,
                PRIMARY KEY(guild_id, user_id)
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS inventory (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                item_id TEXT NOT NULL,
                amount INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(guild_id, user_id, item_id)
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS quests (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                quest_id TEXT NOT NULL,
                objective TEXT NOT NULL,
                target INTEGER NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                reward_gold INTEGER NOT NULL,
                reward_xp INTEGER NOT NULL,
                period TEXT NOT NULL DEFAULT 'none',
                prereq_quest_id TEXT NOT NULL DEFAULT '',
                reset_after INTEGER NOT NULL DEFAULT 0,
                claimed INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY(guild_id, user_id, quest_id)
            )
            """
        )
        try:
            await conn.execute("ALTER TABLE quests ADD COLUMN period TEXT NOT NULL DEFAULT 'none'")
        except Exception:
            pass
        try:
            await conn.execute("ALTER TABLE quests ADD COLUMN reset_after INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass
        try:
            await conn.execute("ALTER TABLE quests ADD COLUMN prereq_quest_id TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS equipment (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                slot TEXT NOT NULL,
                item_id TEXT NOT NULL,
                PRIMARY KEY(guild_id, user_id, slot)
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS monsters_killed (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                monster_name TEXT NOT NULL,
                kills INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(guild_id, user_id, monster_name)
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cooldowns (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                ready_at INTEGER NOT NULL,
                PRIMARY KEY(guild_id, user_id, key)
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS slime_jackpot_stats (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                jackpot_hits INTEGER NOT NULL DEFAULT 0,
                total_jackpot_gold INTEGER NOT NULL DEFAULT 0,
                best_jackpot_gold INTEGER NOT NULL DEFAULT 0,
                last_jackpot_ts INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(guild_id, user_id)
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lootbox_daily_limit (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                day_key TEXT NOT NULL,
                opened_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(guild_id, user_id, day_key)
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS player_skills (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                skill_id TEXT NOT NULL,
                unlocked_at INTEGER NOT NULL,
                PRIMARY KEY(guild_id, user_id, skill_id)
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rpg_transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                sender_user_id INTEGER NOT NULL,
                receiver_user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rpg_gold_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                delta INTEGER NOT NULL,
                flow_type TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rpg_seasons (
                season_id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_ts INTEGER NOT NULL,
                end_ts INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                note TEXT NOT NULL DEFAULT ''
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rpg_season_rewards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                season_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                rank INTEGER NOT NULL,
                score INTEGER NOT NULL DEFAULT 0,
                reward_gold INTEGER NOT NULL DEFAULT 0,
                reward_lootbox INTEGER NOT NULL DEFAULT 0,
                awarded_at INTEGER NOT NULL
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS combat_telemetry (
                guild_id INTEGER NOT NULL,
                mode TEXT NOT NULL,
                level_bracket TEXT NOT NULL,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                total_gold INTEGER NOT NULL DEFAULT 0,
                total_xp INTEGER NOT NULL DEFAULT 0,
                total_turns INTEGER NOT NULL DEFAULT 0,
                total_damage_dealt INTEGER NOT NULL DEFAULT 0,
                total_damage_taken INTEGER NOT NULL DEFAULT 0,
                total_drop_qty INTEGER NOT NULL DEFAULT 0,
                samples INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY(guild_id, mode, level_bracket)
            )
            """
        )
        try:
            await conn.execute("ALTER TABLE combat_telemetry ADD COLUMN total_turns INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass
        try:
            await conn.execute("ALTER TABLE combat_telemetry ADD COLUMN total_damage_dealt INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass
        try:
            await conn.execute("ALTER TABLE combat_telemetry ADD COLUMN total_damage_taken INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass
        try:
            await conn.execute("ALTER TABLE combat_telemetry ADD COLUMN total_drop_qty INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass

        await conn.execute("CREATE INDEX IF NOT EXISTS idx_players_gold ON players(guild_id, gold DESC)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_players_level ON players(guild_id, level DESC, xp DESC)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_kills_total ON monsters_killed(guild_id, user_id, kills DESC)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_jackpot_hits ON slime_jackpot_stats(guild_id, jackpot_hits DESC)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_combat_telemetry_mode ON combat_telemetry(guild_id, mode)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rpg_transfers_daily ON rpg_transfers(guild_id, sender_user_id, receiver_user_id, created_at)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rpg_gold_ledger_guild_ts ON rpg_gold_ledger(guild_id, created_at)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rpg_seasons_active ON rpg_seasons(is_active, season_id DESC)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rpg_season_rewards_sid ON rpg_season_rewards(season_id, guild_id, rank)"
        )
        await conn.commit()


async def ensure_db_ready():
    global _DB_READY
    if _DB_READY:
        return
    async with _DB_INIT_LOCK:
        if _DB_READY:
            return
        await _db_init()
        _DB_READY = True


async def ensure_player(conn: aiosqlite.Connection, guild_id: int, user_id: int):
    await conn.execute(
        """
        INSERT OR IGNORE INTO players(
            guild_id, user_id, level, xp, hp, max_hp, attack, defense, gold, created_at
        )
        VALUES (?, ?, 1, 0, 100, 100, 12, 6, 150, ?)
        """,
        (guild_id, user_id, int(time.time())),
    )


async def ensure_default_quests(conn: aiosqlite.Connection, guild_id: int, user_id: int):
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

    await refresh_quests_if_needed(conn, guild_id, user_id)


async def refresh_quests_if_needed(conn: aiosqlite.Connection, guild_id: int, user_id: int):
    now = int(time.time())
    async with conn.execute(
        """
        SELECT quest_id, period, reset_after
        FROM quests
        WHERE guild_id = ? AND user_id = ?
        """,
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
            SET progress = 0,
                claimed = 0,
                reset_after = ?,
                updated_at = ?
            WHERE guild_id = ? AND user_id = ? AND quest_id = ?
            """,
            (new_reset, now, guild_id, user_id, quest_id),
        )


async def get_player(conn: aiosqlite.Connection, guild_id: int, user_id: int):
    await ensure_player(conn, guild_id, user_id)
    async with conn.execute(
        """
        SELECT level, xp, hp, max_hp, attack, defense, gold
        FROM players
        WHERE guild_id = ? AND user_id = ?
        """,
        (guild_id, user_id),
    ) as cur:
        return await cur.fetchone()


async def set_cooldown(conn: aiosqlite.Connection, guild_id: int, user_id: int, key: str, seconds: int):
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


async def cooldown_remain(conn: aiosqlite.Connection, guild_id: int, user_id: int, key: str) -> int:
    async with conn.execute(
        "SELECT ready_at FROM cooldowns WHERE guild_id = ? AND user_id = ? AND key = ?",
        (guild_id, user_id, key),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return 0
    return max(0, int(row[0]) - int(time.time()))


async def add_inventory(conn: aiosqlite.Connection, guild_id: int, user_id: int, item_id: str, amount: int):
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


async def remove_inventory(conn: aiosqlite.Connection, guild_id: int, user_id: int, item_id: str, amount: int) -> bool:
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
    return True


async def gain_xp_and_level(conn: aiosqlite.Connection, guild_id: int, user_id: int, add_xp: int) -> tuple[int, int, bool]:
    row = await get_player(conn, guild_id, user_id)
    if not row:
        return 1, 0, False
    level, xp, hp, max_hp, attack, defense, gold = map(int, row)

    xp += max(0, add_xp)
    up = False
    while xp >= xp_need_for_next(level):
        xp -= xp_need_for_next(level)
        level += 1
        max_hp += 12
        attack += 2
        defense += 1
        hp = max_hp
        up = True

    await conn.execute(
        """
        UPDATE players
        SET level = ?, xp = ?, hp = ?, max_hp = ?, attack = ?, defense = ?
        WHERE guild_id = ? AND user_id = ?
        """,
        (level, xp, hp, max_hp, attack, defense, guild_id, user_id),
    )
    return level, xp, up


async def get_equipped(conn: aiosqlite.Connection, guild_id: int, user_id: int) -> dict[str, str]:
    async with conn.execute(
        "SELECT slot, item_id FROM equipment WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    ) as cur:
        rows = await cur.fetchall()
    return {str(slot): str(item_id) for slot, item_id in rows}


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
        """
        INSERT INTO player_skills(guild_id, user_id, skill_id, unlocked_at)
        VALUES (?, ?, ?, ?)
        """,
        (guild_id, user_id, skill_id, int(time.time())),
    )
    return True


async def record_slime_jackpot(conn: aiosqlite.Connection, guild_id: int, user_id: int, gold_bonus: int):
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


async def add_quest_progress(conn: aiosqlite.Connection, guild_id: int, user_id: int, objective: str, amount: int = 1):
    if amount <= 0:
        return
    await conn.execute(
        """
        UPDATE quests
        SET progress = progress + ?,
            updated_at = ?
        WHERE guild_id = ? AND user_id = ? AND objective = ? AND claimed = 0
        """,
        (amount, int(time.time()), guild_id, user_id, objective),
    )


def _utc_day_key(ts: int | None = None) -> str:
    import datetime

    now = datetime.datetime.utcfromtimestamp(ts or int(time.time()))
    return now.strftime("%Y-%m-%d")


async def consume_lootbox_open_limit(conn: aiosqlite.Connection, guild_id: int, user_id: int, amount: int) -> tuple[bool, int]:
    if amount <= 0:
        return False, 0
    day_key = _utc_day_key()
    limit = max(1, RPG_LOOTBOX_DAILY_LIMIT)

    async with conn.execute(
        """
        SELECT opened_count
        FROM lootbox_daily_limit
        WHERE guild_id = ? AND user_id = ? AND day_key = ?
        """,
        (guild_id, user_id, day_key),
    ) as cur:
        row = await cur.fetchone()
    opened = int(row[0]) if row else 0
    remain = max(0, limit - opened)
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


async def get_jackpot_stats(conn: aiosqlite.Connection, guild_id: int, user_id: int):
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


def level_bracket(level: int, size: int = 10) -> str:
    lvl = max(1, int(level))
    step = max(1, int(size))
    low = ((lvl - 1) // step) * step + 1
    high = low + step - 1
    return f"{low}-{high}"


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
):
    bracket = level_bracket(player_level)
    now = int(time.time())
    win_inc = 1 if win else 0
    loss_inc = 0 if win else 1
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
            guild_id,
            str(mode),
            bracket,
            win_inc,
            loss_inc,
            max(0, int(gold)),
            max(0, int(xp)),
            max(0, int(turns)),
            max(0, int(damage_dealt)),
            max(0, int(damage_taken)),
            max(0, int(drop_qty)),
            now,
        ),
    )


async def get_combat_telemetry(conn: aiosqlite.Connection, guild_id: int, mode: str | None = None):
    if mode:
        async with conn.execute(
            """
            SELECT mode, level_bracket, wins, losses, total_gold, total_xp,
                   total_turns, total_damage_dealt, total_damage_taken, total_drop_qty, samples
            FROM combat_telemetry
            WHERE guild_id = ? AND mode = ?
            ORDER BY level_bracket ASC
            """,
            (guild_id, str(mode)),
        ) as cur:
            return await cur.fetchall()

    async with conn.execute(
        """
        SELECT mode, level_bracket, wins, losses, total_gold, total_xp,
               total_turns, total_damage_dealt, total_damage_taken, total_drop_qty, samples
        FROM combat_telemetry
        WHERE guild_id = ?
        ORDER BY mode ASC, level_bracket ASC
        """,
        (guild_id,),
    ) as cur:
        return await cur.fetchall()


def utc_day_start(ts: int | None = None) -> int:
    import datetime

    dt = datetime.datetime.utcfromtimestamp(ts or int(time.time()))
    start = datetime.datetime(dt.year, dt.month, dt.day)
    return int(start.timestamp())


async def get_rpg_transfer_stats(
    conn: aiosqlite.Connection,
    guild_id: int,
    sender_user_id: int,
    receiver_user_id: int,
    since_ts: int,
) -> tuple[int, int]:
    async with conn.execute(
        """
        SELECT COALESCE(SUM(amount), 0)
        FROM rpg_transfers
        WHERE guild_id = ? AND sender_user_id = ? AND created_at >= ?
        """,
        (guild_id, sender_user_id, since_ts),
    ) as cur:
        row = await cur.fetchone()
    sent_today = int(row[0]) if row else 0

    async with conn.execute(
        """
        SELECT COALESCE(SUM(amount), 0)
        FROM rpg_transfers
        WHERE guild_id = ? AND sender_user_id = ? AND receiver_user_id = ? AND created_at >= ?
        """,
        (guild_id, sender_user_id, receiver_user_id, since_ts),
    ) as cur:
        row = await cur.fetchone()
    pair_today = int(row[0]) if row else 0
    return sent_today, pair_today


async def record_rpg_transfer(
    conn: aiosqlite.Connection,
    guild_id: int,
    sender_user_id: int,
    receiver_user_id: int,
    amount: int,
):
    await conn.execute(
        """
        INSERT INTO rpg_transfers(guild_id, sender_user_id, receiver_user_id, amount, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (guild_id, sender_user_id, receiver_user_id, max(0, int(amount)), int(time.time())),
    )


async def record_gold_flow(
    conn: aiosqlite.Connection,
    guild_id: int,
    user_id: int,
    delta: int,
    source: str,
):
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


async def get_gold_flow_summary(conn: aiosqlite.Connection, guild_id: int, since_ts: int):
    async with conn.execute(
        """
        SELECT flow_type, source, COALESCE(SUM(delta), 0) AS total_delta, COUNT(*) AS n
        FROM rpg_gold_ledger
        WHERE guild_id = ? AND created_at >= ?
        GROUP BY flow_type, source
        ORDER BY ABS(total_delta) DESC
        """,
        (guild_id, int(since_ts)),
    ) as cur:
        rows = await cur.fetchall()
    return rows


def _stats_for_level(level: int) -> tuple[int, int, int]:
    lvl = max(1, int(level))
    max_hp = 100 + (lvl - 1) * 12
    attack = 12 + (lvl - 1) * 2
    defense = 6 + (lvl - 1)
    return max_hp, attack, defense


def _soft_reset_level(level: int) -> int:
    lvl = max(1, int(level))
    return max(1, 1 + int((lvl - 1) * 0.4))


def _soft_reset_gold(gold: int) -> int:
    g = max(0, int(gold))
    return max(150, int(g * 0.35))


async def get_active_season(conn: aiosqlite.Connection):
    async with conn.execute(
        """
        SELECT season_id, start_ts, end_ts, is_active, note
        FROM rpg_seasons
        WHERE is_active = 1
        ORDER BY season_id DESC
        LIMIT 1
        """
    ) as cur:
        return await cur.fetchone()


async def start_new_season(conn: aiosqlite.Connection, note: str = "") -> int:
    now = int(time.time())
    await conn.execute("UPDATE rpg_seasons SET is_active = 0 WHERE is_active = 1")
    cur = await conn.execute(
        "INSERT INTO rpg_seasons(start_ts, end_ts, is_active, note) VALUES (?, 0, 1, ?)",
        (now, str(note or "")),
    )
    return int(cur.lastrowid or 0)


async def close_active_season(conn: aiosqlite.Connection) -> int:
    now = int(time.time())
    active = await get_active_season(conn)
    if not active:
        return 0
    season_id = int(active[0])
    await conn.execute(
        "UPDATE rpg_seasons SET is_active = 0, end_ts = ? WHERE season_id = ?",
        (now, season_id),
    )
    return season_id


async def get_season_leaderboard_snapshot(conn: aiosqlite.Connection, guild_id: int, limit: int = 10):
    async with conn.execute(
        """
        SELECT p.user_id,
               p.level,
               p.gold,
               COALESCE(k.total_kills, 0) AS total_kills,
               (p.level * 1000 + p.gold + COALESCE(k.total_kills, 0) * 25) AS score
        FROM players p
        LEFT JOIN (
            SELECT user_id, SUM(kills) AS total_kills
            FROM monsters_killed
            WHERE guild_id = ?
            GROUP BY user_id
        ) k ON k.user_id = p.user_id
        WHERE p.guild_id = ?
        ORDER BY score DESC
        LIMIT ?
        """,
        (guild_id, guild_id, max(1, int(limit))),
    ) as cur:
        return await cur.fetchall()


async def record_season_reward(
    conn: aiosqlite.Connection,
    season_id: int,
    guild_id: int,
    user_id: int,
    rank: int,
    score: int,
    reward_gold: int,
    reward_lootbox: int,
):
    await conn.execute(
        """
        INSERT INTO rpg_season_rewards(
            season_id, guild_id, user_id, rank, score, reward_gold, reward_lootbox, awarded_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(season_id),
            int(guild_id),
            int(user_id),
            int(rank),
            int(score),
            max(0, int(reward_gold)),
            max(0, int(reward_lootbox)),
            int(time.time()),
        ),
    )


async def apply_season_soft_reset(conn: aiosqlite.Connection, guild_id: int) -> int:
    async with conn.execute(
        "SELECT user_id, level, gold FROM players WHERE guild_id = ?",
        (guild_id,),
    ) as cur:
        rows = await cur.fetchall()

    for uid, level, gold in rows:
        new_level = _soft_reset_level(int(level))
        new_gold = _soft_reset_gold(int(gold))
        max_hp, attack, defense = _stats_for_level(new_level)
        await conn.execute(
            """
            UPDATE players
            SET level = ?, xp = 0, hp = ?, max_hp = ?, attack = ?, defense = ?, gold = ?
            WHERE guild_id = ? AND user_id = ?
            """,
            (new_level, max_hp, max_hp, attack, defense, new_gold, guild_id, int(uid)),
        )

    now = int(time.time())
    await conn.execute("DELETE FROM cooldowns WHERE guild_id = ?", (guild_id,))
    await conn.execute("DELETE FROM monsters_killed WHERE guild_id = ?", (guild_id,))
    await conn.execute(
        """
        UPDATE quests
        SET progress = 0,
            claimed = 0,
            reset_after = CASE
                WHEN period = 'daily' THEN ?
                WHEN period = 'weekly' THEN ?
                ELSE reset_after
            END,
            updated_at = ?
        WHERE guild_id = ?
        """,
        (now + 86400, now + 86400 * 7, now, guild_id),
    )
    return len(rows)
