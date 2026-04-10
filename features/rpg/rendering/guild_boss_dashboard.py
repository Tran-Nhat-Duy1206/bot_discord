from __future__ import annotations

import io
import os
import re
from typing import Any

import aiohttp
import discord

from features.emoji_registry import emoji_fallback_for_token

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover
    Image = None
    ImageDraw = None
    ImageFont = None


EMOJI_RE = re.compile(r"^<(a?):([a-zA-Z0-9_]+):(\d+)>$")

RARITY_THEME = {
    "common": {
        "outline": (124, 116, 138, 255),
        "fill": (34, 26, 38, 228),
        "badge": (114, 98, 124, 255),
    },
    "uncommon": {
        "outline": (108, 140, 104, 255),
        "fill": (28, 42, 34, 228),
        "badge": (98, 128, 94, 255),
    },
    "rare": {
        "outline": (184, 148, 92, 255),
        "fill": (54, 42, 30, 228),
        "badge": (166, 128, 78, 255),
    },
    "epic": {
        "outline": (132, 106, 168, 255),
        "fill": (44, 30, 60, 228),
        "badge": (120, 94, 152, 255),
    },
    "legendary": {
        "outline": (178, 118, 86, 255),
        "fill": (62, 32, 28, 228),
        "badge": (164, 102, 72, 255),
    },
    "mythic": {
        "outline": (170, 96, 108, 255),
        "fill": (62, 24, 32, 228),
        "badge": (152, 86, 96, 255),
    },
}


def _font(size: int, bold: bool = False):
    if ImageFont is None:
        raise RuntimeError("Pillow is required")
    candidates = []
    if bold:
        candidates.extend(["arialbd.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf"])
    else:
        candidates.extend(["arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"])
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _parse_emoji_url(emoji_token: str | None, size: int = 128) -> str | None:
    if not isinstance(emoji_token, str):
        return None
    raw = emoji_token.strip()
    if not raw:
        return None
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    m = EMOJI_RE.match(raw)
    if not m:
        return None
    animated = bool(m.group(1))
    emoji_id = m.group(3)
    ext = "gif" if animated else "png"
    return f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}?size={max(32, int(size))}&quality=lossless"


def _load_local_image(path: str | None) -> Image.Image | None:
    if Image is None:
        return None
    if not isinstance(path, str) or not path.strip():
        return None
    p = path.strip()
    if not os.path.isfile(p):
        return None
    try:
        return Image.open(p).convert("RGBA")
    except Exception:
        return None


async def fetch_discord_emoji_image(
    session: aiohttp.ClientSession,
    emoji_token: str | None,
    *,
    size: int = 96,
    cache: dict[str, Any] | None = None,
) -> Image.Image | None:
    if Image is None:
        return None

    url = _parse_emoji_url(emoji_token, size=max(96, size * 2))
    if not url:
        return None
    key = f"{emoji_token}:{size}"
    if cache is not None and key in cache:
        return cache[key].copy()

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


def draw_panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    radius: int = 18,
    fill: tuple[int, int, int, int] = (24, 20, 32, 238),
    outline: tuple[int, int, int, int] = (112, 96, 126, 255),
    width: int = 2,
    title: str | None = None,
    title_font=None,
    title_color: tuple[int, int, int, int] = (238, 228, 210, 255),
) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle((x1, y1, x2, y2), radius=radius, fill=fill, outline=outline, width=width)
    if title:
        tf = title_font or _font(24, bold=True)
        draw.text((x1 + 18, y1 + 12), title, font=tf, fill=title_color)


def _draw_hp_bar(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    hp: int,
    max_hp: int,
    *,
    bg: tuple[int, int, int, int] = (44, 50, 64, 255),
    fg: tuple[int, int, int, int] = (222, 78, 78, 255),
) -> float:
    x1, y1, x2, y2 = box
    width = max(1, x2 - x1)
    ratio = 0.0 if max_hp <= 0 else max(0.0, min(1.0, float(hp) / float(max_hp)))
    draw.rounded_rectangle((x1, y1, x2, y2), radius=6, fill=bg)
    fw = max(1, int(width * ratio))
    draw.rounded_rectangle((x1, y1, x1 + fw, y2), radius=6, fill=fg)
    return ratio


