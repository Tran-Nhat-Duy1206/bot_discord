import random
from dataclasses import dataclass
from typing import Optional

from ..data import ITEMS, RPG_DAMAGE_REDUCTION_CAP


UPGRADE_BASE_COST = int(__import__('os').getenv("RPG_UPGRADE_BASE_COST", "100"))
UPGRADE_COST_MULTIPLIER = int(__import__('os').getenv("RPG_UPGRADE_COST_MULTIPLIER", "80"))
UPGRADE_MAX_LEVEL = int(__import__('os').getenv("RPG_UPGRADE_MAX_LEVEL", "10"))
UPGRADE_SUCCESS_BASE = float(__import__('os').getenv("RPG_UPGRADE_SUCCESS_BASE", "0.90"))
UPGRADE_SUCCESS_MIN = float(__import__('os').getenv("RPG_UPGRADE_SUCCESS_MIN", "0.50"))

REROLL_BASE_COST = int(__import__('os').getenv("RPG_REROLL_BASE_COST", "200"))
REROLL_COST_MULTIPLIER = int(__import__('os').getenv("RPG_REROLL_COST_MULTIPLIER", "40"))


@dataclass
class UpgradeStats:
    attack_bonus: int = 0
    defense_bonus: int = 0
    hp_bonus: int = 0
    crit_bonus: float = 0.0
    lifesteal_bonus: float = 0.0
    damage_reduction_bonus: float = 0.0


@dataclass
class UpgradeResult:
    success: bool
    new_level: int
    stat_gains: UpgradeStats
    cost_paid: int
    message: str


@dataclass
class RerollResult:
    success: bool
    new_stats: UpgradeStats
    cost_paid: int
    message: str


@dataclass
class PlayerUpgradeData:
    guild_id: int
    user_id: int
    item_id: str
    upgrade_level: int = 0
    attack_bonus: int = 0
    defense_bonus: int = 0
    hp_bonus: int = 0
    crit_bonus: float = 0.0
    lifesteal_bonus: float = 0.0
    damage_reduction_bonus: float = 0.0


def get_upgrade_cost(current_level: int) -> int:
    return UPGRADE_BASE_COST + current_level * UPGRADE_COST_MULTIPLIER


def get_upgrade_success_rate(current_level: int) -> float:
    rate = UPGRADE_SUCCESS_BASE - (current_level * 0.05)
    return max(UPGRADE_SUCCESS_MIN, rate)


def get_upgrade_stats(item_id: str) -> UpgradeStats:
    item = ITEMS.get(item_id, {})
    return UpgradeStats(
        attack_bonus=int(item.get("bonus_attack", 0)),
        defense_bonus=int(item.get("bonus_defense", 0)),
        hp_bonus=int(item.get("bonus_hp", 0)),
        crit_bonus=float(item.get("crit_bonus", 0.0)),
        lifesteal_bonus=float(item.get("lifesteal", 0.0)),
        damage_reduction_bonus=float(item.get("damage_reduction", 0.0)),
    )


def calculate_upgrade_gains(item_id: str, level: int) -> UpgradeStats:
    base = get_upgrade_stats(item_id)
    
    if "weapon" in item_id or "blade" in item_id:
        atk_gain = 2 + level
        def_gain = 0
        hp_gain = level // 2
        crit_gain = 0.01 * level
        ls_gain = 0.005 * level if level >= 5 else 0
        dr_gain = 0
    elif "armor" in item_id or "plate" in item_id:
        atk_gain = 0
        def_gain = 1 + level
        hp_gain = 5 + level * 2
        crit_gain = 0
        ls_gain = 0
        dr_gain = 0.01 * level
    elif "ring" in item_id or "charm" in item_id:
        atk_gain = 1 + level // 2
        def_gain = 1 + level // 3
        hp_gain = 3 + level
        crit_gain = 0.015 * level
        ls_gain = 0.005 * level if level >= 3 else 0
        dr_gain = 0.005 * level
    else:
        atk_gain = level
        def_gain = level // 2
        hp_gain = level * 2
        crit_gain = 0.01 * level
        ls_gain = 0
        dr_gain = 0
    
    return UpgradeStats(
        attack_bonus=base.attack_bonus + atk_gain,
        defense_bonus=base.defense_bonus + def_gain,
        hp_bonus=base.hp_bonus + hp_gain,
        crit_bonus=min(0.85, base.crit_bonus + crit_gain),
        lifesteal_bonus=min(0.9, base.lifesteal_bonus + ls_gain),
        damage_reduction_bonus=min(RPG_DAMAGE_REDUCTION_CAP, base.damage_reduction_bonus + dr_gain),
    )


