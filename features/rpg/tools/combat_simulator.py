import random
from dataclasses import dataclass
from typing import Optional

from ..data import (
    ITEMS, MONSTERS, BOSS_VARIANTS,
    RPG_CRIT_CHANCE, RPG_CRIT_MULT, RPG_DAMAGE_VAR_MIN, RPG_DAMAGE_VAR_MAX,
    RPG_DAMAGE_REDUCTION_CAP, RPG_LIFESTEAL_HEAL_CAP,
)


@dataclass
class PlayerSnapshot:
    level: int
    hp: int
    max_hp: int
    attack: int
    defense: int
    crit_bonus: float = 0.0
    damage_reduction: float = 0.0
    lifesteal: float = 0.0
    bonus_attack: int = 0
    bonus_defense: int = 0
    bonus_hp: int = 0


@dataclass
class MonsterSnapshot:
    name: str
    hp: int
    attack: int
    defense: int
    escape_turn: Optional[int] = None


@dataclass
class BattleResult:
    win: bool
    turns: int
    player_hp: int
    monster_hp: int
    damage_dealt: int
    damage_taken: int
    lifesteal_heal: int
    escaped: bool = False


def roll_damage(atk: int, defense: int, crit_bonus: float = 0.0) -> tuple[int, bool]:
    base_damage = atk * (100 / (100 + max(0, defense))) + random.randint(RPG_DAMAGE_VAR_MIN, RPG_DAMAGE_VAR_MAX)
    damage = max(1, int(base_damage))
    
    crit_chance = min(0.85, max(0.0, RPG_CRIT_CHANCE + max(0.0, crit_bonus)))
    is_crit = random.random() < crit_chance
    if is_crit:
        damage = int(damage * RPG_CRIT_MULT)
    return damage, is_crit


def build_player_snapshot(
    level: int,
    base_attack: int = 12,
    base_defense: int = 6,
    base_max_hp: int = 100,
    bonus_attack: int = 0,
    bonus_defense: int = 0,
    bonus_hp: int = 0,
    crit_bonus: float = 0.0,
    damage_reduction: float = 0.0,
    lifesteal: float = 0.0,
) -> PlayerSnapshot:
    return PlayerSnapshot(
        level=level,
        hp=base_max_hp + bonus_hp,
        max_hp=base_max_hp + bonus_hp,
        attack=base_attack + bonus_attack,
        defense=base_defense + bonus_defense,
        crit_bonus=crit_bonus,
        damage_reduction=min(RPG_DAMAGE_REDUCTION_CAP, max(0.0, damage_reduction)),
        lifesteal=lifesteal,
        bonus_attack=bonus_attack,
        bonus_defense=bonus_defense,
        bonus_hp=bonus_hp,
    )


def build_monster_snapshot(
    monster_data: dict,
    level_bonus: int = 0,
) -> MonsterSnapshot:
    return MonsterSnapshot(
        name=str(monster_data.get("name", "Unknown")),
        hp=int(monster_data.get("hp", 50)) + level_bonus * 2,
        attack=int(monster_data.get("atk", 10)),
        defense=int(monster_data.get("def", 3)),
        escape_turn=int(monster_data.get("escape_turn", 0)) if monster_data.get("escape_turn") else None,
    )


def simulate_single_battle(
    player: PlayerSnapshot,
    monster: MonsterSnapshot,
) -> BattleResult:
    p_hp = player.hp
    m_hp = monster.hp
    turns = 0
    damage_dealt = 0
    damage_taken = 0
    lifesteal_heal = 0
    escaped = False
    
    while p_hp > 0 and m_hp > 0:
        turns += 1
        
        dealt, _ = roll_damage(player.attack, monster.defense, player.crit_bonus)
        dealt = max(1, dealt)
        m_hp -= dealt
        damage_dealt += dealt
        
        if player.lifesteal > 0 and dealt > 0:
            raw_heal = int(dealt * player.lifesteal)
            max_heal = int(player.max_hp * RPG_LIFESTEAL_HEAL_CAP)
            heal = min(raw_heal, max_heal)
            if heal > 0 and p_hp < player.max_hp:
                p_hp = min(player.max_hp, p_hp + heal)
                lifesteal_heal += heal
        
        if m_hp <= 0:
            break
        
        if monster.escape_turn and turns > monster.escape_turn:
            escaped = True
            break
        
        taken, _ = roll_damage(monster.attack, player.defense)
        reduced = int(taken * player.damage_reduction) if player.damage_reduction > 0 else 0
        final_taken = max(1, taken - reduced)
        p_hp -= final_taken
        damage_taken += final_taken
    
    return BattleResult(
        win=m_hp <= 0 and p_hp > 0,
        turns=turns,
        player_hp=max(0, p_hp),
        monster_hp=max(0, m_hp),
        damage_dealt=damage_dealt,
        damage_taken=damage_taken,
        lifesteal_heal=lifesteal_heal,
        escaped=escaped,
    )


