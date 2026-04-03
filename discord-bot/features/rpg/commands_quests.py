import time

import discord
from discord import app_commands
from discord.ext import commands

from .assets import apply_embed_asset
from .db import (
    DB_WRITE_LOCK,
    add_quest_progress,
    ensure_db_ready,
    ensure_default_quests,
    ensure_player,
    gain_xp_and_level,
    open_db,
    record_gold_flow,
    refresh_quests_if_needed,
)


def _collect_files(*files: discord.File | None) -> list[discord.File]:
    return [f for f in files if f is not None]


def _quest_lines(rows) -> list[str]:
    names = {
        "kill_monsters": "Hạ quái",
        "kill_slime": "Hạ Slime Jackpot",
        "hunt_runs": "Chạy hunt",
        "open_lootboxes": "Mở lootbox",
        "boss_wins": "Thắng boss",
    }
    lines: list[str] = []
    now = int(time.time())
    claimed_map = {str(r[0]): int(r[9]) for r in rows}
    for qid, objective, target, progress, reward_gold, reward_xp, period, reset_after, prereq_quest_id, claimed in rows:
        prereq = str(prereq_quest_id or "")
        is_locked = bool(prereq) and claimed_map.get(prereq, 0) == 0
        if is_locked:
            status = f"🔒 Locked (need `{prereq}`)"
        else:
            status = "✅ Claimed" if int(claimed) == 1 else ("🎯 Ready" if int(progress) >= int(target) else "⏳ In progress")
        period_txt = ""
        if str(period) in {"daily", "weekly"} and int(reset_after or 0) > now:
            period_txt = f" • reset <t:{int(reset_after)}:R>"
        lines.append(
            f"`{qid}` • **{names.get(objective, objective)}** {progress}/{target}\n"
            f"Reward: {reward_gold} gold + {reward_xp} xp • {status}{period_txt}"
        )
    return lines


def register_quest_commands(bot: commands.Bot, guilds: list = None):
    guilds = guilds or []
    @bot.tree.command(name="quest", description="Xem quest RPG")
    async def quest(interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)

        await ensure_db_ready()
        async with DB_WRITE_LOCK:
            async with open_db() as conn:
                await ensure_player(conn, interaction.guild.id, interaction.user.id)
                await ensure_default_quests(conn, interaction.guild.id, interaction.user.id)
                await refresh_quests_if_needed(conn, interaction.guild.id, interaction.user.id)
                async with conn.execute(
                    """
                    SELECT quest_id, objective, target, progress, reward_gold, reward_xp, period, reset_after, prereq_quest_id, claimed
                    FROM quests
                    WHERE guild_id = ? AND user_id = ?
                    ORDER BY quest_id ASC
                    """,
                    (interaction.guild.id, interaction.user.id),
                ) as cur:
                    rows = await cur.fetchall()
                await conn.commit()

        e = discord.Embed(title="📜 RPG Quests", description="\n\n".join(_quest_lines(rows)), color=discord.Color.teal())
        await interaction.response.send_message(embed=e, ephemeral=True, files=_collect_files(apply_embed_asset(e, "quest")))

    @bot.tree.command(name="quest_claim", description="Nhận thưởng quest RPG")
    @app_commands.describe(quest_id="ID quest, ví dụ: kill_10")
    async def quest_claim(interaction: discord.Interaction, quest_id: str):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)

        await ensure_db_ready()
        async with DB_WRITE_LOCK:
            async with open_db() as conn:
                await ensure_player(conn, interaction.guild.id, interaction.user.id)
                await ensure_default_quests(conn, interaction.guild.id, interaction.user.id)
                await refresh_quests_if_needed(conn, interaction.guild.id, interaction.user.id)
                async with conn.execute(
                    """
                    SELECT target, progress, reward_gold, reward_xp, prereq_quest_id, claimed
                    FROM quests
                    WHERE guild_id = ? AND user_id = ? AND quest_id = ?
                    """,
                    (interaction.guild.id, interaction.user.id, quest_id),
                ) as cur:
                    row = await cur.fetchone()

                if not row:
                    return await interaction.response.send_message("❌ Không tìm thấy quest.", ephemeral=True)
                target, progress, reward_gold, reward_xp, prereq_quest_id, claimed = row
                prereq = str(prereq_quest_id or "")
                if prereq:
                    async with conn.execute(
                        "SELECT claimed FROM quests WHERE guild_id = ? AND user_id = ? AND quest_id = ?",
                        (interaction.guild.id, interaction.user.id, prereq),
                    ) as cur:
                        prow = await cur.fetchone()
                    if not prow or int(prow[0]) == 0:
                        return await interaction.response.send_message(
                            f"❌ Quest này chưa mở. Hoàn thành `{prereq}` trước.",
                            ephemeral=True,
                        )
                if int(claimed) == 1:
                    return await interaction.response.send_message("❌ Quest đã claim rồi.", ephemeral=True)
                if int(progress) < int(target):
                    return await interaction.response.send_message("❌ Quest chưa hoàn thành.", ephemeral=True)

                await conn.execute(
                    """
                    UPDATE quests SET claimed = 1, updated_at = strftime('%s','now')
                    WHERE guild_id = ? AND user_id = ? AND quest_id = ?
                    """,
                    (interaction.guild.id, interaction.user.id, quest_id),
                )
                await conn.execute(
                    "UPDATE players SET gold = gold + ? WHERE guild_id = ? AND user_id = ?",
                    (int(reward_gold), interaction.guild.id, interaction.user.id),
                )
                await record_gold_flow(conn, interaction.guild.id, interaction.user.id, int(reward_gold), "quest_claim")
                new_level, _remain_xp, leveled = await gain_xp_and_level(
                    conn, interaction.guild.id, interaction.user.id, int(reward_xp)
                )
                await conn.commit()

        msg = f"✅ Claim quest `{quest_id}`: +{reward_gold} gold, +{reward_xp} xp"
        if leveled:
            msg += f"\n🎉 Bạn đã lên level **{new_level}**"
        await interaction.response.send_message(msg)
