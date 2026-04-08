from dataclasses import dataclass, field
from typing import Optional

from ..data import ITEMS, SKILLS, xp_need_for_next

from ..repositories import player_repo, inventory_repo
from .base import BaseService


@dataclass
class ProfileResult:
    ok: bool = False
    level: int = 1
    xp: int = 0
    hp: int = 100
    max_hp: int = 100
    attack: int = 12
    defense: int = 6
    gold: int = 0
    equipped: dict = field(default_factory=dict)
    set_bonus: str = ""
    lifesteal: float = 0.0
    crit_bonus: float = 0.0
    damage_reduction: float = 0.0
    passive_skills: list = field(default_factory=list)
    xp_need: int = 120


@dataclass
class EquipmentResult:
    ok: bool = False
    equipped: dict = field(default_factory=dict)
    bonus_atk: int = 0
    bonus_def: int = 0
    bonus_hp: int = 0
    set_bonus: str = ""
    lifesteal: float = 0.0
    crit_bonus: float = 0.0
    damage_reduction: float = 0.0
    passive_skills: list = field(default_factory=list)


@dataclass
class SkillUnlockResult:
    ok: bool = False
    skill_id: str = ""
    skill_name: str = ""
    message: str = ""


@dataclass
class SkillUseResult:
    ok: bool = False
    message: str = ""


SLOTS = {"weapon", "armor", "accessory"}


def _is_vi(lang: str) -> bool:
    return str(lang).lower().startswith("vi")