def simulate_upgrade(
    item_id: str,
    current_level: int,
    current_stats: UpgradeStats,
) -> UpgradeResult:
    if current_level >= UPGRADE_MAX_LEVEL:
        return UpgradeResult(
            success=False,
            new_level=current_level,
            stat_gains=current_stats,
            cost_paid=0,
            message=f"Item đã đạt cấp tối đa ({UPGRADE_MAX_LEVEL})!"
        )
    
    cost = get_upgrade_cost(current_level)
    success_rate = get_upgrade_success_rate(current_level)
    
    if random.random() < success_rate:
        new_level = current_level + 1
        new_stats = calculate_upgrade_gains(item_id, new_level)
        return UpgradeResult(
            success=True,
            new_level=new_level,
            stat_gains=new_stats,
            cost_paid=cost,
            message=f"Upgrade thành công! +Lv.{new_level}"
        )
    else:
        return UpgradeResult(
            success=False,
            new_level=current_level,
            stat_gains=current_stats,
            cost_paid=cost,
            message=f"Upgrade thất bại! Mất {cost} gold"
        )


def get_reroll_cost(level: int) -> int:
    return REROLL_BASE_COST + level * REROLL_COST_MULTIPLIER


def reroll_stats(
    item_id: str,
    upgrade_level: int,
    current_stats: UpgradeStats,
) -> RerollResult:
    cost = get_reroll_cost(upgrade_level)
    base = get_upgrade_stats(item_id)
    
    if upgrade_level == 0:
        return RerollResult(
            success=False,
            new_stats=current_stats,
            cost_paid=0,
            message="Item chưa upgrade không thể reroll!"
        )
    
    roll = random.random()
    
    if roll < 0.1:
        new_stats = calculate_upgrade_gains(item_id, upgrade_level)
        new_stats.crit_bonus = base.crit_bonus + 0.02 * upgrade_level
        new_stats.lifesteal_bonus = base.lifesteal_bonus + 0.01 * upgrade_level
        message = f"Reroll BONUS! Crit +2%, Lifesteal +1%"
    elif roll < 0.25:
        new_stats = calculate_upgrade_gains(item_id, upgrade_level)
        new_stats.attack_bonus = base.attack_bonus + upgrade_level * 3
        message = f"Reroll BONUS! ATK x3!"
    elif roll < 0.4:
        new_stats = calculate_upgrade_gains(item_id, upgrade_level)
        new_stats.hp_bonus = base.hp_bonus + upgrade_level * 5
        message = f"Reroll BONUS! HP x5!"
    else:
        new_stats = calculate_upgrade_gains(item_id, upgrade_level)
        message = f"Reroll thành công!"
    
    return RerollResult(
        success=True,
        new_stats=new_stats,
        cost_paid=cost,
        message=message,
    )


def format_upgrade_cost(level: int) -> str:
    cost = get_upgrade_cost(level)
    return f"{cost:,} gold"


def format_success_rate(level: int) -> str:
    rate = get_upgrade_success_rate(level) * 100
    return f"{rate:.0f}%"


def format_upgrade_info(item_id: str, level: int, stats: UpgradeStats) -> str:
    item = ITEMS.get(item_id, {})
    item_name = item.get("name", item_id)
    
    lines = [
        f"**{item_name}** (Lv.{level}/{UPGRADE_MAX_LEVEL})",
        f"───",
    ]
    
    if stats.attack_bonus > 0:
        lines.append(f"⚔️ ATK: +{stats.attack_bonus}")
    if stats.defense_bonus > 0:
        lines.append(f"🛡️ DEF: +{stats.defense_bonus}")
    if stats.hp_bonus > 0:
        lines.append(f"❤️ HP: +{stats.hp_bonus}")
    if stats.crit_bonus > 0:
        lines.append(f"💥 Crit: +{stats.crit_bonus*100:.1f}%")
    if stats.lifesteal_bonus > 0:
        lines.append(f"🩸 Lifesteal: +{stats.lifesteal_bonus*100:.1f}%")
    if stats.damage_reduction_bonus > 0:
        lines.append(f"🛡️ DR: +{stats.damage_reduction_bonus*100:.1f}%")
    
    if level < UPGRADE_MAX_LEVEL:
        cost = get_upgrade_cost(level)
        rate = get_upgrade_success_rate(level)
        lines.append(f"───")
        lines.append(f"💰 Cost: {cost:,} gold")
        lines.append(f"📊 Success: {rate*100:.0f}%")
    
    return "\n".join(lines)
