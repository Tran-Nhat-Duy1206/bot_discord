MONSTERS: list[dict] = [
    {
        "id": "goblin",
        "name": "Goblin",
        "hp": 45,
        "atk": 10,
        "def": 3,
        "chance": 38,
        "xp": (16, 24),
        "gold": (15, 25),
        "drops": [("potion", 0.14)],
    },
    {
        "id": "skeleton",
        "name": "Skeleton",
        "hp": 62,
        "atk": 13,
        "def": 4,
        "chance": 33,
        "xp": (22, 33),
        "gold": (20, 32),
        "drops": [("potion", 0.2), ("lootbox", 0.04)],
    },
    {
        "id": "wolf",
        "name": "Wolf",
        "hp": 56,
        "atk": 15,
        "def": 4,
        "chance": 27,
        "xp": (24, 36),
        "gold": (24, 38),
        "drops": [("potion", 0.12)],
    },
    {
        "id": "slime",
        "name": "Slime Jackpot",
        "hp": 18,
        "atk": 6,
        "def": 1,
        "chance": 2,
        "xp": (75, 120),
        "gold": (150, 280),
        "drops": [("rare_crystal", 0.58), ("lootbox", 0.3), ("mega_potion", 0.22)],
        "escape_turn": 3,
    },
]


BOSS_MONSTER: dict = {
    "id": "ancient_ogre",
    "name": "Ancient Ogre",
    "hp": 360,
    "atk": 32,
    "def": 12,
    "xp": (210, 340),
    "gold": (250, 430),
    "drops": [("rare_crystal", 0.65), ("lootbox", 0.35), ("mega_potion", 0.3)],
}


BOSS_VARIANTS: list[dict] = [
    {
        "id": "ancient_ogre",
        "name": "Ancient Ogre",
        "hp": 360,
        "atk": 32,
        "def": 12,
        "chance": 30,
        "xp": (210, 340),
        "gold": (250, 430),
        "drops": [("rare_crystal", 0.65), ("lootbox", 0.35), ("mega_potion", 0.3)],
    },
    {
        "id": "ogre_chief",
        "name": "Ogre Chief",
        "hp": 520,
        "atk": 38,
        "def": 15,
        "chance": 25,
        "xp": (280, 400),
        "gold": (320, 520),
        "drops": [("rare_crystal", 0.7), ("lootbox", 0.45)],
        "level_bracket": "15-24",
    },
    {
        "id": "ogre_king",
        "name": "Ogre King",
        "hp": 720,
        "atk": 45,
        "def": 20,
        "chance": 20,
        "xp": (380, 550),
        "gold": (420, 680),
        "drops": [("rare_crystal", 0.8), ("lootbox", 0.55), ("phoenix_charm", 0.08)],
        "level_bracket": "25+",
    },
]


def pick_monster():
    import random
    weights = [m["chance"] for m in MONSTERS]
    return random.choices(MONSTERS, weights=weights, k=1)[0]


def pick_boss_variant(player_level: int):
    import random
    viable = BOSS_VARIANTS
    if player_level < 15:
        viable = [b for b in BOSS_VARIANTS if "level_bracket" not in b or b["level_bracket"] == "15-24"]
    elif player_level >= 25:
        viable = BOSS_VARIANTS
    elif player_level >= 15:
        viable = [b for b in BOSS_VARIANTS if "level_bracket"] != "25+"
    return random.choice(viable)
