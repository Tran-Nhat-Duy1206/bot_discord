import discord
from discord.ext import commands

from .assets import apply_embed_asset, apply_monster_asset
from .combatlog import build_combat_log_text, publish_combat_log
from .boss import simulate_boss
from .coop import simulate_party_hunt
from .data import BOSS_VARIANTS, ITEMS, MONSTERS
from .db import (
    DB_WRITE_LOCK,
    RPG_BOSS_COOLDOWN,
    RPG_DUNGEON_COOLDOWN,
    RPG_HUNT_COOLDOWN,
    RPG_PARTY_HUNT_COOLDOWN,
    cooldown_remain,
    ensure_db_ready,
    ensure_default_quests,
    ensure_player,
    fmt_secs,
    get_player,
    open_db,
    refresh_quests_if_needed,
    set_cooldown,
)
from .dungeon import simulate_dungeon
from .events import current_weekly_event, event_brief
from .hunt import simulate_hunt


_MONSTER_NAME = {str(m.get("id")): str(m.get("name")) for m in (MONSTERS + BOSS_VARIANTS)}


def _collect_files(*files: discord.File | None) -> list[discord.File]:
    return [f for f in files if f is not None]


def _item_label(item_id: str) -> str:
    item = ITEMS.get(item_id, {"name": item_id, "emoji": "📦"})
    return f"{item['emoji']} {item['name']}"


def _rarity_emoji(rarity: str) -> str:
    r = (rarity or "common").lower()
    if r == "common":
        return "⚪"
    if r == "uncommon":
        return "🟢"
    if r == "rare":
        return "🔵"
    if r == "epic":
        return "🟣"
    if r == "legendary":
        return "🟡"
    return "⚫"


def _to_pct(value: float) -> int:
    return int(round(max(0.0, float(value)) * 100))


def _passive_text(lifesteal: float, crit_bonus: float, damage_reduction: float) -> str:
    return (
        f"Lifesteal +{_to_pct(lifesteal)}% • "
        f"Crit +{_to_pct(crit_bonus)}% • "
        f"Damage Reduction {_to_pct(damage_reduction)}%"
    )


def _as_str_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(x) for x in value]


