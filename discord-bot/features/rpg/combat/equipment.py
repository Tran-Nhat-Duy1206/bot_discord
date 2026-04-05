from ..data.data import ITEMS
from ..db.db import add_inventory, remove_inventory, get_equipped


SLOTS = {"weapon", "armor", "accessory"}

SET_BONUSES: list[dict] = [
    {
        "id": "adventurer_triad",
        "name": "Adventurer Triad",
        "items": {
            "weapon": "wood_sword",
            "armor": "iron_armor",
            "accessory": "lucky_ring",
        },
        "bonus_attack": 2,
        "bonus_defense": 2,
        "bonus_hp": 15,
        "crit_bonus": 0.04,
        "damage_reduction": 0.04,
    },
    {
        "id": "phoenix_guard",
        "name": "Phoenix Guard",
        "items": {
            "weapon": "slime_blade",
            "armor": "ogre_plate",
            "accessory": "phoenix_charm",
        },
        "bonus_attack": 4,
        "bonus_defense": 3,
        "bonus_hp": 35,
        "lifesteal": 0.06,
        "crit_bonus": 0.05,
        "damage_reduction": 0.08,
    },
]


def _item_bonus(item_id: str) -> tuple[int, int, int]:
    data = ITEMS.get(item_id, {})
    return (
        int(data.get("bonus_attack", 0)),
        int(data.get("bonus_defense", 0)),
        int(data.get("bonus_hp", 0)),
    )


def _item_passive(item_id: str) -> tuple[float, float, float]:
    data = ITEMS.get(item_id, {})
    return (
        float(data.get("lifesteal", 0.0)),
        float(data.get("crit_bonus", 0.0)),
        float(data.get("damage_reduction", 0.0)),
    )


def _clamp_rate(value: float, upper: float) -> float:
    return max(0.0, min(upper, float(value)))


def _resolve_set_bonus(equipped: dict[str, str]) -> dict | None:
    for set_bonus in SET_BONUSES:
        req = set_bonus.get("items") or {}
        if all(equipped.get(slot) == item_id for slot, item_id in req.items()):
            return set_bonus
    return None


async def equipped_profile(conn, guild_id: int, user_id: int) -> dict:
    equipped = await get_equipped(conn, guild_id, user_id)
    atk = 0
    defense = 0
    hp = 0
    lifesteal = 0.0
    crit_bonus = 0.0
    damage_reduction = 0.0

    for item_id in equipped.values():
        a, d, h = _item_bonus(item_id)
        ls, crit, red = _item_passive(item_id)
        atk += a
        defense += d
        hp += h
        lifesteal += ls
        crit_bonus += crit
        damage_reduction += red

    active_set = _resolve_set_bonus(equipped)
    if active_set:
        atk += int(active_set.get("bonus_attack", 0))
        defense += int(active_set.get("bonus_defense", 0))
        hp += int(active_set.get("bonus_hp", 0))
        lifesteal += float(active_set.get("lifesteal", 0.0))
        crit_bonus += float(active_set.get("crit_bonus", 0.0))
        damage_reduction += float(active_set.get("damage_reduction", 0.0))

    return {
        "attack": atk,
        "defense": defense,
        "hp": hp,
        "lifesteal": _clamp_rate(lifesteal, 0.45),
        "crit_bonus": _clamp_rate(crit_bonus, 0.40),
        "damage_reduction": _clamp_rate(damage_reduction, 0.65),
        "equipped": equipped,
        "set_bonus": active_set,
    }


async def equipped_bonus(conn, guild_id: int, user_id: int) -> tuple[int, int, int, dict[str, str]]:
    profile = await equipped_profile(conn, guild_id, user_id)
    return int(profile["attack"]), int(profile["defense"]), int(profile["hp"]), dict(profile["equipped"])


async def equip_item(conn, guild_id: int, user_id: int, item_id: str) -> tuple[bool, str]:
    data = ITEMS.get(item_id)
    if not data:
        return False, "Item không tồn tại."
    if data.get("use") != "equip":
        return False, "Item này không phải trang bị."

    slot = str(data.get("slot", ""))
    if slot not in SLOTS:
        return False, "Item thiếu slot hợp lệ."

    ok = await remove_inventory(conn, guild_id, user_id, item_id, 1)
    if not ok:
        return False, "Bạn không có item này trong túi."

    current = await get_equipped(conn, guild_id, user_id)
    old_item = current.get(slot)
    if old_item:
        await add_inventory(conn, guild_id, user_id, old_item, 1)

    await conn.execute(
        """
        INSERT INTO equipment(guild_id, user_id, slot, item_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(guild_id, user_id, slot)
        DO UPDATE SET item_id = excluded.item_id
        """,
        (guild_id, user_id, slot, item_id),
    )

    return True, slot


async def unequip_slot(conn, guild_id: int, user_id: int, slot: str) -> tuple[bool, str]:
    slot = slot.strip().lower()
    if slot not in SLOTS:
        return False, "Slot phải là weapon/armor/accessory."

    current = await get_equipped(conn, guild_id, user_id)
    old_item = current.get(slot)
    if not old_item:
        return False, "Slot này chưa có trang bị."

    await conn.execute(
        "DELETE FROM equipment WHERE guild_id = ? AND user_id = ? AND slot = ?",
        (guild_id, user_id, slot),
    )
    await add_inventory(conn, guild_id, user_id, old_item, 1)
    return True, old_item
