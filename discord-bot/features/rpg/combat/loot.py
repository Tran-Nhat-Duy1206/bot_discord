import random


def roll_gold_xp(monster: dict, reward_mult: float = 1.0) -> tuple[int, int]:
    gold = random.randint(int(monster["gold"][0]), int(monster["gold"][1]))
    xp = random.randint(int(monster["xp"][0]), int(monster["xp"][1]))
    if reward_mult != 1.0:
        gold = max(1, int(gold * reward_mult))
        xp = max(1, int(xp * reward_mult))
    return gold, xp


def roll_drops(monster: dict, drop_mult: float = 1.0) -> dict[str, int]:
    drops: dict[str, int] = {}
    for item_id, chance in monster.get("drops", []):
        final_chance = min(0.95, max(0.0, float(chance) * max(0.1, drop_mult)))
        if random.random() <= final_chance:
            drops[item_id] = drops.get(item_id, 0) + 1
    return drops
