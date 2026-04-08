from __future__ import annotations

from typing import Iterable

import discord


THEME_COLORS = {
    "profile": discord.Color.from_rgb(198, 161, 91),
    "team": discord.Color.from_rgb(140, 38, 38),
    "combat": discord.Color.from_rgb(196, 84, 31),
    "victory": discord.Color.from_rgb(56, 161, 105),
    "defeat": discord.Color.from_rgb(106, 31, 31),
    "gacha": discord.Color.from_rgb(136, 84, 208),
    "shop": discord.Color.from_rgb(212, 175, 55),
}

ROLE_ICONS = {
    "tank": "🛡️",
    "dps": "⚔️",
    "healer": "💚",
    "support": "✨",
}

RARITY_ICONS = {
    "common": "⚪",
    "uncommon": "🟢",
    "rare": "🔵",
    "epic": "🟣",
    "legendary": "🟡",
    "mythic": "🔴",
}

FRONTLINE_ROLES = {"tank", "dps"}


def progress_bar(current: int, maximum: int, width: int = 12, filled: str = "█", empty: str = "░") -> str:
    max_value = max(1, int(maximum))
    cur_value = max(0, min(int(current), max_value))
    filled_width = int(round((cur_value / max_value) * width))
    filled_width = max(0, min(width, filled_width))
    return (filled * filled_width) + (empty * (width - filled_width))


def hp_bar(current: int, maximum: int, width: int = 12) -> str:
    return progress_bar(current, maximum, width=width, filled="█", empty="▁")


def role_icon(role: str) -> str:
    return ROLE_ICONS.get(str(role or "").lower(), "❔")


def rarity_icon(rarity: str) -> str:
    return RARITY_ICONS.get(str(rarity or "common").lower(), "⚫")


def panel_embed(
    mode: str,
    title: str,
    description: str,
    theme: str,
    thumbnail_url: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=THEME_COLORS.get(theme, discord.Color.dark_embed()),
    )
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    embed.set_footer(text=f"Squad System • {mode}")
    return embed


def member_line(member: dict) -> str:
    role = str(member.get("role", "")).lower()
    rarity = str(member.get("rarity", "common")).lower()
    name = str(member.get("name", "Unknown"))
    level = int(member.get("level", 1) or 1)
    star = int(member.get("star", 1) or 1)
    captain = " 👑" if bool(member.get("is_main")) else ""
    return f"{role_icon(role)} {rarity_icon(rarity)} {name}{captain} • Lv{level} ★{star}"


def split_formation(members: Iterable[dict]) -> tuple[list[str], list[str]]:
    front: list[str] = []
    back: list[str] = []
    for m in members:
        role = str(m.get("role", "")).lower()
        line = member_line(m)
        if role in FRONTLINE_ROLES:
            front.append(line)
        else:
            back.append(line)
    return front, back
