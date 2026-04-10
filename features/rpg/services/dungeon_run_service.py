import datetime
import random
import time
from dataclasses import dataclass, field

from ..dungeon import build_choice_bundle, compute_run_rewards, generate_floor_nodes
from ..repositories import dungeon_repo, inventory_repo, player_repo
from .base import BaseService
from .combat_service import CombatService


DIFFICULTY_SET = {"normal", "hard", "nightmare"}
SQLITE_INT64_MAX = (1 << 63) - 1


@dataclass
class DungeonStartResult:
    ok: bool
    run_id: str = ""
    entry_embed_data: dict = field(default_factory=dict)
    error: str = ""


@dataclass
class DungeonStateResult:
    ok: bool
    phase: str = ""
    run_id: str = ""
    difficulty: str = "normal"
    floor: int = 1
    total_floors: int = 12
    score: int = 0
    risk_score: int = 0
    supply: int = 0
    fatigue: int = 0
    corruption: int = 0
    nodes: list[dict] = field(default_factory=list)
    units: list[dict] = field(default_factory=list)
    modifiers: list[dict] = field(default_factory=list)
    pending_choice: dict = field(default_factory=dict)
    error: str = ""


@dataclass
class DungeonNodeResolveResult:
    ok: bool
    run_id: str = ""
    floor: int = 1
    node_id: str = ""
    node_type: str = ""
    result: dict = field(default_factory=dict)
    next_phase: str = ""
    error: str = ""


@dataclass
class DungeonChoiceResult:
    ok: bool
    run_id: str = ""
    choice_id: str = ""
    result: dict = field(default_factory=dict)
    next_phase: str = ""
    error: str = ""


@dataclass
class DungeonFinishResult:
    ok: bool
    run_id: str = ""
    status: str = ""
    rewards: dict = field(default_factory=dict)
    score: int = 0
    rank_points: int = 0
    error: str = ""


def _week_key(now_ts: int | None = None) -> str:
    now = datetime.datetime.utcfromtimestamp(int(now_ts or time.time()))
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def _difficulty(value: str) -> str:
    d = str(value or "normal").strip().lower()
    return d if d in DIFFICULTY_SET else "normal"


def _lane_for_role(role: str) -> str:
    r = str(role or "").lower()
    return "frontline" if r in {"tank", "dps"} else "backline"


def _is_alive(units: list[dict]) -> bool:
    return any(bool(u.get("alive", False)) for u in units)


