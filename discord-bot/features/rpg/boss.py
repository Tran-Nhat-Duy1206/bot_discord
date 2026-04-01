import random

from .data import BOSS_VARIANTS, roll_damage
from .loot import roll_drops, roll_gold_xp
from .db import gain_xp_and_level, add_inventory, add_quest_progress, record_combat_telemetry, record_gold_flow
from .equipment import equipped_profile
from .skills import skill_profile
from .events import current_weekly_event


def _select_boss_variant(level: int) -> dict:
    candidates = [b for b in BOSS_VARIANTS if int(b.get("min_level", 1)) <= level]
    if not candidates:
        candidates = [BOSS_VARIANTS[0]]
    return candidates[-1].copy()


def _run_boss_phase_battle(
    player_hp: int,
    player_atk: int,
    player_def: int,
    player_max_hp: int,
    player_lifesteal: float,
    player_crit_bonus: float,
    player_damage_reduction: float,
    boss_hp: int,
    boss_atk: int,
    boss_def: int,
) -> dict:
    turns = 0
    turn_logs: list[str] = []
    phase_events: list[str] = []

    rage_triggered = False
    rage_threshold = max(1, int(boss_hp * 0.45))
    shield_turns = 0
    summon_count = 0
    total_lifesteal_heal = 0
    total_damage_blocked = 0
    total_damage_dealt = 0
    total_damage_taken = 0

    lifesteal = max(0.0, min(0.9, float(player_lifesteal)))
    crit_bonus = max(0.0, float(player_crit_bonus))
    damage_reduction = max(0.0, min(0.85, float(player_damage_reduction)))

    while boss_hp > 0 and player_hp > 0:
        turns += 1

        shield_active = turns % 4 == 0
        if shield_active:
            shield_turns += 1
            phase_events.append(f"Turn {turns}: shield")
            turn_logs.append(f"Turn {turns}: boss bật khiên giảm sát thương")

        dealt, is_crit = roll_damage(player_atk, boss_def, crit_bonus=crit_bonus)
        total_damage_dealt += max(0, int(dealt))
        if shield_active:
            blocked_by_shield = max(0, int(dealt * 0.55))
            dealt = max(1, dealt - blocked_by_shield)
            turn_logs.append(f"Turn {turns}: khiên chặn {blocked_by_shield} dmg")

        boss_hp -= dealt
        turn_logs.append(f"Turn {turns}: bạn gây {dealt} dmg{' (CRIT)' if is_crit else ''}")

        if lifesteal > 0 and dealt > 0 and player_hp > 0:
            heal = int(dealt * lifesteal)
            if heal > 0 and player_hp < player_max_hp:
                old_hp = player_hp
                player_hp = min(player_max_hp, player_hp + heal)
                healed = max(0, player_hp - old_hp)
                if healed > 0:
                    total_lifesteal_heal += healed
                    turn_logs.append(f"Turn {turns}: lifesteal hồi {healed} HP")

        if boss_hp <= 0:
            turn_logs.append(f"Turn {turns}: boss gục")
            break

        if not rage_triggered and boss_hp <= rage_threshold:
            rage_triggered = True
            phase_events.append(f"Turn {turns}: rage")
            turn_logs.append(f"Turn {turns}: boss vào RAGE MODE")

        if turns % 5 == 0:
            summon_count += 1
            phase_events.append(f"Turn {turns}: summon")
            summon_raw = max(1, int(boss_atk * 0.38))
            summon_blocked = int(summon_raw * damage_reduction) if damage_reduction > 0 else 0
            summon_taken = max(1, summon_raw - summon_blocked)
            total_damage_taken += max(0, int(summon_taken))
            player_hp -= summon_taken
            total_damage_blocked += max(0, summon_blocked)
            turn_logs.append(
                f"Turn {turns}: boss triệu hồi minion gây {summon_taken} dmg"
                f"{' (giảm ' + str(summon_blocked) + ')' if summon_blocked > 0 else ''}"
            )
            if player_hp <= 0:
                break

        current_boss_atk = int(boss_atk * 1.28) if rage_triggered else boss_atk
        taken, enemy_crit = roll_damage(current_boss_atk, player_def)
        blocked = int(taken * damage_reduction) if damage_reduction > 0 else 0
        final_taken = max(1, taken - blocked) if taken > 0 else 0
        total_damage_taken += max(0, int(final_taken))
        player_hp -= final_taken
        total_damage_blocked += max(0, blocked)
        turn_logs.append(
            f"Turn {turns}: bạn nhận {final_taken} dmg"
            f"{' (CRIT)' if enemy_crit else ''}"
            f"{' (RAGE)' if rage_triggered else ''}"
            f"{' (giảm ' + str(blocked) + ')' if blocked > 0 else ''}"
        )

    return {
        "turns": turns,
        "player_hp": player_hp,
        "monster_hp": boss_hp,
        "turn_logs": turn_logs,
        "phase_events": phase_events,
        "rage_triggered": rage_triggered,
        "shield_turns": shield_turns,
        "summon_count": summon_count,
        "lifesteal_heal": total_lifesteal_heal,
        "damage_blocked": total_damage_blocked,
        "damage_dealt": total_damage_dealt,
        "damage_taken": total_damage_taken,
    }


