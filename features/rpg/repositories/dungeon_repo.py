import json
import time
from typing import Any

import aiosqlite


ACTIVE_PHASES = ("selecting_path", "resolving_node", "choice")
CLAIMABLE_PHASES = ("claimable",)
SQLITE_INT64_MAX = (1 << 63) - 1


def _now() -> int:
    return int(time.time())


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _sqlite_int64(value: Any) -> int:
    n = int(value)
    if n < 0:
        return int((-n) % SQLITE_INT64_MAX) * -1
    return int(n % SQLITE_INT64_MAX)


def _loads_dict(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        out = json.loads(str(raw))
        return out if isinstance(out, dict) else {}
    except Exception:
        return {}


def _loads_list(raw: Any) -> list:
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    try:
        out = json.loads(str(raw))
        return out if isinstance(out, list) else []
    except Exception:
        return []


async def get_active_run(conn: aiosqlite.Connection, guild_id: int, user_id: int) -> dict | None:
    placeholders = ",".join("?" for _ in ACTIVE_PHASES)
    async with conn.execute(
        f"""
        SELECT run_id, guild_id, user_id, difficulty, phase, floor, total_floors, act,
               score, risk_score, supply, fatigue, corruption, revive_tokens,
               seed, weekly_seed, current_node_id, pending_choice_json,
               pending_rewards_json, final_rewards_json, version,
               started_at, updated_at, ended_at
        FROM dungeon_runs
        WHERE guild_id = ? AND user_id = ? AND phase IN ({placeholders})
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (guild_id, user_id, *ACTIVE_PHASES),
    ) as cur:
        row = await cur.fetchone()

    if not row:
        return None

    return {
        "run_id": str(row[0]),
        "guild_id": int(row[1]),
        "user_id": int(row[2]),
        "difficulty": str(row[3]),
        "phase": str(row[4]),
        "floor": int(row[5]),
        "total_floors": int(row[6]),
        "act": int(row[7]),
        "score": int(row[8]),
        "risk_score": int(row[9]),
        "supply": int(row[10]),
        "fatigue": int(row[11]),
        "corruption": int(row[12]),
        "revive_tokens": int(row[13]),
        "seed": int(row[14]),
        "weekly_seed": int(row[15]),
        "current_node_id": str(row[16] or ""),
        "pending_choice": _loads_dict(row[17]),
        "pending_rewards": _loads_dict(row[18]),
        "final_rewards": _loads_dict(row[19]),
        "version": int(row[20]),
        "started_at": int(row[21]),
        "updated_at": int(row[22]),
        "ended_at": int(row[23]),
    }


async def get_run_by_id(conn: aiosqlite.Connection, run_id: str) -> dict | None:
    async with conn.execute(
        """
        SELECT run_id, guild_id, user_id, difficulty, phase, floor, total_floors, act,
               score, risk_score, supply, fatigue, corruption, revive_tokens,
               seed, weekly_seed, current_node_id, pending_choice_json,
               pending_rewards_json, final_rewards_json, version,
               started_at, updated_at, ended_at
        FROM dungeon_runs
        WHERE run_id = ?
        LIMIT 1
        """,
        (run_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    return {
        "run_id": str(row[0]),
        "guild_id": int(row[1]),
        "user_id": int(row[2]),
        "difficulty": str(row[3]),
        "phase": str(row[4]),
        "floor": int(row[5]),
        "total_floors": int(row[6]),
        "act": int(row[7]),
        "score": int(row[8]),
        "risk_score": int(row[9]),
        "supply": int(row[10]),
        "fatigue": int(row[11]),
        "corruption": int(row[12]),
        "revive_tokens": int(row[13]),
        "seed": int(row[14]),
        "weekly_seed": int(row[15]),
        "current_node_id": str(row[16] or ""),
        "pending_choice": _loads_dict(row[17]),
        "pending_rewards": _loads_dict(row[18]),
        "final_rewards": _loads_dict(row[19]),
        "version": int(row[20]),
        "started_at": int(row[21]),
        "updated_at": int(row[22]),
        "ended_at": int(row[23]),
    }


async def get_claimable_run(conn: aiosqlite.Connection, guild_id: int, user_id: int) -> dict | None:
    placeholders = ",".join("?" for _ in CLAIMABLE_PHASES)
    async with conn.execute(
        f"""
        SELECT run_id
        FROM dungeon_runs
        WHERE guild_id = ? AND user_id = ? AND phase IN ({placeholders})
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (guild_id, user_id, *CLAIMABLE_PHASES),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    return await get_run_by_id(conn, str(row[0]))


async def create_run(conn: aiosqlite.Connection, run: dict) -> None:
    now = _now()
    await conn.execute(
        """
        INSERT INTO dungeon_runs(
            run_id, guild_id, user_id, difficulty, phase, floor, total_floors, act,
            score, risk_score, supply, fatigue, corruption, revive_tokens,
            seed, weekly_seed, current_node_id,
            pending_choice_json, pending_rewards_json, final_rewards_json,
            version, started_at, updated_at, ended_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(run["run_id"]),
            int(run["guild_id"]),
            int(run["user_id"]),
            str(run.get("difficulty", "normal")),
            str(run.get("phase", "selecting_path")),
            int(run.get("floor", 1)),
            int(run.get("total_floors", 12)),
            int(run.get("act", 1)),
            int(run.get("score", 0)),
            int(run.get("risk_score", 0)),
            int(run.get("supply", 0)),
            int(run.get("fatigue", 0)),
            int(run.get("corruption", 0)),
            int(run.get("revive_tokens", 0)),
            _sqlite_int64(run.get("seed", 0)),
            _sqlite_int64(run.get("weekly_seed", 0)),
            str(run.get("current_node_id", "")),
            _dumps(run.get("pending_choice", {})),
            _dumps(run.get("pending_rewards", {})),
            _dumps(run.get("final_rewards", {})),
            int(run.get("version", 0)),
            int(run.get("started_at", now)),
            int(run.get("updated_at", now)),
            int(run.get("ended_at", 0)),
        ),
    )


async def patch_run(conn: aiosqlite.Connection, run_id: str, patch: dict, version: int | None = None) -> bool:
    if not patch:
        return True
    allowed = {
        "difficulty", "phase", "floor", "total_floors", "act",
        "score", "risk_score", "supply", "fatigue", "corruption", "revive_tokens",
        "seed", "weekly_seed", "current_node_id",
        "pending_choice", "pending_rewards", "final_rewards", "ended_at",
    }
    sets: list[str] = []
    params: list[Any] = []
    for key, value in patch.items():
        if key not in allowed:
            continue
        if key in {"pending_choice", "pending_rewards", "final_rewards"}:
            sets.append(f"{key}_json = ?")
            params.append(_dumps(value if value is not None else {}))
        else:
            sets.append(f"{key} = ?")
            params.append(value)

    sets.append("updated_at = ?")
    params.append(_now())
    sets.append("version = version + 1")

    sql = f"UPDATE dungeon_runs SET {', '.join(sets)} WHERE run_id = ?"
    params.append(str(run_id))
    if version is not None:
        sql += " AND version = ?"
        params.append(int(version))

    cur = await conn.execute(sql, tuple(params))
    return int(getattr(cur, "rowcount", 0) or 0) > 0


async def update_run_phase(conn: aiosqlite.Connection, run_id: str, phase: str, version: int | None = None) -> bool:
    return await patch_run(conn, run_id, {"phase": phase}, version=version)


async def end_run(conn: aiosqlite.Connection, run_id: str, phase: str, final_rewards: dict, ended_at: int) -> None:
    await patch_run(
        conn,
        run_id,
        {
            "phase": phase,
            "final_rewards": final_rewards or {},
            "ended_at": int(ended_at),
        },
        version=None,
    )


async def insert_run_units(conn: aiosqlite.Connection, run_id: str, units: list[dict]) -> None:
    for u in units:
        await conn.execute(
            """
            INSERT OR REPLACE INTO dungeon_run_units(
                run_id, character_id, slot, lane, role, level, star,
                max_hp, hp, attack, defense, speed, alive,
                buffs_json, debuffs_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(run_id),
                str(u.get("character_id", "")),
                int(u.get("slot", 0)),
                str(u.get("lane", "backline")),
                str(u.get("role", "dps")),
                int(u.get("level", 1)),
                int(u.get("star", 1)),
                int(u.get("max_hp", 1)),
                int(u.get("hp", 1)),
                int(u.get("attack", 1)),
                int(u.get("defense", 1)),
                int(u.get("speed", 1)),
                int(1 if u.get("alive", True) else 0),
                _dumps(u.get("buffs", [])),
                _dumps(u.get("debuffs", [])),
            ),
        )


async def get_run_units(conn: aiosqlite.Connection, run_id: str) -> list[dict]:
    async with conn.execute(
        """
        SELECT character_id, slot, lane, role, level, star,
               max_hp, hp, attack, defense, speed, alive, buffs_json, debuffs_json
        FROM dungeon_run_units
        WHERE run_id = ?
        ORDER BY slot ASC
        """,
        (run_id,),
    ) as cur:
        rows = await cur.fetchall()

    out: list[dict] = []
    for r in rows:
        out.append(
            {
                "character_id": str(r[0]),
                "slot": int(r[1]),
                "lane": str(r[2]),
                "role": str(r[3]),
                "level": int(r[4]),
                "star": int(r[5]),
                "max_hp": int(r[6]),
                "hp": int(r[7]),
                "attack": int(r[8]),
                "defense": int(r[9]),
                "speed": int(r[10]),
                "alive": bool(int(r[11])),
                "buffs": _loads_list(r[12]),
                "debuffs": _loads_list(r[13]),
            }
        )
    return out


async def update_unit_state(conn: aiosqlite.Connection, run_id: str, character_id: str, patch: dict) -> None:
    if not patch:
        return
    allowed = {"hp", "max_hp", "attack", "defense", "speed", "alive", "buffs", "debuffs"}
    sets: list[str] = []
    params: list[Any] = []
    for k, v in patch.items():
        if k not in allowed:
            continue
        if k in {"buffs", "debuffs"}:
            sets.append(f"{k}_json = ?")
            params.append(_dumps(v if isinstance(v, list) else []))
        else:
            sets.append(f"{k} = ?")
            params.append(v)
    if not sets:
        return
    params.extend([run_id, character_id])
    await conn.execute(
        f"UPDATE dungeon_run_units SET {', '.join(sets)} WHERE run_id = ? AND character_id = ?",
        tuple(params),
    )


async def insert_nodes(conn: aiosqlite.Connection, run_id: str, nodes: list[dict]) -> None:
    for n in nodes:
        await conn.execute(
            """
            INSERT OR REPLACE INTO dungeon_run_nodes(
                run_id, floor, node_id, node_type, danger,
                payload_json, selected, resolved, result_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(run_id),
                int(n.get("floor", 1)),
                str(n.get("node_id", "")),
                str(n.get("node_type", "combat")),
                int(n.get("danger", 1)),
                _dumps(n.get("payload", {})),
                int(n.get("selected", 0)),
                int(n.get("resolved", 0)),
                _dumps(n.get("result", {})),
            ),
        )


async def get_floor_nodes(conn: aiosqlite.Connection, run_id: str, floor: int) -> list[dict]:
    async with conn.execute(
        """
        SELECT node_id, node_type, danger, payload_json, selected, resolved, result_json
        FROM dungeon_run_nodes
        WHERE run_id = ? AND floor = ?
        ORDER BY node_id ASC
        """,
        (run_id, int(floor)),
    ) as cur:
        rows = await cur.fetchall()
    out: list[dict] = []
    for r in rows:
        out.append(
            {
                "node_id": str(r[0]),
                "node_type": str(r[1]),
                "danger": int(r[2]),
                "payload": _loads_dict(r[3]),
                "selected": bool(int(r[4])),
                "resolved": bool(int(r[5])),
                "result": _loads_dict(r[6]),
            }
        )
    return out


async def get_node(conn: aiosqlite.Connection, run_id: str, node_id: str) -> dict | None:
    async with conn.execute(
        """
        SELECT floor, node_id, node_type, danger, payload_json, selected, resolved, result_json
        FROM dungeon_run_nodes
        WHERE run_id = ? AND node_id = ?
        LIMIT 1
        """,
        (run_id, node_id),
    ) as cur:
        r = await cur.fetchone()
    if not r:
        return None
    return {
        "floor": int(r[0]),
        "node_id": str(r[1]),
        "node_type": str(r[2]),
        "danger": int(r[3]),
        "payload": _loads_dict(r[4]),
        "selected": bool(int(r[5])),
        "resolved": bool(int(r[6])),
        "result": _loads_dict(r[7]),
    }


async def select_node(conn: aiosqlite.Connection, run_id: str, floor: int, node_id: str) -> None:
    await conn.execute(
        "UPDATE dungeon_run_nodes SET selected = 0 WHERE run_id = ? AND floor = ?",
        (run_id, int(floor)),
    )
    await conn.execute(
        "UPDATE dungeon_run_nodes SET selected = 1 WHERE run_id = ? AND node_id = ?",
        (run_id, node_id),
    )


async def resolve_node(conn: aiosqlite.Connection, run_id: str, node_id: str, result: dict) -> None:
    await conn.execute(
        """
        UPDATE dungeon_run_nodes
        SET resolved = 1, result_json = ?
        WHERE run_id = ? AND node_id = ?
        """,
        (_dumps(result or {}), run_id, node_id),
    )


async def upsert_modifier(conn: aiosqlite.Connection, run_id: str, mod: dict) -> None:
    await conn.execute(
        """
        INSERT INTO dungeon_run_modifiers(run_id, mod_id, mod_type, stack, source, data_json)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, mod_id, mod_type, source)
        DO UPDATE SET
            stack = excluded.stack,
            data_json = excluded.data_json
        """,
        (
            run_id,
            str(mod.get("mod_id", "")),
            str(mod.get("mod_type", "global")),
            int(mod.get("stack", 1)),
            str(mod.get("source", "")),
            _dumps(mod.get("data", {})),
        ),
    )


async def get_modifiers(conn: aiosqlite.Connection, run_id: str, mod_type: str | None = None) -> list[dict]:
    if mod_type:
        async with conn.execute(
            """
            SELECT mod_id, mod_type, stack, source, data_json
            FROM dungeon_run_modifiers
            WHERE run_id = ? AND mod_type = ?
            ORDER BY mod_type, mod_id
            """,
            (run_id, mod_type),
        ) as cur:
            rows = await cur.fetchall()
    else:
        async with conn.execute(
            """
            SELECT mod_id, mod_type, stack, source, data_json
            FROM dungeon_run_modifiers
            WHERE run_id = ?
            ORDER BY mod_type, mod_id
            """,
            (run_id,),
        ) as cur:
            rows = await cur.fetchall()
    return [
        {
            "mod_id": str(r[0]),
            "mod_type": str(r[1]),
            "stack": int(r[2]),
            "source": str(r[3]),
            "data": _loads_dict(r[4]),
        }
        for r in rows
    ]


async def append_run_event(conn: aiosqlite.Connection, run_id: str, event_type: str, payload: dict) -> None:
    async with conn.execute(
        "SELECT COALESCE(MAX(seq), 0) FROM dungeon_run_events WHERE run_id = ?",
        (run_id,),
    ) as cur:
        row = await cur.fetchone()
    seq = int(row[0] or 0) + 1
    await conn.execute(
        """
        INSERT INTO dungeon_run_events(run_id, seq, event_type, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (run_id, seq, str(event_type), _dumps(payload or {}), _now()),
    )


async def list_run_events(conn: aiosqlite.Connection, run_id: str, limit: int = 200) -> list[dict]:
    async with conn.execute(
        """
        SELECT seq, event_type, payload_json, created_at
        FROM dungeon_run_events
        WHERE run_id = ?
        ORDER BY seq ASC
        LIMIT ?
        """,
        (run_id, max(1, int(limit))),
    ) as cur:
        rows = await cur.fetchall()
    return [
        {
            "seq": int(r[0]),
            "event_type": str(r[1]),
            "payload": _loads_dict(r[2]),
            "created_at": int(r[3]),
        }
        for r in rows
    ]


async def upsert_weekly_state(conn: aiosqlite.Connection, week_key: str, data: dict) -> None:
    await conn.execute(
        """
        INSERT INTO dungeon_weekly_state(week_key, seed, boss_family, global_modifiers_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(week_key)
        DO UPDATE SET
            seed = excluded.seed,
            boss_family = excluded.boss_family,
            global_modifiers_json = excluded.global_modifiers_json
        """,
        (
            str(week_key),
            _sqlite_int64(data.get("seed", 0)),
            str(data.get("boss_family", "ancient")),
            _dumps(data.get("global_modifiers", [])),
            _sqlite_int64(data.get("created_at", _now())),
        ),
    )


async def get_weekly_state(conn: aiosqlite.Connection, week_key: str) -> dict | None:
    async with conn.execute(
        """
        SELECT week_key, seed, boss_family, global_modifiers_json, created_at
        FROM dungeon_weekly_state
        WHERE week_key = ?
        LIMIT 1
        """,
        (str(week_key),),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    return {
        "week_key": str(row[0]),
        "seed": int(row[1]),
        "boss_family": str(row[2]),
        "global_modifiers": _loads_list(row[3]),
        "created_at": int(row[4]),
    }


async def add_weekly_rank_points(
    conn: aiosqlite.Connection,
    week_key: str,
    guild_id: int,
    user_id: int,
    points: int,
    score: int,
) -> None:
    now = _now()
    await conn.execute(
        """
        INSERT INTO dungeon_weekly_rank(week_key, guild_id, user_id, rank_points, best_score, runs_count, updated_at)
        VALUES (?, ?, ?, ?, ?, 1, ?)
        ON CONFLICT(week_key, guild_id, user_id)
        DO UPDATE SET
            rank_points = rank_points + excluded.rank_points,
            best_score = MAX(best_score, excluded.best_score),
            runs_count = runs_count + 1,
            updated_at = excluded.updated_at
        """,
        (str(week_key), int(guild_id), int(user_id), int(points), int(score), now),
    )