class PlayerService(BaseService):
    @staticmethod
    async def _resolve_target_character_id(conn, guild_id: int, user_id: int, character_id: str | None = None) -> tuple[bool, str | None, str]:
        cid = str(character_id or "").strip().lower()
        if cid:
            async with conn.execute(
                "SELECT 1 FROM player_characters WHERE guild_id = ? AND user_id = ? AND character_id = ?",
                (guild_id, user_id, cid),
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return False, None, "character_not_owned"
            return True, cid, ""

        async with conn.execute(
            "SELECT character_id FROM player_characters WHERE guild_id = ? AND user_id = ? AND is_main = 1 LIMIT 1",
            (guild_id, user_id),
        ) as cur:
            row = await cur.fetchone()
        if row and row[0]:
            return True, str(row[0]), ""
        return False, None, "no_main"

    @staticmethod
    async def get_profile(guild_id: int, user_id: int) -> ProfileResult:
        async with BaseService.with_user_transaction(guild_id, user_id, "get_profile") as conn:
            await player_repo.ensure_player_ready(conn, guild_id, user_id)
            row = await player_repo.get_player_stats(conn, guild_id, user_id)
            if not row:
                return ProfileResult()

            level, xp, hp, max_hp, attack, defense, gold = map(int, row)
            
            from ..combat.equipment import equipped_profile
            from ..combat.skills import skill_profile
            
            ok_target, target_cid, _ = await PlayerService._resolve_target_character_id(conn, guild_id, user_id, None)
            profile = await equipped_profile(
                conn,
                guild_id,
                user_id,
                character_id=target_cid if ok_target else None,
                fallback_legacy=bool(ok_target),
            )
            sprofile = await skill_profile(conn, guild_id, user_id)

            bonus_atk = int(profile["attack"])
            bonus_def = int(profile["defense"])
            bonus_hp = int(profile["hp"])
            lifesteal = float(profile["lifesteal"]) + float(sprofile["lifesteal"])
            crit_bonus = float(profile["crit_bonus"]) + float(sprofile["crit_bonus"])
            damage_reduction = float(profile["damage_reduction"]) + float(sprofile["damage_reduction"])
            active_set = profile.get("set_bonus")

            await conn.commit()

            return ProfileResult(
                ok=True,
                level=level,
                xp=xp,
                hp=hp,
                max_hp=max_hp,
                attack=attack,
                defense=defense,
                gold=gold,
                equipped=profile["equipped"],
                set_bonus=str(active_set.get("name", "")) if active_set else "",
                lifesteal=lifesteal,
                crit_bonus=crit_bonus,
                damage_reduction=damage_reduction,
                passive_skills=list(sprofile.get("passives", [])),
                xp_need=xp_need_for_next(level),
            )

    @staticmethod
    async def get_inventory(guild_id: int, user_id: int) -> list[tuple[str, int]]:
        async with BaseService.with_user_transaction(guild_id, user_id, "get_inventory") as conn:
            await player_repo.ensure_player_ready(conn, guild_id, user_id)
            items = await inventory_repo.get_inventory(conn, guild_id, user_id)
            await conn.commit()
        return items

    @staticmethod
    async def equip_item(
        guild_id: int,
        user_id: int,
        item_id: str,
        lang: str = "en",
        character_id: str | None = None,
    ) -> tuple[bool, str]:
        data = ITEMS.get(item_id)
        if not data:
            return False, ("Item không tồn tại." if _is_vi(lang) else "Item does not exist.")
        if data.get("use") != "equip":
            return False, ("Item này không phải trang bị." if _is_vi(lang) else "This item is not equipment.")

        slot = str(data.get("slot", ""))
        if slot not in SLOTS:
            return False, ("Item thiếu slot hợp lệ." if _is_vi(lang) else "Item has invalid slot.")

        async with BaseService.with_user_transaction(guild_id, user_id, "equip") as conn:
            await player_repo.ensure_player_ready(conn, guild_id, user_id)

            ok_target, target_cid, reason = await PlayerService._resolve_target_character_id(conn, guild_id, user_id, character_id)
            if not ok_target:
                if reason == "character_not_owned":
                    return False, ("Bạn không sở hữu hero này." if _is_vi(lang) else "You don't own this hero.")
                return False, ("Bạn chưa có Captain để trang bị." if _is_vi(lang) else "You don't have a Captain to equip.")
            
            ok = await inventory_repo.remove_inventory(conn, guild_id, user_id, item_id, 1)
            if not ok:
                return False, ("Bạn không có item này trong túi." if _is_vi(lang) else "You don't have this item in inventory.")

            current_specific = await player_repo.get_equipped_items(
                conn,
                guild_id,
                user_id,
                character_id=target_cid,
                fallback_legacy=False,
            )
            current = await player_repo.get_equipped_items(
                conn,
                guild_id,
                user_id,
                character_id=target_cid,
                fallback_legacy=bool(character_id is None and target_cid),
            )
            old_item = current.get(slot)
            if old_item:
                await inventory_repo.add_inventory(conn, guild_id, user_id, old_item, 1)
                if slot not in current_specific:
                    await conn.execute(
                        "DELETE FROM equipment WHERE guild_id = ? AND user_id = ? AND slot = ?",
                        (guild_id, user_id, slot),
                    )

            await player_repo.equip_item(conn, guild_id, user_id, slot, item_id, character_id=target_cid)
            await conn.commit()

        return True, f"{slot}|{target_cid}"

    @staticmethod
    async def unequip_item(
        guild_id: int,
        user_id: int,
        slot: str,
        lang: str = "en",
        character_id: str | None = None,
    ) -> tuple[bool, str]:
        slot = slot.strip().lower()
        if slot not in SLOTS:
            return False, ("Slot phải là weapon/armor/accessory." if _is_vi(lang) else "Slot must be weapon/armor/accessory.")

        async with BaseService.with_user_transaction(guild_id, user_id, "unequip") as conn:
            await player_repo.ensure_player_ready(conn, guild_id, user_id)

            ok_target, target_cid, reason = await PlayerService._resolve_target_character_id(conn, guild_id, user_id, character_id)
            if not ok_target:
                if reason == "character_not_owned":
                    return False, ("Bạn không sở hữu hero này." if _is_vi(lang) else "You don't own this hero.")
                return False, ("Bạn chưa có Captain để tháo trang bị." if _is_vi(lang) else "You don't have a Captain to unequip.")
            
            old_item = await player_repo.unequip_item(
                conn,
                guild_id,
                user_id,
                slot,
                character_id=target_cid,
                fallback_legacy=bool(character_id is None and target_cid),
            )
            if not old_item:
                return False, ("Slot này chưa có trang bị." if _is_vi(lang) else "This slot has no equipment.")

            await inventory_repo.add_inventory(conn, guild_id, user_id, old_item, 1)

            async with conn.execute(
                "SELECT hp, max_hp FROM players WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()
            hp = int(row[0]) if row else 1
            max_hp = int(row[1]) if row else 100
            if hp > max_hp:
                await player_repo.update_player_hp(conn, guild_id, user_id, max_hp)

            await conn.commit()

        return True, f"{old_item}|{target_cid}"

    @staticmethod
    async def get_equipment(guild_id: int, user_id: int, character_id: str | None = None) -> EquipmentResult:
        async with BaseService.with_user_transaction(guild_id, user_id, "get_equipment") as conn:
            await player_repo.ensure_player_ready(conn, guild_id, user_id)
            
            from ..combat.equipment import equipped_profile
            from ..combat.skills import skill_profile
            
            ok_target, target_cid, reason = await PlayerService._resolve_target_character_id(conn, guild_id, user_id, character_id)
            if character_id and not ok_target and reason == "character_not_owned":
                return EquipmentResult(ok=False)
            profile = await equipped_profile(
                conn,
                guild_id,
                user_id,
                character_id=target_cid if ok_target else None,
                fallback_legacy=bool(ok_target),
            )
            sprofile = await skill_profile(conn, guild_id, user_id)
            await conn.commit()

        bonus_atk = int(profile["attack"])
        bonus_def = int(profile["defense"])
        bonus_hp = int(profile["hp"])
        lifesteal = float(profile["lifesteal"]) + float(sprofile["lifesteal"])
        crit_bonus = float(profile["crit_bonus"]) + float(sprofile["crit_bonus"])
        damage_reduction = float(profile["damage_reduction"]) + float(sprofile["damage_reduction"])
        active_set = profile.get("set_bonus")

        return EquipmentResult(
            ok=True,
            equipped=profile["equipped"],
            bonus_atk=bonus_atk,
            bonus_def=bonus_def,
            bonus_hp=bonus_hp,
            set_bonus=str(active_set.get("name", "")) if active_set else "",
            lifesteal=lifesteal,
            crit_bonus=crit_bonus,
            damage_reduction=damage_reduction,
            passive_skills=list(sprofile.get("passives", [])),
        )

    @staticmethod
    async def unlock_skill(guild_id: int, user_id: int, skill_id: str, lang: str = "en") -> SkillUnlockResult:
        skill = SKILLS.get(skill_id)
        if not skill:
            return SkillUnlockResult(ok=False, skill_id=skill_id, message=("Skill không tồn tại." if _is_vi(lang) else "Skill does not exist."))

        async with BaseService.with_user_transaction(guild_id, user_id, "unlock_skill") as conn:
            await player_repo.ensure_player_ready(conn, guild_id, user_id)
            
            level, _ = await player_repo.get_player_level_gold(conn, guild_id, user_id)
            req = int(skill.get("level_req", 1))
            if level < req:
                return SkillUnlockResult(
                    ok=False,
                    skill_id=skill_id,
                    message=(f"Cần level **{req}** để unlock `{skill_id}`." if _is_vi(lang) else f"Need level **{req}** to unlock `{skill_id}`."),
                )

            ok = await player_repo.unlock_skill(conn, guild_id, user_id, skill_id)
            if not ok:
                return SkillUnlockResult(ok=False, skill_id=skill_id, message=("Skill đã unlock trước đó." if _is_vi(lang) else "Skill already unlocked."))
            
            await conn.commit()

        return SkillUnlockResult(
            ok=True,
            skill_id=skill_id,
            skill_name=str(skill.get("name", skill_id)),
            message=(
                f"✅ Đã unlock skill **{skill.get('name', skill_id)}** (`{skill_id}`)."
                if _is_vi(lang)
                else f"✅ Unlocked skill **{skill.get('name', skill_id)}** (`{skill_id}`)."
            ),
        )

    @staticmethod
    async def use_skill(guild_id: int, user_id: int, skill_id: str, lang: str = "en") -> SkillUseResult:
        skill = SKILLS.get(skill_id)
        if not skill:
            return SkillUseResult(ok=False, message=("Skill không tồn tại." if _is_vi(lang) else "Skill does not exist."))
        if str(skill.get("type", "")) != "active":
            return SkillUseResult(ok=False, message=("Đây là passive skill, không thể dùng." if _is_vi(lang) else "This is a passive skill and cannot be used."))

        async with BaseService.with_user_transaction(guild_id, user_id, "use_skill") as conn:
            await player_repo.ensure_player_ready(conn, guild_id, user_id)
            
            level, _ = await player_repo.get_player_level_gold(conn, guild_id, user_id)
            req = int(skill.get("level_req", 1))
            if level < req:
                return SkillUseResult(ok=False, message=(f"Cần level **{req}** để dùng skill này." if _is_vi(lang) else f"Need level **{req}** to use this skill."))

            unlocked = await player_repo.get_unlocked_skills(conn, guild_id, user_id)
            if skill_id not in unlocked:
                return SkillUseResult(ok=False, message=("Bạn chưa unlock skill này." if _is_vi(lang) else "You haven't unlocked this skill yet."))

            from ..db.db import cooldown_remain, set_cooldown
            key = f"skill:{skill_id}"
            remain = await cooldown_remain(conn, guild_id, user_id, key)
            if remain > 0:
                return SkillUseResult(ok=False, message=(f"Skill đang cooldown: **{remain}s**" if _is_vi(lang) else f"Skill cooldown: **{remain}s**"))

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

                await player_repo.update_player_hp(conn, guild_id, user_id, new_hp)
                await set_cooldown(conn, guild_id, user_id, key, int(skill.get("cooldown", 900)))
                await conn.commit()

                return SkillUseResult(
                    ok=True,
                    message=(
                        f"✨ {skill.get('name', 'Skill')}: hồi **{actual} HP** ({new_hp}/{max_hp})"
                        if _is_vi(lang)
                        else f"✨ {skill.get('name', 'Skill')}: healed **{actual} HP** ({new_hp}/{max_hp})"
                    ),
                )

            return SkillUseResult(ok=False, message=("Skill active này chưa được implement." if _is_vi(lang) else "This active skill is not implemented yet."))

    @staticmethod
    async def get_skills(guild_id: int, user_id: int) -> dict:
        async with BaseService.with_user_transaction(guild_id, user_id, "get_skills") as conn:
            await player_repo.ensure_player_ready(conn, guild_id, user_id)
            level, _ = await player_repo.get_player_level_gold(conn, guild_id, user_id)
            unlocked = await player_repo.get_unlocked_skills(conn, guild_id, user_id)
            await conn.commit()

        return {"level": level, "unlocked": unlocked, "skills": SKILLS}