async def simulate_boss(conn, guild_id: int, user_id: int, base_row):
    level, xp, hp, max_hp, attack, defense, gold = map(int, base_row)
    event = current_weekly_event()
    profile = await equipped_profile(conn, guild_id, user_id)
    sprofile = await skill_profile(conn, guild_id, user_id)
    bonus_atk = int(profile["attack"])
    bonus_def = int(profile["defense"])
    bonus_hp = int(profile["hp"])
    lifesteal = float(profile["lifesteal"])
    crit_bonus = float(profile["crit_bonus"])
    damage_reduction = float(profile["damage_reduction"])
    equipped = profile["equipped"]
    active_set = profile.get("set_bonus") if isinstance(profile.get("set_bonus"), dict) else None

    skill_bonus_atk = int(sprofile["attack"])
    skill_bonus_def = int(sprofile["defense"])
    skill_bonus_hp = int(sprofile["hp"])

    eff_atk = attack + bonus_atk + skill_bonus_atk
    eff_def = defense + bonus_def + skill_bonus_def
    eff_max_hp = max_hp + bonus_hp + skill_bonus_hp
    lifesteal = lifesteal + float(sprofile["lifesteal"])
    crit_bonus = crit_bonus + float(sprofile["crit_bonus"])
    damage_reduction = damage_reduction + float(sprofile["damage_reduction"])
    eff_hp = min(eff_max_hp, hp + bonus_hp)

    boss = _select_boss_variant(level)
    boss_hp = int(boss["hp"]) + level * 12
    boss_atk = int(boss["atk"]) + level // 2
    boss_def = int(boss["def"]) + level // 4

    battle = _run_boss_phase_battle(
        player_hp=eff_hp,
        player_atk=eff_atk,
        player_def=eff_def,
        player_max_hp=eff_max_hp,
        player_lifesteal=lifesteal,
        player_crit_bonus=crit_bonus,
        player_damage_reduction=damage_reduction,
        boss_hp=boss_hp,
        boss_atk=boss_atk,
        boss_def=boss_def,
    )

    win = int(battle["monster_hp"]) <= 0 and int(battle["player_hp"]) > 0
    battle_logs = battle.get("turn_logs") if isinstance(battle.get("turn_logs"), list) else []
    phase_events = battle.get("phase_events") if isinstance(battle.get("phase_events"), list) else []

    if not win:
        remain_effective_hp = max(1, int(battle["player_hp"]))
        base_hp = max(1, min(max_hp, remain_effective_hp - bonus_hp))
        await conn.execute(
            "UPDATE players SET hp = ? WHERE guild_id = ? AND user_id = ?",
            (base_hp, guild_id, user_id),
        )
        await record_combat_telemetry(
            conn,
            guild_id,
            mode="boss",
            player_level=level,
            win=False,
            gold=0,
            xp=0,
            turns=int(battle.get("turns", 0)),
            damage_dealt=int(battle.get("damage_dealt", 0)),
            damage_taken=int(battle.get("damage_taken", 0)),
            drop_qty=0,
        )
        return {
            "ok": True,
            "win": False,
            "boss_id": boss.get("id", "ancient_ogre"),
            "boss": boss["name"],
            "base_hp": base_hp,
            "equipped": equipped,
            "logs": battle_logs,
            "combat_effects": {
                "lifesteal": lifesteal,
                "crit_bonus": crit_bonus,
                "damage_reduction": damage_reduction,
            },
            "set_bonus": str(active_set.get("name", "")) if active_set else "",
            "passive_skills": list(sprofile.get("passives", [])),
            "lifesteal_heal": int(battle.get("lifesteal_heal", 0)),
            "damage_blocked": int(battle.get("damage_blocked", 0)),
            "phase_events": phase_events,
            "rage_triggered": bool(battle.get("rage_triggered", False)),
            "shield_turns": int(battle.get("shield_turns", 0)),
            "summon_count": int(battle.get("summon_count", 0)),
            "weekly_event": {
                "id": str(event.get("id", "")),
                "name": str(event.get("name", "Weekly Event")),
            },
        }

    reward_mult = 1.08 * float(event.get("boss_reward_mult", 1.0))
    base_gold, base_xp = roll_gold_xp({"gold": boss["gold"], "xp": boss["xp"]}, reward_mult=reward_mult)
    extra_gold = random.randint(40, 140) + int(event.get("boss_bonus_gold", 0))
    reward_gold = base_gold + extra_gold
    reward_xp = base_xp

    drops = roll_drops(boss, drop_mult=float(event.get("boss_drop_mult", 1.0)))
    for item_id, amount in drops.items():
        await add_inventory(conn, guild_id, user_id, item_id, amount)

    remain_effective_hp = max(1, int(battle["player_hp"]))
    base_hp = max(1, min(max_hp, remain_effective_hp - bonus_hp))

    await conn.execute(
        "UPDATE players SET hp = ?, gold = gold + ? WHERE guild_id = ? AND user_id = ?",
        (base_hp, reward_gold, guild_id, user_id),
    )
    await record_gold_flow(conn, guild_id, user_id, reward_gold, "boss_reward")
    await add_quest_progress(conn, guild_id, user_id, "boss_wins", 1)
    new_level, remain_xp, leveled_up = await gain_xp_and_level(conn, guild_id, user_id, reward_xp)
    await record_combat_telemetry(
        conn,
        guild_id,
        mode="boss",
        player_level=level,
        win=True,
        gold=reward_gold,
        xp=reward_xp,
        turns=int(battle.get("turns", 0)),
        damage_dealt=int(battle.get("damage_dealt", 0)),
        damage_taken=int(battle.get("damage_taken", 0)),
        drop_qty=sum(int(v) for v in drops.values()),
    )

    return {
        "ok": True,
        "win": True,
        "boss_id": boss.get("id", "ancient_ogre"),
        "boss": boss["name"],
        "gold": reward_gold,
        "xp": reward_xp,
        "drops": drops,
        "base_hp": base_hp,
        "leveled_up": leveled_up,
        "level": new_level,
        "xp_remain": remain_xp,
        "equipped": equipped,
        "logs": battle_logs,
        "combat_effects": {
            "lifesteal": lifesteal,
            "crit_bonus": crit_bonus,
            "damage_reduction": damage_reduction,
        },
        "set_bonus": str(active_set.get("name", "")) if active_set else "",
        "passive_skills": list(sprofile.get("passives", [])),
        "lifesteal_heal": int(battle.get("lifesteal_heal", 0)),
        "damage_blocked": int(battle.get("damage_blocked", 0)),
        "phase_events": phase_events,
        "rage_triggered": bool(battle.get("rage_triggered", False)),
        "shield_turns": int(battle.get("shield_turns", 0)),
        "summon_count": int(battle.get("summon_count", 0)),
        "weekly_event": {
            "id": str(event.get("id", "")),
            "name": str(event.get("name", "Weekly Event")),
        },
    }
