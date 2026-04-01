import random

from .data import (
    ITEMS,
    pick_monster,
    RPG_SLIME_BONUS_GOLD,
    RPG_SLIME_BONUS_XP,
    RPG_SLIME_JACKPOT_CHANCE,
    RPG_SLIME_JACKPOT_MIN,
    RPG_SLIME_JACKPOT_MAX,
)
from .battle import run_battle_turns
from .loot import roll_gold_xp, roll_drops
from .db import (
    get_player,
    add_inventory,
    gain_xp_and_level,
    record_slime_jackpot,
    add_quest_progress,
    record_combat_telemetry,
    record_gold_flow,
)
from .equipment import equipped_profile
from .skills import skill_profile
from .events import current_weekly_event


async def _update_kill_and_quests(conn, guild_id: int, user_id: int, monster_id: str):
    await conn.execute(
        """
        INSERT INTO monsters_killed(guild_id, user_id, monster_name, kills)
        VALUES (?, ?, ?, 1)
        ON CONFLICT(guild_id, user_id, monster_name)
        DO UPDATE SET kills = kills + 1
        """,
        (guild_id, user_id, monster_id),
    )

    await add_quest_progress(conn, guild_id, user_id, "kill_monsters", 1)
    if monster_id == "slime":
        await add_quest_progress(conn, guild_id, user_id, "kill_slime", 1)


async def _update_hunt_run_quest(conn, guild_id: int, user_id: int):
    await add_quest_progress(conn, guild_id, user_id, "hunt_runs", 1)


