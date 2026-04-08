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

from language import (
    CMD_I18N,
    ensure_lang_db_ready,
    resolve_lang,
    save_lang,
    tr,
)

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

bot = commands.Bot(command_prefix=commands.when_mentioned_or("-", "s!"), intents=intents, help_command=None)
_START_TS = time.time()

class BotTranslator(app_commands.Translator):
    async def translate(
        self,
        string: app_commands.locale_str,
        locale: discord.Locale,
        context: app_commands.TranslationContext,
    ) -> Optional[str]:
        key = str(string.message)
        table = CMD_I18N.get(key)
        if not table:
            return None
        lang = "vi" if str(locale).lower().startswith("vi") else "en"
        return table.get(lang)


_TRANSLATOR_SET = False

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
    await bot.change_presence(activity=discord.Game(name="/rpg_start | /status"))
    global _TRANSLATOR_SET
    try:
        if not _TRANSLATOR_SET:
            await bot.tree.set_translator(BotTranslator())
            _TRANSLATOR_SET = True
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} app commands.")
    except Exception:
        logger.exception("tree.sync failed")
    logger.info(f"Bot {bot.user} ready.")


@bot.tree.command(name="ping", description=app_commands.locale_str("cmd.ping.desc"))
async def ping(interaction: discord.Interaction):
    ping_time = bot.latency * 1000
    logger.info(f"Ping command used by {interaction.user} ({interaction.user.id}), latency: {ping_time:.2f}ms")
    lang = await resolve_lang(interaction)
    await interaction.response.send_message(tr(lang, "ping", latency=ping_time), ephemeral=True)


@bot.tree.command(name="hello", description=app_commands.locale_str("cmd.hello.desc"))
async def hello(interaction: discord.Interaction):
    lang = await resolve_lang(interaction)
    await interaction.response.send_message(
        f"{tr(lang, 'hello', name=interaction.user.display_name)}\n{tr(lang, 'hello_hint')}",
        ephemeral=True,
    )


@bot.tree.command(name="lang", description=app_commands.locale_str("cmd.lang.desc"))
@app_commands.describe(language=app_commands.locale_str("cmd.lang.param.language"))
@app_commands.choices(language=[
    app_commands.Choice(name="Tiếng Việt", value="vi"),
    app_commands.Choice(name="English", value="en"),
])
async def lang_cmd(interaction: discord.Interaction, language: app_commands.Choice[str]):
    await save_lang(interaction.user.id, language.value)
    await interaction.response.send_message(tr(language.value, "lang_saved"), ephemeral=True)


@bot.tree.command(name="status", description=app_commands.locale_str("cmd.status.desc"))
async def status(interaction: discord.Interaction):
    up = int(time.time() - _START_TS)
    guilds = len(bot.guilds)
    lang = await resolve_lang(interaction)
    await interaction.response.send_message(tr(lang, "status", up=up, guilds=guilds), ephemeral=True)

class NukeConfirmView(discord.ui.View):
    def __init__(self, author_id: int, lang: str):
        super().__init__(timeout=30)
        self.author_id = author_id
        self.lang = lang if lang in {"vi", "en"} else "en"
        self.confirm.label = tr(self.lang, "nuke_confirm_button")
        self.cancel.label = tr(self.lang, "nuke_cancel_button")

    @discord.ui.button(label="confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message(
                tr(self.lang, "nuke_not_caller"),
                ephemeral=True
            )

        channel = interaction.channel
        if channel is None:
            return await interaction.response.send_message(
                tr(self.lang, "nuke_channel_not_found"),
                ephemeral=True
            )

        await interaction.response.send_message(
            tr(self.lang, "nuke_in_progress", mention=interaction.user.mention),
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
            title=tr(self.lang, "nuke_done_title"),
            description=tr(self.lang, "nuke_done_desc", mention=interaction.user.mention),
            color=discord.Color.red()
        )

        embed.add_field(name=tr(self.lang, "nuke_deleted_field"), value=str(count), inline=True)
        embed.add_field(name=tr(self.lang, "nuke_channel_field"), value=channel.mention, inline=True)
        embed.set_footer(text=f"User ID: {interaction.user.id}")

        await channel.send(embed=embed)

        await interaction.followup.send(
            tr(self.lang, "nuke_done_followup", count=count),
            ephemeral=True
        )

        self.stop()

    @discord.ui.button(label="cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message(
                tr(self.lang, "nuke_not_caller"),
                ephemeral=True
            )

        await interaction.response.send_message(tr(self.lang, "nuke_cancelled"), ephemeral=True)
        self.stop()


@bot.tree.command(
    name="nuke",
    description=app_commands.locale_str("cmd.nuke.desc")
)
async def nuke(interaction: discord.Interaction):
    lang = await resolve_lang(interaction)
    if interaction.guild is None:
        return await interaction.response.send_message(
            tr(lang, "nuke_server_only"),
            ephemeral=True
        )

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            tr(lang, "nuke_admin_only"),
            ephemeral=True
        )

    me = interaction.guild.me
    if me is None or not interaction.channel.permissions_for(me).manage_messages:
        return await interaction.response.send_message(
            tr(lang, "nuke_missing_perm"),
            ephemeral=True
        )

    await interaction.response.send_message(
        tr(lang, "nuke_confirm_prompt"),
        view=NukeConfirmView(interaction.user.id, lang),
        ephemeral=True
    )


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    logger.exception("app command error: %r", error)
    lang = await resolve_lang(interaction)
    if isinstance(error, discord.app_commands.CheckFailure):
        msg = str(error) or tr(lang, "check_failure")
    else:
        msg = tr(lang, "unknown_error")
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

    await ensure_lang_db_ready()

    await economy.setup_economy(bot)
    
    from features.rpg.cache import PLAYER_CACHE, INVENTORY_CACHE, EQUIPPED_CACHE, SKILLS_CACHE
    await PLAYER_CACHE.start()
    await INVENTORY_CACHE.start()
    await EQUIPPED_CACHE.start()
    await SKILLS_CACHE.start()
    
    try:
        await bot.start(TOKEN)
    finally:
        await PLAYER_CACHE.stop()
        await INVENTORY_CACHE.stop()
        await EQUIPPED_CACHE.stop()
        await SKILLS_CACHE.stop()


if __name__ == "__main__":
    asyncio.run(main())
