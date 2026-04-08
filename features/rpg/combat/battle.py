import random
from typing import Any

from ..data.data import RPG_DAMAGE_REDUCTION_CAP, RPG_LIFESTEAL_HEAL_CAP, RPG_CRIT_CAP
from ..data.data import RPG_DAMAGE_VAR_MIN, RPG_DAMAGE_VAR_MAX, RPG_CRIT_CHANCE, RPG_CRIT_MULT, RPG_CRIT_CAP
from ..data.characters import PASSIVE_SKILLS, ROLE_SYNERGY


def normalize_role(role: str) -> str:
    r = str(role or "").strip().lower()
    if r in {"sp", "support"}:
        return "support"
    return r


def roll_damage(atk: int, defense: int, crit_bonus: float = 0.0) -> tuple[int, bool]:
    base_damage = atk * (100 / (100 + max(0, defense))) + random.randint(RPG_DAMAGE_VAR_MIN, RPG_DAMAGE_VAR_MAX)
    damage = max(1, int(base_damage))
    
    crit_chance = min(RPG_CRIT_CAP, max(0.0, RPG_CRIT_CHANCE + max(0.0, float(crit_bonus))))
    is_crit = random.random() < crit_chance
    if is_crit:
        damage = int(damage * RPG_CRIT_MULT)
    return damage, is_crit


def run_battle_turns(
    player_hp: int,
    player_atk: int,
    player_def: int,
    monster_hp: int,
    monster_atk: int,
    monster_def: int,
    monster_escape_turn: int | None,
    player_max_hp: int | None = None,
    player_lifesteal: float = 0.0,
    player_crit_bonus: float = 0.0,
    player_damage_reduction: float = 0.0,
):
    turns = 0
    escaped = False
    turn_logs: list[str] = []
    max_player_hp = int(player_max_hp) if player_max_hp is not None else int(player_hp)
    lifesteal = max(0.0, float(player_lifesteal))
    crit_bonus = max(0.0, float(player_crit_bonus))
    damage_reduction = min(RPG_DAMAGE_REDUCTION_CAP, max(0.0, float(player_damage_reduction)))
    total_lifesteal_heal = 0
    total_damage_blocked = 0
    total_damage_dealt = 0
    total_damage_taken = 0

    while monster_hp > 0 and player_hp > 0:
        turns += 1
        dealt, is_crit = roll_damage(player_atk, monster_def, crit_bonus=crit_bonus)
        total_damage_dealt += max(0, int(dealt))
        monster_hp -= dealt
        crit_str = " (CRIT)" if is_crit else ""
        turn_logs.append(f"Turn {turns}: ban ghe {dealt} dmg{crit_str}")

        if lifesteal > 0 and dealt > 0 and player_hp > 0:
            raw_heal = int(dealt * lifesteal)
            max_heal = int(max_player_hp * RPG_LIFESTEAL_HEAL_CAP)
            heal = min(raw_heal, max_heal)
            if heal > 0 and player_hp < max_player_hp:
                old_hp = player_hp
                player_hp = min(max_player_hp, player_hp + heal)
                healed = max(0, player_hp - old_hp)
                if healed > 0:
                    total_lifesteal_heal += healed
                    turn_logs.append(f"Turn {turns}: lifesteal hoi {healed} HP")

        if monster_hp <= 0:
            turn_logs.append(f"Turn {turns}: quai guc")
            break

        if monster_escape_turn is not None and turns > monster_escape_turn:
            escaped = True
            turn_logs.append(f"Turn {turns}: quai bo chay")
            break

        taken, enemy_crit = roll_damage(monster_atk, player_def)
        blocked = int(taken * damage_reduction) if damage_reduction > 0 else 0
        final_taken = max(1, taken - blocked) if taken > 0 else 0
        total_damage_taken += max(0, int(final_taken))
        player_hp -= final_taken
        total_damage_blocked += max(0, blocked)
        crit_str = " (CRIT)" if enemy_crit else ""
        block_str = f" (giam {blocked})" if blocked > 0 else ""
        turn_logs.append(f"Turn {turns}: ban nhan {final_taken} dmg{crit_str}{block_str}")

    return {
        "turns": turns,
        "escaped": escaped,
        "player_hp": player_hp,
        "monster_hp": monster_hp,
        "turn_logs": turn_logs,
        "lifesteal_heal": total_lifesteal_heal,
        "damage_blocked": total_damage_blocked,
        "damage_dealt": total_damage_dealt,
        "damage_taken": total_damage_taken,
    }


