from __future__ import annotations

import re
from typing import Optional

import discord
from discord.ext import commands


CURRENCY_ICON = ":slimecoin:"
XP_ICON = ":xp:"

RARITY_ICON_COMMON = ":common:"
RARITY_ICON_UNCOMMON = ":uncommon:"
RARITY_ICON_RARE = ":rare:"
RARITY_ICON_EPIC = ":Epic:"
RARITY_ICON_LEGENDARY = ":legends:"
RARITY_ICON_MYTHIC = ":mythic:"

RARITY_ICONS: dict[str, str] = {
    "common": RARITY_ICON_COMMON,
    "uncommon": RARITY_ICON_UNCOMMON,
    "rare": RARITY_ICON_RARE,
    "epic": RARITY_ICON_EPIC,
    "legendary": RARITY_ICON_LEGENDARY,
    "mythic": RARITY_ICON_MYTHIC,
}


RPG_EMOJI_ALIASES: dict[str, list[str]] = {
    "goblin": ["goblin", "mob_goblin", "enemy_goblin"],
    "skeleton": ["skeleton", "bone", "mob_skeleton", "enemy_skeleton"],
    "wolf": ["wolf", "dire_wolf", "mob_wolf", "enemy_wolf"],
    "slime": ["slime", "slime_jackpot", "mob_slime", "enemy_slime"],
    "ancient_ogre": ["ancient_ogre", "ogre", "boss_ogre", "ancientogre"],
    "ogre_chief": ["ogre_chief", "chief_ogre", "boss_chief"],
    "ogre_king": ["ogre_king", "king_ogre", "boss_king"],
    "void_tyrant": ["void_tyrant", "void", "tyrant"],
    "ashen_dragon": ["ashen_dragon", "dragon", "boss_dragon"],
    "slimecoin": ["slimecoin", "slime_coin", "coin", "slimecurrency"],
    "xp": ["xp", "exp", "experience"],
    "fight": ["fight", "battle", "sword", "attack"],
    "boss": ["boss", "guild_boss", "raid_boss"],
    "potion": ["potion", "heal_potion", "hp_potion"],
    "mega_potion": ["mega_potion", "megaheal", "big_potion"],
    "rare_crystal": ["rare_crystal", "crystal", "shard_crystal", "weapon_shards"],
    "lootbox": ["lootbox", "loot_box", "crate_loot", "reward_box"],
    "phoenix_charm": ["phoenix_charm", "phoenix", "boss_relic"],
    "weapon_shards": ["weapon_shards", "weaponshards", "shard", "shards"],
    "weapon_crate": ["weapon_crate", "weaponcrate", "crate", "wcrate"],
    "boss_weapon_crate": ["boss_weapon_crate", "bossweaponcrate", "boss_crate", "bosscrate"],
    "common": ["common", "thuong", "normal"],
    "uncommon": ["uncommon", "uncomon", "notcommon"],
    "rare": ["rare", "hiem"],
    "epic": ["epic", "Epic"],
    "legendary": ["legendary", "legend", "legends"],
    "mythic": ["mythic", "myth"],
}

RPG_EMOJI_UNICODE_FALLBACKS: dict[str, str] = {
    "goblin": "👺",
    "skeleton": "💀",
    "wolf": "🐺",
    "slime": "🟢",
    "ancient_ogre": "👹",
    "ogre_chief": "👺",
    "ogre_king": "👑",
    "void_tyrant": "🕳️",
    "ashen_dragon": "🐉",
    "potion": "🧪",
    "mega_potion": "🧴",
    "lootbox": "🎁",
    "rare_crystal": "💎",
    "phoenix_charm": "🔥",
    "slimecoin": "🪙",
    "xp": "✨",
    "fight": "⚔️",
    "boss": "👑",
    "common": "⚪",
    "uncommon": "🟢",
    "rare": "🔵",
    "epic": "🟣",
    "legendary": "🟠",
    "mythic": "🌌",
}


