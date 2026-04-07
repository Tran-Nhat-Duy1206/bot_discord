import asyncio
from datetime import datetime, timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands


def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "N/A"
    if dt.tzinfo is None:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    ts = int(dt.timestamp())
    return f"<t:{ts}:F>"


def setup(bot: commands.Bot, guilds: list = None):
    guilds = guilds or []
    @bot.tree.command(name="avatar", description="Xem avatar của bạn hoặc người khác")
    @app_commands.describe(member="Member cần xem avatar")
    async def avatar(interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or (interaction.user if isinstance(interaction.user, discord.Member) else None)
        if target is None:
            return await interaction.response.send_message("❌ Không xác định được người dùng.", ephemeral=True)

        e = discord.Embed(title=f"🖼️ Avatar - {target.display_name}", color=discord.Color.blurple())
        e.set_image(url=target.display_avatar.url)
        await interaction.response.send_message(embed=e)

    @bot.tree.command(name="userinfo", description="Xem thông tin user")
    @app_commands.describe(member="Member cần xem")
    async def userinfo(interaction: discord.Interaction, member: Optional[discord.Member] = None):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        target = member or (interaction.user if isinstance(interaction.user, discord.Member) else None)
        if target is None:
            return await interaction.response.send_message("❌ Không xác định được member.", ephemeral=True)

        roles = [r.mention for r in target.roles if r.name != "@everyone"]
        role_txt = ", ".join(roles[-8:]) if roles else "(none)"

        e = discord.Embed(title=f"👤 User Info - {target}", color=discord.Color.green())
        e.add_field(name="ID", value=str(target.id), inline=True)
        e.add_field(name="Bot", value=str(target.bot), inline=True)
        e.add_field(name="Top Role", value=target.top_role.mention if target.top_role else "N/A", inline=True)
        e.add_field(name="Created", value=_fmt_dt(target.created_at), inline=False)
        e.add_field(name="Joined", value=_fmt_dt(target.joined_at), inline=False)
        e.add_field(name="Roles", value=role_txt, inline=False)
        e.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=e)

    @bot.tree.command(name="serverinfo", description="Xem thông tin server")
    async def serverinfo(interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)

        text_count = len([c for c in guild.channels if isinstance(c, discord.TextChannel)])
        voice_count = len([c for c in guild.channels if isinstance(c, discord.VoiceChannel)])

        e = discord.Embed(title=f"🏠 Server Info - {guild.name}", color=discord.Color.gold())
        e.add_field(name="ID", value=str(guild.id), inline=True)
        e.add_field(name="Owner", value=guild.owner.mention if guild.owner else "N/A", inline=True)
        e.add_field(name="Created", value=_fmt_dt(guild.created_at), inline=False)
        e.add_field(name="Members", value=str(guild.member_count), inline=True)
        e.add_field(name="Text/Voice", value=f"{text_count}/{voice_count}", inline=True)
        e.add_field(name="Roles", value=str(len(guild.roles)), inline=True)
        if guild.icon:
            e.set_thumbnail(url=guild.icon.url)
        await interaction.response.send_message(embed=e)

    @bot.tree.command(name="remind", description="Nhắc bạn sau một khoảng thời gian")
    @app_commands.describe(minutes="Số phút nhắc", message="Nội dung nhắc")
    async def remind(interaction: discord.Interaction, minutes: int, message: str):
        if minutes <= 0 or minutes > 1440:
            return await interaction.response.send_message("❌ Minutes phải trong khoảng 1-1440.", ephemeral=True)
        if not message.strip():
            return await interaction.response.send_message("❌ Nội dung nhắc không được trống.", ephemeral=True)

        channel = interaction.channel
        if channel is None:
            return await interaction.response.send_message("❌ Không xác định được channel.", ephemeral=True)

        await interaction.response.send_message(
            f"⏰ Ok, mình sẽ nhắc bạn sau **{minutes}** phút.",
            ephemeral=True,
        )

        user_id = interaction.user.id
        guild_id = interaction.guild.id if interaction.guild else None
        channel_id = channel.id
        reminder_text = message.strip()

        async def _job():
            await asyncio.sleep(minutes * 60)
            target_channel = bot.get_channel(channel_id)
            if target_channel is None:
                return
            prefix = f"<@{user_id}>"
            if guild_id is None:
                prefix = "Bạn ơi"
            try:
                await target_channel.send(f"🔔 {prefix} nhắc bạn: {reminder_text}")
            except Exception:
                pass

        asyncio.create_task(_job())
