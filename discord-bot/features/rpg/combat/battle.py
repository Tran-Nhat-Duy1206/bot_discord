from ..data.data import roll_damage


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
    lifesteal = max(0.0, min(0.9, float(player_lifesteal)))
    crit_bonus = max(0.0, float(player_crit_bonus))
    damage_reduction = max(0.0, min(0.85, float(player_damage_reduction)))
    total_lifesteal_heal = 0
    total_damage_blocked = 0
    total_damage_dealt = 0
    total_damage_taken = 0

    while monster_hp > 0 and player_hp > 0:
        turns += 1
        dealt, is_crit = roll_damage(player_atk, monster_def, crit_bonus=crit_bonus)
        total_damage_dealt += max(0, int(dealt))
        monster_hp -= dealt
        turn_logs.append(f"Turn {turns}: bạn gây {dealt} dmg{' (CRIT)' if is_crit else ''}")

        if lifesteal > 0 and dealt > 0 and player_hp > 0:
            heal = int(dealt * lifesteal)
            if heal > 0 and player_hp < max_player_hp:
                old_hp = player_hp
                player_hp = min(max_player_hp, player_hp + heal)
                healed = max(0, player_hp - old_hp)
                if healed > 0:
                    total_lifesteal_heal += healed
                    turn_logs.append(f"Turn {turns}: lifesteal hồi {healed} HP")

        if monster_hp <= 0:
            turn_logs.append(f"Turn {turns}: quái gục")
            break

        if monster_escape_turn is not None and turns > monster_escape_turn:
            escaped = True
            turn_logs.append(f"Turn {turns}: quái bỏ chạy")
            break

        taken, enemy_crit = roll_damage(monster_atk, player_def)
        blocked = int(taken * damage_reduction) if damage_reduction > 0 else 0
        final_taken = max(1, taken - blocked) if taken > 0 else 0
        total_damage_taken += max(0, int(final_taken))
        player_hp -= final_taken
        total_damage_blocked += max(0, blocked)
        turn_logs.append(
            f"Turn {turns}: bạn nhận {final_taken} dmg"
            f"{' (CRIT)' if enemy_crit else ''}"
            f"{' (giảm ' + str(blocked) + ')' if blocked > 0 else ''}"
        )

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
