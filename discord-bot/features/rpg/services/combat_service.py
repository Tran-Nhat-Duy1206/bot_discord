import random
from dataclasses import dataclass, field
from typing import Optional

from ..data.data import (
    ITEMS, MONSTERS, BOSS_VARIANTS,
    pick_monster, roll_damage,
    RPG_SLIME_BONUS_GOLD, RPG_SLIME_BONUS_XP,
    RPG_SLIME_JACKPOT_CHANCE, RPG_SLIME_JACKPOT_MIN, RPG_SLIME_JACKPOT_MAX,
)
from ..combat.battle import run_battle_turns
from ..combat.loot import roll_gold_xp, roll_drops
from ..utils.events import current_weekly_event

from ..repositories import player_repo, inventory_repo, telemetry_repo, quest_repo
from .base import BaseService


@dataclass
class CombatEffects:
    lifesteal: float = 0.0
    crit_bonus: float = 0.0
    damage_reduction: float = 0.0


@dataclass
class CombatResult:
    ok: bool = False
    pack: int = 0
    kills: int = 0
    slime_kills: int = 0
    gold: int = 0
    xp: int = 0
    leveled_up: bool = False
    level: int = 1
    xp_remain: int = 0
    hp: int = 0
    effective_hp: int = 0
    drops: dict = field(default_factory=dict)
    logs: list = field(default_factory=list)
    encounters: dict = field(default_factory=dict)
    drop_rarity: dict = field(default_factory=dict)
    jackpot_hits: int = 0
    jackpot_gold: int = 0
    combat_effects: CombatEffects = field(default_factory=CombatEffects)
    set_bonus: str = ""
    passive_skills: list = field(default_factory=list)
    lifesteal_heal: int = 0
    damage_blocked: int = 0
    weekly_event: dict = field(default_factory=dict)


@dataclass
class BossResult:
    ok: bool = False
    win: bool = False
    boss_id: str = ""
    boss: str = ""
    gold: int = 0
    xp: int = 0
    drops: dict = field(default_factory=dict)
    base_hp: int = 0
    leveled_up: bool = False
    level: int = 1
    xp_remain: int = 0
    logs: list = field(default_factory=list)
    combat_effects: CombatEffects = field(default_factory=CombatEffects)
    set_bonus: str = ""
    passive_skills: list = field(default_factory=list)
    lifesteal_heal: int = 0
    damage_blocked: int = 0
    phase_events: list = field(default_factory=list)
    rage_triggered: bool = False
    shield_turns: int = 0
    summon_count: int = 0
    weekly_event: dict = field(default_factory=dict)


@dataclass
class DungeonResult:
    ok: bool = False
    cleared: bool = False
    floors_cleared: int = 0
    total_floors: int = 0
    gold: int = 0
    xp: int = 0
    drops: dict = field(default_factory=dict)
    hp: int = 0
    level: int = 1
    xp_remain: int = 0
    leveled_up: bool = False
    logs: list = field(default_factory=list)
    combat_effects: CombatEffects = field(default_factory=CombatEffects)
    set_bonus: str = ""
    passive_skills: list = field(default_factory=list)
    lifesteal_heal: int = 0
    damage_blocked: int = 0
    weekly_event: dict = field(default_factory=dict)


@dataclass
class PartyHuntResult:
    ok: bool = False
    pack: int = 0
    kills: int = 0
    gold: int = 0
    xp: int = 0
    drops: dict = field(default_factory=dict)
    logs: list = field(default_factory=list)
    members: list = field(default_factory=list)
    weekly_event: dict = field(default_factory=dict)