def _count_roles(units: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for u in units:
        r = str(u.get("role", "dps")).lower()
        out[r] = out.get(r, 0) + 1
    return out


def _sum_team_power(units: list[dict]) -> float:
    total = 0.0
    for u in units:
        if not bool(u.get("alive", True)):
            continue
        total += int(u.get("attack", 0)) * 1.5
        total += int(u.get("defense", 0)) * 1.2
        total += int(u.get("hp", 0)) * 0.35
    return total


def _merge_reward(dst: dict, add: dict) -> dict:
    out = dict(dst or {})
    out["gold"] = int(out.get("gold", 0)) + int(add.get("gold", 0))
    out["xp"] = int(out.get("xp", 0)) + int(add.get("xp", 0))
    out["rank_points"] = int(out.get("rank_points", 0)) + int(add.get("rank_points", 0))

    items = dict(out.get("items", {}))
    for k, v in (add.get("items", {}) or {}).items():
        items[str(k)] = int(items.get(str(k), 0)) + int(v)
    out["items"] = items

    shards = dict(out.get("shards", {}))
    for k, v in (add.get("shards", {}) or {}).items():
        shards[str(k)] = int(shards.get(str(k), 0)) + int(v)
    out["shards"] = shards
    return out


def _sqlite_int64(value: int) -> int:
    n = int(value)
    if n < 0:
        return int((-n) % SQLITE_INT64_MAX) * -1
    return int(n % SQLITE_INT64_MAX)


class DungeonRunService(BaseService):
    @staticmethod
    async def _get_or_init_weekly_state(conn) -> dict:
        wk = _week_key()
        state = await dungeon_repo.get_weekly_state(conn, wk)
        if state:
            return state

        seed = int(time.time()) // 3600
        families = ["warlord", "aberrant", "sentinel", "void"]
        mods = [
            {"mod_id": "blood_moon", "mod_type": "global", "stack": 1, "source": "weekly", "data": {"player_lifesteal": 0.05, "enemy_crit": 0.08}},
            {"mod_id": "arcane_storm", "mod_type": "global", "stack": 1, "source": "weekly", "data": {"event_flux": 1}},
            {"mod_id": "iron_oath", "mod_type": "global", "stack": 1, "source": "weekly", "data": {"enemy_def_pct": 0.10, "heal_efficiency_pct": -0.10}},
            {"mod_id": "echo_ruin", "mod_type": "global", "stack": 1, "source": "weekly", "data": {"echo_skill_chance": 0.25}},
        ]
        rng = random.Random(seed)
        rng.shuffle(mods)
        state = {
            "week_key": wk,
            "seed": seed,
            "boss_family": rng.choice(families),
            "global_modifiers": mods[:2],
            "created_at": int(time.time()),
        }
        await dungeon_repo.upsert_weekly_state(conn, wk, state)
        return state

    @staticmethod
    async def _build_run_units(conn, guild_id: int, user_id: int) -> list[dict]:
        team = await CombatService._load_team_members(conn, guild_id, user_id)
        out: list[dict] = []
        for idx, m in enumerate(team[:5]):
            hp = int(m.get("hp", 1))
            out.append(
                {
                    "character_id": str(m.get("character_id", "")),
                    "slot": idx,
                    "lane": _lane_for_role(str(m.get("role", ""))),
                    "role": str(m.get("role", "dps")),
                    "level": int(m.get("level", 1)),
                    "star": int(m.get("star", 1)),
                    "max_hp": max(1, hp),
                    "hp": max(1, hp),
                    "attack": int(m.get("attack", 1)),
                    "defense": int(m.get("defense", 1)),
                    "speed": int(m.get("speed", 1)),
                    "alive": True,
                    "buffs": [],
                    "debuffs": [],
                }
            )
        return out

    @staticmethod
    async def start_run(guild_id: int, user_id: int, difficulty: str, lang: str = "en") -> DungeonStartResult:
        diff = _difficulty(difficulty)
        async with BaseService.with_user_transaction(guild_id, user_id, "dungeon_start") as conn:
            await player_repo.ensure_player_ready(conn, guild_id, user_id)
            active = await dungeon_repo.get_active_run(conn, guild_id, user_id)
            if active:
                return DungeonStartResult(ok=False, error="An active dungeon run already exists.")

            weekly = await DungeonRunService._get_or_init_weekly_state(conn)
            units = await DungeonRunService._build_run_units(conn, guild_id, user_id)
            if not units:
                return DungeonStartResult(ok=False, error="No valid team available. Set captain and heroes first.")

            run_id = f"dr-{guild_id}-{user_id}-{int(time.time() * 1000)}"
            total_floors = 12
            run_seed_source = int(weekly.get("seed", 0)) ^ (guild_id * 31 + user_id * 17 + int(time.time()))
            run_seed = _sqlite_int64(run_seed_source)
            nodes = generate_floor_nodes(total_floors=total_floors, seed=run_seed, difficulty=diff)

            run = {
                "run_id": run_id,
                "guild_id": guild_id,
                "user_id": user_id,
                "difficulty": diff,
                "phase": "selecting_path",
                "floor": 1,
                "total_floors": total_floors,
                "act": 1,
                "score": 0,
                "risk_score": 0,
                "supply": 0,
                "fatigue": 0,
                "corruption": 0,
                "revive_tokens": 0,
                "seed": run_seed,
                "weekly_seed": _sqlite_int64(int(weekly.get("seed", 0))),
                "current_node_id": "",
                "pending_choice": {},
                "pending_rewards": {},
                "final_rewards": {},
                "version": 0,
                "started_at": int(time.time()),
                "updated_at": int(time.time()),
                "ended_at": 0,
            }

            await dungeon_repo.create_run(conn, run)
            await dungeon_repo.insert_run_units(conn, run_id, units)
            await dungeon_repo.insert_nodes(conn, run_id, nodes)
            for mod in list(weekly.get("global_modifiers", [])):
                await dungeon_repo.upsert_modifier(conn, run_id, mod)
            await dungeon_repo.append_run_event(
                conn,
                run_id,
                "run_start",
                {
                    "difficulty": diff,
                    "total_floors": total_floors,
                    "boss_family": str(weekly.get("boss_family", "unknown")),
                },
            )

            await conn.commit()

        return DungeonStartResult(
            ok=True,
            run_id=run_id,
            entry_embed_data={
                "difficulty": diff,
                "total_floors": total_floors,
                "boss_family": str(weekly.get("boss_family", "unknown")),
                "global_modifiers": list(weekly.get("global_modifiers", [])),
            },
        )

    @staticmethod
    async def get_state(guild_id: int, user_id: int, lang: str = "en") -> DungeonStateResult:
        async with BaseService.with_user_transaction(guild_id, user_id, "dungeon_state") as conn:
            run = await dungeon_repo.get_active_run(conn, guild_id, user_id)
            if not run:
                run = await dungeon_repo.get_claimable_run(conn, guild_id, user_id)
            if not run:
                return DungeonStateResult(ok=False, error="No active run.")

            nodes = await dungeon_repo.get_floor_nodes(conn, run["run_id"], int(run["floor"]))
            units = await dungeon_repo.get_run_units(conn, run["run_id"])
            modifiers = await dungeon_repo.get_modifiers(conn, run["run_id"], mod_type=None)
            await conn.commit()

        return DungeonStateResult(
            ok=True,
            phase=str(run["phase"]),
            run_id=str(run["run_id"]),
            difficulty=str(run.get("difficulty", "normal")),
            floor=int(run["floor"]),
            total_floors=int(run["total_floors"]),
            score=int(run.get("score", 0)),
            risk_score=int(run.get("risk_score", 0)),
            supply=int(run.get("supply", 0)),
            fatigue=int(run.get("fatigue", 0)),
            corruption=int(run.get("corruption", 0)),
            nodes=nodes,
            units=units,
            modifiers=modifiers,
            pending_choice=dict(run.get("pending_choice", {})),
        )

    @staticmethod
    async def choose_node(guild_id: int, user_id: int, node_id: str, lang: str = "en") -> DungeonNodeResolveResult:
        async with BaseService.with_user_transaction(guild_id, user_id, "dungeon_choose_node") as conn:
            run = await dungeon_repo.get_active_run(conn, guild_id, user_id)
            if not run:
                return DungeonNodeResolveResult(ok=False, error="No active run.")
            if str(run.get("phase")) != "selecting_path":
                return DungeonNodeResolveResult(ok=False, run_id=str(run["run_id"]), error="Run is not waiting for path selection.")

            node = await dungeon_repo.get_node(conn, str(run["run_id"]), str(node_id))
            if not node or int(node.get("floor", 0)) != int(run.get("floor", 0)) or bool(node.get("resolved", False)):
                return DungeonNodeResolveResult(ok=False, run_id=str(run["run_id"]), error="Invalid node selection.")

            await dungeon_repo.select_node(conn, str(run["run_id"]), int(run["floor"]), str(node_id))
            ok = await dungeon_repo.patch_run(
                conn,
                str(run["run_id"]),
                {"phase": "resolving_node", "current_node_id": str(node_id)},
                version=int(run["version"]),
            )
            if not ok:
                return DungeonNodeResolveResult(ok=False, run_id=str(run["run_id"]), error="Run state changed, retry.")
            await conn.commit()

        return await DungeonRunService.resolve_current_node(guild_id, user_id, lang=lang)

    @staticmethod
    async def _apply_hp_delta(units: list[dict], pct_loss: float, frontline_extra: float = 0.0) -> tuple[list[dict], int]:
        casualties = 0
        updated: list[dict] = []
        for u in units:
            hp = int(u.get("hp", 1))
            max_hp = int(u.get("max_hp", 1))
            lane = str(u.get("lane", "backline"))
            loss_pct = pct_loss + (frontline_extra if lane == "frontline" else 0.0)
            lost = max(1, int(max_hp * max(0.0, loss_pct)))
            new_hp = max(0, hp - lost)
            u2 = dict(u)
            u2["hp"] = new_hp
            u2["alive"] = bool(new_hp > 0)
            if not u2["alive"]:
                casualties += 1
            updated.append(u2)
        return updated, casualties

    @staticmethod
    async def resolve_current_node(guild_id: int, user_id: int, lang: str = "en") -> DungeonNodeResolveResult:
        async with BaseService.with_user_transaction(guild_id, user_id, "dungeon_resolve_node") as conn:
            run = await dungeon_repo.get_active_run(conn, guild_id, user_id)
            if not run:
                return DungeonNodeResolveResult(ok=False, error="No active run.")
            if str(run.get("phase")) != "resolving_node":
                return DungeonNodeResolveResult(ok=False, run_id=str(run["run_id"]), error="Run is not resolving a node.")

            run_id = str(run["run_id"])
            node_id = str(run.get("current_node_id", ""))
            node = await dungeon_repo.get_node(conn, run_id, node_id)
            if not node:
                return DungeonNodeResolveResult(ok=False, run_id=run_id, error="Current node not found.")

            units = await dungeon_repo.get_run_units(conn, run_id)
            modifiers = await dungeon_repo.get_modifiers(conn, run_id)
            role_count = _count_roles(units)

            floor = int(run["floor"])
            total_floors = int(run["total_floors"])
            diff = _difficulty(str(run.get("difficulty", "normal")))
            rng = random.Random(int(run.get("seed", 0)) + floor * 131 + len(node_id) * 17)

            result: dict = {
                "node_id": node_id,
                "node_type": str(node.get("node_type", "combat")),
                "floor": floor,
                "win": True,
                "casualties": 0,
                "delta": {},
                "rewards": {},
            }

            pending_rewards = dict(run.get("pending_rewards", {}))
            patch: dict = {
                "score": int(run.get("score", 0)),
                "risk_score": int(run.get("risk_score", 0)),
                "supply": int(run.get("supply", 0)),
                "fatigue": int(run.get("fatigue", 0)),
                "corruption": int(run.get("corruption", 0)),
                "pending_choice": {},
            }

            ntype = str(node.get("node_type", "combat"))
            danger = int(node.get("danger", 1))
            diff_enemy = {"normal": 1.0, "hard": 1.18, "nightmare": 1.40}[diff]

            if ntype in {"combat", "elite", "boss_gate"}:
                team_power = _sum_team_power(units)
                enemy_power = (260 + floor * 85 + danger * 70) * diff_enemy
                if ntype == "elite":
                    enemy_power *= 1.22
                if ntype == "boss_gate":
                    enemy_power *= 1.55

                has_tank = role_count.get("tank", 0) > 0
                has_healer = role_count.get("healer", 0) > 0
                has_support = role_count.get("support", 0) > 0

                win_chance = team_power / max(1.0, team_power + enemy_power)
                if has_tank:
                    win_chance += 0.05
                if has_healer:
                    win_chance += 0.03
                if has_support:
                    win_chance += 0.02
                if ntype == "boss_gate":
                    win_chance -= 0.08
                win_chance = max(0.08, min(0.92, win_chance))

                won = rng.random() < win_chance
                result["win"] = won

                if won:
                    base_loss = 0.06 + danger * 0.015
                    if ntype == "elite":
                        base_loss += 0.03
                    if ntype == "boss_gate":
                        base_loss += 0.06
                    if has_healer:
                        base_loss -= 0.03
                    if has_support:
                        base_loss -= 0.02
                    units, casualties = await DungeonRunService._apply_hp_delta(units, max(0.02, base_loss), frontline_extra=0.02)
                    result["casualties"] = casualties

                    bonus = {
                        "gold": int(35 + floor * 18 + danger * 12),
                        "xp": int(24 + floor * 14 + danger * 8),
                        "items": {},
                        "shards": {},
                        "rank_points": int(8 + danger * 3 + (6 if ntype in {"elite", "boss_gate"} else 0)),
                    }
                    if ntype in {"elite", "boss_gate"}:
                        bonus["items"] = {"rare_crystal": 1}
                    pending_rewards = _merge_reward(pending_rewards, bonus)
                    patch["score"] = int(patch["score"]) + int(20 + danger * 8)
                    patch["risk_score"] = int(patch["risk_score"]) + int(max(0, danger - 3))
                    patch["fatigue"] = int(patch["fatigue"]) + int(2 + danger // 2)
                    result["rewards"] = bonus
                else:
                    units, casualties = await DungeonRunService._apply_hp_delta(units, 0.24 + danger * 0.02, frontline_extra=0.05)
                    result["casualties"] = casualties
                    patch["score"] = int(patch["score"]) + int(4 + danger)
                    patch["fatigue"] = int(patch["fatigue"]) + int(5 + danger)
                    result["delta"] = {"fatigue": patch["fatigue"]}

            elif ntype == "sanctuary":
                for u in units:
                    if not bool(u.get("alive", True)):
                        continue
                    heal = max(1, int(int(u.get("max_hp", 1)) * 0.22))
                    u["hp"] = min(int(u.get("max_hp", 1)), int(u.get("hp", 1)) + heal)
                patch["fatigue"] = max(0, int(patch["fatigue"]) - 4)
                patch["score"] = int(patch["score"]) + 10
                result["delta"] = {"heal": "22%", "fatigue": patch["fatigue"]}

            elif ntype == "merchant":
                gain = int(20 + floor * 3 + rng.randint(0, 15))
                patch["supply"] = int(patch["supply"]) + gain
                patch["score"] = int(patch["score"]) + 8
                result["delta"] = {"supply_gain": gain}

            elif ntype == "event":
                events = ["ambush", "blessing", "treasure", "omens"]
                ev = rng.choice(events)
                result["event"] = ev
                if ev == "blessing":
                    await dungeon_repo.upsert_modifier(
                        conn,
                        run_id,
                        {
                            "mod_id": f"blessing_f{floor}",
                            "mod_type": "relic",
                            "stack": 1,
                            "source": "event",
                            "data": {"atk_pct": 0.08, "duration_floors": 2},
                        },
                    )
                    patch["score"] = int(patch["score"]) + 14
                elif ev == "treasure":
                    bonus = {"gold": 40 + floor * 6, "xp": 0, "items": {"potion": 1}, "shards": {}, "rank_points": 6}
                    pending_rewards = _merge_reward(pending_rewards, bonus)
                    patch["score"] = int(patch["score"]) + 12
                    result["rewards"] = bonus
                elif ev == "ambush":
                    units, casualties = await DungeonRunService._apply_hp_delta(units, 0.12, frontline_extra=0.03)
                    result["casualties"] = casualties
                    patch["fatigue"] = int(patch["fatigue"]) + 4
                else:
                    patch["corruption"] = int(patch["corruption"]) + 2

            elif ntype == "curse":
                patch["corruption"] = int(patch["corruption"]) + int(4 + danger)
                patch["risk_score"] = int(patch["risk_score"]) + int(2 + danger)
                patch["score"] = int(patch["score"]) + int(16 + danger)
                await dungeon_repo.upsert_modifier(
                    conn,
                    run_id,
                    {
                        "mod_id": f"curse_f{floor}_{danger}",
                        "mod_type": "curse",
                        "stack": 1,
                        "source": "node",
                        "data": {"dmg_taken_pct": 0.08 + danger * 0.01},
                    },
                )
                result["delta"] = {"corruption": patch["corruption"]}

            for u in units:
                u["alive"] = bool(int(u.get("hp", 0)) > 0)

            for u in units:
                await dungeon_repo.update_unit_state(
                    conn,
                    run_id,
                    str(u.get("character_id", "")),
                    {
                        "hp": int(u.get("hp", 0)),
                        "alive": int(1 if u.get("alive", False) else 0),
                        "buffs": list(u.get("buffs", [])),
                        "debuffs": list(u.get("debuffs", [])),
                    },
                )

            await dungeon_repo.resolve_node(conn, run_id, node_id, result)
            await dungeon_repo.append_run_event(conn, run_id, "node_result", result)

            alive = _is_alive(units)
            won_gate = (ntype == "boss_gate" and bool(result.get("win", False)))
            finished = False
            finish_status = ""
            if not alive:
                finished = True
                finish_status = "failed"
            elif won_gate or floor >= total_floors:
                finished = True
                finish_status = "completed" if bool(result.get("win", True)) else "failed"

            next_phase = "selecting_path"
            next_floor = int(floor)
            if finished:
                floors_cleared = max(0, floor if bool(result.get("win", False)) else floor - 1)
                final_rewards = compute_run_rewards(
                    difficulty=diff,
                    floors_cleared=floors_cleared,
                    total_floors=total_floors,
                    risk_score=int(patch["risk_score"]),
                    score=int(patch["score"]),
                    status=finish_status,
                    seed=int(run.get("seed", 0)),
                )
                final_rewards = _merge_reward(final_rewards, pending_rewards)
                final_rewards["status"] = finish_status

                await dungeon_repo.patch_run(
                    conn,
                    run_id,
                    {
                        "phase": "claimable",
                        "pending_rewards": {},
                        "final_rewards": final_rewards,
                        "ended_at": int(time.time()),
                        "current_node_id": "",
                        "score": int(patch["score"]),
                        "risk_score": int(patch["risk_score"]),
                        "supply": int(patch["supply"]),
                        "fatigue": int(patch["fatigue"]),
                        "corruption": int(patch["corruption"]),
                    },
                    version=None,
                )
                await dungeon_repo.append_run_event(conn, run_id, "run_finished", final_rewards)
                next_phase = "claimable"
            else:
                next_floor = floor + 1
                choice_needed = (floor % 2 == 0)
                if choice_needed:
                    choice = build_choice_bundle(floor=floor, rng_seed=int(run.get("seed", 0)))
                    patch["pending_choice"] = choice
                    next_phase = "choice"
                else:
                    patch["pending_choice"] = {}
                    next_phase = "selecting_path"

                patch["pending_rewards"] = pending_rewards
                patch["phase"] = next_phase
                patch["floor"] = next_floor
                patch["act"] = 1 if next_floor <= 4 else (2 if next_floor <= 8 else 3)
                patch["current_node_id"] = ""

                await dungeon_repo.patch_run(conn, run_id, patch, version=None)

            await conn.commit()

            return DungeonNodeResolveResult(
                ok=True,
                run_id=run_id,
                floor=floor,
                node_id=node_id,
                node_type=ntype,
                result=result,
                next_phase=next_phase,
            )

    @staticmethod
    async def apply_choice(guild_id: int, user_id: int, choice_id: str, lang: str = "en") -> DungeonChoiceResult:
        cid = str(choice_id or "").strip().lower()
        async with BaseService.with_user_transaction(guild_id, user_id, "dungeon_choice") as conn:
            run = await dungeon_repo.get_active_run(conn, guild_id, user_id)
            if not run:
                return DungeonChoiceResult(ok=False, error="No active run.")
            if str(run.get("phase")) != "choice":
                return DungeonChoiceResult(ok=False, run_id=str(run["run_id"]), error="Run is not waiting for a strategic choice.")

            bundle = dict(run.get("pending_choice", {}))
            options = list(bundle.get("options", []))
            opt = next((o for o in options if str(o.get("choice_id", "")).lower() == cid), None)
            if not opt:
                return DungeonChoiceResult(ok=False, run_id=str(run["run_id"]), error="Invalid choice.")

            run_id = str(run["run_id"])
            units = await dungeon_repo.get_run_units(conn, run_id)

            patch: dict = {
                "phase": "selecting_path",
                "pending_choice": {},
                "score": int(run.get("score", 0)) + 8,
                "supply": int(run.get("supply", 0)),
                "fatigue": int(run.get("fatigue", 0)),
                "corruption": int(run.get("corruption", 0)),
                "risk_score": int(run.get("risk_score", 0)),
            }

            effect = dict(opt.get("effect", {}))
            result = {"choice": str(opt.get("choice_id", "")), "title": str(opt.get("title", "")), "effect": effect}

            if cid == "campfire":
                heal_pct = float(effect.get("heal_pct", 0.25))
                for u in units:
                    if not bool(u.get("alive", True)):
                        continue
                    heal = max(1, int(int(u.get("max_hp", 1)) * heal_pct))
                    u["hp"] = min(int(u.get("max_hp", 1)), int(u.get("hp", 1)) + heal)
                patch["score"] = max(0, int(patch["score"]) - 3)

            elif cid == "war_ritual":
                await dungeon_repo.upsert_modifier(
                    conn,
                    run_id,
                    {
                        "mod_id": f"war_ritual_f{int(run.get('floor', 1))}",
                        "mod_type": "relic",
                        "stack": 1,
                        "source": "choice",
                        "data": {"atk_pct": float(effect.get("atk_buff_pct", 0.15)), "duration_floors": int(effect.get("duration_floors", 2))},
                    },
                )
                hp_loss = float(effect.get("max_hp_loss_pct", 0.10))
                for u in units:
                    max_hp = int(u.get("max_hp", 1))
                    reduced = max(1, int(max_hp * (1.0 - hp_loss)))
                    u["max_hp"] = reduced
                    u["hp"] = min(int(u.get("hp", reduced)), reduced)
                patch["risk_score"] = int(patch["risk_score"]) + 2

            elif cid == "forbidden_pact":
                await dungeon_repo.upsert_modifier(
                    conn,
                    run_id,
                    {
                        "mod_id": f"pact_relic_f{int(run.get('floor', 1))}",
                        "mod_type": "relic",
                        "stack": 1,
                        "source": "choice",
                        "data": {"power": 1},
                    },
                )
                await dungeon_repo.upsert_modifier(
                    conn,
                    run_id,
                    {
                        "mod_id": f"pact_curse_f{int(run.get('floor', 1))}",
                        "mod_type": "curse",
                        "stack": 1,
                        "source": "choice",
                        "data": {"dmg_taken_pct": 0.10},
                    },
                )
                patch["corruption"] = int(patch["corruption"]) + 5
                patch["risk_score"] = int(patch["risk_score"]) + 3

            elif cid == "scavenge":
                gain = int(effect.get("supply", 30))
                patch["supply"] = int(patch["supply"]) + gain
                rng = random.Random(int(run.get("seed", 0)) + int(run.get("floor", 1)) * 13)
                if rng.random() < float(effect.get("ambush_chance", 0.30)):
                    patch["fatigue"] = int(patch["fatigue"]) + 4
                    result["ambush"] = True

            elif cid == "purify":
                mods = await dungeon_repo.get_modifiers(conn, run_id, mod_type="curse")
                if mods:
                    victim = mods[0]
                    await conn.execute(
                        "DELETE FROM dungeon_run_modifiers WHERE run_id = ? AND mod_id = ? AND mod_type = ? AND source = ?",
                        (run_id, str(victim.get("mod_id", "")), "curse", str(victim.get("source", ""))),
                    )
                    patch["corruption"] = max(0, int(patch["corruption"]) - 4)
                    result["removed_curse"] = str(victim.get("mod_id", ""))

            for u in units:
                await dungeon_repo.update_unit_state(
                    conn,
                    run_id,
                    str(u.get("character_id", "")),
                    {
                        "hp": int(u.get("hp", 0)),
                        "max_hp": int(u.get("max_hp", 1)),
                        "alive": int(1 if int(u.get("hp", 0)) > 0 else 0),
                    },
                )

            await dungeon_repo.patch_run(conn, run_id, patch, version=int(run.get("version", 0)))
            await dungeon_repo.append_run_event(conn, run_id, "choice_taken", result)
            await conn.commit()

            return DungeonChoiceResult(
                ok=True,
                run_id=run_id,
                choice_id=cid,
                result=result,
                next_phase="selecting_path",
            )

    @staticmethod
    async def retreat(guild_id: int, user_id: int, lang: str = "en") -> DungeonFinishResult:
        async with BaseService.with_user_transaction(guild_id, user_id, "dungeon_retreat") as conn:
            run = await dungeon_repo.get_active_run(conn, guild_id, user_id)
            if not run:
                return DungeonFinishResult(ok=False, error="No active run.")
            floors_cleared = max(0, int(run.get("floor", 1)) - 1)
            rewards = compute_run_rewards(
                difficulty=str(run.get("difficulty", "normal")),
                floors_cleared=floors_cleared,
                total_floors=int(run.get("total_floors", 12)),
                risk_score=int(run.get("risk_score", 0)),
                score=int(run.get("score", 0)),
                status="retreated",
                seed=int(run.get("seed", 0)),
            )
            rewards = _merge_reward(rewards, dict(run.get("pending_rewards", {})))
            rewards["status"] = "retreated"
            await dungeon_repo.end_run(conn, str(run["run_id"]), "claimable", rewards, int(time.time()))
            await dungeon_repo.append_run_event(conn, str(run["run_id"]), "run_retreat", rewards)
            await conn.commit()

            return DungeonFinishResult(
                ok=True,
                run_id=str(run["run_id"]),
                status="retreated",
                rewards=rewards,
                score=int(run.get("score", 0)),
                rank_points=int(rewards.get("rank_points", 0)),
            )

    @staticmethod
    async def claim_rewards(guild_id: int, user_id: int, lang: str = "en") -> DungeonFinishResult:
        async with BaseService.with_user_transaction(guild_id, user_id, "dungeon_claim") as conn:
            run = await dungeon_repo.get_claimable_run(conn, guild_id, user_id)
            if not run:
                return DungeonFinishResult(ok=False, error="No claimable run.")

            rewards = dict(run.get("final_rewards", {}))
            gold = int(rewards.get("gold", 0))
            xp = int(rewards.get("xp", 0))
            rank_points = int(rewards.get("rank_points", 0))

            if gold > 0:
                await player_repo.add_gold(conn, guild_id, user_id, gold)
            if xp > 0:
                await player_repo.gain_xp_and_level(conn, guild_id, user_id, xp)

            for item_id, amount in dict(rewards.get("items", {})).items():
                amt = int(amount)
                if amt > 0:
                    await inventory_repo.add_inventory(conn, guild_id, user_id, str(item_id), amt)

            for shard_id, amount in dict(rewards.get("shards", {})).items():
                amt = int(amount)
                if amt > 0:
                    await inventory_repo.add_inventory(conn, guild_id, user_id, str(shard_id), amt)

            await dungeon_repo.patch_run(
                conn,
                str(run["run_id"]),
                {"phase": "claimed", "pending_rewards": {}},
                version=int(run.get("version", 0)),
            )

            wk = _week_key()
            await dungeon_repo.add_weekly_rank_points(
                conn,
                wk,
                guild_id,
                user_id,
                points=rank_points,
                score=int(run.get("score", 0)),
            )
            await dungeon_repo.append_run_event(conn, str(run["run_id"]), "run_claimed", rewards)
            await conn.commit()

            return DungeonFinishResult(
                ok=True,
                run_id=str(run["run_id"]),
                status=str(rewards.get("status", "completed")),
                rewards=rewards,
                score=int(run.get("score", 0)),
                rank_points=rank_points,
            )
