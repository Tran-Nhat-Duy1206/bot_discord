import discord
from discord import app_commands
from discord.ext import commands

from .db import (
    DB_WRITE_LOCK,
    ensure_db_ready,
    open_db,
    get_active_season,
    start_new_season,
    close_active_season,
    get_season_leaderboard_snapshot,
    record_season_reward,
    apply_season_soft_reset,
)
from .db import record_gold_flow
from .db import add_inventory


def _season_reward(rank: int) -> tuple[int, int]:
    if rank <= 1:
        return 5000, 10
    if rank == 2:
        return 3500, 7
    if rank == 3:
        return 2500, 5
    if rank <= 10:
        return 1200, 2
    return 0, 0


def register_season_commands(bot: commands.Bot):
    @bot.tree.command(name="rpg_season_status", description="Xem trạng thái season RPG")
    async def rpg_season_status(interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)

        await ensure_db_ready()
        async with open_db() as conn:
            active = await get_active_season(conn)

        if not active:
            return await interaction.response.send_message(
                "Hiện chưa có season active. Dùng `/rpg_season_rollover` để khởi tạo.",
                ephemeral=True,
            )

        season_id, start_ts, _end_ts, is_active, note = active
        e = discord.Embed(title="🏁 RPG Season Status", color=discord.Color.teal())
        e.add_field(name="Season", value=f"#{int(season_id)}", inline=True)
        e.add_field(name="Started", value=f"<t:{int(start_ts)}:R>", inline=True)
        e.add_field(name="State", value="Active" if int(is_active) == 1 else "Closed", inline=True)
        if str(note or "").strip():
            e.add_field(name="Note", value=str(note), inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @bot.tree.command(name="rpg_season_rollover", description="Đóng season cũ, thưởng top và soft reset")
    @app_commands.describe(note="Ghi chú season mới")
    async def rpg_season_rollover(interaction: discord.Interaction, note: str = ""):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Chỉ admin mới dùng lệnh này.", ephemeral=True)

        await ensure_db_ready()
        async with DB_WRITE_LOCK:
            async with open_db() as conn:
                active = await get_active_season(conn)
                if not active:
                    new_sid = await start_new_season(conn, note or "Season 1")
                    await conn.commit()
                    return await interaction.response.send_message(
                        f"✅ Đã khởi tạo season đầu tiên: **#{new_sid}**.",
                        ephemeral=True,
                    )

                old_sid = int(active[0])
                rows = await get_season_leaderboard_snapshot(conn, interaction.guild.id, limit=10)
                winners: list[str] = []
                for idx, row in enumerate(rows, start=1):
                    uid, _lvl, _gold, _kills, score = row
                    reward_gold, reward_lootbox = _season_reward(idx)
                    if reward_gold > 0:
                        await conn.execute(
                            "UPDATE players SET gold = gold + ? WHERE guild_id = ? AND user_id = ?",
                            (reward_gold, interaction.guild.id, int(uid)),
                        )
                        await record_gold_flow(conn, interaction.guild.id, int(uid), reward_gold, "season_reward")
                    if reward_lootbox > 0:
                        await add_inventory(conn, interaction.guild.id, int(uid), "lootbox", reward_lootbox)

                    await record_season_reward(
                        conn,
                        old_sid,
                        interaction.guild.id,
                        int(uid),
                        idx,
                        int(score),
                        reward_gold,
                        reward_lootbox,
                    )

                    member = interaction.guild.get_member(int(uid))
                    name = member.display_name if member else f"<@{uid}>"
                    winners.append(
                        f"**#{idx}** {name} • score {int(score)} • +{reward_gold}g, +{reward_lootbox} lootbox"
                    )

                await close_active_season(conn)
                reset_count = await apply_season_soft_reset(conn, interaction.guild.id)
                new_sid = await start_new_season(conn, note or f"Season {old_sid + 1}")
                await conn.commit()

        e = discord.Embed(title="🔄 RPG Season Rollover", color=discord.Color.gold())
        e.add_field(name="Closed", value=f"#{old_sid}", inline=True)
        e.add_field(name="New", value=f"#{new_sid}", inline=True)
        e.add_field(name="Reset players", value=str(reset_count), inline=True)
        e.add_field(name="Top Rewards", value="\n".join(winners) if winners else "(không có dữ liệu)", inline=False)
        await interaction.response.send_message(embed=e)