class CombatService(BaseService):
    @staticmethod
    async def hunt(guild_id: int, user_id: int) -> CombatResult:
        async with BaseService.with_user_transaction(guild_id, user_id, "hunt") as conn:
            await player_repo.ensure_player_ready(conn, guild_id, user_id)
            await quest_repo.ensure_default_quests(conn, guild_id, user_id)
            await quest_repo.refresh_quests_if_needed(conn, guild_id, user_id)
            
            from ..db.db import cooldown_remain
            remain = await cooldown_remain(conn, guild_id, user_id, "hunt")
            if remain > 0:
                return CombatResult()

            result = await CombatService._simulate_hunt(conn, guild_id, user_id)
            
            await telemetry_repo.set_cooldown(conn, guild_id, user_id, "hunt", 45)
            await conn.commit()
            
            return result

    @staticmethod
    async def _simulate_hunt(conn, guild_id: int, user_id: int) -> CombatResult:
        row = await player_repo.get_player_stats(conn, guild_id, user_id)
        if not row:
            return CombatResult()

        level, xp, hp, max_hp, attack, defense, gold = map(int, row)
        event = current_weekly_event()
        
        from ..combat.equipment import equipped_profile
        from ..combat.skills import skill_profile
        
        profile = await equipped_profile(conn, guild_id, user_id)
        sprofile = await skill_profile(conn, guild_id, user_id)
        
        bonus_atk = int(profile["attack"])
        bonus_def = int(profile["defense"])
        bonus_hp = int(profile["hp"])
        equipped = profile["equipped"]
        lifesteal = float(profile["lifesteal"])
        crit_bonus = float(profile["crit_bonus"])
        damage_reduction = float(profile["damage_reduction"])
        active_set = profile.get("set_bonus")

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
        drops: dict[str, int] = {}
        logs: list[str] = []
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
            battle_logs = battle.get("turn_logs", [])

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
                    await telemetry_repo.record_slime_jackpot(conn, guild_id, user_id, jg)
                    logs.append(f"  ✨ JACKPOT! Slime rơi thêm +{jg} gold")

            total_gold += g
            total_xp += x
            logs.append(f"{i+1}. Hạ {m['name']} (+{g} gold, +{x} xp, {battle.get('turns', 0)} turns)")

            if battle_logs:
                logs.extend([f"  {line}" for line in battle_logs[:4]])

            await telemetry_repo.record_monster_kill(conn, guild_id, user_id, m["id"])
            await quest_repo.add_quest_progress(conn, guild_id, user_id, "kill_monsters", 1)
            if m["id"] == "slime":
                await quest_repo.add_quest_progress(conn, guild_id, user_id, "kill_slime", 1)

            drop_mult = 1.0 + min(0.25, level * 0.01)
            drop_mult *= float(event.get("hunt_drop_mult", 1.0))
            rolled = roll_drops(m, drop_mult=drop_mult)
            for item_id, amount in rolled.items():
                drops[item_id] = drops.get(item_id, 0) + amount
                await inventory_repo.add_inventory(conn, guild_id, user_id, item_id, amount)
                rarity = str((ITEMS.get(item_id) or {}).get("rarity", "common"))
                rarity_counts[rarity] = rarity_counts.get(rarity, 0) + amount

        player_hp = max(1, player_hp)
        base_hp_after = max(1, min(max_hp, player_hp - bonus_hp))

        await quest_repo.add_quest_progress(conn, guild_id, user_id, "hunt_runs", 1)
        await player_repo.update_player_hp_gold(conn, guild_id, user_id, base_hp_after, total_gold)
        await telemetry_repo.record_gold_flow(conn, guild_id, user_id, total_gold, "hunt_reward")
        new_level, remain_xp, leveled_up = await player_repo.gain_xp_and_level(conn, guild_id, user_id, total_xp)
        hunt_win = not defeated
        await telemetry_repo.record_combat_telemetry(
            conn, guild_id, "hunt", level, hunt_win,
            gold=total_gold, xp=total_xp, turns=total_turns,
            damage_dealt=total_damage_dealt, damage_taken=total_damage_taken,
            drop_qty=sum(int(v) for v in drops.values()),
        )

        return CombatResult(
            ok=True,
            pack=pack,
            kills=kills,
            slime_kills=slime_kills,
            gold=total_gold,
            xp=total_xp,
            leveled_up=leveled_up,
            level=new_level,
            xp_remain=remain_xp,
            hp=base_hp_after,
            effective_hp=player_hp,
            drops=drops,
            logs=logs,
            encounters=encounter_counts,
            drop_rarity=rarity_counts,
            jackpot_hits=jackpot_hits,
            jackpot_gold=jackpot_gold,
            combat_effects=CombatEffects(lifesteal=lifesteal, crit_bonus=crit_bonus, damage_reduction=damage_reduction),
            set_bonus=str(active_set.get("name", "")) if active_set else "",
            passive_skills=list(sprofile.get("passives", [])),
            lifesteal_heal=total_lifesteal_heal,
            damage_blocked=total_damage_blocked,
            weekly_event={"id": str(event.get("id", "")), "name": str(event.get("name", "Weekly Event"))},
        )

    @staticmethod
    async def boss(guild_id: int, user_id: int) -> BossResult:
        async with BaseService.with_user_transaction(guild_id, user_id, "boss") as conn:
            await player_repo.ensure_player_ready(conn, guild_id, user_id)
            await quest_repo.ensure_default_quests(conn, guild_id, user_id)
            await quest_repo.refresh_quests_if_needed(conn, guild_id, user_id)
            
            from ..db.db import cooldown_remain
            remain = await cooldown_remain(conn, guild_id, user_id, "boss")
            if remain > 0:
                return BossResult()

            row = await player_repo.get_player_stats(conn, guild_id, user_id)
            result = await CombatService._simulate_boss(conn, guild_id, user_id, row)
            
            await telemetry_repo.set_cooldown(conn, guild_id, user_id, "boss", 1800)
            await conn.commit()
            
            return result

    @staticmethod
    async def _simulate_boss(conn, guild_id: int, user_id: int, base_row) -> BossResult:
        level, xp, hp, max_hp, attack, defense, gold = map(int, base_row)
        event = current_weekly_event()
        
        from ..combat.equipment import equipped_profile
        from ..combat.skills import skill_profile
        
        profile = await equipped_profile(conn, guild_id, user_id)
        sprofile = await skill_profile(conn, guild_id, user_id)
        
        bonus_atk = int(profile["attack"])
        bonus_def = int(profile["defense"])
        bonus_hp = int(profile["hp"])
        lifesteal = float(profile["lifesteal"])
        crit_bonus = float(profile["crit_bonus"])
        damage_reduction = float(profile["damage_reduction"])
        equipped = profile["equipped"]
        active_set = profile.get("set_bonus")

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

        candidates = [b for b in BOSS_VARIANTS if int(b.get("min_level", 1)) <= level]
        boss = (candidates[-1] if candidates else BOSS_VARIANTS[0]).copy()
        boss_hp = int(boss["hp"]) + level * 12
        boss_atk = int(boss["atk"]) + level // 2
        boss_def = int(boss["def"]) + level // 4

        battle = CombatService._run_boss_phase(
            eff_hp, eff_atk, eff_def, eff_max_hp,
            lifesteal, crit_bonus, damage_reduction,
            boss_hp, boss_atk, boss_def,
        )

        win = int(battle["monster_hp"]) <= 0 and int(battle["player_hp"]) > 0
        battle_logs = battle.get("turn_logs", [])
        phase_events = battle.get("phase_events", [])

        if not win:
            remain_eff_hp = max(1, int(battle["player_hp"]))
            base_hp = max(1, min(max_hp, remain_eff_hp - bonus_hp))
            await player_repo.update_player_hp(conn, guild_id, user_id, base_hp)
            await telemetry_repo.record_combat_telemetry(
                conn, guild_id, "boss", level, False,
                turns=int(battle.get("turns", 0)),
                damage_dealt=int(battle.get("damage_dealt", 0)),
                damage_taken=int(battle.get("damage_taken", 0)),
            )
            return BossResult(
                ok=True, win=False,
                boss_id=boss.get("id", "ancient_ogre"), boss=boss["name"],
                base_hp=base_hp,
                equipped=equipped,
                logs=battle_logs,
                combat_effects=CombatEffects(lifesteal=lifesteal, crit_bonus=crit_bonus, damage_reduction=damage_reduction),
                set_bonus=str(active_set.get("name", "")) if active_set else "",
                passive_skills=list(sprofile.get("passives", [])),
                lifesteal_heal=int(battle.get("lifesteal_heal", 0)),
                damage_blocked=int(battle.get("damage_blocked", 0)),
                phase_events=phase_events,
                rage_triggered=bool(battle.get("rage_triggered", False)),
                shield_turns=int(battle.get("shield_turns", 0)),
                summon_count=int(battle.get("summon_count", 0)),
                weekly_event={"id": str(event.get("id", "")), "name": str(event.get("name", "Weekly Event"))},
            )

        reward_mult = 1.08 * float(event.get("boss_reward_mult", 1.0))
        base_gold, base_xp = roll_gold_xp({"gold": boss["gold"], "xp": boss["xp"]}, reward_mult=reward_mult)
        extra_gold = random.randint(40, 140) + int(event.get("boss_bonus_gold", 0))
        reward_gold = base_gold + extra_gold
        reward_xp = base_xp

        drops = roll_drops(boss, drop_mult=float(event.get("boss_drop_mult", 1.0)))
        for item_id, amount in drops.items():
            await inventory_repo.add_inventory(conn, guild_id, user_id, item_id, amount)

        remain_eff_hp = max(1, int(battle["player_hp"]))
        base_hp = max(1, min(max_hp, remain_eff_hp - bonus_hp))

        await player_repo.update_player_hp_gold(conn, guild_id, user_id, base_hp, reward_gold)
        await telemetry_repo.record_gold_flow(conn, guild_id, user_id, reward_gold, "boss_reward")
        await quest_repo.add_quest_progress(conn, guild_id, user_id, "boss_wins", 1)
        new_level, remain_xp, leveled_up = await player_repo.gain_xp_and_level(conn, guild_id, user_id, reward_xp)
        await telemetry_repo.record_combat_telemetry(
            conn, guild_id, "boss", level, True,
            gold=reward_gold, xp=reward_xp,
            turns=int(battle.get("turns", 0)),
            damage_dealt=int(battle.get("damage_dealt", 0)),
            damage_taken=int(battle.get("damage_taken", 0)),
            drop_qty=sum(int(v) for v in drops.values()),
        )

        return BossResult(
            ok=True, win=True,
            boss_id=boss.get("id", "ancient_ogre"), boss=boss["name"],
            gold=reward_gold, xp=reward_xp, drops=drops,
            base_hp=base_hp, leveled_up=leveled_up, level=new_level, xp_remain=remain_xp,
            logs=battle_logs,
            combat_effects=CombatEffects(lifesteal=lifesteal, crit_bonus=crit_bonus, damage_reduction=damage_reduction),
            set_bonus=str(active_set.get("name", "")) if active_set else "",
            passive_skills=list(sprofile.get("passives", [])),
            lifesteal_heal=int(battle.get("lifesteal_heal", 0)),
            damage_blocked=int(battle.get("damage_blocked", 0)),
            phase_events=phase_events,
            rage_triggered=bool(battle.get("rage_triggered", False)),
            shield_turns=int(battle.get("shield_turns", 0)),
            summon_count=int(battle.get("summon_count", 0)),
            weekly_event={"id": str(event.get("id", "")), "name": str(event.get("name", "Weekly Event"))},
        )

    @staticmethod
    def _run_boss_phase(
        player_hp: int, player_atk: int, player_def: int, player_max_hp: int,
        player_lifesteal: float, player_crit_bonus: float, player_damage_reduction: float,
        boss_hp: int, boss_atk: int, boss_def: int,
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
            "turns": turns, "player_hp": player_hp, "monster_hp": boss_hp,
            "turn_logs": turn_logs, "phase_events": phase_events,
            "rage_triggered": rage_triggered, "shield_turns": shield_turns, "summon_count": summon_count,
            "lifesteal_heal": total_lifesteal_heal, "damage_blocked": total_damage_blocked,
            "damage_dealt": total_damage_dealt, "damage_taken": total_damage_taken,
        }

    @staticmethod
    async def dungeon(guild_id: int, user_id: int) -> DungeonResult:
        async with BaseService.with_user_transaction(guild_id, user_id, "dungeon") as conn:
            await player_repo.ensure_player_ready(conn, guild_id, user_id)
            
            from ..db.db import cooldown_remain
            remain = await cooldown_remain(conn, guild_id, user_id, "dungeon")
            if remain > 0:
                return DungeonResult()

            result = await CombatService._simulate_dungeon(conn, guild_id, user_id)
            
            await telemetry_repo.set_cooldown(conn, guild_id, user_id, "dungeon", 3600)
            await conn.commit()
            
            return result

    @staticmethod
    async def _simulate_dungeon(conn, guild_id: int, user_id: int) -> DungeonResult:
        row = await player_repo.get_player_stats(conn, guild_id, user_id)
        if not row:
            return DungeonResult()

        level, xp, hp, max_hp, attack, defense, gold = map(int, row)
        event = current_weekly_event()
        
        from ..combat.equipment import equipped_profile
        from ..combat.skills import skill_profile
        
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
                candidates = [b for b in BOSS_VARIANTS if int(b.get("min_level", 1)) <= level]
                enemy = (candidates[-1] if candidates else BOSS_VARIANTS[0]).copy()
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
                player_hp=player_hp, player_atk=effective_attack, player_def=effective_defense,
                monster_hp=enemy_hp, monster_atk=enemy_atk, monster_def=enemy_def,
                monster_escape_turn=None, player_max_hp=effective_max_hp,
                player_lifesteal=lifesteal, player_crit_bonus=crit_bonus, player_damage_reduction=damage_reduction,
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

            drop_mult = (1.0 + floor * 0.1) * float(
                event.get("boss_drop_mult", 1.0) if floor == total_floors else event.get("hunt_drop_mult", 1.0)
            )
            rolled = roll_drops(reward_src, drop_mult=drop_mult)
            for item_id, amount in rolled.items():
                drops[item_id] = drops.get(item_id, 0) + amount
                await inventory_repo.add_inventory(conn, guild_id, user_id, item_id, amount)

            logs.append(f"Tầng {floor}: hạ {enemy_name} (+{g} gold, +{x} xp)")

        base_hp_after = max(1, min(max_hp, player_hp - bonus_hp_total))
        await player_repo.update_player_hp_gold(conn, guild_id, user_id, base_hp_after, total_gold)
        await telemetry_repo.record_gold_flow(conn, guild_id, user_id, total_gold, "dungeon_reward")
        new_level, remain_xp, leveled_up = await player_repo.gain_xp_and_level(conn, guild_id, user_id, total_xp)
        await telemetry_repo.record_combat_telemetry(
            conn, guild_id, "dungeon", level, floors_cleared == total_floors,
            gold=total_gold, xp=total_xp, turns=total_turns,
            damage_dealt=total_damage_dealt, damage_taken=total_damage_taken,
            drop_qty=sum(int(v) for v in drops.values()),
        )

        return DungeonResult(
            ok=True,
            cleared=floors_cleared == total_floors,
            floors_cleared=floors_cleared,
            total_floors=total_floors,
            gold=total_gold, xp=total_xp, drops=drops,
            hp=base_hp_after, level=new_level, xp_remain=remain_xp, leveled_up=leveled_up,
            logs=logs,
            combat_effects=CombatEffects(lifesteal=lifesteal, crit_bonus=crit_bonus, damage_reduction=damage_reduction),
            set_bonus=str((eprofile.get("set_bonus") or {}).get("name", "")),
            passive_skills=list(sprofile.get("passives", [])),
            lifesteal_heal=total_lifesteal_heal,
            damage_blocked=total_damage_blocked,
            weekly_event={"id": str(event.get("id", "")), "name": str(event.get("name", "Weekly Event"))},
        )

    @staticmethod
    async def party_hunt(guild_id: int, user_ids: list[int]) -> PartyHuntResult:
        async with BaseService.with_multi_user_transaction(guild_id, user_ids, "party_hunt") as conn:
            for uid in user_ids:
                await player_repo.ensure_player_ready(conn, guild_id, uid)
            
            from ..db.db import cooldown_remain
            for uid in user_ids:
                remain = await cooldown_remain(conn, guild_id, uid, "party_hunt")
                if remain > 0:
                    return PartyHuntResult()

            result = await CombatService._simulate_party_hunt(conn, guild_id, user_ids)
            
            for uid in user_ids:
                await telemetry_repo.set_cooldown(conn, guild_id, uid, "party_hunt", 1200)
            await conn.commit()
            
            return result

    @staticmethod
    async def _simulate_party_hunt(conn, guild_id: int, user_ids: list[int]) -> PartyHuntResult:
        event = current_weekly_event()
        
        from ..combat.equipment import equipped_profile
        from ..combat.skills import skill_profile
        
        members: list[dict] = []
        for uid in user_ids:
            row = await player_repo.get_player_stats(conn, guild_id, uid)
            if not row:
                continue
            level, xp, hp, max_hp, attack, defense, gold = map(int, row)
            eprofile = await equipped_profile(conn, guild_id, uid)
            sprofile = await skill_profile(conn, guild_id, uid)

            bonus_hp = int(eprofile["hp"]) + int(sprofile["hp"])
            max_eff_hp = max_hp + bonus_hp
            members.append({
                "user_id": uid, "level": level, "base_max_hp": max_hp, "bonus_hp": bonus_hp,
                "hp": min(max_eff_hp, hp + bonus_hp), "max_eff_hp": max_eff_hp,
                "atk": attack + int(eprofile["attack"]) + int(sprofile["attack"]),
                "def": defense + int(eprofile["defense"]) + int(sprofile["defense"]),
                "crit": float(eprofile["crit_bonus"]) + float(sprofile["crit_bonus"]),
                "dr": float(eprofile["damage_reduction"]) + float(sprofile["damage_reduction"]),
                "ls": float(eprofile["lifesteal"]) + float(sprofile["lifesteal"]),
                "alive": True, "kills": 0, "dealt": 0, "taken": 0,
            })

        if len(members) < 2:
            return PartyHuntResult()

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

        n = len(members)
        gold_each = total_gold // n
        xp_each = total_xp // n

        member_results: list[dict] = []
        for m in members:
            uid = int(m["user_id"])
            bonus_hp = int(m["bonus_hp"])
            base_hp_after = max(1, min(int(m["base_max_hp"]), int(m["hp"]) - bonus_hp))

            await player_repo.update_player_hp_gold(conn, guild_id, uid, base_hp_after, gold_each)
            await telemetry_repo.record_gold_flow(conn, guild_id, uid, gold_each, "party_hunt_reward")
            new_level, _, leveled_up = await player_repo.gain_xp_and_level(conn, guild_id, uid, xp_each)
            await quest_repo.add_quest_progress(conn, guild_id, uid, "hunt_runs", 1)
            await quest_repo.add_quest_progress(conn, guild_id, uid, "kill_monsters", int(m["kills"]))

            member_results.append({
                "user_id": uid, "hp": base_hp_after, "gold": gold_each, "xp": xp_each,
                "kills": int(m["kills"]), "dealt": int(m["dealt"]), "taken": int(m["taken"]),
                "level": int(new_level), "leveled_up": bool(leveled_up),
            })

        receivers = [m for m in members if m["alive"]] or members
        for item_id, amount in drops.items():
            for _ in range(int(amount)):
                r = random.choice(receivers)
                await inventory_repo.add_inventory(conn, guild_id, int(r["user_id"]), item_id, 1)

        return PartyHuntResult(
            ok=True, pack=pack, kills=kills,
            gold=total_gold, xp=total_xp, drops=drops, logs=logs,
            members=member_results,
            weekly_event={"id": str(event.get("id", "")), "name": str(event.get("name", "Weekly Event"))},
        )
