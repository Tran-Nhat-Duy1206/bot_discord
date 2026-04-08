import random


NODE_WEIGHTS = {
    "normal": {
        "combat": 50,
        "elite": 12,
        "event": 14,
        "sanctuary": 10,
        "merchant": 8,
        "curse": 6,
    },
    "hard": {
        "combat": 45,
        "elite": 16,
        "event": 12,
        "sanctuary": 8,
        "merchant": 7,
        "curse": 12,
    },
    "nightmare": {
        "combat": 40,
        "elite": 20,
        "event": 10,
        "sanctuary": 6,
        "merchant": 6,
        "curse": 18,
    },
}


def _choices_count(floor: int, difficulty: str) -> int:
    if floor % 4 == 0:
        return 2
    if str(difficulty) == "nightmare":
        return 2
    return 3


def _weighted_pick(rng: random.Random, weights: dict[str, int]) -> str:
    pool = []
    for key, w in weights.items():
        pool.extend([key] * max(1, int(w)))
    return rng.choice(pool)


def _danger_for(node_type: str, floor: int, difficulty: str, rng: random.Random) -> int:
    base = max(1, floor // 2)
    if node_type == "elite":
        base += 2
    elif node_type == "curse":
        base += 2
    elif node_type == "sanctuary":
        base = max(1, base - 1)
    if difficulty == "hard":
        base += 1
    if difficulty == "nightmare":
        base += 2
    return max(1, min(10, base + rng.randint(0, 1)))


def generate_floor_nodes(total_floors: int, seed: int, difficulty: str) -> list[dict]:
    rng = random.Random(int(seed))
    diff = str(difficulty or "normal").lower()
    weights = NODE_WEIGHTS.get(diff, NODE_WEIGHTS["normal"])

    nodes: list[dict] = []
    for floor in range(1, max(2, int(total_floors)) + 1):
        if floor == total_floors:
            nodes.append(
                {
                    "floor": floor,
                    "node_id": f"F{floor}-BOSS",
                    "node_type": "boss_gate",
                    "danger": 10,
                    "payload": {"boss_tier": "final", "floor": floor},
                }
            )
            continue

        count = _choices_count(floor, diff)
        for idx in range(count):
            node_type = _weighted_pick(rng, weights)
            danger = _danger_for(node_type, floor, diff, rng)
            payload = {
                "floor": floor,
                "enemy_tier": "elite" if node_type == "elite" else "normal",
                "reward_mult": 1.0 + (danger * 0.03),
                "risk": max(0, danger - 3),
            }
            nodes.append(
                {
                    "floor": floor,
                    "node_id": f"F{floor}-{idx + 1}",
                    "node_type": node_type,
                    "danger": danger,
                    "payload": payload,
                }
            )
    return nodes


def build_choice_bundle(floor: int, rng_seed: int) -> dict:
    rng = random.Random(int(rng_seed) + int(floor) * 97)
    options = [
        {
            "choice_id": "campfire",
            "title": "Campfire",
            "effect": {"heal_pct": 0.25, "reward_mult_loss": 0.05},
            "tradeoff": "Heal squad but reduce final reward multiplier.",
        },
        {
            "choice_id": "war_ritual",
            "title": "War Ritual",
            "effect": {"atk_buff_pct": 0.15, "max_hp_loss_pct": 0.10, "duration_floors": 2},
            "tradeoff": "Gain burst power but lower max HP.",
        },
        {
            "choice_id": "forbidden_pact",
            "title": "Forbidden Pact",
            "effect": {"gain_relic": 1, "add_curse": 1},
            "tradeoff": "Immediate power with future curse pressure.",
        },
        {
            "choice_id": "scavenge",
            "title": "Scavenge",
            "effect": {"supply": 30, "ambush_chance": 0.30},
            "tradeoff": "Gain supply but risk ambush.",
        },
        {
            "choice_id": "purify",
            "title": "Purify",
            "effect": {"remove_curse": 1},
            "tradeoff": "Remove a curse but gain no combat power.",
        },
    ]
    rng.shuffle(options)
    return {"floor": floor, "options": options[:3]}