async def draw_boss_card(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    session: aiohttp.ClientSession,
    boss: dict,
    box: tuple[int, int, int, int],
    *,
    cache: dict[str, Any] | None = None,
) -> None:
    rarity = str(boss.get("rarity", "common")).strip().lower()
    theme = RARITY_THEME.get(rarity, RARITY_THEME["common"])

    draw_panel(
        draw,
        box,
        radius=20,
        fill=theme["fill"],
        outline=theme["outline"],
        width=3,
    )

    x1, y1, x2, y2 = box
    card_w = x2 - x1
    title_font = _font(26, bold=True)
    sub_font = _font(18)
    stat_font = _font(17)

    name = str(boss.get("name", "Unknown Boss"))
    level = int(boss.get("level", 1) or 1)
    rarity_title = rarity.title()
    draw.text((x1 + 18, y1 + 14), f"{name}", font=title_font, fill=(246, 249, 255, 255))
    draw.text((x1 + 18, y1 + 46), f"Lv.{level}", font=sub_font, fill=(208, 218, 238, 255))

    badge_w, badge_h = 108, 28
    bx = x2 - badge_w - 16
    by = y1 + 16
    draw.rounded_rectangle((bx, by, bx + badge_w, by + badge_h), radius=10, fill=theme["badge"])
    draw.text((bx + 14, by + 5), rarity_title, font=_font(16, bold=True), fill=(255, 248, 235, 255))

    boss_img = await fetch_discord_emoji_image(
        session,
        str(boss.get("emoji", "") or ""),
        size=170,
        cache=cache,
    )
    if boss_img is not None:
        cx = x1 + int((card_w - 170) / 2)
        cy = y1 + 86
        canvas.alpha_composite(boss_img, (cx, cy))
    else:
        boss_fb = emoji_fallback_for_token(str(boss.get("emoji", "") or "")) or "👹"
        draw.text((x1 + int((card_w - 70) / 2), y1 + 134), boss_fb, font=_font(76, bold=True), fill=(244, 230, 210, 220))

    hp = int(boss.get("hp", 0) or 0)
    max_hp = max(1, int(boss.get("max_hp", 1) or 1))
    ratio = _draw_hp_bar(draw, (x1 + 18, y1 + 270, x2 - 18, y1 + 290), hp, max_hp)
    hp_color = (245, 210, 92, 255) if ratio < 0.35 else (236, 241, 255, 255)
    draw.text(
        (x1 + 18, y1 + 294),
        f"HP {hp:,}/{max_hp:,} ({int(ratio * 100)}%)",
        font=_font(16, bold=True),
        fill=hp_color,
    )

    stats = boss.get("stats", {}) if isinstance(boss.get("stats", {}), dict) else {}
    stat_lines = [
        ("HP", int(stats.get("hp", 0) or 0)),
        ("ATK", int(stats.get("atk", 0) or 0)),
        ("DEF", int(stats.get("def", 0) or 0)),
        ("CRIT", int(stats.get("crit", 0) or 0)),
        ("RES", int(stats.get("res", 0) or 0)),
    ]
    sy = y1 + 324
    for label, value in stat_lines:
        draw.text((x1 + 20, sy), f"{label:<4} {value}", font=stat_font, fill=(215, 224, 245, 255))
        sy += 24

    icon_tokens = [str(t) for t in (boss.get("icons", []) or [])][:3]
    ix = x1 + 18
    iy = y2 - 52
    for token in icon_tokens:
        icon = await fetch_discord_emoji_image(session, token, size=34, cache=cache)
        if icon is not None:
            draw.rounded_rectangle((ix - 3, iy - 3, ix + 37, iy + 37), radius=8, fill=(18, 24, 36, 255), outline=(110, 128, 166, 255), width=1)
            canvas.alpha_composite(icon, (ix, iy))
        else:
            fallback = emoji_fallback_for_token(token)
            if fallback:
                draw.rounded_rectangle((ix - 3, iy - 3, ix + 37, iy + 37), radius=8, fill=(18, 24, 36, 255), outline=(110, 128, 166, 255), width=1)
                draw.text((ix + 6, iy + 6), fallback, font=_font(20), fill=(238, 244, 255, 255))
        ix += 42