def register_combat_commands(bot: commands.Bot):
    @bot.tree.command(name="rpg_event", description="Xem PvE weekly event hiện tại")
    async def rpg_event(interaction: discord.Interaction):
        event = current_weekly_event()
        e = discord.Embed(title="📅 Weekly PvE Event", color=discord.Color.teal())
        e.add_field(name="Event", value=event_brief(event), inline=False)
        e.add_field(name="Week", value=str(int(event.get("week", 0))), inline=True)
        e.add_field(name="ID", value=str(event.get("id", "")), inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @bot.tree.command(name="hunt", description="Đi săn quái RPG")
    async def hunt(interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)

        await ensure_db_ready()
        await interaction.response.defer()

        async with DB_WRITE_LOCK:
            async with open_db() as conn:
                await ensure_player(conn, interaction.guild.id, interaction.user.id)
                await ensure_default_quests(conn, interaction.guild.id, interaction.user.id)
                await refresh_quests_if_needed(conn, interaction.guild.id, interaction.user.id)
                remain = await cooldown_remain(conn, interaction.guild.id, interaction.user.id, "hunt")
                if remain > 0:
                    return await interaction.followup.send(
                        f"⏳ Hunt cooldown còn **{fmt_secs(remain)}**.",
                        ephemeral=True,
                    )

                result = await simulate_hunt(conn, interaction.guild.id, interaction.user.id)
                await set_cooldown(conn, interaction.guild.id, interaction.user.id, "hunt", RPG_HUNT_COOLDOWN)
                await conn.commit()

        if not result.get("ok"):
            return await interaction.followup.send("❌ Hunt lỗi.", ephemeral=True)

        drops = result.get("drops") if isinstance(result.get("drops"), dict) else {}
        drop_txt = ", ".join(f"{_item_label(item_id)} x{amount}" for item_id, amount in drops.items()) if drops else "Không có"
        rarity_map = result.get("drop_rarity") if isinstance(result.get("drop_rarity"), dict) else {}
        rarity_txt = ", ".join(f"{_rarity_emoji(str(k))} {str(k)} x{int(v)}" for k, v in rarity_map.items()) if rarity_map else "(none)"

        e = discord.Embed(title="⚔️ Kết quả Hunt", color=discord.Color.red())
        e.add_field(name="Đã gặp", value=f"{int(result.get('pack', 0))} quái", inline=True)
        e.add_field(name="Hạ gục", value=str(int(result.get("kills", 0))), inline=True)
        e.add_field(name="Slime", value=str(int(result.get("slime_kills", 0))), inline=True)
        e.add_field(name="Reward", value=f"+{int(result.get('gold', 0))} gold\n+{int(result.get('xp', 0))} xp", inline=False)
        effects = result.get("combat_effects") if isinstance(result.get("combat_effects"), dict) else {}
        e.add_field(
            name="Combat Passive",
            value=_passive_text(float(effects.get("lifesteal", 0.0)), float(effects.get("crit_bonus", 0.0)), float(effects.get("damage_reduction", 0.0))),
            inline=False,
        )
        set_bonus_name = str(result.get("set_bonus", "")).strip()
        if set_bonus_name:
            e.add_field(name="Set Bonus", value=f"🧩 {set_bonus_name}", inline=False)
        weekly_event = result.get("weekly_event") if isinstance(result.get("weekly_event"), dict) else {}
        if weekly_event:
            e.add_field(name="Weekly Event", value=str(weekly_event.get("name", "Weekly Event")), inline=False)
        skill_passives = _as_str_list(result.get("passive_skills"))
        if skill_passives:
            e.add_field(name="Skill Passive", value="\n".join(f"• {s}" for s in skill_passives[:3]), inline=False)
        lifesteal_heal = int(result.get("lifesteal_heal", 0))
        damage_blocked = int(result.get("damage_blocked", 0))
        if lifesteal_heal > 0 or damage_blocked > 0:
            e.add_field(name="Passive Impact", value=f"❤️ +{lifesteal_heal} HP lifesteal • 🛡️ chặn {damage_blocked} dmg", inline=False)
        e.add_field(name="Drops", value=drop_txt, inline=False)
        e.add_field(name="Drop Rarity", value=rarity_txt, inline=False)
        jackpot_hits = int(result.get("jackpot_hits", 0))
        if jackpot_hits > 0:
            e.add_field(name="Slime Jackpot", value=f"✨ {jackpot_hits} hit(s), +{int(result.get('jackpot_gold', 0))} gold", inline=False)
        e.add_field(name="HP còn lại", value=str(int(result.get("hp", 0))), inline=True)
        if bool(result.get("leveled_up", False)):
            e.add_field(name="Level Up", value=f"🎉 Lên level **{int(result.get('level', 1))}**", inline=True)
        logs = result.get("logs") if isinstance(result.get("logs"), list) else []
        if logs:
            e.add_field(name="Chi tiết", value="\n".join(logs[:10]), inline=False)

        encounters = result.get("encounters") if isinstance(result.get("encounters"), dict) else {}
        encounter_ids = list(encounters.keys())
        hunt_asset_file = apply_monster_asset(e, encounter_ids[0]) if encounter_ids else None
        if hunt_asset_file is None:
            hunt_asset_file = apply_embed_asset(e, "hunt")

        log_url = await publish_combat_log(build_combat_log_text(str(interaction.user), result))
        e.add_field(name="Combat Log", value=f"🔗 {log_url}" if log_url else "(web log unavailable, using inline summary)", inline=False)
        await interaction.followup.send(embed=e, files=_collect_files(hunt_asset_file))

    @bot.tree.command(name="boss", description="Đánh boss RPG")
    async def boss(interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        await ensure_db_ready()
        await interaction.response.defer()

        async with DB_WRITE_LOCK:
            async with open_db() as conn:
                await ensure_player(conn, interaction.guild.id, interaction.user.id)
                await ensure_default_quests(conn, interaction.guild.id, interaction.user.id)
                await refresh_quests_if_needed(conn, interaction.guild.id, interaction.user.id)
                remain = await cooldown_remain(conn, interaction.guild.id, interaction.user.id, "boss")
                if remain > 0:
                    return await interaction.followup.send(f"⏳ Boss cooldown còn **{fmt_secs(remain)}**.", ephemeral=True)
                base_row = await get_player(conn, interaction.guild.id, interaction.user.id)
                result = await simulate_boss(conn, interaction.guild.id, interaction.user.id, base_row)
                await set_cooldown(conn, interaction.guild.id, interaction.user.id, "boss", RPG_BOSS_COOLDOWN)
                await conn.commit()

        if not result.get("ok"):
            return await interaction.followup.send("❌ Boss battle lỗi.", ephemeral=True)

        is_win = bool(result.get("win"))
        e = discord.Embed(title="👑 Boss Victory" if is_win else "💀 Boss Defeat", color=discord.Color.orange() if is_win else discord.Color.dark_red())
        if not is_win:
            e.description = f"Bạn đã thua trước **{result.get('boss', 'Boss')}**.\nHP còn lại: **{result.get('base_hp', 1)}**"
        else:
            e.add_field(name="Boss", value=str(result.get("boss", "Unknown")), inline=True)
            e.add_field(name="Reward", value=f"+{int(result.get('gold', 0))} gold\n+{int(result.get('xp', 0))} xp", inline=False)

        effects = result.get("combat_effects") if isinstance(result.get("combat_effects"), dict) else {}
        e.add_field(name="Combat Passive", value=_passive_text(float(effects.get("lifesteal", 0.0)), float(effects.get("crit_bonus", 0.0)), float(effects.get("damage_reduction", 0.0))), inline=False)
        set_bonus_name = str(result.get("set_bonus", "")).strip()
        if set_bonus_name:
            e.add_field(name="Set Bonus", value=f"🧩 {set_bonus_name}", inline=False)
        weekly_event = result.get("weekly_event") if isinstance(result.get("weekly_event"), dict) else {}
        if weekly_event:
            e.add_field(name="Weekly Event", value=str(weekly_event.get("name", "Weekly Event")), inline=False)
        skill_passives = _as_str_list(result.get("passive_skills"))
        if skill_passives:
            e.add_field(name="Skill Passive", value="\n".join(f"• {s}" for s in skill_passives[:3]), inline=False)
        lifesteal_heal = int(result.get("lifesteal_heal", 0))
        damage_blocked = int(result.get("damage_blocked", 0))
        if lifesteal_heal > 0 or damage_blocked > 0:
            e.add_field(name="Passive Impact", value=f"❤️ +{lifesteal_heal} HP lifesteal • 🛡️ chặn {damage_blocked} dmg", inline=False)
        e.add_field(name="Boss Mechanics", value=f"Rage: {'Yes' if bool(result.get('rage_triggered', False)) else 'No'} • Shield turns: {int(result.get('shield_turns', 0))} • Summons: {int(result.get('summon_count', 0))}", inline=False)
        phase_events = result.get("phase_events") if isinstance(result.get("phase_events"), list) else []
        if phase_events:
            e.add_field(name="Mechanic Timeline", value="\n".join(phase_events[:4]), inline=False)
        drops = result.get("drops") if isinstance(result.get("drops"), dict) else {}
        if drops:
            e.add_field(name="Drops", value=", ".join(f"{_item_label(k)} x{v}" for k, v in drops.items()), inline=False)
        e.add_field(name="HP còn lại", value=str(int(result.get("base_hp", 1))), inline=True)
        if bool(result.get("leveled_up", False)):
            e.add_field(name="Level Up", value=f"🎉 Lên level **{int(result.get('level', 1))}**", inline=True)
        logs = result.get("logs") if isinstance(result.get("logs"), list) else []
        if logs:
            e.add_field(name="Chi tiết", value="\n".join(logs[:8]), inline=False)

        boss_id = str(result.get("boss_id", "ancient_ogre"))
        boss_asset_file = apply_monster_asset(e, boss_id)
        if boss_asset_file is None:
            boss_asset_file = apply_embed_asset(e, "boss")

        log_url = await publish_combat_log(build_combat_log_text(f"{interaction.user} [BOSS]", result))
        if log_url:
            e.add_field(name="Combat Log", value=f"🔗 {log_url}", inline=False)
        await interaction.followup.send(embed=e, files=_collect_files(boss_asset_file))

    @bot.tree.command(name="dungeon", description="Chinh phục dungeon nhiều tầng")
    async def dungeon(interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        await ensure_db_ready()
        await interaction.response.defer()
        async with DB_WRITE_LOCK:
            async with open_db() as conn:
                await ensure_player(conn, interaction.guild.id, interaction.user.id)
                remain = await cooldown_remain(conn, interaction.guild.id, interaction.user.id, "dungeon")
                if remain > 0:
                    return await interaction.followup.send(f"⏳ Dungeon cooldown còn **{fmt_secs(remain)}**.", ephemeral=True)
                result = await simulate_dungeon(conn, interaction.guild.id, interaction.user.id)
                await set_cooldown(conn, interaction.guild.id, interaction.user.id, "dungeon", RPG_DUNGEON_COOLDOWN)
                await conn.commit()

        if not result.get("ok"):
            return await interaction.followup.send("❌ Dungeon lỗi.", ephemeral=True)

        e = discord.Embed(
            title="🏰 Dungeon Cleared" if bool(result.get("cleared", False)) else "🩸 Dungeon Failed",
            color=discord.Color.green() if bool(result.get("cleared", False)) else discord.Color.dark_red(),
        )
        e.add_field(name="Progress", value=f"{int(result.get('floors_cleared', 0))}/{int(result.get('total_floors', 0))} tầng", inline=True)
        e.add_field(name="HP còn lại", value=str(int(result.get("hp", 1))), inline=True)
        e.add_field(name="Reward", value=f"+{int(result.get('gold', 0))} gold\n+{int(result.get('xp', 0))} xp", inline=False)
        drops = result.get("drops") if isinstance(result.get("drops"), dict) else {}
        e.add_field(name="Drops", value=", ".join(f"{_item_label(k)} x{v}" for k, v in drops.items()) if drops else "Không có", inline=False)
        effects = result.get("combat_effects") if isinstance(result.get("combat_effects"), dict) else {}
        e.add_field(name="Combat Passive", value=_passive_text(float(effects.get("lifesteal", 0.0)), float(effects.get("crit_bonus", 0.0)), float(effects.get("damage_reduction", 0.0))), inline=False)
        set_bonus_name = str(result.get("set_bonus", "")).strip()
        if set_bonus_name:
            e.add_field(name="Set Bonus", value=f"🧩 {set_bonus_name}", inline=False)
        weekly_event = result.get("weekly_event") if isinstance(result.get("weekly_event"), dict) else {}
        if weekly_event:
            e.add_field(name="Weekly Event", value=str(weekly_event.get("name", "Weekly Event")), inline=False)
        skill_passives = _as_str_list(result.get("passive_skills"))
        if skill_passives:
            e.add_field(name="Skill Passive", value="\n".join(f"• {s}" for s in skill_passives[:3]), inline=False)
        if bool(result.get("leveled_up", False)):
            e.add_field(name="Level Up", value=f"🎉 Lên level **{int(result.get('level', 1))}**", inline=True)
        logs = result.get("logs") if isinstance(result.get("logs"), list) else []
        if logs:
            e.add_field(name="Chi tiết", value="\n".join(logs[:8]), inline=False)
        await interaction.followup.send(embed=e, files=_collect_files(apply_embed_asset(e, "hunt")))

    @bot.tree.command(name="party_hunt", description="Co-op hunt 2-4 người")
    @discord.app_commands.describe(member2="Thành viên thứ 2", member3="Thành viên thứ 3", member4="Thành viên thứ 4")
    async def party_hunt(
        interaction: discord.Interaction,
        member2: discord.Member,
        member3: discord.Member | None = None,
        member4: discord.Member | None = None,
    ):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)

        party = [interaction.user, member2]
        if member3 is not None:
            party.append(member3)
        if member4 is not None:
            party.append(member4)

        unique_ids: set[int] = set()
        clean_party: list[discord.Member] = []
        for m in party:
            if m.bot or m.id in unique_ids:
                continue
            unique_ids.add(m.id)
            clean_party.append(m)
        if len(clean_party) < 2:
            return await interaction.response.send_message("❌ Party cần tối thiểu 2 người thật.", ephemeral=True)

        await ensure_db_ready()
        await interaction.response.defer()
        async with DB_WRITE_LOCK:
            async with open_db() as conn:
                for m in clean_party:
                    await ensure_player(conn, interaction.guild.id, m.id)
                for m in clean_party:
                    remain = await cooldown_remain(conn, interaction.guild.id, m.id, "party_hunt")
                    if remain > 0:
                        return await interaction.followup.send(f"⏳ {m.mention} còn cooldown party hunt **{fmt_secs(remain)}**.", ephemeral=True)
                result = await simulate_party_hunt(conn, interaction.guild.id, [m.id for m in clean_party])
                if not result.get("ok"):
                    await conn.rollback()
                    return await interaction.followup.send("❌ Party hunt lỗi.", ephemeral=True)
                for m in clean_party:
                    await set_cooldown(conn, interaction.guild.id, m.id, "party_hunt", RPG_PARTY_HUNT_COOLDOWN)
                await conn.commit()

        e = discord.Embed(title="🤝 Party Hunt", color=discord.Color.gold())
        e.add_field(name="Party", value=", ".join(m.mention for m in clean_party), inline=False)
        e.add_field(name="Kết quả", value=f"Kills: {int(result.get('kills', 0))}/{int(result.get('pack', 0))}\nGold tổng: +{int(result.get('gold', 0))}\nXP tổng: +{int(result.get('xp', 0))}", inline=False)
        member_rows = result.get("members") if isinstance(result.get("members"), list) else []
        if member_rows:
            lines = []
            for row in member_rows[:4]:
                if not isinstance(row, dict):
                    continue
                uid = int(row.get("user_id", 0))
                m = interaction.guild.get_member(uid)
                name = m.display_name if m else str(uid)
                lines.append(f"**{name}**: +{int(row.get('gold', 0))}g, +{int(row.get('xp', 0))}xp, kills {int(row.get('kills', 0))}, hp {int(row.get('hp', 1))}")
            if lines:
                e.add_field(name="Theo thành viên", value="\n".join(lines), inline=False)
        drops = result.get("drops") if isinstance(result.get("drops"), dict) else {}
        e.add_field(name="Drops", value=", ".join(f"{_item_label(k)} x{v}" for k, v in drops.items()) if drops else "Không có", inline=False)
        weekly_event = result.get("weekly_event") if isinstance(result.get("weekly_event"), dict) else {}
        if weekly_event:
            e.add_field(name="Weekly Event", value=str(weekly_event.get("name", "Weekly Event")), inline=False)
        logs = result.get("logs") if isinstance(result.get("logs"), list) else []
        if logs:
            e.add_field(name="Chi tiết", value="\n".join(logs[:8]), inline=False)
        await interaction.followup.send(embed=e, files=_collect_files(apply_embed_asset(e, "hunt")))