_ALIAS_TOKEN_RE = re.compile(r"[^a-z0-9_]+")
_CUSTOM_EMOJI_RE = re.compile(r"^<(a?):([a-zA-Z0-9_]+):(\d+)>$")
_NAME_EMOJI_RE = re.compile(r"^:([a-zA-Z0-9_]+):$")


def _normalize_alias_token(value: str) -> str:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    normalized = _ALIAS_TOKEN_RE.sub("", raw)
    return normalized.strip("_")


def _build_character_emoji_aliases() -> dict[str, list[str]]:
    try:
        from features.rpg.data.characters import CHARACTERS
    except Exception:
        return {}

    out: dict[str, list[str]] = {}
    for cid, meta in (CHARACTERS or {}).items():
        key = _normalize_alias_token(str(cid))
        if not key:
            continue

        aliases: set[str] = {key, key.replace("_", "")}
        evolution_line = _normalize_alias_token(str((meta or {}).get("evolution_line", "")))
        name = _normalize_alias_token(str((meta or {}).get("name", "")))
        form = _normalize_alias_token(str((meta or {}).get("form", "")))
        rarity = _normalize_alias_token(str((meta or {}).get("rarity", "")))

        if evolution_line:
            aliases.add(evolution_line)
        if name:
            aliases.add(name)
        if form:
            aliases.add(form)
        if name and form:
            aliases.add(f"{name}_{form}")
        if evolution_line and form:
            aliases.add(f"{evolution_line}_{form}")
        if evolution_line and rarity:
            aliases.add(f"{evolution_line}_{rarity}")

        out[key] = sorted(a for a in aliases if a)
    return out


def _is_custom_emoji_token(value: str) -> bool:
    raw = str(value or "").strip()
    return bool(raw and (_CUSTOM_EMOJI_RE.match(raw) or _NAME_EMOJI_RE.match(raw)))


def _build_data_emoji_fallbacks() -> dict[str, str]:
    out: dict[str, str] = {}

    try:
        from features.rpg.data.characters import CHARACTERS

        for cid, meta in (CHARACTERS or {}).items():
            key = _normalize_alias_token(str(cid))
            emoji = str((meta or {}).get("emoji", "") or "").strip()
            if not key or not emoji or _is_custom_emoji_token(emoji):
                continue
            out.setdefault(key, emoji)

            line = _normalize_alias_token(str((meta or {}).get("evolution_line", "")))
            name = _normalize_alias_token(str((meta or {}).get("name", "")))
            if line:
                out.setdefault(line, emoji)
            if name:
                out.setdefault(name, emoji)
    except Exception:
        pass

    try:
        from features.rpg.data.items import ITEMS

        for item_id, meta in (ITEMS or {}).items():
            key = _normalize_alias_token(str(item_id))
            emoji = str((meta or {}).get("emoji", "") or "").strip()
            if not key or not emoji or _is_custom_emoji_token(emoji):
                continue
            out.setdefault(key, emoji)
    except Exception:
        pass

    return out


def _build_data_emoji_aliases() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}

    def _push(key: str, values: list[str]) -> None:
        k = _normalize_alias_token(key)
        if not k:
            return
        merged = set(out.get(k, []))
        merged.add(k)
        for v in values:
            vv = _normalize_alias_token(v)
            if vv:
                merged.add(vv)
        out[k] = sorted(merged)

    try:
        from features.rpg.data.items import ITEMS

        for iid, meta in (ITEMS or {}).items():
            key = str(iid)
            name = str((meta or {}).get("name", ""))
            _push(key, [name, str(key).replace("_", "")])
    except Exception:
        pass

    try:
        from features.rpg.data.monsters import MONSTERS, BOSS_VARIANTS

        for m in list(MONSTERS or []) + list(BOSS_VARIANTS or []):
            if not isinstance(m, dict):
                continue
            mid = str(m.get("id", ""))
            name = str(m.get("name", ""))
            _push(mid, [name, mid.replace("_", "")])
    except Exception:
        pass

    return out


