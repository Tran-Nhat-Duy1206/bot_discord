from .data import SKILLS
from .db import get_unlocked_skills, cooldown_remain, set_cooldown


def _clamp(value: float, upper: float) -> float:
    return max(0.0, min(upper, float(value)))


async def skill_profile(conn, guild_id: int, user_id: int) -> dict:
    unlocked = await get_unlocked_skills(conn, guild_id, user_id)

    attack = 0
    defense = 0
    hp = 0
    lifesteal = 0.0
    crit_bonus = 0.0
    damage_reduction = 0.0
    passive_names: list[str] = []

    for skill_id in unlocked:
        skill = SKILLS.get(skill_id)
        if not skill or str(skill.get("type", "")) != "passive":
            continue

        passive_names.append(str(skill.get("name", skill_id)))
        attack += int(skill.get("bonus_attack", 0))
        defense += int(skill.get("bonus_defense", 0))
        hp += int(skill.get("bonus_hp", 0))
        lifesteal += float(skill.get("lifesteal", 0.0))
        crit_bonus += float(skill.get("crit_bonus", 0.0))
        damage_reduction += float(skill.get("damage_reduction", 0.0))

    return {
        "attack": attack,
        "defense": defense,
        "hp": hp,
        "lifesteal": _clamp(lifesteal, 0.35),
        "crit_bonus": _clamp(crit_bonus, 0.3),
        "damage_reduction": _clamp(damage_reduction, 0.35),
        "passives": sorted(passive_names),
        "unlocked": unlocked,
    }


async def use_active_skill(conn, guild_id: int, user_id: int, skill_id: str, level: int) -> tuple[bool, str]:
    skill = SKILLS.get(skill_id)
    if not skill:
        return False, "Skill không tồn tại."
    if str(skill.get("type", "")) != "active":
        return False, "Đây là passive skill, không thể /rpg_skill_use."

    req = int(skill.get("level_req", 1))
    if level < req:
        return False, f"Cần level **{req}** để dùng skill này."

    unlocked = await get_unlocked_skills(conn, guild_id, user_id)
    if skill_id not in unlocked:
        return False, "Bạn chưa unlock skill này. Dùng `/rpg_skill_unlock` trước."

    key = f"skill:{skill_id}"
    remain = await cooldown_remain(conn, guild_id, user_id, key)
    if remain > 0:
        return False, f"Skill đang cooldown: **{remain}s**"

    if skill_id == "second_wind":
        async with conn.execute(
            "SELECT hp, max_hp FROM players WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ) as cur:
            row = await cur.fetchone()
        hp = int(row[0]) if row else 1
        max_hp = int(row[1]) if row else 100
        heal = max(1, int(max_hp * float(skill.get("heal_ratio", 0.35))))
        new_hp = min(max_hp, hp + heal)
        actual = max(0, new_hp - hp)

        await conn.execute(
            "UPDATE players SET hp = ? WHERE guild_id = ? AND user_id = ?",
            (new_hp, guild_id, user_id),
        )
        await set_cooldown(conn, guild_id, user_id, key, int(skill.get("cooldown", 900)))
        return True, f"✨ {skill.get('name', 'Skill')}: hồi **{actual} HP** ({new_hp}/{max_hp})"

    return False, "Skill active này chưa được implement."
