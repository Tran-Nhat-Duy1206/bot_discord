import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from .assets import apply_embed_asset
from .data import ITEMS, MONSTERS, BOSS_VARIANTS, xp_need_for_next
from .db import ensure_db_ready, open_db, get_jackpot_stats, get_combat_telemetry, get_gold_flow_summary


def _collect_files(*files: discord.File | None) -> list[discord.File]:
    return [f for f in files if f is not None]


def _member_or_self(interaction: discord.Interaction, member: Optional[discord.Member]) -> Optional[discord.Member]:
    if member is not None:
        return member
    if isinstance(interaction.user, discord.Member):
        return interaction.user
    return None


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


def _safe_avg(total: int, count: int) -> float:
    c = max(1, int(count))
    return float(total) / float(c)


def register_reports_commands(bot: commands.Bot, guilds: list = None):
    guilds = guilds or []
    @bot.tree.command(name="rpg_loot", description="Xem loot table và rarity RPG")
    async def rpg_loot(interaction: discord.Interaction):
        rarity_order = ["common", "uncommon", "rare", "epic", "legendary"]
        grouped: dict[str, list[str]] = {k: [] for k in rarity_order}

        for key, item in ITEMS.items():
            rarity = str(item.get("rarity", "common")).lower()
            if rarity not in grouped:
                grouped[rarity] = []
            grouped[rarity].append(f"{item.get('emoji', '📦')} {item.get('name', key)} (`{key}`)")

        e = discord.Embed(title="🎲 RPG Loot Table", color=discord.Color.blue())
        for rarity in rarity_order:
            values = grouped.get(rarity, [])
            if not values:
                continue
            e.add_field(
                name=f"{_rarity_emoji(rarity)} {rarity.title()}",
                value="\n".join(values[:8]),
                inline=False,
            )
        f = apply_embed_asset(e, "inventory")
        await interaction.response.send_message(embed=e, files=_collect_files(f))