async def draw_damage_table(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    session: aiohttp.ClientSession,
    rows: list[dict],
    box: tuple[int, int, int, int],
    *,
    cache: dict[str, Any] | None = None,
) -> None:
    draw_panel(draw, box, title="Top 10 Damage Dealt", title_font=_font(24, bold=True))
    x1, y1, x2, y2 = box
    header_y = y1 + 56
    draw.text((x1 + 20, header_y), "Rank", font=_font(17, bold=True), fill=(226, 212, 190, 255))
    draw.text((x1 + 92, header_y), "Damage", font=_font(17, bold=True), fill=(226, 212, 190, 255))
    draw.text((x1 + 258, header_y), "Username", font=_font(17, bold=True), fill=(226, 212, 190, 255))

    max_rows = min(10, len(rows or []))
    row_h = 34
    for i in range(max_rows):
        r = rows[i] if isinstance(rows[i], dict) else {}
        y = header_y + 28 + i * row_h
        alt = (34, 26, 40, 230) if i % 2 == 0 else (30, 22, 36, 230)
        draw.rounded_rectangle((x1 + 14, y - 3, x2 - 14, y + row_h - 4), radius=8, fill=alt)

        rank = int(r.get("rank", i + 1) or (i + 1))
        dmg = int(r.get("damage", 0) or 0)
        username = str(r.get("username", "Unknown"))
        draw.text((x1 + 24, y + 5), f"{rank}", font=_font(16, bold=True), fill=(245, 236, 220, 255))
        draw.text((x1 + 92, y + 5), f"{dmg:,}", font=_font(16, bold=True), fill=(232, 198, 132, 255))

        icon_x = x1 + 258
        token = str(r.get("emoji", "") or "").strip()
        if token:
            icon = await fetch_discord_emoji_image(session, token, size=22, cache=cache)
            if icon is not None:
                canvas.alpha_composite(icon, (icon_x, y + 5))
                icon_x += 28
            else:
                fallback = emoji_fallback_for_token(token)
                if fallback:
                    draw.text((icon_x, y + 5), fallback, font=_font(16), fill=(236, 228, 214, 255))
                    icon_x += 24
        draw.text((icon_x, y + 5), username[:34], font=_font(16), fill=(236, 228, 214, 255))


async def draw_reward_boxes(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    session: aiohttp.ClientSession,
    rewards: list[dict],
    box: tuple[int, int, int, int],
    *,
    cache: dict[str, Any] | None = None,
) -> None:
    draw_panel(draw, box, title="Rewards", title_font=_font(24, bold=True))
    x1, y1, x2, y2 = box

    items = [r for r in (rewards or []) if isinstance(r, dict)]
    if not items:
        return

    cols = min(4, max(1, len(items)))
    gap = 12
    inner_x1 = x1 + 16
    inner_y = y1 + 56
    inner_w = (x2 - x1) - 32
    cell_w = int((inner_w - gap * (cols - 1)) / cols)
    cell_h = max(110, (y2 - inner_y - 16))

    for idx, reward in enumerate(items[:4]):
        cx = inner_x1 + idx * (cell_w + gap)
        cy = inner_y
        draw.rounded_rectangle((cx, cy, cx + cell_w, cy + cell_h), radius=12, fill=(30, 22, 36, 236), outline=(118, 100, 126, 255), width=2)

        token = str(reward.get("emoji", "") or "")
        icon = await fetch_discord_emoji_image(session, token, size=48, cache=cache)
        if icon is not None:
            canvas.alpha_composite(icon, (cx + 14, cy + 14))
        else:
            fallback = emoji_fallback_for_token(token)
            if fallback:
                draw.text((cx + 22, cy + 22), fallback, font=_font(30), fill=(238, 228, 212, 255))

        amount = int(reward.get("amount", 0) or 0)
        name = str(reward.get("name", "Reward"))
        draw.text((cx + 72, cy + 20), f"x{amount:,}", font=_font(24, bold=True), fill=(232, 200, 138, 255))
        draw.text((cx + 14, cy + 74), name[:20], font=_font(16, bold=True), fill=(234, 226, 210, 255))


def draw_footer_status(
    draw: ImageDraw.ImageDraw,
    data: dict,
    box: tuple[int, int, int, int],
) -> None:
    x1, y1, x2, y2 = box
    draw_panel(
        draw,
        box,
        radius=16,
        fill=(22, 18, 30, 240),
        outline=(118, 102, 128, 255),
        width=2,
    )

    runs_away = str(data.get("runs_away_in", "unknown"))
    fighters = int(data.get("fighters", 0) or 0)
    defeated = int(data.get("defeated", 0) or 0)
    left = f"runs away in {runs_away}   |   fighters: {fighters}   |   defeated: {defeated}"
    draw.text((x1 + 20, y1 + 20), left, font=_font(20, bold=True), fill=(236, 226, 210, 255))

    btn_w, btn_h = 186, 56
    bx = x2 - btn_w - 14
    by = y1 + int((y2 - y1 - btn_h) / 2)
    draw.rounded_rectangle((bx, by, bx + btn_w, by + btn_h), radius=14, fill=(146, 78, 70, 255), outline=(218, 168, 128, 255), width=2)
    draw.text((bx + 54, by + 14), "Engage", font=_font(28, bold=True), fill=(250, 236, 216, 255))


