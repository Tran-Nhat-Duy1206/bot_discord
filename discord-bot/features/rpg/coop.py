import random

from .data import pick_monster, roll_damage
from .loot import roll_gold_xp, roll_drops
from .db import get_player, add_inventory, gain_xp_and_level, add_quest_progress, record_gold_flow
from .equipment import equipped_profile
from .skills import skill_profile
from .events import current_weekly_event


async def simulate_party_hunt(conn, guild_id: int, user_ids: list[int]) -> dict:
    event = current_weekly_event()
    members: list[dict] = []
    for uid in user_ids:
        row = await get_player(conn, guild_id, uid)
        if not row:
            continue
        level, xp, hp, max_hp, attack, defense, gold = map(int, row)
        eprofile = await equipped_profile(conn, guild_id, uid)
        sprofile = await skill_profile(conn, guild_id, uid)

        bonus_hp = int(eprofile["hp"]) + int(sprofile["hp"])
        max_eff_hp = max_hp + bonus_hp
        members.append(
            {
                "user_id": uid,
                "level": level,
                "base_max_hp": max_hp,
                "bonus_hp": bonus_hp,
                "hp": min(max_eff_hp, hp + bonus_hp),
                "max_eff_hp": max_eff_hp,
                "atk": attack + int(eprofile["attack"]) + int(sprofile["attack"]),
                "def": defense + int(eprofile["defense"]) + int(sprofile["defense"]),
                "crit": float(eprofile["crit_bonus"]) + float(sprofile["crit_bonus"]),
                "dr": float(eprofile["damage_reduction"]) + float(sprofile["damage_reduction"]),
                "ls": float(eprofile["lifesteal"]) + float(sprofile["lifesteal"]),
                "alive": True,
                "kills": 0,
                "dealt": 0,
                "taken": 0,
            }
        )

    if len(members) < 2:
        return {"ok": False, "reason": "not_enough_members"}

    pack = random.randint(6, 11) + len(members)
    logs: list[str] = []
    drops: dict[str, int] = {}
    total_gold = 0
    total_xp = 0
    kills = 0

    avg_level = max(1, int(sum(m["level"] for m in members) / len(members)))

    for i in range(pack):
        alive = [m for m in members if m["alive"]]
        if not alive:
            break

        monster = pick_monster().copy()
        mhp = int(monster["hp"]) + avg_level * 3 + len(members) * 10
        matk = int(monster["atk"]) + len(members)
        mdef = int(monster["def"]) + len(members) // 2

        turn = 0
        while mhp > 0 and any(m["alive"] for m in members):
            turn += 1
            for m in members:
                if not m["alive"] or mhp <= 0:
                    continue
                dealt, _ = roll_damage(int(m["atk"]), mdef, crit_bonus=float(m["crit"]))
                mhp -= dealt
                m["dealt"] += dealt

                heal = int(dealt * max(0.0, float(m["ls"])))
                if heal > 0 and m["hp"] < m["max_eff_hp"]:
                    m["hp"] = min(m["max_eff_hp"], int(m["hp"]) + heal)

            if mhp <= 0:
                killer = max((x for x in members if x["alive"]), key=lambda x: int(x["dealt"]), default=None)
                if killer:
                    killer["kills"] += 1
                kills += 1
                break

            targets = [m for m in members if m["alive"]]
            if not targets:
                break
            target = random.choice(targets)
            taken, _ = roll_damage(matk, int(target["def"]))
            blocked = int(taken * max(0.0, min(0.75, float(target["dr"]))))
            final_taken = max(1, taken - blocked)
            target["hp"] -= final_taken
            target["taken"] += final_taken
            if int(target["hp"]) <= 0:
                target["alive"] = False

        if mhp <= 0:
            reward_mult = 1.0 + len(members) * 0.1
            g, x = roll_gold_xp(monster, reward_mult=reward_mult)
            total_gold += g
            total_xp += x
            rolled = roll_drops(monster, drop_mult=(1.0 + len(members) * 0.05) * float(event.get("hunt_drop_mult", 1.0)))
            for item_id, amount in rolled.items():
                drops[item_id] = drops.get(item_id, 0) + amount
            logs.append(f"{i+1}. Team hạ {monster['name']} (+{g} gold, +{x} xp)")
        else:
            logs.append(f"{i+1}. Team wipe trước {monster['name']}")
            break

    party_bonus = max(1.0, 1.0 + (len(members) - 1) * 0.08)
    total_gold = int(total_gold * party_bonus)
    total_xp = int(total_xp * party_bonus)

    # split rewards
    n = len(members)
    gold_each = total_gold // n
    xp_each = total_xp // n

    member_results: list[dict] = []
    for m in members:
        uid = int(m["user_id"])
        bonus_hp = int(m["bonus_hp"])
        base_hp_after = max(1, min(int(m["base_max_hp"]), int(m["hp"]) - bonus_hp))

        await conn.execute(
            "UPDATE players SET hp = ?, gold = gold + ? WHERE guild_id = ? AND user_id = ?",
            (base_hp_after, gold_each, guild_id, uid),
        )
        await record_gold_flow(conn, guild_id, uid, gold_each, "party_hunt_reward")
        new_level, remain_xp, leveled_up = await gain_xp_and_level(conn, guild_id, uid, xp_each)
        await add_quest_progress(conn, guild_id, uid, "hunt_runs", 1)
        await add_quest_progress(conn, guild_id, uid, "kill_monsters", int(m["kills"]))

        member_results.append(
            {
                "user_id": uid,
                "hp": base_hp_after,
                "gold": gold_each,
                "xp": xp_each,
                "kills": int(m["kills"]),
                "dealt": int(m["dealt"]),
                "taken": int(m["taken"]),
                "level": int(new_level),
                "leveled_up": bool(leveled_up),
            }
        )

    # distribute drops randomly to alive-first then all
    receivers = [m for m in members if m["alive"]] or members
    for item_id, amount in drops.items():
        for _ in range(int(amount)):
            r = random.choice(receivers)
            await add_inventory(conn, guild_id, int(r["user_id"]), item_id, 1)

    return {
        "ok": True,
        "pack": pack,
        "kills": kills,
        "gold": total_gold,
        "xp": total_xp,
        "drops": drops,
        "logs": logs,
        "members": member_results,
        "weekly_event": {
            "id": str(event.get("id", "")),
            "name": str(event.get("name", "Weekly Event")),
        },
    }
