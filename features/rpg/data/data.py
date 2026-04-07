import os
import random


RPG_DAMAGE_VAR_MIN = int(os.getenv("RPG_DAMAGE_VAR_MIN", "-2"))
RPG_DAMAGE_VAR_MAX = int(os.getenv("RPG_DAMAGE_VAR_MAX", "4"))
RPG_CRIT_CHANCE = float(os.getenv("RPG_CRIT_CHANCE", "0.08"))
RPG_CRIT_MULT = float(os.getenv("RPG_CRIT_MULT", "1.5"))
RPG_CRIT_CAP = float(os.getenv("RPG_CRIT_CAP", "0.85"))

RPG_DAMAGE_REDUCTION_CAP = float(os.getenv("RPG_DAMAGE_REDUCTION_CAP", "0.65"))
RPG_LIFESTEAL_HEAL_CAP = float(os.getenv("RPG_LIFESTEAL_HEAL_CAP", "0.25"))

RPG_REST_COOLDOWN = int(os.getenv("RPG_REST_COOLDOWN", "300"))
RPG_REST_HP_PERCENT = float(os.getenv("RPG_REST_HP_PERCENT", "0.5"))
RPG_DEATH_HP_PERCENT = float(os.getenv("RPG_DEATH_HP_PERCENT", "0.3"))
RPG_STARTER_GOLD_THRESHOLD = int(os.getenv("RPG_STARTER_GOLD_THRESHOLD", "50"))

RPG_SLIME_BONUS_GOLD = int(os.getenv("RPG_SLIME_BONUS_GOLD", "120"))
RPG_SLIME_BONUS_XP = int(os.getenv("RPG_SLIME_BONUS_XP", "60"))
RPG_SLIME_JACKPOT_CHANCE = float(os.getenv("RPG_SLIME_JACKPOT_CHANCE", "0.12"))
RPG_SLIME_JACKPOT_MIN = int(os.getenv("RPG_SLIME_JACKPOT_MIN", "280"))
RPG_SLIME_JACKPOT_MAX = int(os.getenv("RPG_SLIME_JACKPOT_MAX", "620"))

RPG_HUNT_COOLDOWN = int(os.getenv("RPG_HUNT_COOLDOWN", "45"))
RPG_DAILY_COOLDOWN = int(os.getenv("RPG_DAILY_COOLDOWN", "86400"))
RPG_DAILY_GOLD = int(os.getenv("RPG_DAILY_GOLD", "120"))
RPG_BOSS_COOLDOWN = int(os.getenv("RPG_BOSS_COOLDOWN", "1800"))
RPG_DUNGEON_COOLDOWN = int(os.getenv("RPG_DUNGEON_COOLDOWN", "3600"))
RPG_PARTY_HUNT_COOLDOWN = int(os.getenv("RPG_PARTY_HUNT_COOLDOWN", "1200"))
RPG_LOOTBOX_DAILY_LIMIT = int(os.getenv("RPG_LOOTBOX_DAILY_LIMIT", "25"))
RPG_PAY_MIN_LEVEL = int(os.getenv("RPG_PAY_MIN_LEVEL", "5"))
RPG_PAY_MIN_ACCOUNT_AGE_SECS = int(os.getenv("RPG_PAY_MIN_ACCOUNT_AGE_SECS", "259200"))
RPG_PAY_DAILY_SEND_LIMIT = int(os.getenv("RPG_PAY_DAILY_SEND_LIMIT", "5000"))
RPG_PAY_DAILY_PAIR_LIMIT = int(os.getenv("RPG_PAY_DAILY_PAIR_LIMIT", "2000"))


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
        "quest_id": "team_hunt_daily",
        "objective": "team_hunt_runs",
        "target": 3,
        "reward_gold": 180,
        "reward_xp": 90,
        "period": "daily",
    },
    {
        "quest_id": "gacha_daily",
        "objective": "summon_times",
        "target": 5,
        "reward_gold": 200,
        "reward_xp": 110,
        "period": "daily",
    },
    {
        "quest_id": "healer_daily",
        "objective": "use_healer_battles",
        "target": 2,
        "reward_gold": 160,
        "reward_xp": 100,
        "period": "daily",
    },
    {
        "quest_id": "team_clear_weekly",
        "objective": "team_hunt_clears",
        "target": 12,
        "reward_gold": 520,
        "reward_xp": 260,
        "period": "weekly",
    },
    {
        "quest_id": "boss_weekly",
        "objective": "boss_wins",
        "target": 2,
        "reward_gold": 680,
        "reward_xp": 340,
        "period": "weekly",
    },
    {
        "quest_id": "dungeon_weekly",
        "objective": "team_dungeon_clears",
        "target": 1,
        "reward_gold": 780,
        "reward_xp": 380,
        "period": "weekly",
    },
    {
        "quest_id": "lootbox_support",
        "objective": "open_lootbox",
        "target": 3,
        "reward_gold": 220,
        "reward_xp": 110,
    },
    {
        "quest_id": "slime_weekly",
        "objective": "kill_slime",
        "target": 4,
        "reward_gold": 440,
        "reward_xp": 220,
        "period": "weekly",
    },
]


def xp_need_for_next(level: int) -> int:
    return int(120 + (level ** 1.4) * 35)


def roll_damage(atk: int, defense: int, crit_bonus: float = 0.0) -> tuple[int, bool]:
    base_damage = atk * (100 / (100 + max(0, defense))) + random.randint(RPG_DAMAGE_VAR_MIN, RPG_DAMAGE_VAR_MAX)
    damage = max(1, int(base_damage))
    
    crit_chance = min(RPG_CRIT_CAP, max(0.0, RPG_CRIT_CHANCE + max(0.0, float(crit_bonus))))
    is_crit = random.random() < crit_chance
    if is_crit:
        damage = int(damage * RPG_CRIT_MULT)
    return damage, is_crit