async def render_guild_boss_image(data: dict) -> io.BytesIO:
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow is required")

    width, height = 1700, 980
    canvas = Image.new("RGBA", (width, height), (14, 20, 34, 255))
    draw = ImageDraw.Draw(canvas)

    assets = data.get("assets", {}) if isinstance(data.get("assets", {}), dict) else {}
    bg = _load_local_image(str(assets.get("background", "") or ""))
    if bg is not None:
        resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.BICUBIC)
        bg = bg.resize((width, height), resample)
        canvas.alpha_composite(bg, (0, 0))
    else:
        for y in range(height):
            t = y / max(1, height - 1)
            r = int(12 + (30 - 12) * t)
            g = int(12 + (18 - 12) * t)
            b = int(18 + (24 - 18) * t)
            draw.line((0, y, width, y), fill=(r, g, b, 255), width=1)
        draw.rectangle((0, 0, width, 108), fill=(26, 20, 30, 255))
        for i in range(10):
            x = int((i / 9.0) * width) - 240
            draw.polygon(
                [(x, 0), (x + 200, 0), (x + 700, height), (x + 500, height)],
                fill=(72, 62, 80, 16),
            )

    cache: dict[str, Any] = {}
    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        draw_panel(
            draw,
            (20, 18, width - 20, 98),
            radius=16,
            fill=(22, 18, 28, 232),
            outline=(138, 112, 88, 255),
            width=2,
        )

        title = str(data.get("title", "A Guild Boss Appeared!"))
        draw.text((124, 42), title, font=_font(42, bold=True), fill=(244, 232, 214, 255))

        header_icon = await fetch_discord_emoji_image(
            session,
            str(data.get("header_emoji", "") or ""),
            size=74,
            cache=cache,
        )
        if header_icon is not None:
            canvas.alpha_composite(header_icon, (34, 22))
        else:
            header_fb = emoji_fallback_for_token(str(data.get("header_emoji", "") or ""))
            if header_fb:
                draw.text((44, 30), header_fb, font=_font(54, bold=True), fill=(244, 248, 255, 235))

        deco_icon = await fetch_discord_emoji_image(
            session,
            str(data.get("decor_emoji", "") or ""),
            size=48,
            cache=cache,
        )
        if deco_icon is not None:
            canvas.alpha_composite(deco_icon, (width - 84, 34))
        else:
            deco_fb = emoji_fallback_for_token(str(data.get("decor_emoji", "") or ""))
            if deco_fb:
                draw.text((width - 74, 38), deco_fb, font=_font(34, bold=True), fill=(244, 248, 255, 230))

        bosses = [b for b in (data.get("bosses", []) or []) if isinstance(b, dict)][:3]
        card_w = 530
        gap = 24
        start_x = 20
        for i, boss in enumerate(bosses):
            x1 = start_x + i * (card_w + gap)
            x2 = x1 + card_w
            await draw_boss_card(canvas, draw, session, boss, (x1, 120, x2, 610), cache=cache)

        await draw_damage_table(
            canvas,
            draw,
            session,
            [r for r in (data.get("top_damage", []) or []) if isinstance(r, dict)],
            (20, 628, 930, 888),
            cache=cache,
        )

        await draw_reward_boxes(
            canvas,
            draw,
            session,
            [r for r in (data.get("rewards", []) or []) if isinstance(r, dict)],
            (954, 628, 1680, 888),
            cache=cache,
        )

    draw_footer_status(draw, data, (20, 902, 1680, 962))

    out = io.BytesIO()
    canvas.save(out, format="PNG")
    out.seek(0)
    return out


async def render_guild_boss_discord_file(data: dict, filename: str = "guild_boss_dashboard.png") -> discord.File:
    png = await render_guild_boss_image(data)
    return discord.File(fp=png, filename=filename)