for _char_key, _char_aliases in _build_character_emoji_aliases().items():
    _existing = set(RPG_EMOJI_ALIASES.get(_char_key, []))
    _existing.add(_char_key)
    _existing.update(_char_aliases)
    RPG_EMOJI_ALIASES[_char_key] = sorted(x for x in _existing if x)

for _data_key, _data_aliases in _build_data_emoji_aliases().items():
    _existing = set(RPG_EMOJI_ALIASES.get(_data_key, []))
    _existing.add(_data_key)
    _existing.update(_data_aliases)
    RPG_EMOJI_ALIASES[_data_key] = sorted(x for x in _existing if x)

for _fb_key, _fb_emoji in _build_data_emoji_fallbacks().items():
    RPG_EMOJI_UNICODE_FALLBACKS.setdefault(_fb_key, _fb_emoji)

_EMOJI_ALIAS_TO_CANONICAL: dict[str, str] = {}
for _canonical, _aliases in RPG_EMOJI_ALIASES.items():
    _canon_norm = _normalize_alias_token(_canonical)
    if not _canon_norm:
        continue
    _EMOJI_ALIAS_TO_CANONICAL[_canon_norm] = _canon_norm
    for _alias in _aliases:
        _alias_norm = _normalize_alias_token(_alias)
        if _alias_norm:
            _EMOJI_ALIAS_TO_CANONICAL[_alias_norm] = _canon_norm

for _canonical, _emoji in list(RPG_EMOJI_UNICODE_FALLBACKS.items()):
    _canon_norm = _normalize_alias_token(_canonical)
    if not _canon_norm:
        continue
    RPG_EMOJI_UNICODE_FALLBACKS[_canon_norm] = _emoji


def emoji_fallback_for_token(token: str | None) -> str:
    raw = str(token or "").strip()
    if not raw:
        return ""

    if _CUSTOM_EMOJI_RE.match(raw):
        return ""

    name_match = _NAME_EMOJI_RE.match(raw)
    if name_match:
        alias = _normalize_alias_token(name_match.group(1))
        canonical = _EMOJI_ALIAS_TO_CANONICAL.get(alias, alias)
        return str(RPG_EMOJI_UNICODE_FALLBACKS.get(canonical, RPG_EMOJI_UNICODE_FALLBACKS.get(alias, "")))

    if any(ord(ch) > 127 for ch in raw):
        return raw

    alias = _normalize_alias_token(raw)
    canonical = _EMOJI_ALIAS_TO_CANONICAL.get(alias, alias)
    return str(RPG_EMOJI_UNICODE_FALLBACKS.get(canonical, RPG_EMOJI_UNICODE_FALLBACKS.get(alias, "")))


def rarity_icon(rarity: str | None) -> str:
    key = str(rarity or "common").strip().lower()
    return RARITY_ICONS.get(key, RARITY_ICON_COMMON)


BLACKJACK_SUIT_TO_WORD = {
    "S": "spades",
    "H": "hearts",
    "D": "diamonds",
    "C": "clubs",
}


BLACKJACK_RANK_TO_WORD = {
    "A": "ace",
    "K": "king",
    "Q": "queen",
    "J": "jack",
    "10": "10",
    "9": "9",
    "8": "8",
    "7": "7",
    "6": "6",
    "5": "5",
    "4": "4",
    "3": "3",
    "2": "2",
}


def blackjack_card_emoji_name(card: str) -> str:
    rank = card[:-1]
    suit = card[-1]
    return f"{BLACKJACK_RANK_TO_WORD[rank]}_of_{BLACKJACK_SUIT_TO_WORD[suit]}"


def find_bot_emoji_by_name(bot: Optional[commands.Bot], name: str) -> Optional[discord.Emoji]:
    if bot is None:
        return None
    for emoji in bot.emojis:
        if emoji.name == name:
            return emoji
    return None


def emoji_or_fallback(bot: Optional[commands.Bot], name: str, fallback: str) -> str:
    emoji = find_bot_emoji_by_name(bot, name)
    return str(emoji) if emoji else fallback
