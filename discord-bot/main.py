import os
import time
import logging
import asyncio
from logging.handlers import RotatingFileHandler
from typing import Optional

from discord import app_commands
import discord
from discord.ext import commands
from dotenv import load_dotenv

GUILDS: list[discord.abc.Snowflake] = []

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

os.makedirs("logs", exist_ok=True)
logger = logging.getLogger("bot")
logger.setLevel(logging.INFO)

fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s]: %(message)s")

sh = logging.StreamHandler()
sh.setFormatter(fmt)
logger.addHandler(sh)

fh = RotatingFileHandler("logs/bot.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
fh.setFormatter(fmt)
logger.addHandler(fh)

bot = commands.Bot(command_prefix="-", intents=intents, help_command=None)
_START_TS = time.time()

try:
    from features import economy, moderation, leveling, rpg, utility, music, fun
except ImportError:
    try:
        from features import economy
        from features import moderation
        from features import leveling
        from features import rpg
        from features import utility
        from features import music
        from features import fun
    except ImportError as e:
        logger.error(f"Failed to import required modules: {e}")
        raise
    
moderation.setup(bot, GUILDS)
leveling.setup(bot, GUILDS)
rpg.setup(bot, GUILDS)
utility.setup(bot, GUILDS)
music.setup(bot, GUILDS)
fun.setup(bot, GUILDS)

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Game(name="Nô lệ của mọi nhà"))
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} app commands.")
    except Exception:
        logger.exception("tree.sync failed")
    logger.info(f"Bot {bot.user} ready.")


@bot.tree.command(name="ping", description="Kiểm tra bot sống")
async def ping(interaction: discord.Interaction):
    ping_time = bot.latency * 1000
    logger.info(f"Ping command used by {interaction.user} ({interaction.user.id}), latency: {ping_time:.2f}ms")
    await interaction.response.send_message(f"Pong! Latency: {ping_time:.2f}ms", ephemeral=True)


@bot.tree.command(name="status", description="Xem tình trạng bot")
async def status(interaction: discord.Interaction):
    up = int(time.time() - _START_TS)
    guilds = len(bot.guilds)
    await interaction.response.send_message(
        f"🧠 Uptime: **{up}s**\n🌐 Servers: **{guilds}**",
        ephemeral=True,
    )

