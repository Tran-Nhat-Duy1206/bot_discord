import os
import random


RPG_DAMAGE_MIN = int(os.getenv("RPG_DAMAGE_MIN", "1"))
RPG_DAMAGE_VAR_MIN = int(os.getenv("RPG_DAMAGE_VAR_MIN", "-2"))
RPG_DAMAGE_VAR_MAX = int(os.getenv("RPG_DAMAGE_VAR_MAX", "4"))
RPG_CRIT_CHANCE = float(os.getenv("RPG_CRIT_CHANCE", "0.08"))
RPG_CRIT_MULT = float(os.getenv("RPG_CRIT_MULT", "1.65"))

RPG_SLIME_BONUS_GOLD = int(os.getenv("RPG_SLIME_BONUS_GOLD", "120"))
RPG_SLIME_BONUS_XP = int(os.getenv("RPG_SLIME_BONUS_XP", "60"))
RPG_SLIME_JACKPOT_CHANCE = float(os.getenv("RPG_SLIME_JACKPOT_CHANCE", "0.12"))
RPG_SLIME_JACKPOT_MIN = int(os.getenv("RPG_SLIME_JACKPOT_MIN", "280"))
RPG_SLIME_JACKPOT_MAX = int(os.getenv("RPG_SLIME_JACKPOT_MAX", "620"))


ITEMS: dict[str, dict] = {
    "potion": {
        "name": "Potion",
        "emoji": "🧪",
        "buy": 60,
        "sell": 30,
        "desc": "Hồi 35 HP",
        "rarity": "common",
        "use": "heal",
        "value": 35,
    },
    "mega_potion": {
        "name": "Mega Potion",
        "emoji": "🧴",
        "buy": 180,
        "sell": 90,
        "desc": "Hồi 100 HP",
        "rarity": "uncommon",
        "use": "heal",
        "value": 100,
    },
    "lootbox": {
        "name": "Lootbox",
        "emoji": "🎁",
        "buy": 0,
        "sell": 70,
        "desc": "Mở để nhận vàng hoặc vật phẩm",
        "rarity": "rare",
        "use": "lootbox",
        "value": 0,
    },
    "rare_crystal": {
        "name": "Rare Crystal",
        "emoji": "💎",
        "buy": 0,
        "sell": 260,
        "desc": "Tài nguyên hiếm từ slime",
        "rarity": "epic",
        "use": "none",
        "value": 0,
    },
    "wood_sword": {
        "name": "Wood Sword",
        "emoji": "🗡️",
        "buy": 240,
        "sell": 120,
        "desc": "Vũ khí cơ bản (+4 ATK, +2% crit)",
        "rarity": "uncommon",
        "use": "equip",
        "slot": "weapon",
        "bonus_attack": 4,
        "bonus_defense": 0,
        "bonus_hp": 0,
        "crit_bonus": 0.02,
    },
    "iron_armor": {
        "name": "Iron Armor",
        "emoji": "🛡️",
        "buy": 320,
        "sell": 160,
        "desc": "Áo giáp bền (+4 DEF, +25 HP, giảm 6% damage)",
        "rarity": "rare",
        "use": "equip",
        "slot": "armor",
        "bonus_attack": 0,
        "bonus_defense": 4,
        "bonus_hp": 25,
        "damage_reduction": 0.06,
    },
    "lucky_ring": {
        "name": "Lucky Ring",
        "emoji": "💍",
        "buy": 380,
        "sell": 190,
        "desc": "Nhẫn may mắn (+2 ATK, +1 DEF, +10 HP, +3% crit)",
        "rarity": "rare",
        "use": "equip",
        "slot": "accessory",
        "bonus_attack": 2,
        "bonus_defense": 1,
        "bonus_hp": 10,
        "crit_bonus": 0.03,
    },
    "slime_blade": {
        "name": "Slime Blade",
        "emoji": "🧬",
        "buy": 0,
        "sell": 360,
        "desc": "Kiếm rèn từ slime core (+7 ATK, hút máu 8%)",
        "rarity": "epic",
        "use": "equip",
        "slot": "weapon",
        "bonus_attack": 7,
        "bonus_defense": 0,
        "bonus_hp": 0,
        "lifesteal": 0.08,
    },
    "ogre_plate": {
        "name": "Ogre Plate",
        "emoji": "🧱",
        "buy": 0,
        "sell": 420,
        "desc": "Giáp dày của ogre (+6 DEF, +40 HP, giảm 12% damage)",
        "rarity": "epic",
        "use": "equip",
        "slot": "armor",
        "bonus_attack": 0,
        "bonus_defense": 6,
        "bonus_hp": 40,
        "damage_reduction": 0.12,
    },
    "phoenix_charm": {
        "name": "Phoenix Charm",
        "emoji": "🔥",
        "buy": 0,
        "sell": 480,
        "desc": "Bùa lửa cổ (+4 ATK, +3 DEF, +20 HP, +8% crit, hút máu 4%)",
        "rarity": "legendary",
        "use": "equip",
        "slot": "accessory",
        "bonus_attack": 4,
        "bonus_defense": 3,
        "bonus_hp": 20,
        "crit_bonus": 0.08,
        "lifesteal": 0.04,
    },
}


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
        "min_level": 1,
        "hp": 360,
        "atk": 32,
        "def": 12,
        "xp": (210, 340),
        "gold": (250, 430),
        "drops": [("rare_crystal", 0.65), ("lootbox", 0.35), ("mega_potion", 0.3), ("ogre_plate", 0.08)],
    },
    {
        "id": "void_tyrant",
        "name": "Void Tyrant",
        "min_level": 12,
        "hp": 460,
        "atk": 38,
        "def": 14,
        "xp": (300, 460),
        "gold": (360, 560),
        "drops": [("rare_crystal", 0.75), ("lootbox", 0.45), ("slime_blade", 0.11), ("ogre_plate", 0.12)],
    },
    {
        "id": "ashen_dragon",
        "name": "Ashen Dragon",
        "min_level": 22,
        "hp": 620,
        "atk": 46,
        "def": 18,
        "xp": (460, 760),
        "gold": (520, 880),
        "drops": [("rare_crystal", 0.85), ("lootbox", 0.55), ("phoenix_charm", 0.12), ("slime_blade", 0.18)],
    },
]


