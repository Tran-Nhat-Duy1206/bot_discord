from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass, field
from typing import Any

import aiohttp
import discord

from features.emoji_registry import RARITY_ICON_COMMON
from features.emoji_registry import RPG_EMOJI_ALIASES
from features.emoji_registry import emoji_fallback_for_token
from features.emoji_registry import rarity_icon as rarity_icon_token

from ..data import MONSTERS

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except Exception:  # pragma: no cover
    Image = None
    ImageDraw = None
    ImageFilter = None
    ImageFont = None


CUSTOM_EMOJI_RE = re.compile(r"^<(a?):([a-zA-Z0-9_]+):(\d+)>$")
NAME_EMOJI_RE = re.compile(r"^:([a-zA-Z0-9_]+):$")
TURN_RE = re.compile(r"(\d+)\s*turn", re.IGNORECASE)

ROLE_EMOJI = {
    "tank": ":tank:",
    "dps": ":DPS:",
    "healer": ":Healer:",
    "support": ":Support:",
}


@dataclass
class CardUnit:
    name: str
    level: int = 1
    avatar_emoji: str = ""
    rarity_emoji: str = RARITY_ICON_COMMON
    role_emoji: str = ":Support:"
    item_emojis: list[str] = field(default_factory=list)
    hp: int = 100
    max_hp: int = 100
    attack: int = 0
    defense: int = 0


@dataclass
class BattleCardData:
    title: str
    left_team_name: str
    right_team_name: str
    left_units: list[CardUnit]
    right_units: list[CardUnit]
    result_line: str
    victory: bool = True


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if ImageFont is None:
        raise RuntimeError("Pillow is required")
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def _emoji_lookup_from_guild(guild: discord.Guild | None) -> dict[str, tuple[str, bool]]:
    out: dict[str, tuple[str, bool]] = {}
    if guild is None:
        return out

    state = getattr(guild, "_state", None)
    client = state._get_client() if state is not None and hasattr(state, "_get_client") else None
    emoji_sources = list(getattr(client, "emojis", []) or []) + list(getattr(guild, "emojis", []) or [])

    for e in emoji_sources:
        key = str(e.name).lower()
        out[key] = (str(e.id), bool(getattr(e, "animated", False)))

    alias_map = RPG_EMOJI_ALIASES if isinstance(RPG_EMOJI_ALIASES, dict) else {}
    for canonical, aliases in alias_map.items():
        ckey = str(canonical or "").strip().lower()
        if not ckey:
            continue
        tokens = [ckey] + [str(a).strip().lower() for a in (aliases or []) if str(a).strip()]
        found = None
        for token in tokens:
            if token in out:
                found = out[token]
                break
        if found is None:
            continue
        for token in tokens:
            out.setdefault(token, found)

    return out


def _emoji_to_cdn_target(token: str | None, emoji_lookup: dict[str, tuple[str, bool]]) -> tuple[str, bool] | None:
    if not isinstance(token, str):
        return None
    raw = token.strip()
    if not raw:
        return None

    m = CUSTOM_EMOJI_RE.match(raw)
    if m:
        animated = bool(m.group(1))
        return m.group(3), animated

    n = NAME_EMOJI_RE.match(raw)
    if n:
        key = str(n.group(1)).lower()
        found = emoji_lookup.get(key)
        if found:
            return found
        return None

    if raw.isdigit():
        return raw, False
    return None


async def fetch_discord_emoji_image(
    session: aiohttp.ClientSession,
    emoji_token: str | None,
    emoji_lookup: dict[str, tuple[str, bool]] | None = None,
    *,
    size: int = 64,
    cache: dict[str, Any] | None = None,
) -> Image.Image | None:
    if Image is None:
        return None

    lookup = emoji_lookup or {}
    target = _emoji_to_cdn_target(emoji_token, lookup)
    if not target:
        return None
    emoji_id, animated = target
    key = f"{emoji_id}:{1 if animated else 0}:{size}"
    if cache is not None and key in cache:
        return cache[key].copy()

    ext = "gif" if animated else "png"
    url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}?size=128&quality=lossless"
    try:
        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            payload = await resp.read()
    except Exception:
        return None

    try:
        img = Image.open(io.BytesIO(payload))
        if getattr(img, "is_animated", False):
            img.seek(0)
        img = img.convert("RGBA")
        resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.BICUBIC)
        img = img.resize((size, size), resample)
        if cache is not None:
            cache[key] = img
        return img.copy()
    except Exception:
        return None


def _draw_bar(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    value: int,
    maximum: int,
    fill: tuple[int, int, int],
    bg: tuple[int, int, int] = (38, 44, 58),
) -> None:
    max_v = max(1, int(maximum))
    cur = max(0, min(int(value), max_v))
    pct = cur / max_v
    draw.rounded_rectangle((x, y, x + w, y + h), radius=4, fill=(*bg, 255))
    fw = int(w * pct)
    if fw <= 0:
        return
    draw.rounded_rectangle((x, y, x + fw, y + h), radius=4, fill=fill)


def _team_power_from_units(units: list[CardUnit]) -> int:
    total = 0
    for u in units:
        total += int(u.hp * 0.35 + u.level * 14 + len(u.item_emojis) * 22)
    return max(1, total)


