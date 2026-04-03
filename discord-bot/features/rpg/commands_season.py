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


def register_season_commands(bot: commands.Bot, guilds: list = None):
    guilds = guilds or []
    @bot.tree.command(name="rpg_season_status", description="Xem trạng thái season RPG")
    async def rpg_season_status(interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)

        await ensure_db_ready()
        async with open_db() as conn:
            active = await get_active_season(conn)

        if not active:
            return await interaction.response.send_message(
                "Hiện chưa có season active.",
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