class TeamMember:
    def __init__(self, char_id: str, name: str, role: str, hp: int, atk: int, def_: int, speed: int, 
                 level: int = 1, star: int = 1, passive_skill: str = ""):
        self.char_id = char_id
        self.name = name
        self.role = normalize_role(role)
        self.max_hp = int(hp * (1 + (level - 1) * 0.1) * (1 + (star - 1) * 0.2))
        self.current_hp = self.max_hp
        self.atk = int(atk * (1 + (level - 1) * 0.1) * (1 + (star - 1) * 0.2))
        self.def_ = int(def_ * (1 + (level - 1) * 0.1) * (1 + (star - 1) * 0.2))
        self.speed = speed
        self.level = level
        self.star = star
        self.passive_skill = passive_skill

    def is_alive(self) -> bool:
        return self.current_hp > 0

    def take_damage(self, dmg: int) -> int:
        actual = max(1, dmg - self.def_ // 2)
        self.current_hp = max(0, self.current_hp - actual)
        return actual


def run_team_battle(
    team: list[dict[str, Any]],
    monster_hp: int,
    monster_atk: int,
    monster_def: int,
) -> dict[str, Any]:
    members = [
        TeamMember(
            char_id=t.get("character_id", ""),
            name=t.get("name", "Unknown"),
            role=t.get("role", "dps"),
            hp=t.get("hp", 100),
            atk=t.get("attack", 10),
            def_=t.get("defense", 5),
            speed=t.get("speed", 10),
            level=t.get("level", 1),
            star=t.get("star", 1),
            passive_skill=t.get("passive_skill", ""),
        )
        for t in team
    ]
    members = [m for m in members if m.is_alive()]
    
    if not members:
        return {"win": False, "turns": 0, "team_hp": 0, "monster_hp": monster_hp, "logs": ["Team dead"]}
    
    roles = [str(m.role).lower() for m in members if m.is_alive()]
    synergy_bonus_atk = 0.0
    synergy_bonus_def = 0.0
    synergy_bonus_heal = 0.0
    synergy_notes: list[str] = []

    for i, r1 in enumerate(roles):
        for j in range(i + 1, len(roles)):
            r2 = roles[j]
            key = (r1, r2)
            if key not in ROLE_SYNERGY:
                key = (r2, r1)
            if key not in ROLE_SYNERGY:
                continue
            syn = ROLE_SYNERGY[key]
            synergy_bonus_atk += float(syn.get("dmg_bonus", 0.0))
            synergy_bonus_def += float(syn.get("def_bonus", 0.0))
            synergy_bonus_heal += float(syn.get("heal_bonus", 0.0))
            desc = str(syn.get("desc", "")).strip()
            if desc:
                synergy_notes.append(desc)

    synergy_bonus_atk = min(0.35, synergy_bonus_atk)
    synergy_bonus_def = min(0.35, synergy_bonus_def)
    synergy_bonus_heal = min(0.45, synergy_bonus_heal)
    
    total_team_hp = sum(m.max_hp for m in members)
    
    for m in members:
        m._crit_bonus = 0.0
        m._lifesteal = 0.0
        m._reduction = 0.0
        m._heal_power = 0.0
        m._double_strike = 0.0
        m._is_support = str(m.role).lower() == "support"

        if m.passive_skill and m.passive_skill in PASSIVE_SKILLS:
            ps = PASSIVE_SKILLS[m.passive_skill]
            stat = str(ps.get("stat", "")).lower()
            bonus = float(ps.get("bonus", 0.0))
            if stat == "attack":
                m.atk = int(m.atk * (1 + bonus))
            elif stat == "defense":
                m.def_ = int(m.def_ * (1 + bonus))
            elif stat == "crit":
                m._crit_bonus += bonus
            elif stat == "lifesteal":
                m._lifesteal += bonus
            elif stat == "reduction":
                m._reduction += bonus
            elif stat == "heal":
                m._heal_power += bonus
            elif stat == "double":
                m._double_strike += bonus

        if m._is_support:
            m._crit_bonus += 0.02
            m._heal_power += 0.05
            m._reduction += 0.03
    
    turns = 0
    logs = []
    total_damage_dealt = 0
    total_damage_taken = 0
    alive = [m for m in members if m.is_alive()]
    
    while monster_hp > 0 and alive:
        turns += 1
        alive.sort(key=lambda m: m.speed, reverse=True)
        
        for m in alive:
            if not m.is_alive() or monster_hp <= 0:
                break
            
            crit_bonus = float(m._crit_bonus)
            if m.passive_skill == "fury" and m.current_hp > m.max_hp * 0.5:
                crit_bonus += 0.1

            hit_count = 2 if random.random() < min(0.5, m._double_strike) else 1
            turn_dealt = 0
            for _ in range(hit_count):
                dealt, is_crit = roll_damage(
                    int(m.atk * (1 + synergy_bonus_atk)),
                    monster_def,
                    crit_bonus=crit_bonus,
                )
                total_damage_dealt += dealt
                turn_dealt += dealt
                monster_hp -= dealt
                crit_str = " (CRIT)" if is_crit else ""
                logs.append(f"{m.name} attacks {dealt} dmg{crit_str}")
                if monster_hp <= 0:
                    break

            if m._lifesteal > 0 and m.current_hp < m.max_hp and turn_dealt > 0:
                heal = int(turn_dealt * min(0.25, m._lifesteal))
                if heal > 0:
                    m.current_hp = min(m.max_hp, m.current_hp + heal)
                    logs.append(f"{m.name} heals {heal} HP")
            
            if monster_hp <= 0:
                break
        
        if monster_hp <= 0:
            logs.append("Monster defeated!")
            break
        
        for m in alive:
            if not m.is_alive():
                continue
            dmg_reduction = min(0.65, synergy_bonus_def + float(m._reduction))
            
            taken, _ = roll_damage(monster_atk, m.def_)
            blocked = int(taken * dmg_reduction) if dmg_reduction > 0 else 0
            actual = max(1, taken - blocked)
            total_damage_taken += actual
            m.take_damage(actual)
            block_str = f" (blocked {blocked})" if blocked > 0 else ""
            logs.append(f"{m.name} takes {actual} dmg{block_str}")
        
        alive = [m for m in members if m.is_alive()]
        
        for m in alive:
            if m.passive_skill == "heal_team" or m.passive_skill == "mass_heal" or m._is_support:
                heal_ratio = 0.22 + float(m._heal_power)
                heal_amt = int(m.atk * heal_ratio * (1 + synergy_bonus_heal))
                for tm in alive:
                    if tm.current_hp < tm.max_hp:
                        old = tm.current_hp
                        tm.current_hp = min(tm.max_hp, tm.current_hp + heal_amt)
                        logs.append(f"{m.name} heals team {tm.current_hp - old} HP")
    
    win = monster_hp <= 0 and bool(alive)
    final_team_hp = sum(m.current_hp for m in members)
    
    return {
        "win": win,
        "turns": turns,
        "team_hp": final_team_hp,
        "total_team_hp": total_team_hp,
        "monster_hp": max(0, monster_hp),
        "logs": logs,
        "damage_dealt": total_damage_dealt,
        "damage_taken": total_damage_taken,
        "synergy_notes": list(dict.fromkeys(synergy_notes))[:3],
        "team_members": [
            {
                "name": m.name,
                "role": m.role,
                "hp": m.current_hp,
                "max_hp": m.max_hp,
                "alive": m.is_alive(),
            }
            for m in members
        ],
    }