async def _draw_token_strip(
    base: Image.Image,
    draw: ImageDraw.ImageDraw,
    session: aiohttp.ClientSession,
    emoji_lookup: dict[str, tuple[str, bool]],
    cache: dict[str, Any],
    tokens: list[str],
    x: int,
    y: int,
    size: int,
    gap: int,
) -> int:
    cur_x = x
    for token in tokens:
        em = await fetch_discord_emoji_image(session, token, emoji_lookup, size=size, cache=cache)
        if em is None:
            fallback = emoji_fallback_for_token(token)
            if not fallback:
                continue
            draw.text((cur_x, y + max(0, (size - 16) // 2)), fallback, font=_font(max(14, size - 2)), fill=(236, 242, 255, 255))
            cur_x += size + gap
            continue
        base.alpha_composite(em, (cur_x, y))
        cur_x += size + gap
    return cur_x


async def _draw_unit_row(
    base: Image.Image,
    draw: ImageDraw.ImageDraw,
    session: aiohttp.ClientSession,
    emoji_lookup: dict[str, tuple[str, bool]],
    cache: dict[str, Any],
    unit: CardUnit,
    x: int,
    y: int,
    w: int,
    h: int,
) -> None:
    unit_alive = int(unit.hp) > 0
    row_fill = (30, 24, 36, 232) if unit_alive else (44, 34, 42, 232)
    row_outline = (112, 96, 126, 255) if unit_alive else (126, 96, 104, 255)
    draw.rounded_rectangle((x, y, x + w, y + h), radius=12, fill=row_fill, outline=row_outline, width=2)

    avatar = await fetch_discord_emoji_image(session, unit.avatar_emoji, emoji_lookup, size=54, cache=cache)
    if avatar is not None:
        base.alpha_composite(avatar, (x + 10, y + 8))
    else:
        fallback_avatar = emoji_fallback_for_token(unit.avatar_emoji)
        if fallback_avatar:
            draw.text((x + 20, y + 18), fallback_avatar, font=_font(26), fill=(236, 242, 255, 255))

    rarity = await fetch_discord_emoji_image(session, unit.rarity_emoji, emoji_lookup, size=20, cache=cache)
    if rarity is not None:
        base.alpha_composite(rarity, (x + 74, y + 10))
    else:
        fallback_rarity = emoji_fallback_for_token(unit.rarity_emoji)
        if fallback_rarity:
            draw.text((x + 74, y + 10), fallback_rarity, font=_font(16), fill=(228, 234, 248, 255))

    role = await fetch_discord_emoji_image(session, unit.role_emoji, emoji_lookup, size=20, cache=cache)
    if role is not None:
        base.alpha_composite(role, (x + 74, y + 34))
    else:
        fallback_role = emoji_fallback_for_token(unit.role_emoji)
        if fallback_role:
            draw.text((x + 74, y + 34), fallback_role, font=_font(16), fill=(228, 234, 248, 255))

    f_title = _font(19)
    f_body = _font(15)
    icon_y = y + 34
    stat_text_y = y + max(44, h - 34)
    hp_bar_y = y + h - 16
    title_color = (238, 229, 216, 255) if unit_alive else (198, 182, 176, 255)
    body_color = (220, 206, 190, 255) if unit_alive else (176, 164, 160, 255)
    hp_fill = (128, 170, 116) if unit_alive else (154, 86, 102)
    hp_bg = (54, 46, 58) if unit_alive else (88, 72, 80)
    draw.text((x + 98, y + 8), f"Lv.{int(unit.level)}  {unit.name}", font=f_title, fill=title_color)

    await _draw_token_strip(base, draw, session, emoji_lookup, cache, unit.item_emojis[:4], x + 98, icon_y, 18, 4)

    _draw_bar(draw, x + 98, hp_bar_y, w - 110, 8, int(unit.hp), int(unit.max_hp), hp_fill, bg=hp_bg)
    draw.text(
        (x + 98, stat_text_y),
        f"HP {int(unit.hp)}/{int(unit.max_hp)} | ATK {int(unit.attack)} DEF {int(unit.defense)}",
        font=f_body,
        fill=body_color,
    )


def _estimate_turns(logs: list[str] | None, fallback: int = 1) -> int:
    lines = logs or []
    turns: list[int] = []
    for line in lines:
        for m in TURN_RE.finditer(str(line)):
            turns.append(int(m.group(1)))
    if turns:
        return max(1, sum(turns))
    return max(1, int(fallback))


def _normalize_avatar_token(member: dict) -> str:
    raw = str(member.get("emoji", "") or "").strip()
    if CUSTOM_EMOJI_RE.match(raw) or NAME_EMOJI_RE.match(raw):
        return raw
    cid = str(member.get("character_id", "") or "").strip().lower()
    if cid:
        return f":{cid}:"
    return ""


def _member_item_tokens(member: dict) -> list[str]:
    eq = member.get("equipment", {}) if isinstance(member.get("equipment", {}), dict) else {}
    out: list[str] = []
    for slot in ("weapon", "armor", "accessory"):
        item_id = str(eq.get(slot, "") or "").strip().lower()
        if item_id:
            out.append(f":{item_id}:")
    passive = str(member.get("passive_skill", "") or "").strip().lower()
    if passive:
        out.append(f":{passive}:")
    return out


def convert_combat_result_to_battle_data(
    player_name: str,
    team_members: list[dict],
    combat_result: Any,
    *,
    lang: str = "en",
) -> BattleCardData:
    left_units: list[CardUnit] = []
    for m in (team_members or [])[:5]:
        rarity_key = str(m.get("rarity", "common")).lower()
        role_key = str(m.get("role", "support")).strip().lower()
        max_hp = max(1, int(m.get("hp", 100) or 100))
        left_units.append(
            CardUnit(
                name=str(m.get("name", "Unit")),
                level=int(m.get("level", 1) or 1),
                avatar_emoji=_normalize_avatar_token(m),
                rarity_emoji=rarity_icon_token(rarity_key),
                role_emoji=ROLE_EMOJI.get(role_key, ":Support:"),
                item_emojis=_member_item_tokens(m),
                hp=max_hp,
                max_hp=max_hp,
                attack=int(m.get("attack", 0) or 0),
                defense=int(m.get("defense", 0) or 0),
            )
        )

    monster_map = {str(m.get("id", "")): m for m in MONSTERS}
    encounters = dict(getattr(combat_result, "encounters", {}) or {})
    avg_level = int(sum(u.level for u in left_units) / max(1, len(left_units))) if left_units else 1
    right_units: list[CardUnit] = []
    team_power = _team_power_from_units(left_units)
    hp_scale = 0.9 + min(1.8, team_power / 700.0)

    def _enemy_rarity(mid: str) -> str:
        key = str(mid).lower()
        if key in {"void_tyrant", "ashen_dragon"}:
            return rarity_icon_token("mythic")
        if key in {"ancient_ogre", "ogre_king", "ogre_chief"}:
            return rarity_icon_token("legendary")
        if key in {"slime", "wolf"}:
            return rarity_icon_token("rare")
        return rarity_icon_token("common")

    for mid, count in encounters.items():
        m = monster_map.get(str(mid), {})
        for _ in range(max(1, int(count))):
            if len(right_units) >= 5:
                break
            hp = max(1, int((int(m.get("hp", 80) or 80)) * hp_scale))
            right_units.append(
                CardUnit(
                    name=str(m.get("name", str(mid).title())),
                    level=max(1, avg_level - 1),
                    avatar_emoji=f":{str(mid).lower()}:" if str(mid).strip() else "",
                    rarity_emoji=_enemy_rarity(str(mid)),
                    role_emoji=":DPS:",
                    item_emojis=[],
                    hp=hp,
                    max_hp=hp,
                    attack=int(m.get("atk", 0) or 0),
                    defense=int(m.get("def", 0) or 0),
                )
            )
        if len(right_units) >= 5:
            break

    if not right_units:
        right_units.append(CardUnit(name="Unknown", level=avg_level, role_emoji=":DPS:", hp=100, max_hp=100, attack=10, defense=5))

    kills = int(getattr(combat_result, "kills", 0) or 0)
    for idx in range(min(kills, len(right_units))):
        right_units[idx].hp = 0

    pack = max(1, int(getattr(combat_result, "pack", 1) or 1))
    won = kills >= pack
    turns = int(getattr(combat_result, "turns", 0) or 0)
    if turns <= 0:
        turns = _estimate_turns(getattr(combat_result, "logs", []) or [], fallback=kills or 1)
    xp = int(getattr(combat_result, "xp", 0) or 0)
    streak = max(0, int(getattr(combat_result, "streak", 0) or 0))
    is_vi = str(lang).lower().startswith("vi")
    if won:
        result_line = (
            f"Bạn thắng trong {turns} lượt! | +{xp} xp | Streak: {streak}"
            if is_vi
            else f"You won in {turns} turns! | +{xp} xp | Streak: {streak}"
        )
    else:
        result_line = (
            f"Bạn hạ {kills}/{pack} mục tiêu trong {turns} lượt | +{xp} xp | Streak: {streak}"
            if is_vi
            else f"You cleared {kills}/{pack} fights in {turns} turns | +{xp} xp | Streak: {streak}"
        )

    left_name = f"{player_name}'s Team" if player_name else "Your Team"
    if is_vi:
        left_name = f"Đội của {player_name}" if player_name else "Đội của bạn"
    right_name = "Wild Pack"
    if encounters:
        top_mid = str(max(encounters.items(), key=lambda kv: int(kv[1]))[0])
        top_mon = monster_map.get(top_mid, {})
        top_name = str(top_mon.get("name", top_mid.title() if top_mid else "Enemy"))
        right_name = f"{top_name} Pack"
    if is_vi:
        right_name = f"Bầy {right_name.replace(' Pack', '')}"

    return BattleCardData(
        title=(
            f"{player_name} bước vào giao tranh!"
            if is_vi and player_name
            else ("Giao tranh" if is_vi else (f"{player_name} goes into battle!" if player_name else "Battle Report"))
        ),
        left_team_name=left_name,
        right_team_name=right_name,
        left_units=left_units,
        right_units=right_units,
        result_line=result_line,
        victory=won,
    )


async def render_battle_card(data: BattleCardData, guild: discord.Guild | None) -> io.BytesIO | None:
    if Image is None or ImageDraw is None:
        return None

    if data.victory:
        accent = (134, 114, 84)
        shadow = (70, 86, 64)
        panel = (28, 22, 34, 236)
        outline = (116, 104, 134, 255)
        result_fill = (34, 30, 42, 245)
        result_outline = (138, 122, 92, 255)
        result_text = (238, 227, 212, 255)
        vs_color = (209, 184, 142, 255)
    else:
        accent = (126, 90, 98)
        shadow = (92, 52, 64)
        panel = (30, 20, 28, 236)
        outline = (132, 90, 108, 255)
        result_fill = (44, 22, 32, 245)
        result_outline = (162, 94, 112, 255)
        result_text = (244, 220, 224, 255)
        vs_color = (204, 150, 166, 255)

    img = Image.new("RGBA", (1280, 720), (13, 18, 30, 255))
    draw = ImageDraw.Draw(img)

    _apply_dark_fantasy_backdrop(draw, 1280, 720, accent=accent, shadow=shadow)
    draw.rounded_rectangle((20, 14, 1260, 94), radius=16, fill=(18, 16, 24, 232), outline=(accent[0], accent[1], accent[2], 255), width=2)
    draw.rectangle((22, 70, 1258, 92), fill=(accent[0], accent[1], accent[2], 50))
    draw.text((34, 26), data.title, font=_font(32), fill=(244, 236, 222, 255))

    left_box = (32, 104, 620, 620)
    right_box = (660, 104, 1248, 620)
    for box in (left_box, right_box):
        draw.rounded_rectangle(box, radius=18, fill=panel, outline=outline, width=3)
        x1, y1, x2, _ = box
        draw.line((x1 + 16, y1 + 12, x2 - 16, y1 + 12), fill=(146, 126, 96, 104), width=1)

    team_font = _font(24)
    draw.text((52, 122), data.left_team_name, font=team_font, fill=(236, 224, 206, 255))
    draw.text((680, 122), data.right_team_name, font=team_font, fill=(236, 224, 206, 255))

    vs_font = _font(24)
    vs_label = "VS"
    gap_left = left_box[2]
    gap_right = right_box[0]
    try:
        bbox = draw.textbbox((0, 0), vs_label, font=vs_font)
        vs_w = max(0, int(bbox[2] - bbox[0]))
    except Exception:
        vs_w = 28
    vs_x = int(gap_left + ((gap_right - gap_left - vs_w) / 2))
    draw.text((vs_x, 122), vs_label, font=vs_font, fill=vs_color)

    lookup = _emoji_lookup_from_guild(guild)
    cache: dict[str, Any] = {}
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        row_h = 84
        for i, unit in enumerate((data.left_units or [])[:5]):
            await _draw_unit_row(img, draw, session, lookup, cache, unit, 46, 160 + i * (row_h + 8), 560, row_h)
        for i, unit in enumerate((data.right_units or [])[:5]):
            await _draw_unit_row(img, draw, session, lookup, cache, unit, 674, 160 + i * (row_h + 8), 560, row_h)

    draw.rounded_rectangle((32, 642, 1248, 702), radius=14, fill=result_fill, outline=result_outline, width=2)
    draw.text((52, 660), data.result_line, font=_font(24), fill=result_text)

    out = io.BytesIO()
    img.save(out, format="PNG")
    out.seek(0)
    return out


async def render_team_card(
    owner_name: str,
    team_members: list[dict],
    guild: discord.Guild | None,
    *,
    lang: str = "en",
) -> io.BytesIO | None:
    if Image is None or ImageDraw is None:
        return None

    units: list[CardUnit] = []
    for m in (team_members or [])[:5]:
        rarity_key = str(m.get("rarity", "common")).lower()
        role_key = str(m.get("role", "support")).strip().lower()
        hp = max(1, int(m.get("hp", 100) or 100))
        units.append(
            CardUnit(
                name=str(m.get("name", "Unit")),
                level=int(m.get("level", 1) or 1),
                avatar_emoji=_normalize_avatar_token(m),
                rarity_emoji=rarity_icon_token(rarity_key),
                role_emoji=ROLE_EMOJI.get(role_key, ":Support:"),
                item_emojis=_member_item_tokens(m),
                hp=hp,
                max_hp=hp,
                attack=int(m.get("attack", 0) or 0),
                defense=int(m.get("defense", 0) or 0),
            )
        )

    if not units:
        return None

    img = Image.new("RGBA", (1180, 700), (12, 18, 30, 255))
    draw = ImageDraw.Draw(img)

    _apply_dark_fantasy_backdrop(draw, 1180, 700, accent=(130, 104, 88), shadow=(70, 52, 66))
    draw.rounded_rectangle((20, 14, 1160, 94), radius=16, fill=(18, 16, 24, 232), outline=(128, 106, 88, 255), width=2)
    draw.rectangle((22, 70, 1158, 92), fill=(128, 106, 88, 52))
    title = f"{owner_name}'s Team" if not str(lang).lower().startswith("vi") else f"Đội hình của {owner_name}"
    draw.text((34, 26), title, font=_font(33), fill=(244, 236, 222, 255))

    draw.rounded_rectangle((28, 110, 1152, 670), radius=18, fill=(24, 20, 32, 236), outline=(110, 96, 124, 255), width=3)
    draw.line((46, 122, 1134, 122), fill=(146, 126, 96, 98), width=1)
    draw.text((52, 128), "Formation Card", font=_font(24), fill=(236, 224, 206, 255))

    total_hp = sum(int(u.max_hp) for u in units)
    total_atk = sum(int(u.attack) for u in units)
    total_def = sum(int(u.defense) for u in units)
    power = _team_power_from_units(units)
    draw.text(
        (52, 156),
        f"Squad Power {power} | HP {total_hp} | ATK {total_atk} | DEF {total_def}",
        font=_font(16),
        fill=(218, 206, 188, 255),
    )

    lookup = _emoji_lookup_from_guild(guild)
    cache: dict[str, Any] = {}
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        row_h = 82
        for i, unit in enumerate(units[:5]):
            await _draw_unit_row(img, draw, session, lookup, cache, unit, 44, 182 + i * (row_h + 8), 1090, row_h)

    out = io.BytesIO()
    img.save(out, format="PNG")
    out.seek(0)
    return out


_GACHA_RARITY_ORDER = {
    "mythic": 5,
    "legendary": 4,
    "epic": 3,
    "rare": 2,
    "uncommon": 1,
    "common": 0,
}

_GACHA_RARITY_COLOR = {
    "mythic": (189, 130, 255, 255),
    "legendary": (255, 196, 94, 255),
    "epic": (188, 116, 255, 255),
    "rare": (110, 190, 255, 255),
    "uncommon": (108, 230, 160, 255),
    "common": (182, 186, 198, 255),
}


def _gacha_rarity_rank(rarity: str) -> int:
    return _GACHA_RARITY_ORDER.get(str(rarity or "common").strip().lower(), -1)


def _gacha_rarity_color(rarity: str) -> tuple[int, int, int, int]:
    return _GACHA_RARITY_COLOR.get(str(rarity or "common").strip().lower(), (182, 186, 198, 255))


def _mix_rgb(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    x = max(0.0, min(1.0, float(t)))
    return (
        int(a[0] + (b[0] - a[0]) * x),
        int(a[1] + (b[1] - a[1]) * x),
        int(a[2] + (b[2] - a[2]) * x),
    )


def _draw_vertical_gradient(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    top: tuple[int, int, int],
    bottom: tuple[int, int, int],
) -> None:
    h = max(1, int(height) - 1)
    for y in range(height):
        c = _mix_rgb(top, bottom, y / h)
        draw.line((0, y, width, y), fill=(c[0], c[1], c[2], 255), width=1)


def _draw_soft_glow(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    color: tuple[int, int, int],
    *,
    passes: int = 6,
) -> None:
    x1, y1, x2, y2 = box
    for i in range(passes):
        expand = (i + 1) * 6
        alpha = max(8, 58 - i * 8)
        draw.rounded_rectangle(
            (x1 - expand, y1 - expand, x2 + expand, y2 + expand),
            radius=18 + i * 2,
            fill=(color[0], color[1], color[2], alpha),
        )


def _draw_star(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    size: int,
    color: tuple[int, int, int],
    alpha: int,
) -> None:
    a = max(20, min(255, int(alpha)))
    s = max(2, int(size))
    draw.line((cx - s, cy, cx + s, cy), fill=(color[0], color[1], color[2], a), width=2)
    draw.line((cx, cy - s, cx, cy + s), fill=(color[0], color[1], color[2], a), width=2)
    d = max(1, int(s * 0.72))
    draw.line((cx - d, cy - d, cx + d, cy + d), fill=(color[0], color[1], color[2], max(18, a - 40)), width=1)
    draw.line((cx - d, cy + d, cx + d, cy - d), fill=(color[0], color[1], color[2], max(18, a - 40)), width=1)


def _draw_vignette(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    *,
    passes: int = 12,
    alpha_start: int = 20,
    alpha_end: int = 96,
) -> None:
    w = max(1, int(width))
    h = max(1, int(height))
    for i in range(passes):
        t = i / max(1, passes - 1)
        a = int(alpha_start + (alpha_end - alpha_start) * t)
        pad = int(6 + i * 7)
        draw.rounded_rectangle((pad, pad, w - pad, h - pad), radius=24 + i * 2, outline=(8, 8, 12, max(6, a)), width=2)


def _draw_mist_layers(
    draw: ImageDraw.ImageDraw,
    width: int,
    y_start: int,
    y_end: int,
    tint: tuple[int, int, int],
) -> None:
    ys = max(0, int(y_start))
    ye = max(ys + 1, int(y_end))
    h = max(1, ye - ys)
    for y in range(ys, ye):
        t = (y - ys) / h
        base = int(14 + 46 * t)
        sway = int(10 * math.sin(y / 23.0))
        alpha = max(8, min(92, base + sway))
        draw.line((0, y, width, y), fill=(tint[0], tint[1], tint[2], alpha), width=1)


def _apply_dark_fantasy_backdrop(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    *,
    accent: tuple[int, int, int] = (130, 102, 86),
    shadow: tuple[int, int, int] = (72, 52, 66),
) -> None:
    top_grad = _mix_rgb((10, 14, 20), accent, 0.16)
    bottom_grad = _mix_rgb((22, 12, 18), shadow, 0.24)
    _draw_vertical_gradient(draw, width, height, top_grad, bottom_grad)

    for i in range(10):
        x = int((i / 9.0) * width) - 220
        tone = _mix_rgb((54, 56, 70), accent, (i % 3) / 2.0)
        draw.polygon(
            [(x, 0), (x + 170, 0), (x + 560, height), (x + 390, height)],
            fill=(tone[0], tone[1], tone[2], 18),
        )

    _draw_mist_layers(draw, width, int(height * 0.64), height - 2, (24, 20, 28))
    _draw_vignette(draw, width, height, passes=11, alpha_start=18, alpha_end=88)


async def render_gacha_card(
    player_name: str,
    pulls: list[dict],
    guild: discord.Guild | None,
    *,
    pull_count: int,
    banner_name: str,
    pity_now: int,
    soft_pity: int,
    hard_pity: int,
    cost: int,
    duplicate_shard_value: int,
    lang: str = "en",
) -> io.BytesIO | None:
    if Image is None or ImageDraw is None:
        return None

    pull_rows = [p for p in (pulls or []) if isinstance(p, dict)][:10]
    if not pull_rows:
        return None

    is_vi = str(lang).lower().startswith("vi")
    row_h = 56
    row_gap = 8
    rows_h = len(pull_rows) * row_h + max(0, len(pull_rows) - 1) * row_gap

    width = 1220
    height = max(650, 336 + rows_h + 112)

    img = Image.new("RGBA", (width, height), (12, 18, 30, 255))
    draw = ImageDraw.Draw(img)

    _apply_dark_fantasy_backdrop(draw, width, height, accent=(138, 102, 116), shadow=(78, 50, 72))

    header_box = (20, 14, width - 20, 94)
    _draw_soft_glow(draw, header_box, (152, 118, 96), passes=4)
    draw.rounded_rectangle(header_box, radius=16, fill=(18, 16, 24, 232), outline=(152, 118, 96, 255), width=2)
    draw.rectangle((22, 70, width - 22, 92), fill=(128, 94, 76, 78))

    title = "Dimensional Recruitment" if not is_vi else "Chieu Mo Khong Gian"
    subtitle = (
        f"{player_name} executes {int(pull_count)} pull(s)"
        if not is_vi
        else f"{player_name} quay {int(pull_count)} luot"
    )
    draw.text((40, 26), title, font=_font(34), fill=(246, 236, 220, 255))
    draw.text((42, 66), subtitle, font=_font(16), fill=(224, 210, 188, 255))

    featured = max(pull_rows, key=lambda row: _gacha_rarity_rank(str(row.get("rarity", "common"))))
    featured_rarity = str(featured.get("rarity", "common")).strip().lower()
    featured_name = str(featured.get("name", "Unknown"))
    featured_form = str(featured.get("form", "Base"))
    featured_emoji = str(featured.get("emoji", "") or "").strip()
    featured_emoji_fb = emoji_fallback_for_token(featured_emoji)
    featured_color = _gacha_rarity_color(featured_rarity)
    featured_rgb = (featured_color[0], featured_color[1], featured_color[2])

    feature_box = (24, 108, 830, 246)
    _draw_soft_glow(draw, feature_box, featured_rgb, passes=6)
    draw.rounded_rectangle(feature_box, radius=18, fill=(24, 20, 32, 236), outline=featured_color, width=3)
    draw.rectangle((26, 110, 828, 136), fill=(featured_color[0], featured_color[1], featured_color[2], 82))
    draw.text((44, 114), "Featured Pull" if not is_vi else "Vat pham noi bat", font=_font(20), fill=(252, 252, 255, 255))
    featured_prefix = f"{featured_emoji_fb} " if featured_emoji_fb else ""
    featured_line = f"{featured_prefix}{featured_name} [{featured_form}]"
    draw.text((44, 156), featured_line, font=_font(30), fill=(244, 248, 255, 255))
    draw.text((44, 206), featured_rarity.upper(), font=_font(16), fill=(232, 220, 198, 255))
    draw.text((760, 146), "SSR" if _gacha_rarity_rank(featured_rarity) >= 4 else "SR", font=_font(44), fill=(255, 255, 255, 86))
    _draw_star(draw, 780, 124, 10, (255, 235, 189), 230)
    _draw_star(draw, 744, 218, 8, (198, 227, 255), 190)

    stat_box = (848, 108, 1196, 246)
    _draw_soft_glow(draw, stat_box, (150, 120, 92), passes=4)
    draw.rounded_rectangle(stat_box, radius=18, fill=(24, 20, 30, 236), outline=(150, 120, 92, 255), width=2)
    draw.text((868, 124), "Banner", font=_font(18), fill=(230, 216, 194, 255))
    draw.text((868, 150), str(banner_name or "Standard Rift"), font=_font(18), fill=(246, 236, 220, 255))
    pity_label = f"Pity {int(pity_now)}/{int(hard_pity)}"
    draw.text((868, 180), pity_label, font=_font(16), fill=(220, 206, 184, 255))

    pity_ratio = max(0.0, min(float(pity_now) / max(1.0, float(hard_pity)), 1.0))
    pity_x, pity_y, pity_w, pity_h = 868, 206, 306, 12
    draw.rounded_rectangle((pity_x, pity_y, pity_x + pity_w, pity_y + pity_h), radius=6, fill=(54, 48, 60, 255))
    fill_w = int(pity_w * pity_ratio)
    if fill_w > 0:
        left = (178, 142, 96)
        right = (132, 90, 114)
        for x in range(fill_w):
            c = _mix_rgb(left, right, x / max(1, fill_w - 1))
            draw.line((pity_x + x, pity_y, pity_x + x, pity_y + pity_h), fill=(c[0], c[1], c[2], 255), width=1)
    soft_px = pity_x + int(pity_w * (max(0, int(soft_pity)) / max(1.0, float(hard_pity))))
    draw.line((soft_px, pity_y - 4, soft_px, pity_y + pity_h + 4), fill=(255, 235, 170, 220), width=2)
    draw.text((868, 222), f"Soft pity {int(soft_pity)}", font=_font(14), fill=(228, 206, 162, 255))

    section_y = 266
    section_h = rows_h + 96
    panel_box = (24, section_y, 1196, section_y + section_h)
    _draw_soft_glow(draw, panel_box, (142, 114, 90), passes=3)
    draw.rounded_rectangle(panel_box, radius=16, fill=(22, 18, 30, 236), outline=(116, 96, 124, 255), width=2)
    draw.rectangle((26, section_y + 2, 1194, section_y + 34), fill=(122, 88, 72, 116))
    draw.text((44, section_y + 8), "Summon Results" if not is_vi else "Ket qua quay", font=_font(20), fill=(242, 229, 206, 255))

    lookup = _emoji_lookup_from_guild(guild)
    cache: dict[str, Any] = {}
    timeout = aiohttp.ClientTimeout(total=20)

    row_start_y = section_y + 44
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for i, row in enumerate(pull_rows):
            y = row_start_y + i * (row_h + row_gap)
            rarity = str(row.get("rarity", "common")).strip().lower()
            rarity_color = _gacha_rarity_color(rarity)
            r_rgb = (rarity_color[0], rarity_color[1], rarity_color[2])
            base_fill = (30, 24, 38, 236) if i % 2 == 0 else (26, 20, 34, 236)

            draw.rounded_rectangle((40, y, 1178, y + row_h), radius=12, fill=base_fill, outline=(116, 98, 126, 255), width=2)
            draw.rounded_rectangle((44, y + 4, 56, y + row_h - 4), radius=6, fill=rarity_color)
            draw.rectangle((58, y + 5, 1174, y + 14), fill=(255, 255, 255, 24))

            _draw_star(draw, 1148, y + 19, 5, r_rgb, 130)

            r_icon = await fetch_discord_emoji_image(
                session,
                rarity_icon_token(rarity),
                lookup,
                size=22,
                cache=cache,
            )
            if r_icon is not None:
                img.alpha_composite(r_icon, (66, y + 17))
            else:
                rarity_fb = emoji_fallback_for_token(rarity_icon_token(rarity))
                if rarity_fb:
                    draw.text((66, y + 16), rarity_fb, font=_font(16), fill=(232, 224, 208, 255))

            idx = int(row.get("index", i + 1) or (i + 1))
            draw.text((98, y + 18), f"#{idx:02d}", font=_font(16), fill=(216, 204, 188, 255))

            emoji = str(row.get("emoji", "") or "").strip()
            if emoji:
                em = await fetch_discord_emoji_image(session, emoji, lookup, size=22, cache=cache)
                if em is not None:
                    img.alpha_composite(em, (156, y + 16))
                else:
                    emoji_fb = emoji_fallback_for_token(emoji)
                    if emoji_fb:
                        draw.text((156, y + 14), emoji_fb, font=_font(22), fill=(249, 250, 255, 255))

            name = str(row.get("name", "Unknown"))
            form = str(row.get("form", "Base"))
            draw.text((194, y + 10), name, font=_font(21), fill=(244, 234, 220, 255))
            draw.text((194, y + 33), form, font=_font(14), fill=(192, 178, 164, 255))

            is_dup = bool(row.get("is_duplicate", False))
            if is_dup:
                tag_text = (
                    f"DUP +{int(duplicate_shard_value)} shard"
                    if not is_vi
                    else f"TRUNG +{int(duplicate_shard_value)} manh"
                )
                tag_fill = (126, 80, 48, 255)
                tag_outline = (240, 179, 116, 255)
            else:
                tag_text = "NEW" if not is_vi else "MOI"
                tag_fill = (44, 90, 66, 255)
                tag_outline = (124, 232, 173, 255)

            tag_w = 170
            tag_x1 = 984
            tag_x2 = tag_x1 + tag_w
            draw.rounded_rectangle((tag_x1, y + 13, tag_x2, y + 43), radius=10, fill=tag_fill, outline=tag_outline, width=2)
            draw.text((tag_x1 + 12, y + 20), tag_text, font=_font(14), fill=(248, 250, 255, 255))

            rarity_text = rarity.upper()
            try:
                rb = draw.textbbox((0, 0), rarity_text, font=_font(15))
                rw = max(0, int(rb[2] - rb[0]))
            except Exception:
                rw = len(rarity_text) * 8
            draw.text((956 - rw, y + 21), rarity_text, font=_font(15), fill=rarity_color)

    duplicate_count = sum(1 for row in pull_rows if bool(row.get("is_duplicate", False)))
    top_count = sum(1 for row in pull_rows if _gacha_rarity_rank(str(row.get("rarity", "common"))) >= _gacha_rarity_rank("legendary"))
    footer = (
        f"Spent {int(cost)} coins | Duplicates {duplicate_count} | Legendary+ {top_count} | Soft pity {int(soft_pity)}"
        if not is_vi
        else f"Da tieu {int(cost)} coin | Trung lap {duplicate_count} | Legendary+ {top_count} | Soft pity {int(soft_pity)}"
    )
    footer_y = section_y + section_h + 18
    draw.rounded_rectangle((24, footer_y, 1196, footer_y + 56), radius=12, fill=(24, 20, 32, 238), outline=(116, 98, 126, 255), width=2)
    draw.text((44, footer_y + 18), footer, font=_font(16), fill=(220, 206, 186, 255))

    out = io.BytesIO()
    img.save(out, format="PNG")
    out.seek(0)
    return out


_SHOP_CATEGORY_STYLE = {
    "main": {
        "title": "Quartermaster Bazaar",
        "accent": (136, 112, 94),
        "shadow": (72, 52, 66),
        "panel_top": (38, 30, 46),
        "panel_bottom": (24, 20, 32),
    },
    "consumables": {
        "title": "Consumables Wing",
        "accent": (110, 136, 98),
        "shadow": (56, 80, 64),
        "panel_top": (30, 44, 40),
        "panel_bottom": (18, 30, 28),
        "bg_image": "assets/shop-thuoc.png",
        "bg_blur": 7,
        "bg_opacity": 0.3,
    },
    "equipment": {
        "title": "Equipment Wing",
        "accent": (150, 116, 92),
        "shadow": (84, 62, 52),
        "panel_top": (44, 34, 30),
        "panel_bottom": (28, 22, 20),
    },
    "materials": {
        "title": "Materials Wing",
        "accent": (126, 110, 148),
        "shadow": (66, 54, 86),
        "panel_top": (34, 30, 42),
        "panel_bottom": (22, 20, 34),
    },
    "black_market": {
        "title": "Black Market",
        "accent": (142, 86, 104),
        "shadow": (58, 28, 44),
        "panel_top": (34, 24, 34),
        "panel_bottom": (20, 14, 24),
        "market_label": "PLAYER MARKET",
    },
}


def _shop_style(category: str) -> dict:
    key = str(category or "main").strip().lower()
    return _SHOP_CATEGORY_STYLE.get(key, _SHOP_CATEGORY_STYLE["main"])


def _shop_rarity_glow(rarity: str) -> tuple[int, int, int] | None:
    key = str(rarity or "common").strip().lower()
    if key == "uncommon":
        return (86, 210, 138)
    if key == "rare":
        return (92, 164, 255)
    if key in {"epic", "legendary", "mythic"}:
        return (190, 118, 255)
    return None


def _apply_shop_background_layer(base: Image.Image, style: dict[str, Any]) -> None:
    if Image is None:
        return

    bg_path = str(style.get("bg_image", "") or "").strip()
    if not bg_path:
        return

    try:
        bg = Image.open(bg_path).convert("RGBA")
    except Exception:
        return

    resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.BICUBIC)
    bg = bg.resize(base.size, resample)

    blur_radius = float(style.get("bg_blur", 7) or 7)
    if ImageFilter is not None and blur_radius > 0:
        bg = bg.filter(ImageFilter.GaussianBlur(radius=blur_radius))

    opacity = max(0.0, min(float(style.get("bg_opacity", 0.3) or 0.3), 1.0))
    if opacity < 1.0:
        bg.putalpha(bg.getchannel("A").point(lambda a: int(a * opacity)))

    base.alpha_composite(bg)


def _apply_shop_texture_layer(base: Image.Image, *, strength: int = 18, opacity: int = 14) -> None:
    if Image is None:
        return

    w, h = base.size
    try:
        noise = Image.effect_noise((w, h), max(1, int(strength))).convert("L")
    except Exception:
        return

    clamped_opacity = max(0, min(64, int(opacity)))
    alpha = noise.point(lambda p: int((p * clamped_opacity) / 255))
    grain = Image.new("RGBA", (w, h), (232, 224, 206, 0))
    grain.putalpha(alpha)
    base.alpha_composite(grain)


async def render_shop_card(
    category: str,
    items: list[dict],
    guild: discord.Guild | None,
    *,
    categories: list[dict] | None = None,
    lang: str = "en",
) -> io.BytesIO | None:
    if Image is None or ImageDraw is None:
        return None

    is_vi = str(lang).lower().startswith("vi")
    cat = str(category or "main").strip().lower()
    style = _shop_style(cat)
    accent = tuple(style.get("accent", (120, 186, 255)))
    shadow = tuple(style.get("shadow", (72, 52, 66)))
    title = str(style.get("title", "Quartermaster Bazaar"))

    width = 1220

    if cat == "main":
        cat_rows = [c for c in (categories or []) if isinstance(c, dict)]
        rows_h = max(1, len(cat_rows)) * 112
        height = max(640, 250 + rows_h)
    else:
        item_rows = [i for i in (items or []) if isinstance(i, dict)][:12]
        visible_rows = max(1, min(5, len(item_rows)))
        rows_h = visible_rows * 94 + max(0, visible_rows - 1) * 10
        height = max(700, 322 + rows_h)

    img = Image.new("RGBA", (width, height), (12, 18, 30, 255))
    draw = ImageDraw.Draw(img)

    _apply_dark_fantasy_backdrop(draw, width, height, accent=accent, shadow=shadow)
    _apply_shop_background_layer(img, style)
    _apply_shop_texture_layer(img, strength=18, opacity=12)

    header_box = (20, 14, width - 20, 96)
    _draw_soft_glow(draw, header_box, accent, passes=4)
    draw.rounded_rectangle(header_box, radius=16, fill=(18, 16, 24, 232), outline=(accent[0], accent[1], accent[2], 255), width=2)
    draw.rectangle((22, 72, width - 22, 94), fill=(accent[0], accent[1], accent[2], 54))

    head_title = "Quartermaster Bazaar" if cat == "main" else title
    if is_vi and cat == "main":
        head_title = "Khu Tiep Te Doi Hinh"
    elif is_vi:
        head_title = {
            "consumables": "Khu Vat Pham Tieu Hao",
            "equipment": "Khu Trang Bi",
            "materials": "Khu Vat Lieu",
            "black_market": "Cho Den",
        }.get(cat, title)

    draw.text((40, 28), head_title, font=_font(34), fill=(246, 236, 220, 255))
    subtitle = (
        "Browse categories and choose your supply route"
        if not is_vi
        else "Chon danh muc de mo kho vat pham"
    )
    draw.text((42, 68), subtitle, font=_font(16), fill=(222, 210, 194, 255))

    content_box = (24, 112, width - 24, height - 22)
    _draw_soft_glow(draw, content_box, accent, passes=3)
    panel_top = tuple(style.get("panel_top", (34, 28, 40)))
    panel_bottom = tuple(style.get("panel_bottom", (22, 20, 32)))
    panel_w = content_box[2] - content_box[0]
    panel_h = content_box[3] - content_box[1]
    panel_layer = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
    panel_draw = ImageDraw.Draw(panel_layer)
    for py in range(panel_h):
        blend = py / max(1, panel_h - 1)
        c = _mix_rgb(panel_top, panel_bottom, blend)
        panel_draw.line((0, py, panel_w, py), fill=(c[0], c[1], c[2], 236), width=1)
    panel_mask = Image.new("L", (panel_w, panel_h), 0)
    ImageDraw.Draw(panel_mask).rounded_rectangle((0, 0, panel_w - 1, panel_h - 1), radius=16, fill=255)
    img.paste(panel_layer, (content_box[0], content_box[1]), panel_mask)
    draw.rounded_rectangle(content_box, radius=16, outline=(108, 94, 122, 255), width=2)

    if cat == "main":
        cat_rows = [c for c in (categories or []) if isinstance(c, dict)]
        if not cat_rows:
            draw.text((52, 156), "No categories available." if not is_vi else "Khong co danh muc.", font=_font(20), fill=(238, 244, 255, 255))
        else:
            start_y = 146
            for i, cat_data in enumerate(cat_rows[:8]):
                y = start_y + i * 112
                cid = str(cat_data.get("id", "main"))
                cstyle = _shop_style(cid)
                cacc = tuple(cstyle.get("accent", (120, 186, 255)))
                box = (44, y, width - 44, y + 94)
                draw.rounded_rectangle(box, radius=14, fill=(28, 22, 36, 236), outline=(cacc[0], cacc[1], cacc[2], 255), width=2)

                emoji = str(cat_data.get("emoji", "📦"))
                cname = str(cat_data.get("name", cid))
                cdesc = str(cat_data.get("desc", ""))
                count = int(cat_data.get("count", 0) or 0)
                count_label = f"{count} items" if not is_vi else f"{count} vat pham"

                category_emoji = emoji_fallback_for_token(emoji) or emoji
                draw.text((64, y + 16), f"{category_emoji}  {cname}", font=_font(24), fill=(242, 230, 210, 255))
                draw.text((64, y + 52), cdesc, font=_font(15), fill=(200, 186, 170, 255))
                draw.text((1028, y + 34), count_label, font=_font(16), fill=(230, 218, 196, 255))

    else:
        item_rows = [i for i in (items or []) if isinstance(i, dict)][:12]
        items_per_page = 5

        derived_total_pages = max(1, math.ceil(len(item_rows) / items_per_page))
        if item_rows:
            try:
                current_page = max(1, int(item_rows[0].get("page", 1) or 1))
            except Exception:
                current_page = 1
            try:
                explicit_total_pages = max(1, int(item_rows[0].get("total_pages", derived_total_pages) or derived_total_pages))
            except Exception:
                explicit_total_pages = derived_total_pages
            total_pages = max(derived_total_pages, explicit_total_pages)
        else:
            current_page = 1
            total_pages = 1

        if len(item_rows) <= items_per_page:
            page_rows = item_rows
        else:
            current_page = min(current_page, total_pages)
            start_index = max(0, (current_page - 1) * items_per_page)
            page_rows = item_rows[start_index:start_index + items_per_page]

        draw.rectangle((26, 114, width - 26, 154), fill=(accent[0], accent[1], accent[2], 68))
        draw.text((46, 122), "Inventory Cards" if not is_vi else "The Vat Pham", font=_font(22), fill=(244, 234, 216, 255))
        if cat == "black_market":
            label = str(style.get("market_label", "PLAYER MARKET"))
            draw.rounded_rectangle((width - 304, 120, width - 44, 148), radius=10, fill=(44, 18, 30, 212), outline=(182, 98, 126, 255), width=2)
            draw.text((width - 286, 126), label, font=_font(15), fill=(248, 222, 206, 255))

        if not page_rows:
            empty_text = "No stock in this wing." if not is_vi else "Danh muc nay hien khong co hang."
            draw.text((54, 188), empty_text, font=_font(21), fill=(224, 218, 204, 255))
        else:
            def _stock_and_disabled(row: dict[str, Any]) -> tuple[int, bool]:
                fallback_stock = 1 if cat == "black_market" else 99
                raw_stock = row.get("stock", row.get("remaining_stock", row.get("quantity", fallback_stock)))
                try:
                    stock_value = int(raw_stock if raw_stock is not None else fallback_stock)
                except Exception:
                    stock_value = fallback_stock
                stock_value = max(0, stock_value)
                disabled = bool(row.get("disabled", False) or row.get("out_of_stock", False))
                if cat == "black_market" and stock_value <= 0:
                    disabled = True
                return stock_value, disabled

            selected_index = -1
            for idx, row in enumerate(page_rows):
                if bool(row.get("selected", False)):
                    selected_index = idx
                    break
            if selected_index < 0:
                for idx, row in enumerate(page_rows):
                    _, disabled_state = _stock_and_disabled(row)
                    if not disabled_state:
                        selected_index = idx
                        break
            if selected_index < 0:
                selected_index = 0

            lookup = _emoji_lookup_from_guild(guild)
            cache: dict[str, Any] = {}
            timeout = aiohttp.ClientTimeout(total=20)
            start_y = 170
            card_h = 94
            card_gap = 10
            card_x1 = 44
            card_x2 = width - 44

            async with aiohttp.ClientSession(timeout=timeout) as session:
                for idx, item in enumerate(page_rows):
                    y = start_y + idx * (card_h + card_gap)
                    rarity = str(item.get("rarity", "common")).strip().lower()
                    rarity_color = _gacha_rarity_color(rarity)
                    rarity_glow = _shop_rarity_glow(rarity)
                    stock, is_disabled = _stock_and_disabled(item)
                    is_selected = (idx == selected_index) and not is_disabled

                    for depth in range(3):
                        spread = 4 + depth * 2
                        shade = max(8, 34 - depth * 10)
                        draw.rounded_rectangle(
                            (card_x1 - spread, y - spread + 2, card_x2 + spread, y + card_h + spread + 2),
                            radius=18 + depth * 2,
                            fill=(6, 6, 10, shade),
                        )

                    card_w = card_x2 - card_x1
                    card_layer = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
                    card_draw = ImageDraw.Draw(card_layer)
                    local_top = tuple(style.get("panel_top", (36, 30, 44)))
                    local_bottom = tuple(style.get("panel_bottom", (22, 20, 32)))
                    for py in range(card_h):
                        mix = py / max(1, card_h - 1)
                        c = _mix_rgb(local_top, local_bottom, mix)
                        if is_disabled:
                            c = _mix_rgb(c, (86, 86, 96), 0.58)
                        card_draw.line((0, py, card_w, py), fill=(c[0], c[1], c[2], 236 if not is_disabled else 172), width=1)
                    card_draw.rectangle((2, 2, card_w - 3, 18), fill=(255, 255, 255, 20 if not is_disabled else 10))

                    mask = Image.new("L", (card_w, card_h), 0)
                    ImageDraw.Draw(mask).rounded_rectangle((0, 0, card_w - 1, card_h - 1), radius=16, fill=255)
                    img.paste(card_layer, (card_x1, y), mask)

                    if rarity_glow is not None and not is_disabled:
                        _draw_soft_glow(draw, (card_x1 + 4, y + 4, card_x2 - 4, y + card_h - 4), rarity_glow, passes=2)
                    if is_selected:
                        _draw_soft_glow(draw, (card_x1 + 2, y + 2, card_x2 - 2, y + card_h - 2), accent, passes=3)

                    outline = (110, 96, 124, 230)
                    if is_disabled:
                        outline = (102, 102, 108, 190)
                    elif is_selected:
                        outline = (248, 226, 186, 255)
                    elif rarity_glow is not None:
                        outline = (rarity_glow[0], rarity_glow[1], rarity_glow[2], 232)
                    draw.rounded_rectangle((card_x1, y, card_x2, y + card_h), radius=16, outline=outline, width=3 if is_selected else 2)

                    icon_box = (card_x1 + 16, y + 14, card_x1 + 84, y + 82)
                    draw.rounded_rectangle(icon_box, radius=12, fill=(18, 16, 24, 220), outline=(120, 108, 136, 200), width=2)

                    emoji_token = str(item.get("emoji", "") or "").strip()
                    em = await fetch_discord_emoji_image(session, emoji_token, lookup, size=42, cache=cache)
                    if em is not None:
                        icon_x = icon_box[0] + (icon_box[2] - icon_box[0] - em.width) // 2
                        icon_y = icon_box[1] + (icon_box[3] - icon_box[1] - em.height) // 2
                        img.alpha_composite(em, (icon_x, icon_y))
                    else:
                        fallback = emoji_fallback_for_token(emoji_token) or "📦"
                        draw.text((icon_box[0] + 19, icon_box[1] + 17), fallback, font=_font(24), fill=(244, 234, 216, 255))

                    item_name = str(item.get("name", "Item"))
                    draw.text((card_x1 + 102, y + 13), item_name, font=_font(22), fill=(244, 238, 222, 255) if not is_disabled else (188, 186, 190, 220))

                    if cat == "black_market":
                        price = int(item.get("black_market_sell", item.get("sell_price", 0)) or 0)
                        seller_name = str(item.get("seller_name", item.get("seller", "Player Vendor")))
                        draw.text((card_x1 + 496, y + 16), f"Seller: {seller_name}", font=_font(14), fill=(232, 214, 202, 245) if not is_disabled else (156, 154, 160, 210))
                        draw.text((card_x1 + 496, y + 40), f"Stock: {stock}", font=_font(14), fill=(236, 220, 204, 255) if not is_disabled else (152, 150, 154, 210))
                    else:
                        price = int(item.get("buy_price", 0) or 0)
                        subtitle = str(item.get("subtitle", "")).strip()
                        if not subtitle:
                            subtitle = f"{rarity.title()} supply item"
                        draw.text((card_x1 + 102, y + 66), subtitle[:46], font=_font(13), fill=(202, 190, 176, 232) if not is_disabled else (146, 144, 148, 200))

                    price_label = f"💰 {price:,}"
                    draw.text((card_x1 + 102, y + 42), price_label, font=_font(18), fill=(242, 228, 198, 255) if not is_disabled else (164, 160, 156, 214))

                    rarity_tag_fill = (rarity_color[0], rarity_color[1], rarity_color[2], 120 if not is_disabled else 60)
                    draw.rounded_rectangle((card_x2 - 306, y + 10, card_x2 - 198, y + 32), radius=8, fill=rarity_tag_fill, outline=(rarity_color[0], rarity_color[1], rarity_color[2], 220), width=2)
                    draw.text((card_x2 - 286, y + 14), rarity.upper(), font=_font(13), fill=(248, 248, 252, 255) if not is_disabled else (186, 186, 192, 210))

                    if is_selected:
                        selected_text = "SELECTED" if not is_vi else "DA CHON"
                        draw.rounded_rectangle((card_x2 - 190, y + 10, card_x2 - 20, y + 32), radius=8, fill=(accent[0], accent[1], accent[2], 94), outline=(248, 226, 186, 232), width=2)
                        draw.text((card_x2 - 168, y + 14), selected_text, font=_font(13), fill=(248, 238, 218, 255))

                    qty = max(1, int(item.get("quantity", 1) or 1))
                    if cat == "black_market":
                        qty = max(1, min(qty, max(1, stock)))

                    control_y = y + 45
                    minus_box = (card_x2 - 286, control_y, card_x2 - 252, control_y + 30)
                    qty_box = (card_x2 - 250, control_y, card_x2 - 204, control_y + 30)
                    plus_box = (card_x2 - 202, control_y, card_x2 - 168, control_y + 30)
                    buy_box = (card_x2 - 156, control_y - 2, card_x2 - 22, control_y + 32)

                    control_fill = (34, 30, 42, 230) if not is_disabled else (66, 66, 74, 170)
                    draw.rounded_rectangle(minus_box, radius=8, fill=control_fill, outline=(130, 118, 142, 220), width=2)
                    draw.rounded_rectangle(qty_box, radius=8, fill=control_fill, outline=(130, 118, 142, 220), width=2)
                    draw.rounded_rectangle(plus_box, radius=8, fill=control_fill, outline=(130, 118, 142, 220), width=2)

                    buy_fill = (accent[0], accent[1], accent[2], 170) if not is_disabled else (92, 92, 100, 170)
                    draw.rounded_rectangle(buy_box, radius=9, fill=buy_fill, outline=(248, 226, 186, 214) if not is_disabled else (122, 122, 132, 180), width=2)

                    draw.text((minus_box[0] + 12, minus_box[1] + 6), "-", font=_font(20), fill=(242, 236, 222, 255) if not is_disabled else (164, 164, 170, 220))
                    draw.text((qty_box[0] + 16, qty_box[1] + 7), str(qty), font=_font(16), fill=(248, 238, 220, 255) if not is_disabled else (172, 170, 176, 224))
                    draw.text((plus_box[0] + 10, plus_box[1] + 5), "+", font=_font(20), fill=(242, 236, 222, 255) if not is_disabled else (164, 164, 170, 220))

                    buy_label = "Buy" if not is_vi else "Mua"
                    if bool(item.get("select_only", False)):
                        buy_label = "Select" if not is_vi else "Chon"
                    if is_disabled:
                        buy_label = "Sold Out" if not is_vi else "Het hang"
                    draw.text((buy_box[0] + 20, buy_box[1] + 9), buy_label, font=_font(15), fill=(248, 242, 226, 255) if not is_disabled else (184, 182, 188, 228))

                    if is_disabled:
                        draw.rounded_rectangle((card_x1, y, card_x2, y + card_h), radius=16, fill=(20, 20, 24, 96))

        nav_box = (44, height - 74, width - 44, height - 30)
        draw.rounded_rectangle(nav_box, radius=12, fill=(16, 14, 24, 212), outline=(102, 90, 118, 220), width=2)

        prev_enabled = current_page > 1
        next_enabled = current_page < total_pages
        prev_text = "◀ Prev" if not is_vi else "◀ Truoc"
        next_text = "Next ▶" if not is_vi else "Sau ▶"
        prev_color = (236, 224, 202, 255) if prev_enabled else (130, 126, 136, 190)
        next_color = (236, 224, 202, 255) if next_enabled else (130, 126, 136, 190)
        draw.text((72, nav_box[1] + 10), prev_text, font=_font(18), fill=prev_color)
        draw.text((width - 166, nav_box[1] + 10), next_text, font=_font(18), fill=next_color)

        page_text = f"Page {current_page} / {total_pages}" if not is_vi else f"Trang {current_page} / {total_pages}"
        page_bbox = draw.textbbox((0, 0), page_text, font=_font(18))
        page_w = max(0, int(page_bbox[2] - page_bbox[0]))
        page_x = (width - page_w) // 2
        draw.rounded_rectangle((page_x - 18, nav_box[1] + 8, page_x + page_w + 18, nav_box[3] - 8), radius=10, fill=(accent[0], accent[1], accent[2], 82), outline=(accent[0], accent[1], accent[2], 224), width=2)
        draw.text((page_x, nav_box[1] + 10), page_text, font=_font(18), fill=(248, 238, 218, 255))

    out = io.BytesIO()
    img.save(out, format="PNG")
    out.seek(0)
    return out


def _dungeon_mode_palette(mode: str, won: bool | None = None, status: str = "") -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    m = str(mode or "status").strip().lower()
    if m == "start":
        return (164, 131, 92), (94, 70, 46)
    if m == "choice":
        return (143, 110, 166), (83, 62, 102)
    if m == "finish":
        st = str(status or "").strip().lower()
        if st in {"completed", "retreated"}:
            return (124, 152, 112), (66, 95, 62)
        return (166, 100, 112), (102, 54, 66)
    if m == "node":
        if bool(won):
            return (148, 124, 88), (86, 66, 45)
        return (156, 88, 98), (98, 52, 62)
    return (126, 138, 166), (72, 84, 108)


def _node_type_token(ntype: str) -> str:
    m = {
        "combat": "⚔️",
        "elite": "🩸",
        "event": "🎲",
        "sanctuary": "⛺",
        "merchant": "🛒",
        "curse": "☠️",
        "boss_gate": "👑",
    }
    return m.get(str(ntype or "").strip().lower(), "❔")


async def render_dungeon_card(payload: dict, guild: discord.Guild | None, *, lang: str = "en") -> io.BytesIO | None:
    if Image is None or ImageDraw is None:
        return None

    data = payload if isinstance(payload, dict) else {}
    mode = str(data.get("mode", "status")).strip().lower()
    is_vi = str(lang).lower().startswith("vi")
    won = bool(data.get("win", True))
    status = str(data.get("status", ""))

    accent, shadow = _dungeon_mode_palette(mode, won=won, status=status)
    title = str(data.get("title", "Dungeon Operation"))
    subtitle = str(data.get("subtitle", "Tactical update"))
    run_id = str(data.get("run_id", "-"))
    difficulty = str(data.get("difficulty", "normal")).title()
    floor = int(data.get("floor", 1) or 1)
    total = int(data.get("total_floors", 12) or 12)
    phase = str(data.get("phase", ""))

    units = [u for u in (data.get("units", []) or []) if isinstance(u, dict)][:5]
    details = [str(x) for x in (data.get("detail_lines", []) or []) if str(x).strip()]

    width = 1220
    content_rows = max(6, len(details))
    height = max(700, 372 + len(units) * 44 + content_rows * 26)

    img = Image.new("RGBA", (width, height), (14, 20, 36, 255))
    draw = ImageDraw.Draw(img)

    top_grad = _mix_rgb((10, 14, 22), accent, 0.14)
    bottom_grad = _mix_rgb((20, 12, 19), shadow, 0.24)
    _draw_vertical_gradient(draw, width, height, top_grad, bottom_grad)
    _draw_mist_layers(draw, width, int(height * 0.64), height - 4, (24, 20, 28))
    _draw_vignette(draw, width, height, passes=13, alpha_start=24, alpha_end=102)

    for i in range(12):
        x = int((i / 11.0) * width) - 220
        tone = _mix_rgb((58, 62, 78), accent, (i % 4) / 3.0)
        draw.polygon(
            [(x, 0), (x + 160, 0), (x + 520, height), (x + 360, height)],
            fill=(tone[0], tone[1], tone[2], 20),
        )

    for i in range(16):
        cx = int((i * 129 + 77) % width)
        cy = int((i * 83 + 41) % max(260, height - 60))
        _draw_star(draw, cx, cy, 2 + (i % 3), (236, 207, 164), 90)

    header_box = (20, 16, width - 20, 104)
    _draw_soft_glow(draw, header_box, accent, passes=4)
    draw.rounded_rectangle(header_box, radius=16, fill=(18, 16, 24, 232), outline=(accent[0], accent[1], accent[2], 255), width=2)
    draw.rectangle((22, 76, width - 22, 102), fill=(accent[0], accent[1], accent[2], 52))

    draw.text((40, 30), title, font=_font(33), fill=(246, 249, 255, 255))
    draw.text((42, 72), subtitle, font=_font(16), fill=(222, 210, 192, 255))

    top_left = (24, 120, 620, 312)
    top_right = (640, 120, 1196, 312)
    bottom = (24, 328, 1196, height - 22)

    for box in (top_left, top_right, bottom):
        _draw_soft_glow(draw, box, accent, passes=2)
        draw.rounded_rectangle(box, radius=14, fill=(22, 19, 30, 236), outline=(99, 88, 112, 255), width=2)
        x1, y1, x2, _ = box
        draw.line((x1 + 16, y1 + 10, x2 - 16, y1 + 10), fill=(148, 124, 94, 100), width=1)

    draw.rectangle((26, 122, 618, 150), fill=(accent[0], accent[1], accent[2], 54))
    draw.rectangle((642, 122, 1194, 150), fill=(accent[0], accent[1], accent[2], 54))
    draw.rectangle((26, 330, 1194, 358), fill=(accent[0], accent[1], accent[2], 54))

    left_y = 158
    meta_lines = [
        f"Run ID: {run_id}",
        f"Difficulty: {difficulty}",
        f"Floor: {floor}/{total}",
    ]
    if phase:
        meta_lines.append(f"Phase: {phase}")
    if str(data.get("boss_family", "")):
        meta_lines.append(f"Boss Family: {str(data.get('boss_family', ''))}")

    score = int(data.get("score", 0) or 0)
    risk = int(data.get("risk_score", 0) or 0)
    supply = int(data.get("supply", 0) or 0)
    fatigue = int(data.get("fatigue", 0) or 0)
    corruption = int(data.get("corruption", 0) or 0)
    if any((score, risk, supply, fatigue, corruption)):
        meta_lines.append(f"Score {score} | Risk {risk}")
        meta_lines.append(f"Supply {supply} | Fatigue {fatigue} | Corruption {corruption}")

    draw.text((44, 126), "Run Intel" if not is_vi else "Thong tin run", font=_font(19), fill=(236, 225, 210, 255))
    for line in meta_lines[:8]:
        draw.text((44, left_y), line[:72], font=_font(16), fill=(220, 210, 194, 255))
        left_y += 24

    draw.text((662, 126), "Squad Status" if not is_vi else "Tinh trang doi", font=_font(19), fill=(236, 225, 210, 255))
    lookup = _emoji_lookup_from_guild(guild)
    cache: dict[str, Any] = {}
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        uy = 158
        if not units:
            draw.text((662, uy), "No squad data" if not is_vi else "Khong co du lieu doi", font=_font(16), fill=(214, 226, 252, 255))
        for unit in units:
            hp = int(unit.get("hp", 0) or 0)
            max_hp = max(1, int(unit.get("max_hp", 1) or 1))
            alive = bool(unit.get("alive", hp > 0))
            name = str(unit.get("name", "Unit"))
            emoji_token = str(unit.get("emoji", "") or "").strip()

            draw.rounded_rectangle((656, uy - 4, 1182, uy + 34), radius=10, fill=(28, 22, 36, 236), outline=(108, 94, 122, 255), width=1)
            em = await fetch_discord_emoji_image(session, emoji_token, lookup, size=20, cache=cache)
            if em is not None:
                img.alpha_composite(em, (666, uy + 6))
                name_x = 692
            else:
                fallback = emoji_fallback_for_token(emoji_token)
                if not fallback:
                    fallback = "💀" if not alive else "🛡️"
                draw.text((668, uy + 5), fallback, font=_font(18), fill=(244, 248, 255, 255))
                name_x = 692

            draw.text((name_x, uy + 4), name[:24], font=_font(15), fill=(234, 228, 216, 255))
            _draw_bar(draw, 836, uy + 8, 276, 10, hp, max_hp, (126, 172, 114) if alive else (158, 82, 96), bg=(58, 52, 66))
            draw.text((1120, uy + 5), f"{hp}/{max_hp}", font=_font(12), fill=(219, 208, 190, 255))
            uy += 40

    draw.text((44, 334), "Operation Feed" if not is_vi else "Nhat ky hoat dong", font=_font(19), fill=(236, 225, 210, 255))
    dy = 366
    if not details:
        details = ["No new report."] if not is_vi else ["Khong co bao cao moi."]
    for line in details[:24]:
        draw.text((48, dy), f"• {line}"[:132], font=_font(16), fill=(222, 210, 194, 255))
        dy += 24

    out = io.BytesIO()
    img.save(out, format="PNG")
    out.seek(0)
    return out
