import random

from .battle import run_battle_turns
from .data import BOSS_VARIANTS, pick_monster
from .loot import roll_gold_xp, roll_drops
from .db import get_player, add_inventory, gain_xp_and_level, record_combat_telemetry, record_gold_flow
from .equipment import equipped_profile
from .skills import skill_profile
from .events import current_weekly_event


def _pick_boss_variant(level: int) -> dict:
    candidates = [b for b in BOSS_VARIANTS if int(b.get("min_level", 1)) <= level]
    if not candidates:
        return BOSS_VARIANTS[0].copy()
    return candidates[-1].copy()


async def simulate_dungeon(conn, guild_id: int, user_id: int) -> dict:
    row = await get_player(conn, guild_id, user_id)
    if not row:
        return {"ok": False}

    level, xp, hp, max_hp, attack, defense, gold = map(int, row)
    event = current_weekly_event()
    eprofile = await equipped_profile(conn, guild_id, user_id)
    sprofile = await skill_profile(conn, guild_id, user_id)

    eq_atk = int(eprofile["attack"])
    eq_def = int(eprofile["defense"])
    eq_hp = int(eprofile["hp"])
    sk_atk = int(sprofile["attack"])
    sk_def = int(sprofile["defense"])
    sk_hp = int(sprofile["hp"])

    effective_attack = attack + eq_atk + sk_atk
    effective_defense = defense + eq_def + sk_def
    effective_max_hp = max_hp + eq_hp + sk_hp
    bonus_hp_total = eq_hp + sk_hp
    player_hp = min(effective_max_hp, hp + bonus_hp_total)

    lifesteal = float(eprofile["lifesteal"]) + float(sprofile["lifesteal"])
    crit_bonus = float(eprofile["crit_bonus"]) + float(sprofile["crit_bonus"])
    damage_reduction = float(eprofile["damage_reduction"]) + float(sprofile["damage_reduction"])

    total_floors = random.randint(3, 6)
    floors_cleared = 0
    total_gold = 0
    total_xp = 0
    total_lifesteal_heal = 0
    total_damage_blocked = 0
    total_turns = 0
    total_damage_dealt = 0
    total_damage_taken = 0
    drops: dict[str, int] = {}
    logs: list[str] = []

    for floor in range(1, total_floors + 1):
        if floor == total_floors:
            enemy = _pick_boss_variant(level)
            enemy_name = f"{enemy['name']} (Dungeon Boss)"
            enemy_hp = int(enemy["hp"]) + level * 8 + floor * 40
            enemy_atk = int(enemy["atk"]) + level // 3 + floor * 2
            enemy_def = int(enemy["def"]) + level // 6 + floor
            reward_src = {"gold": enemy["gold"], "xp": enemy["xp"], "drops": enemy.get("drops", [])}
        else:
            enemy = pick_monster().copy()
            enemy_name = str(enemy["name"])
            enemy_hp = int(enemy["hp"]) + level * 2 + floor * 12
            enemy_atk = int(enemy["atk"]) + floor
            enemy_def = int(enemy["def"]) + floor // 2
            reward_src = enemy

        battle = run_battle_turns(
            player_hp=player_hp,
            player_atk=effective_attack,
            player_def=effective_defense,
            monster_hp=enemy_hp,
            monster_atk=enemy_atk,
            monster_def=enemy_def,
            monster_escape_turn=None,
            player_max_hp=effective_max_hp,
            player_lifesteal=lifesteal,
            player_crit_bonus=crit_bonus,
            player_damage_reduction=damage_reduction,
        )

        player_hp = int(battle["player_hp"])
        total_lifesteal_heal += int(battle.get("lifesteal_heal", 0))
        total_damage_blocked += int(battle.get("damage_blocked", 0))
        total_turns += int(battle.get("turns", 0))
        total_damage_dealt += int(battle.get("damage_dealt", 0))
        total_damage_taken += int(battle.get("damage_taken", 0))

        if player_hp <= 0 or int(battle["monster_hp"]) > 0:
            logs.append(f"Tầng {floor}: thua trước {enemy_name}")
            break

        floors_cleared += 1
        reward_mult = 1.0 + floor * 0.15
        reward_mult *= float(event.get("boss_reward_mult", 1.0)) if floor == total_floors else 1.0
        g, x = roll_gold_xp(reward_src, reward_mult=reward_mult)
        total_gold += g
        total_xp += x

        drop_mult = (1.0 + floor * 0.1) * float(event.get("boss_drop_mult", 1.0) if floor == total_floors else event.get("hunt_drop_mult", 1.0))
        rolled = roll_drops(reward_src, drop_mult=drop_mult)
        for item_id, amount in rolled.items():
            drops[item_id] = drops.get(item_id, 0) + amount
            await add_inventory(conn, guild_id, user_id, item_id, amount)

        logs.append(f"Tầng {floor}: hạ {enemy_name} (+{g} gold, +{x} xp)")

    base_hp_after = max(1, min(max_hp, player_hp - bonus_hp_total))
    await conn.execute(
        "UPDATE players SET hp = ?, gold = gold + ? WHERE guild_id = ? AND user_id = ?",
        (base_hp_after, total_gold, guild_id, user_id),
    )
    await record_gold_flow(conn, guild_id, user_id, total_gold, "dungeon_reward")
    new_level, remain_xp, leveled_up = await gain_xp_and_level(conn, guild_id, user_id, total_xp)
    await record_combat_telemetry(
        conn,
        guild_id,
        mode="dungeon",
        player_level=level,
        win=floors_cleared == total_floors,
        gold=total_gold,
        xp=total_xp,
        turns=total_turns,
        damage_dealt=total_damage_dealt,
        damage_taken=total_damage_taken,
        drop_qty=sum(int(v) for v in drops.values()),
    )

    return {
        "ok": True,
        "cleared": floors_cleared == total_floors,
        "floors_cleared": floors_cleared,
        "total_floors": total_floors,
        "gold": total_gold,
        "xp": total_xp,
        "drops": drops,
        "hp": base_hp_after,
        "level": new_level,
        "xp_remain": remain_xp,
        "leveled_up": leveled_up,
        "logs": logs,
        "combat_effects": {
            "lifesteal": lifesteal,
            "crit_bonus": crit_bonus,
            "damage_reduction": damage_reduction,
        },
        "set_bonus": str((eprofile.get("set_bonus") or {}).get("name", "")),
        "passive_skills": list(sprofile.get("passives", [])),
        "lifesteal_heal": total_lifesteal_heal,
        "damage_blocked": total_damage_blocked,
        "weekly_event": {
            "id": str(event.get("id", "")),
            "name": str(event.get("name", "Weekly Event")),
        },
    }
