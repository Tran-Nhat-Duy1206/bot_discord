import random

from ..data import ITEMS


DIFF_REWARD = {
    "normal": 1.0,
    "hard": 1.35,
    "nightmare": 1.8,
}


def _pick_item(rng: random.Random) -> str:
    rarity_weight = [
        ("common", 55),
        ("uncommon", 20),
        ("rare", 13),
        ("epic", 8),
        ("legendary", 4),
    ]
    bucket = []
    for rarity, w in rarity_weight:
        bucket.extend([rarity] * w)
    target = rng.choice(bucket)
    candidates = [iid for iid, meta in ITEMS.items() if str(meta.get("rarity", "common")).lower() == target]
    if not candidates:
        return "potion"
    return rng.choice(candidates)


def compute_run_rewards(
    difficulty: str,
    floors_cleared: int,
    total_floors: int,
    risk_score: int,
    score: int,
    status: str,
    seed: int,
) -> dict:
    diff = str(difficulty or "normal").lower()
    diff_mult = float(DIFF_REWARD.get(diff, 1.0))
    progress = max(0.0, min(1.0, float(floors_cleared) / max(1, int(total_floors))))
    cleared_bonus = 1.25 if str(status) == "completed" else 1.0
    retreat_penalty = 0.65 if str(status) == "retreated" else 1.0

    base_gold = int((120 + floors_cleared * 35 + risk_score * 18) * diff_mult * cleared_bonus * retreat_penalty)
    base_xp = int((80 + floors_cleared * 25 + max(0, score // 10)) * diff_mult * cleared_bonus * retreat_penalty)
    rank_points = int((floors_cleared * 12 + risk_score * 8 + max(0, score // 15)) * (1.0 if status != "failed" else 0.3))

    rng = random.Random(int(seed) + int(score) + int(floors_cleared) * 31)
    drops: dict[str, int] = {}
    rolls = max(1, int(1 + floors_cleared / 3))
    if status == "completed":
        rolls += 2
    for _ in range(rolls):
        iid = _pick_item(rng)
        drops[iid] = drops.get(iid, 0) + 1

    shard_roll = int(progress * (2 if diff == "nightmare" else 1))
    shards = {"universal_shard": max(0, shard_roll)} if shard_roll > 0 else {}
    return {
        "gold": max(0, base_gold),
        "xp": max(0, base_xp),
        "items": drops,
        "shards": shards,
        "rank_points": max(0, rank_points),
    }