class NukeConfirmView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=30)
        self.author_id = author_id

    @discord.ui.button(label="🔥 Xác nhận NUKE", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message(
                "❌ Bạn không phải người đã gọi lệnh này.",
                ephemeral=True
            )

        channel = interaction.channel
        if channel is None:
            return await interaction.response.send_message(
                "❌ Không tìm thấy kênh.",
                ephemeral=True
            )

        await interaction.response.send_message(
            f"💥 {interaction.user.mention} đang xóa tin nhắn trong kênh này...",
            ephemeral=True
        )

        try:
            deleted = await channel.purge(limit=None)
            count = len(deleted)
        except Exception:
            count = 0
            async for msg in channel.history(limit=None):
                try:
                    await msg.delete()
                    count += 1
                except Exception:
                    pass

        logger.warning(
            f"Message nuke by {interaction.user} ({interaction.user.id}) "
            f"in guild {interaction.guild.name} ({interaction.guild.id}) "
            f"channel #{channel.name}"
        )

        embed = discord.Embed(
            title="💥 Channel đã bị NUKE",
            description=f"{interaction.user.mention} đã xóa toàn bộ tin nhắn trong channel này.",
            color=discord.Color.red()
        )

        embed.add_field(name="Tin nhắn đã xóa", value=str(count), inline=True)
        embed.add_field(name="Channel", value=channel.mention, inline=True)
        embed.set_footer(text=f"User ID: {interaction.user.id}")

        await channel.send(embed=embed)

        await interaction.followup.send(
            f"✅ Đã xóa **{count}** tin nhắn.",
            ephemeral=True
        )

        self.stop()

    @discord.ui.button(label="❌ Hủy", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message(
                "❌ Bạn không phải người đã gọi lệnh này.",
                ephemeral=True
            )

        await interaction.response.send_message("❌ Đã hủy nuke.", ephemeral=True)
        self.stop()


@bot.tree.command(
    name="nuke",
    description="Xóa toàn bộ tin nhắn trong kênh (chỉ admin)"
)
async def nuke(interaction: discord.Interaction):
    if interaction.guild is None:
        return await interaction.response.send_message(
            "❌ Chỉ dùng trong server.",
            ephemeral=True
        )

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "❌ Chỉ admin mới dùng được lệnh này.",
            ephemeral=True
        )

    me = interaction.guild.me
    if me is None or not interaction.channel.permissions_for(me).manage_messages:
        return await interaction.response.send_message(
            "❌ Bot không có quyền Manage Messages trong kênh này.",
            ephemeral=True
        )

    await interaction.response.send_message(
        "⚠️ Bạn có chắc muốn xóa toàn bộ tin nhắn trong kênh này không?",
        view=NukeConfirmView(interaction.user.id),
        ephemeral=True
    )


@bot.tree.command(name="help", description="Hướng dẫn nhanh")
async def help_cmd(interaction: discord.Interaction):
    e = discord.Embed(title="📚 Help", color=discord.Color.blurple())
    e.add_field(
        name="🛡️ Moderation",
        value=(
            "`/kick` kick member\n"
            "`/ban` ban member\n"
            "`/timeout`/`/untimeout` quản lý timeout\n"
            "`/warn` `/warnings` `/warnhistory` `/clearwarn` cảnh cáo\n"
            "`/clear` xóa tin nhắn\n"
            "`/setautorole` `/autorole_off` auto role\n"
            "`/setmodlog` `/modlog_off` log moderation"
        ),
        inline=False,
    )
    e.add_field(
        name="📊 Leveling",
        value=(
            "`/rank` xem rank/level\n"
            "`/level_top` leaderboard level\n"
            "`/level_config` cấu hình leveling\n"
            "`/level_ignore_add` `/level_ignore_remove` `/level_ignore_list`"
        ),
        inline=False,
    )
    e.add_field(
        name="🐉 RPG",
        value=(
            "`/rpg_start` tạo nhân vật\n"
            "`/profile` `/stats` xem chỉ số\n"
            "`/hunt` `/boss` chiến đấu\n"
            "`/dungeon` dungeon nhiều tầng\n"
            "`/party_hunt` co-op hunt\n"
            "`/rpg_event` weekly event\n"
            "`/quest` `/quest_claim` quest\n"
            "`/rpg_shop` `/rpg_buy` `/rpg_sell` shop\n"
            "`/craft_list` `/craft` crafting\n"
            "`/rpg_loot` `/rpg_jackpot` loot & jackpot\n"
            "`/rpg_balance_dashboard` dashboard cân bằng\n"
            "`/rpg_economy_audit` audit gold source/sink (admin)\n"
            "`/rpg_season_status` `/rpg_season_rollover` season\n"
            "`/rpg_inventory` `/rpg_use` `/rpg_drop` `/open` túi đồ\n"
            "`/equip` `/unequip` `/rpg_equipment` trang bị\n"
            "`/rpg_skills` `/rpg_skill_unlock` `/rpg_skill_use` skill\n"
            "`/rpg_daily` `/rpg_balance` `/rpg_pay` tiền\n"
            "`/rpg_leaderboard` bảng xếp hạng"
        ),
        inline=False,
    )
    e.add_field(
        name="🎵 Music",
        value=(
            "`/join` vào voice\n"
            "`/play` phát nhạc\n"
            "`/playnext` thêm lên đầu queue\n"
            "`/queue` xem hàng đợi (phân trang)\n"
            "`/shuffle` trộn hàng đợi\n"
            "`/skip` `/pause` `/resume` điều khiển\n"
            "`/loop` lặp 1 bài\n"
            "`/autoplay` related khi hết queue\n"
            "`/volume` chỉnh âm lượng\n"
            "`/lyrics` lyrics bài hiện tại\n"
            "`/set_dj_role` `/clear_dj_role` quyền DJ\n"
            "`/stop` `/leave` dừng và rời"
        ),
        inline=False,
    )
    e.add_field(
        name="🎉 Fun",
        value=(
            "`/meme` meme ngẫu nhiên\n"
            "`/coinflip` tung xu\n"
            "`/dice` đổ xúc xắc\n"
            "`/8ball` hỏi yes/no\n"
            "`/trivia` câu hỏi vui"
        ),
        inline=False,
    )
    e.add_field(
        name="🧰 Utility",
        value=(
            "`/avatar` xem avatar\n"
            "`/userinfo` thông tin user\n"
            "`/serverinfo` thông tin server\n"
            "`/remind` nhắc việc"
        ),
        inline=False,
    )
    e.add_field(
        name="🪙 Economy",
        value=(
            "`/economy balance` xem coin\n"
            "`/economy daily` nhận thưởng ngày\n"
            "`/economy work` đi làm kiếm coin\n"
            "`/economy shop` xem cửa hàng\n"
            "`/economy buy` mua vật phẩm\n"
            "`/economy inventory` xem kho đồ\n"
            "`/economy give` chuyển coin\n"
            "`/economy leaderboard` top coin toàn bot\n"
            "`/economy blackjack` chơi blackjack"
        ),
        inline=False,
    )
    await interaction.response.send_message(embed=e, ephemeral=True)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    logger.exception("app command error: %r", error)
    if isinstance(error, discord.app_commands.CheckFailure):
        msg = str(error) or "❌ Bạn không thể dùng lệnh này lúc này."
    else:
        msg = "❌ Có lỗi xảy ra. Thử lại sau hoặc báo admin."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass


async def main():
    if not TOKEN:
        raise RuntimeError("Missing DISCORD_TOKEN")

    await economy.setup_economy(bot)
    try:
        await bot.start(TOKEN)
    finally:
        pass


if __name__ == "__main__":
    asyncio.run(main())