async def simulate_hunt(conn, guild_id: int, user_id: int):
    row = await get_player(conn, guild_id, user_id)
    if not row:
        return {"ok": False}

    level, xp, hp, max_hp, attack, defense, gold = map(int, row)
    event = current_weekly_event()
    profile = await equipped_profile(conn, guild_id, user_id)
    sprofile = await skill_profile(conn, guild_id, user_id)
    bonus_atk = int(profile["attack"])
    bonus_def = int(profile["defense"])
    bonus_hp = int(profile["hp"])
    equipped = profile["equipped"]
    lifesteal = float(profile["lifesteal"])
    crit_bonus = float(profile["crit_bonus"])
    damage_reduction = float(profile["damage_reduction"])
    active_set = profile.get("set_bonus") if isinstance(profile.get("set_bonus"), dict) else None

    skill_bonus_atk = int(sprofile["attack"])
    skill_bonus_def = int(sprofile["defense"])
    skill_bonus_hp = int(sprofile["hp"])

    effective_attack = attack + bonus_atk + skill_bonus_atk
    effective_defense = defense + bonus_def + skill_bonus_def
    effective_max_hp = max_hp + bonus_hp + skill_bonus_hp
    lifesteal = lifesteal + float(sprofile["lifesteal"])
    crit_bonus = crit_bonus + float(sprofile["crit_bonus"])
    damage_reduction = damage_reduction + float(sprofile["damage_reduction"])

    player_hp = min(effective_max_hp, hp + bonus_hp)
    pack = random.randint(5, 10)

    total_gold = 0
    total_xp = 0
    kills = 0
    slime_kills = 0
    drops = {}
    logs = []
    rarity_counts: dict[str, int] = {}
    jackpot_hits = 0
    jackpot_gold = 0
    total_lifesteal_heal = 0
    total_damage_blocked = 0
    total_turns = 0
    total_damage_dealt = 0
    total_damage_taken = 0
    defeated = False

    encounter_counts: dict[str, int] = {}

    for i in range(pack):
        if player_hp <= 0:
            break

        m = pick_monster().copy()
        monster_id = str(m["id"])
        encounter_counts[monster_id] = encounter_counts.get(monster_id, 0) + 1

        m_hp = int(m["hp"]) + max(0, (level - 1) * 2)
        escape_turn = int(m.get("escape_turn", 0)) if m.get("id") == "slime" else None
        battle = run_battle_turns(
            player_hp=player_hp,
            player_atk=effective_attack,
            player_def=effective_defense,
            monster_hp=m_hp,
            monster_atk=int(m["atk"]),
            monster_def=int(m["def"]),
            monster_escape_turn=escape_turn,
            player_max_hp=effective_max_hp,
            player_lifesteal=lifesteal,
            player_crit_bonus=crit_bonus,
            player_damage_reduction=damage_reduction,
        )
        player_hp = int(battle["player_hp"])
        escaped = bool(battle["escaped"])
        total_lifesteal_heal += int(battle.get("lifesteal_heal", 0))
        total_damage_blocked += int(battle.get("damage_blocked", 0))
        total_turns += int(battle.get("turns", 0))
        total_damage_dealt += int(battle.get("damage_dealt", 0))
        total_damage_taken += int(battle.get("damage_taken", 0))
        battle_logs = battle.get("turn_logs") if isinstance(battle.get("turn_logs"), list) else []

        if escaped:
            logs.append(f"{i+1}. {m['name']} bỏ chạy! ({battle.get('turns', 0)} turns)")
            continue
        if player_hp <= 0:
            defeated = True
            logs.append(f"{i+1}. Bạn bị {m['name']} hạ gục sau {battle.get('turns', 0)} turns.")
            break

        kills += 1
        if m["id"] == "slime":
            slime_kills += 1

        level_gap = max(0, level - int(m.get("def", 1)))
        reward_mult = 1.0 + min(0.4, level_gap * 0.02)
        g, x = roll_gold_xp(m, reward_mult=reward_mult)
        if m["id"] == "slime":
            g += RPG_SLIME_BONUS_GOLD
            x += RPG_SLIME_BONUS_XP
            if random.random() < RPG_SLIME_JACKPOT_CHANCE:
                jg = random.randint(RPG_SLIME_JACKPOT_MIN, RPG_SLIME_JACKPOT_MAX)
                g += jg
                jackpot_hits += 1
                jackpot_gold += jg
                await record_slime_jackpot(conn, guild_id, user_id, jg)
                logs.append(f"  ✨ JACKPOT! Slime rơi thêm +{jg} gold")
        total_gold += g
        total_xp += x
        logs.append(f"{i+1}. Hạ {m['name']} (+{g} gold, +{x} xp, {battle.get('turns', 0)} turns)")

        if battle_logs:
            logs.extend([f"  {line}" for line in battle_logs[:4]])

        await _update_kill_and_quests(conn, guild_id, user_id, m["id"])
        drop_mult = 1.0 + min(0.25, level * 0.01)
        drop_mult *= float(event.get("hunt_drop_mult", 1.0))
        rolled = roll_drops(m, drop_mult=drop_mult)
        for item_id, amount in rolled.items():
            drops[item_id] = drops.get(item_id, 0) + amount
            await add_inventory(conn, guild_id, user_id, item_id, amount)
            rarity = str((ITEMS.get(item_id) or {}).get("rarity", "common"))
            rarity_counts[rarity] = rarity_counts.get(rarity, 0) + amount

    player_hp = max(1, player_hp)
    base_hp_after = max(1, min(max_hp, player_hp - bonus_hp))

    await _update_hunt_run_quest(conn, guild_id, user_id)
    await conn.execute(
        "UPDATE players SET hp = ?, gold = gold + ? WHERE guild_id = ? AND user_id = ?",
        (base_hp_after, total_gold, guild_id, user_id),
    )
    await record_gold_flow(conn, guild_id, user_id, total_gold, "hunt_reward")
    new_level, remain_xp, leveled_up = await gain_xp_and_level(conn, guild_id, user_id, total_xp)
    hunt_win = not defeated
    await record_combat_telemetry(
        conn,
        guild_id,
        mode="hunt",
        player_level=level,
        win=hunt_win,
        gold=total_gold,
        xp=total_xp,
        turns=total_turns,
        damage_dealt=total_damage_dealt,
        damage_taken=total_damage_taken,
        drop_qty=sum(int(v) for v in drops.values()),
    )

    return {
        "ok": True,
        "pack": pack,
        "kills": kills,
        "slime_kills": slime_kills,
        "gold": total_gold,
        "xp": total_xp,
        "leveled_up": leveled_up,
        "level": new_level,
        "xp_remain": remain_xp,
        "hp": base_hp_after,
        "effective_hp": player_hp,
        "drops": drops,
        "logs": logs,
        "encounters": encounter_counts,
        "equipped": equipped,
        "drop_rarity": rarity_counts,
        "jackpot_hits": jackpot_hits,
        "jackpot_gold": jackpot_gold,
        "combat_effects": {
            "lifesteal": lifesteal,
            "crit_bonus": crit_bonus,
            "damage_reduction": damage_reduction,
        },
        "set_bonus": str(active_set.get("name", "")) if active_set else "",
        "passive_skills": list(sprofile.get("passives", [])),
        "lifesteal_heal": total_lifesteal_heal,
        "damage_blocked": total_damage_blocked,
        "weekly_event": {
            "id": str(event.get("id", "")),
            "name": str(event.get("name", "Weekly Event")),
        },
    }
