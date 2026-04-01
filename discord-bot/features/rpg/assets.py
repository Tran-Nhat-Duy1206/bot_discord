import json
import os
from pathlib import Path

import discord


ASSETS_FILE = os.getenv("RPG_ASSETS_FILE", "data/rpg_assets.json")
ASSETS_DIR = os.getenv("RPG_ASSETS_DIR", "assets/rpg")

_ASSETS = {
    "embeds": {
        "profile": None,
        "hunt": None,
        "boss": None,
        "shop": None,
        "quest": None,
        "inventory": None,
        "leaderboard": None,
    },
    "items": {},
    "monsters": {},
}


def _safe_load() -> dict:
    if not os.path.exists(ASSETS_FILE):
        return {}
    try:
        with open(ASSETS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def reload_assets():
    data = _safe_load()
    if not isinstance(data, dict):
        return

    embeds = data.get("embeds")
    if isinstance(embeds, dict):
        _ASSETS["embeds"].update(embeds)

    items = data.get("items")
    if isinstance(items, dict):
        _ASSETS["items"].update(items)

    monsters = data.get("monsters")
    if isinstance(monsters, dict):
        _ASSETS["monsters"].update(monsters)


def _is_url(value) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def _resolve_local_file(value: str | None) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    p = Path(raw)
    if not p.is_absolute():
        p = Path(ASSETS_DIR) / raw
    if p.exists() and p.is_file():
        return p
    return None


def _apply_asset(embed: discord.Embed, value: str | None, as_image: bool, attach_name: str) -> discord.File | None:
    if _is_url(value):
        if as_image:
            embed.set_image(url=value)
        else:
            embed.set_thumbnail(url=value)
        return None

    p = _resolve_local_file(value)
    if p is None:
        return None

    ext = p.suffix.lower() or ".png"
    filename = f"{attach_name}{ext}"
    attach_url = f"attachment://{filename}"
    if as_image:
        embed.set_image(url=attach_url)
    else:
        embed.set_thumbnail(url=attach_url)
    return discord.File(str(p), filename=filename)


def apply_embed_asset(embed: discord.Embed, key: str, as_image: bool = False) -> discord.File | None:
    value = _ASSETS.get("embeds", {}).get(key)
    return _apply_asset(embed, value, as_image, f"embed_{key}")


def apply_item_asset(embed: discord.Embed, item_id: str, as_image: bool = False) -> discord.File | None:
    value = _ASSETS.get("items", {}).get(item_id)
    return _apply_asset(embed, value, as_image, f"item_{item_id}")


def apply_monster_asset(embed: discord.Embed, monster_id: str, as_image: bool = False) -> discord.File | None:
    value = _ASSETS.get("monsters", {}).get(monster_id)
    return _apply_asset(embed, value, as_image, f"monster_{monster_id}")
