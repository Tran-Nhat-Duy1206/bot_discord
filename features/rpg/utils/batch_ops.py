import time
import aiosqlite


class BatchWriter:
    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn
        self._statements: list[tuple[str, tuple]] = []
        self._executed = False

    def add(self, sql: str, params: tuple):
        self._statements.append((sql, params))

    async def execute(self):
        if self._executed or not self._statements:
            return
        self._executed = True
        
        for sql, params in self._statements:
            await self._conn.execute(sql, params)


class BatchInsertBuilder:
    def __init__(self, conn: aiosqlite.Connection, table: str, columns: list[str]):
        self._conn = conn
        self._table = table
        self._columns = columns
        self._rows: list[tuple] = []
        self._executed = False

    def add_row(self, values: tuple):
        if len(values) != len(self._columns):
            raise ValueError(f"Expected {len(self._columns)} values, got {len(values)}")
        self._rows.append(values)

    async def execute(self, batch_size: int = 50):
        if self._executed or not self._rows:
            return
        self._executed = True

        placeholders = ", ".join("?" * len(self._columns))
        base_sql = f"INSERT INTO {self._table}({', '.join(self._columns)}) VALUES ({placeholders})"

        for i in range(0, len(self._rows), batch_size):
            batch = self._rows[i : i + batch_size]
            for row in batch:
                await self._conn.execute(base_sql, row)


async def batch_record_monster_kills(conn: aiosqlite.Connection, guild_id: int, user_id: int, monster_ids: list[str]):
    if not monster_ids:
        return
    
    counts: dict[str, int] = {}
    for mid in monster_ids:
        counts[mid] = counts.get(mid, 0) + 1
    
    now = int(time.time())
    for monster_name, kills in counts.items():
        await conn.execute(
            """
            INSERT INTO monsters_killed(guild_id, user_id, monster_name, kills)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id, monster_name)
            DO UPDATE SET kills = kills + excluded.kills
            """,
            (guild_id, user_id, str(monster_name), kills),
        )


async def batch_add_inventory(conn: aiosqlite.Connection, guild_id: int, user_id: int, items: dict[str, int]):
    if not items:
        return
    
    for item_id, amount in items.items():
        if amount <= 0:
            continue
        await conn.execute(
            """
            INSERT INTO inventory(guild_id, user_id, item_id, amount)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id, item_id)
            DO UPDATE SET amount = amount + excluded.amount
            """,
            (guild_id, user_id, str(item_id), amount),
        )


async def batch_add_quest_progress(conn: aiosqlite.Connection, guild_id: int, user_id: int, progress_updates: list[tuple[str, int]]):
    if not progress_updates:
        return
    
    now = int(time.time())
    seen: set[str] = set()
    
    for objective, amount in progress_updates:
        key = objective
        if key in seen:
            continue
        seen.add(key)
        
        await conn.execute(
            """
            UPDATE quests
            SET progress = progress + ?,
                updated_at = ?
            WHERE guild_id = ? AND user_id = ? AND objective = ? AND claimed = 0
            """,
            (amount, now, guild_id, user_id, objective),
        )


async def batch_set_cooldowns(conn: aiosqlite.Connection, guild_id: int, user_id: int, cooldowns: list[tuple[str, int]]):
    if not cooldowns:
        return
    
    now = int(time.time())
    for key, seconds in cooldowns:
        ready_at = now + seconds
        await conn.execute(
            """
            INSERT INTO cooldowns(guild_id, user_id, key, ready_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id, key)
            DO UPDATE SET ready_at = excluded.ready_at
            """,
            (guild_id, user_id, str(key), ready_at),
        )


async def batch_record_gold_flow(conn: aiosqlite.Connection, guild_id: int, user_id: int, entries: list[tuple[int, str]]):
    if not entries:
        return
    
    now = int(time.time())
    for delta, source in entries:
        amount = int(delta)
        if amount == 0:
            continue
        flow_type = "source" if amount > 0 else "sink"
        await conn.execute(
            """
            INSERT INTO rpg_gold_ledger(guild_id, user_id, delta, flow_type, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (guild_id, user_id, amount, flow_type, str(source), now),
        )


async def batch_record_combat_telemetry(
    conn: aiosqlite.Connection,
    guild_id: int,
    mode: str,
    entries: list[tuple[int, bool, int, int, int, int, int, int]],
):
    if not entries:
        return
    
    now = int(time.time())
    
    for player_level, win, gold, xp, turns, damage_dealt, damage_taken, drop_qty in entries:
        bracket_low = ((max(1, player_level) - 1) // 10) * 10 + 1
        bracket_high = bracket_low + 9
        bracket = f"{bracket_low}-{bracket_high}"
        
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