CRAFT_RECIPES: list[dict] = [
    {
        "id": "slime_blade",
        "name": "Slime Blade",
        "requires": {"wood_sword": 1, "rare_crystal": 2},
        "gold": 450,
        "output": {"slime_blade": 1},
    },
    {
        "id": "ogre_plate",
        "name": "Ogre Plate",
        "requires": {"iron_armor": 1, "rare_crystal": 2},
        "gold": 520,
        "output": {"ogre_plate": 1},
    },
    {
        "id": "phoenix_charm",
        "name": "Phoenix Charm",
        "requires": {"lucky_ring": 1, "rare_crystal": 3, "lootbox": 1},
        "gold": 780,
        "output": {"phoenix_charm": 1},
    },
]


SKILLS: dict[str, dict] = {
    "battle_instinct": {
        "name": "Battle Instinct",
        "type": "passive",
        "level_req": 5,
        "desc": "+3 ATK, +4% crit chance",
        "bonus_attack": 3,
        "crit_bonus": 0.04,
    },
    "guardian_skin": {
        "name": "Guardian Skin",
        "type": "passive",
        "level_req": 8,
        "desc": "+2 DEF, +18 HP, giảm 5% damage",
        "bonus_defense": 2,
        "bonus_hp": 18,
        "damage_reduction": 0.05,
    },
    "second_wind": {
        "name": "Second Wind",
        "type": "active",
        "level_req": 6,
        "desc": "Hồi 35% max HP, cooldown 15 phút",
        "heal_ratio": 0.35,
        "cooldown": 900,
    },
}


QUEST_DEFINITIONS: list[dict] = [
    {
        "quest_id": "kill_10",
        "objective": "kill_monsters",
        "target": 10,
        "reward_gold": 220,
        "reward_xp": 120,
        "period": "none",
        "prereq_quest_id": "",
    },
    {
        "quest_id": "open_5_boxes",
        "objective": "open_lootboxes",
        "target": 5,
        "reward_gold": 260,
        "reward_xp": 140,
        "period": "none",
        "prereq_quest_id": "kill_10",
    },
    {
        "quest_id": "daily_hunt_3",
        "objective": "hunt_runs",
        "target": 3,
        "reward_gold": 180,
        "reward_xp": 90,
        "period": "daily",
        "prereq_quest_id": "",
    },
    {
        "quest_id": "weekly_slime_3",
        "objective": "kill_slime",
        "target": 3,
        "reward_gold": 520,
        "reward_xp": 260,
        "period": "weekly",
        "prereq_quest_id": "",
    },
    {
        "quest_id": "weekly_boss_1",
        "objective": "boss_wins",
        "target": 1,
        "reward_gold": 680,
        "reward_xp": 320,
        "period": "weekly",
        "prereq_quest_id": "weekly_slime_3",
    },
]


def xp_need_for_next(level: int) -> int:
    return 120 + (level - 1) * 40


def pick_monster() -> dict:
    weights = [m["chance"] for m in MONSTERS]
    return random.choices(MONSTERS, weights=weights, k=1)[0]


def roll_damage(atk: int, defense: int, crit_bonus: float = 0.0) -> tuple[int, bool]:
    base = atk - defense + random.randint(RPG_DAMAGE_VAR_MIN, RPG_DAMAGE_VAR_MAX)
    damage = max(RPG_DAMAGE_MIN, base)
    crit_chance = max(0.0, min(0.95, RPG_CRIT_CHANCE + max(0.0, float(crit_bonus))))
    is_crit = random.random() < crit_chance
    if is_crit:
        damage = max(RPG_DAMAGE_MIN, int(damage * RPG_CRIT_MULT))
    return damage, is_crit