def simulate_multiple_battles(
    player: PlayerSnapshot,
    monster: MonsterSnapshot,
    runs: int = 1000,
) -> dict:
    wins = 0
    escapes = 0
    total_turns = 0
    total_damage_dealt = 0
    total_damage_taken = 0
    total_lifesteal_heal = 0
    
    for _ in range(runs):
        result = simulate_single_battle(player, monster)
        if result.win:
            wins += 1
        if result.escaped:
            escapes += 1
        total_turns += result.turns
        total_damage_dealt += result.damage_dealt
        total_damage_taken += result.damage_taken
        total_lifesteal_heal += result.lifesteal_heal
    
    return {
        "monster": monster.name,
        "monster_hp": monster.hp,
        "monster_atk": monster.attack,
        "monster_def": monster.defense,
        "runs": runs,
        "wins": wins,
        "escapes": escapes,
        "losses": runs - wins - escapes,
        "winrate": wins / runs,
        "escape_rate": escapes / runs,
        "avg_turns": total_turns / runs,
        "avg_damage_dealt": total_damage_dealt / runs,
        "avg_damage_taken": total_damage_taken / runs,
        "avg_lifesteal_heal": total_lifesteal_heal / runs,
    }


def analyze_balance(
    player: PlayerSnapshot,
    monsters: list[MonsterSnapshot],
    runs: int = 1000,
) -> list[dict]:
    results = []
    
    for monster in monsters:
        stats = simulate_multiple_battles(player, monster, runs)
        
        winrate = stats["winrate"]
        if winrate > 0.85:
            status = "TOO EASY"
        elif winrate > 0.70:
            status = "EASY"
        elif winrate < 0.15:
            status = "TOO HARD"
        elif winrate < 0.40:
            status = "HARD"
        else:
            status = "BALANCED"
        
        results.append({
            "monster": monster.name,
            "monster_hp": monster.hp,
            "monster_atk": monster.attack,
            "monster_def": monster.defense,
            "winrate": winrate,
            "escape_rate": stats["escape_rate"],
            "avg_turns": stats["avg_turns"],
            "status": status,
        })
    
    return results


def get_level_progress(level: int) -> tuple[int, int, int, int]:
    base_hp = 100 + (level - 1) * 12
    base_attack = 12 + (level - 1) * 2
    base_defense = 6 + (level - 1) * 1
    return base_hp, base_attack, base_defense, level


def create_test_player(level: int) -> PlayerSnapshot:
    base_hp, base_atk, base_def, _ = get_level_progress(level)
    return build_player_snapshot(
        level=level,
        base_attack=base_atk,
        base_defense=base_def,
        base_max_hp=base_hp,
    )


def create_test_monsters() -> list[MonsterSnapshot]:
    monsters = []
    for m in MONSTERS:
        monsters.append(build_monster_snapshot(m))
    for b in BOSS_VARIANTS:
        monsters.append(build_monster_snapshot(b, level_bonus=10))
    return monsters


def run_balance_check(player_level: int = 10, runs: int = 1000) -> list[dict]:
    player = create_test_player(player_level)
    monsters = create_test_monsters()
    return analyze_balance(player, monsters, runs)


def print_balance_report(player_level: int = 10, runs: int = 1000) -> None:
    print(f"\n{'='*60}")
    print(f"COMBAT BALANCE REPORT - Player Level {player_level}")
    print(f"{'='*60}")
    
    results = run_balance_check(player_level, runs)
    
    easy_count = 0
    balanced_count = 0
    hard_count = 0
    
    for r in results:
        status_emoji = {
            "TOO EASY": "🟢",
            "EASY": "🟢",
            "BALANCED": "🟡",
            "HARD": "🔴",
            "TOO HARD": "🔴",
        }.get(r["status"], "⚪")
        
        print(f"\n{status_emoji} {r['monster']}")
        print(f"   HP: {r['monster_hp']} | ATK: {r['monster_atk']} | DEF: {r['monster_def']}")
        print(f"   Winrate: {r['winrate']:.1%} | Escape: {r['escape_rate']:.1%} | Turns: {r['avg_turns']:.1f}")
        print(f"   Status: {r['status']}")
        
        if r["status"] in ("TOO EASY", "EASY"):
            easy_count += 1
        elif r["status"] == "BALANCED":
            balanced_count += 1
        else:
            hard_count += 1
    
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"Easy: {easy_count} | Balanced: {balanced_count} | Hard: {hard_count}")
    print(f"Total monsters tested: {len(results)}")


if __name__ == "__main__":
    import sys
    level = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
    print_balance_report(level, runs)
