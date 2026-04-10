import random
import re
import time
import logging
from collections import defaultdict, deque
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from features.emoji_registry import CURRENCY_ICON, XP_ICON, RPG_EMOJI_ALIASES, RARITY_ICONS

from language import resolve_lang, resolve_lang_ctx, tr

from .data import (
    ITEMS,
    CRAFT_RECIPES,
    SKILLS,
    CHARACTERS,
    BOSS_VARIANTS,
    RPG_BOSS_COOLDOWN,
    GACHA_COST,
    GACHA_BANNERS,
    SOFT_PITY,
    HARD_PITY,
    MYTHIC_ASCEND_LEGENDARY_SHARDS,
    get_mythic_form_for_line,
    roll_character,
    DUPLICATE_SHARD_VALUE,
)
from .db.db import (
    ensure_db_ready,
    open_db,
    get_player,
    calculate_team_power,
    get_player_characters,
    get_team,
    get_gacha_pity,
    update_gacha_pity,
    get_main_character,
    set_team_character,
    clear_team,
)

from .services.combat_service import CombatService
from .services.economy_service import EconomyService
from .services.quest_service import QuestService
from .services.player_service import PlayerService
from .services.dungeon_run_service import DungeonRunService
from .combat.equipment import equipped_profile
from .rendering import (
    convert_combat_result_to_battle_data,
    render_guild_boss_image,
    render_battle_card,
    render_dungeon_card,
    render_gacha_card,
    render_shop_card,
    render_team_card,
)
from .repositories import telemetry_repo

from .shop import ShopCategory, get_items_by_category, get_shop_categories
from .ui_theme import hp_bar, panel_embed, progress_bar, rarity_icon, role_icon, split_formation


RPG_COMMAND_RATE_USER_MAX = 12
RPG_COMMAND_RATE_USER_WINDOW = 20
RPG_COMMAND_RATE_GUILD_MAX = 120
RPG_COMMAND_RATE_GUILD_WINDOW = 20

logger = logging.getLogger("bot.rpg")

_USER_RATE_BUCKET: dict[int, deque[float]] = defaultdict(deque)
_GUILD_RATE_BUCKET: dict[int, deque[float]] = defaultdict(deque)

RPG_COMMAND_NAMES = {
    "rpg_start", "profile", "stats",
    "rpg_daily", "rpg_pay", "rpg_shop", "rpg_shop_category",
    "craft_list", "craft",
    "rpg_buy", "rpg_sell", "rpg_inventory", "rpg_equipment",
    "equip", "unequip", "rpg_skills", "rpg_skill_unlock", "rpg_skill_use",
    "rpg_use", "open", "rpg_drop", "rpg_event", "hunt", "boss",
    "dungeon", "party_hunt", "quest", "quest_claim",
    "rpg_loot", "rpg_balance_dashboard", "rpg_economy_audit",
    "rpg_season_status", "rpg_season_rollover", "rpg_jackpot", "rpg_leaderboard",
    "create_character", "gacha", "my_characters", "roster", "team", "team_stats", "ascend_mythic",
}


def _member_or_self(interaction: discord.Interaction, member: Optional[discord.Member]) -> Optional[discord.Member]:
    if member is not None:
        return member
    if isinstance(interaction.user, discord.Member):
        return interaction.user
    return None


def _item_label(item_id: str) -> str:
    item = ITEMS.get(item_id, {"name": item_id, "emoji": "📦"})
    return f"{item['emoji']} {item['name']}"


async def _lang_for_ctx(ctx: commands.Context) -> str:
    guild_locale = getattr(ctx.guild, "preferred_locale", None) if ctx.guild else None
    return await resolve_lang_ctx(ctx.author.id, guild_locale)


async def _server_only_interaction(interaction: discord.Interaction):
    lang = await resolve_lang(interaction)
    return await interaction.response.send_message(tr(lang, "common.server_only"), ephemeral=True)


async def _server_only_ctx(ctx: commands.Context):
    lang = await _lang_for_ctx(ctx)
    return await ctx.reply(tr(lang, "common.server_only"))


def _rarity_emoji(rarity: str) -> str:
    return rarity_icon(rarity)


def _to_pct(value: float) -> int:
    return int(round(max(0.0, float(value)) * 100))


def _passive_text(lifesteal: float, crit_bonus: float, damage_reduction: float) -> str:
    return f"Lifesteal +{_to_pct(lifesteal)}% • Crit +{_to_pct(crit_bonus)}% • Damage Reduction {_to_pct(damage_reduction)}%"


def _as_str_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(x) for x in value]


def _normalize_shop_category_input(category: str) -> str:
    c = str(category or "main").strip().lower()
    if c in {"blackmarket", "black_market", "black-market"}:
        return ShopCategory.BLACK_MARKET
    if c in {ShopCategory.CONSUMABLES, ShopCategory.EQUIPMENT, ShopCategory.MATERIALS, ShopCategory.BLACK_MARKET, "main"}:
        return c
    return "main"


def _shop_item_tags(item) -> str:
    tags: list[str] = []
    rarity = str(getattr(item, "rarity", "common")).lower()
    if rarity in {"epic", "legendary", "mythic"}:
        tags.append("RARE")
    if bool(getattr(item, "black_market_only", False)):
        tags.append("BLACK MARKET")
    if not tags:
        return ""
    return " • " + " • ".join(tags)


def _build_shop_main_embed(lang: str) -> discord.Embed:
    e = panel_embed(
        mode="Quartermaster Bazaar",
        title="🛒 Quartermaster Bazaar",
        description=(
            "Supply hub for consumables, gear, and rare trade materials."
            if lang == "en"
            else "Trung tâm hậu cần cho vật phẩm tiêu hao, trang bị và vật liệu hiếm."
        ),
        theme="shop",
    )
    rows = []
    for cat in get_shop_categories():
        name = str(cat.get("name", ""))
        emoji = str(cat.get("emoji", "📦"))
        desc = str(cat.get("desc", ""))
        rows.append(f"{emoji} **{name}**\n{desc}")
    e.add_field(name="📂 Market Wings", value="\n\n".join(rows), inline=False)
    e.add_field(
        name="🧭 Quick Select",
        value=(
            "Use the buttons below to switch between shop wings instantly."
            if lang == "en"
            else "Dùng các nút bên dưới để chuyển nhanh giữa các khu shop."
        ),
        inline=False,
    )
    e.add_field(
        name="⚒️ Trade Commands",
        value="`/rpg_buy <item> [amount]`\n`/rpg_sell <item> [amount] [location]`\n`/craft <recipe_id> [amount]`",
        inline=False,
    )
    return e


def _build_shop_category_embed(category: str, lang: str) -> discord.Embed:
    c = _normalize_shop_category_input(category)
    if c == "main":
        return _build_shop_main_embed(lang)

    title_map = {
        ShopCategory.CONSUMABLES: "🧪 Consumables Wing",
        ShopCategory.EQUIPMENT: "⚔️ Equipment Wing",
        ShopCategory.MATERIALS: "💎 Materials Wing",
        ShopCategory.BLACK_MARKET: "🌑 Black Market",
    }
    e = panel_embed(
        mode="Quartermaster Bazaar",
        title=title_map.get(c, "🛒 Quartermaster Bazaar"),
        description=("Available stock for your squad operations." if lang == "en" else "Kho hàng hiện có cho hoạt động đội hình."),
        theme="shop",
    )

    items = get_items_by_category(c)
    if not items:
        empty = "No stock in this wing." if lang == "en" else "Danh mục này hiện không có hàng."
        e.add_field(name="Stock", value=empty, inline=False)
        return e

    rarity_order = ("mythic", "legendary", "epic", "rare", "uncommon", "common")
    rarity_counts: dict[str, int] = {r: 0 for r in rarity_order}
    for item in items:
        rarity_counts[str(getattr(item, "rarity", "common")).lower()] = rarity_counts.get(str(getattr(item, "rarity", "common")).lower(), 0) + 1

    total_items = len(items)
    highlighted = rarity_counts.get("mythic", 0) + rarity_counts.get("legendary", 0) + rarity_counts.get("epic", 0)
    rarity_line = " | ".join(
        f"{rarity_icon(r)} {r.title()} {rarity_counts.get(r, 0)}"
        for r in rarity_order
        if rarity_counts.get(r, 0) > 0
    )

    if c == ShopCategory.BLACK_MARKET:
        display_text = (
            "Player-driven listings are rendered as RPG market cards in the attached image."
            if lang == "en"
            else "Danh sach nguoi choi dang ban duoc hien thi dang the card RPG o anh ben duoi."
        )
    else:
        display_text = (
            "Items are displayed as visual inventory cards in the attached image."
            if lang == "en"
            else "Vat pham duoc hien thi bang the inventory truc quan o anh ben duoi."
        )

    stats_text = (
        f"Total `{total_items}` • High-tier `{highlighted}`\n{rarity_line}"
        if lang == "en"
        else f"Tong `{total_items}` • Bac cao `{highlighted}`\n{rarity_line}"
    )

    e.add_field(name="Display" if lang == "en" else "Hien thi", value=display_text, inline=False)
    e.add_field(name="Stock Snapshot" if lang == "en" else "Tong quan kho", value=stats_text, inline=False)

    return e


def _shop_rarity_rank(rarity: str) -> int:
    order = {
        "mythic": 5,
        "legendary": 4,
        "epic": 3,
        "rare": 2,
        "uncommon": 1,
        "common": 0,
    }
    return order.get(str(rarity or "common").lower(), -1)


def _build_shop_main_card_payload() -> list[dict]:
    rows: list[dict] = []
    for cat in get_shop_categories():
        cid = str(cat.get("id", ""))
        rows.append(
            {
                "id": cid,
                "name": str(cat.get("name", cid)),
                "emoji": str(cat.get("emoji", "📦")),
                "desc": str(cat.get("desc", "")),
                "count": len(get_items_by_category(cid)),
            }
        )
    return rows


def _build_shop_items_card_payload(category: str) -> list[dict]:
    c = _normalize_shop_category_input(category)
    source = list(get_items_by_category(c))
    rows: list[dict] = []
    source.sort(
        key=lambda item: (
            -_shop_rarity_rank(str(getattr(item, "rarity", "common"))),
            -int(getattr(item, "buy_price", 0) or 0),
            str(getattr(item, "name", "")),
        )
    )
    for idx, item in enumerate(source[:12]):
        sell_price = int(getattr(item, "sell_price", 0) or 0)
        desc = str(getattr(item, "desc", "") or "").strip()
        rows.append(
            {
                "id": str(getattr(item, "id", "")),
                "name": str(getattr(item, "name", "")),
                "emoji": str(getattr(item, "emoji", "📦")),
                "rarity": str(getattr(item, "rarity", "common")).lower(),
                "buy_price": int(getattr(item, "buy_price", 0) or 0),
                "sell_price": sell_price,
                "black_market_sell": int(sell_price * 0.6),
                "subtitle": desc,
                "quantity": 1,
                "selected": idx == 0,
            }
        )
        if c == ShopCategory.BLACK_MARKET:
            rows[-1]["seller_name"] = str(getattr(item, "seller_name", "Player Vendor"))
            rows[-1]["stock"] = int(getattr(item, "stock", 3) or 0)
    return rows


async def _build_shop_embed_and_card(
    category: str,
    guild: discord.Guild | None,
    lang: str,
) -> tuple[discord.Embed, discord.File | None]:
    c = _normalize_shop_category_input(category)
    embed = _build_shop_category_embed(c, lang)
    if guild is None:
        return embed, None

    card_file: discord.File | None = None
    if c == "main":
        card_buffer = await render_shop_card(
            category="main",
            items=[],
            guild=guild,
            categories=_build_shop_main_card_payload(),
            lang=lang,
        )
    else:
        card_buffer = await render_shop_card(
            category=c,
            items=_build_shop_items_card_payload(c),
            guild=guild,
            categories=None,
            lang=lang,
        )

    if card_buffer is not None:
        card_file = discord.File(fp=card_buffer, filename="shop_card.png")
        embed.set_image(url="attachment://shop_card.png")
    return embed, card_file


def _build_inventory_embed(target: discord.Member, items: list[tuple[str, int]], lang: str) -> discord.Embed:
    e = panel_embed(
        mode="Supply Bag",
        title=f"🎒 {target.display_name} • Supply Bag",
        description=("Operational consumables and resources ready for deployment." if lang == "en" else "Kho vật phẩm sẵn sàng cho các đợt triển khai."),
        theme="profile",
        thumbnail_url=target.display_avatar.url,
    )
    total_amount = sum(int(a) for _, a in items)
    e.add_field(name="Inventory", value=f"Distinct **{len(items)}** • Total **{total_amount}**", inline=False)

    grouped: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for item_id, amount in items:
        rarity = str(ITEMS.get(item_id, {}).get("rarity", "common")).lower()
        grouped[rarity].append((item_id, int(amount)))

    for rarity in ("mythic", "legendary", "epic", "rare", "uncommon", "common"):
        rows = grouped.get(rarity, [])
        if not rows:
            continue
        value = "\n".join(f"{_item_label(item_id)} x{amount}" for item_id, amount in rows[:10])
        e.add_field(name=f"{rarity_icon(rarity)} {rarity.title()}", value=value, inline=False)
    return e


def _build_loadout_embed(target: discord.Member, result, lang: str, character_title: str | None = None) -> discord.Embed:
    equipped = result.equipped if isinstance(result.equipped, dict) else {}
    slot_icon = {"weapon": "⚔️", "armor": "🛡️", "accessory": "🔮"}

    e = panel_embed(
        mode="Loadout Console",
        title=f"🧰 {target.display_name} • Loadout Console",
        description=("Equipment matrix and passive resonance for your commander." if lang == "en" else "Ma trận trang bị và cộng hưởng nội tại của chỉ huy."),
        theme="team",
        thumbnail_url=target.display_avatar.url,
    )
    if character_title:
        e.add_field(name="Target Hero", value=character_title, inline=False)

    rows = []
    for slot in ("weapon", "armor", "accessory"):
        item_id = equipped.get(slot)
        label = _item_label(item_id) if item_id else "(empty)"
        rows.append(f"{slot_icon.get(slot, '📦')} **{slot.title()}**: {label}")
    e.add_field(name="Deployment Gear", value="\n".join(rows), inline=False)
    e.add_field(name="Base Bonus", value=f"ATK +{result.bonus_atk} • DEF +{result.bonus_def} • HP +{result.bonus_hp}", inline=False)
    e.add_field(name="Passive Matrix", value=_passive_text(result.lifesteal, result.crit_bonus, result.damage_reduction), inline=False)
    if result.set_bonus:
        e.add_field(name="Set Resonance", value=f"{result.set_bonus}", inline=False)
    if result.passive_skills:
        e.add_field(name="Skill Traits", value="\n".join(f"• {name}" for name in result.passive_skills), inline=False)
    return e


_QUEST_NAME_EN = {
    "team_hunt_runs": "Hunt Operations",
    "team_hunt_clears": "Full Hunt Clears",
    "team_dungeon_clears": "Dungeon Clears",
    "summon_times": "Recruitment Summons",
    "use_healer_battles": "Battles with Healer",
    "boss_wins": "Boss Victories",
    "kill_slime": "Jackpot Slime Kills",
    "open_lootbox": "Lootbox Opens",
}

_QUEST_NAME_VI = {
    "team_hunt_runs": "Lượt săn đội",
    "team_hunt_clears": "Lượt clear trọn pack",
    "team_dungeon_clears": "Lượt clear dungeon",
    "summon_times": "Lượt triệu hồi",
    "use_healer_battles": "Trận có healer",
    "boss_wins": "Lượt thắng boss",
    "kill_slime": "Số lần hạ Jackpot Slime",
    "open_lootbox": "Lượt mở lootbox",
}

_QUEST_ICON = {
    "team_hunt_runs": "⚔️",
    "team_hunt_clears": "🎯",
    "team_dungeon_clears": "🏰",
    "summon_times": "🎫",
    "use_healer_battles": ":Healer:",
    "boss_wins": "👑",
    "kill_slime": "🟢",
    "open_lootbox": "💎",
}


def _build_skills_embed(level: int, unlocked: list[str], lang: str) -> discord.Embed:
    e = panel_embed(
        mode="Skill Codex",
        title=f"🧠 Skill Codex • Lv {level}",
        description=("Review your passive and active techniques before deployment." if lang == "en" else "Xem lại kỹ năng trước khi triển khai đội hình."),
        theme="team",
    )
    groups: dict[str, list[str]] = defaultdict(list)
    for sid, skill in sorted(SKILLS.items(), key=lambda x: int(x[1].get("level_req", 1))):
        name = str(skill.get("name", sid))
        stype = str(skill.get("type", "passive")).lower()
        req = int(skill.get("level_req", 1))
        desc = str(skill.get("desc", ""))
        if sid in unlocked:
            status = "✅ Unlocked"
        elif level < req:
            status = f"🔒 Need Lv {req}"
        else:
            status = ":legends: Ready"
        groups[stype].append(f"`{sid}` • **{name}**\n{desc}\n{status}")

    e.add_field(name="Passive Techniques", value="\n\n".join(groups.get("passive", ["(none)"])[:6]), inline=False)
    e.add_field(name="Active Techniques", value="\n\n".join(groups.get("active", ["(none)"])[:6]), inline=False)
    return e


def _build_quest_board_embed(quests, owner_name: str | None = None, lang: str = "en") -> discord.Embed:
    names = _QUEST_NAME_VI if str(lang).lower().startswith("vi") else _QUEST_NAME_EN
    owner = str(owner_name or ("Bạn" if str(lang).lower().startswith("vi") else "Player"))
    is_vi = str(lang).lower().startswith("vi")

    def _hms_upper(secs: int) -> str:
        total = max(0, int(secs))
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        return f"{h}H {m}M {s}S"

    def _quest_line(q, now_ts: int) -> str:
        qid = str(getattr(q, "quest_id", ""))
        obj = str(getattr(q, "objective", ""))
        target = int(getattr(q, "target", 0) or 0)
        prog = int(getattr(q, "progress", 0) or 0)
        reset_after = int(getattr(q, "reset_after", 0) or 0)
        title = names.get(obj, obj)
        icon = _QUEST_ICON.get(obj, "📜")
        is_locked = bool(getattr(q, "is_locked", False))
        is_claimed = bool(getattr(q, "claimed", False))

        if is_locked:
            prereq = str(getattr(q, "prereq_quest_id", "") or "")
            text = (f"{title} đang bị khóa (cần `{prereq}`)." if is_vi else f"{title} is locked (need `{prereq}`).")
            mark = "⬛"
        elif is_claimed:
            text = (f"{title} đã nhận thưởng." if is_vi else f"{title} is already claimed.")
            mark = "☑️"
        elif prog >= target:
            text = (f"{title} có thể nhận ngay." if is_vi else f"{title} is ready to claim.")
            mark = "⬛"
        else:
            text = f"{title} ({prog}/{target})"
            mark = "⬛"

        if reset_after > now_ts:
            text += f" • <t:{reset_after}:R>"
        return f"{mark} {icon} {text} • `{qid}`"

    now = int(time.time())
    lines = [_quest_line(q, now) for q in quests]
    completed = sum(1 for q in quests if bool(getattr(q, "claimed", False)))
    all_done = bool(quests) and completed == len(quests)
    lines.append(
        f"{'☑️' if all_done else '⬛'} 🎉 "
        + ("Hoàn tất checklist để nhận thưởng tổng!" if is_vi else "Complete your checklist to get a reward!")
    )

    reset_targets = [
        int(getattr(q, "reset_after", 0) or 0)
        for q in quests
        if str(getattr(q, "period", "")) in {"daily", "weekly"} and int(getattr(q, "reset_after", 0) or 0) > now
    ]
    if reset_targets:
        next_reset = min(reset_targets)
        remain = max(0, next_reset - now)
        lines.append("")
        lines.append(
            (f"Resets in {_hms_upper(remain)} • <t:{next_reset}:t>" if not is_vi else f"Reset sau {_hms_upper(remain)} • <t:{next_reset}:t>")
        )

    e = panel_embed(
        mode="Mission Board",
        title=(f"{owner}'s Checklist" if not is_vi else f"Checklist của {owner}"),
        description="\n".join(lines),
        theme="team",
    )
    return e


def _build_craft_recipes_embed(lang: str) -> discord.Embed:
    e = panel_embed(
        mode="Forge Recipes",
        title="🛠️ Forge Recipes",
        description=("Craft supplies and gear components for your squad." if lang == "en" else "Ghép vật phẩm và thành phần trang bị cho đội hình."),
        theme="shop",
    )
    rows = []
    for r in CRAFT_RECIPES:
        rid = str(r.get("id", ""))
        name = str(r.get("name", rid))
        req = r.get("requires", {}) or {}
        req_txt = ", ".join(f"{_item_label(str(k))} x{int(v)}" for k, v in req.items()) if req else "(none)"
        gold = int(r.get("gold", 0))
        out = r.get("output", {}) or {}
        out_txt = ", ".join(f"{_item_label(str(k))} x{int(v)}" for k, v in out.items()) if out else "(none)"
        rows.append(f"`{rid}` • **{name}**\nNeed: {req_txt}\nCost: {gold} {CURRENCY_ICON}\nOutput: {out_txt}")
    e.add_field(name="Available Blueprints", value="\n\n".join(rows[:8]) if rows else "(none)", inline=False)
    return e


def _build_loot_codex_embed(lang: str) -> discord.Embed:
    rarity_order = ["mythic", "legendary", "epic", "rare", "uncommon", "common"]
    grouped: dict[str, list[str]] = defaultdict(list)
    for key, item in ITEMS.items():
        rarity = str(item.get("rarity", "common")).lower()
        grouped[rarity].append(f"{item.get('emoji', '📦')} {item.get('name', key)} (`{key}`)")

    e = panel_embed(
        mode="Drop Codex",
        title="🎲 Drop Codex",
        description=("Reference rarity tiers and possible operation drops." if lang == "en" else "Tra cứu độ hiếm và vật phẩm có thể rơi."),
        theme="team",
    )
    for rarity in rarity_order:
        values = grouped.get(rarity, [])
        if values:
            e.add_field(name=f"{rarity_icon(rarity)} {rarity.title()}", value="\n".join(values[:8]), inline=False)
    return e


def _dungeon_node_icon(node_type: str) -> str:
    m = {
        "combat": "⚔️",
        "elite": "🩸",
        "event": "🎲",
        "sanctuary": "⛺",
        "merchant": "🛒",
        "curse": "☠️",
        "boss_gate": "👑",
    }
    return m.get(str(node_type or ""), "❔")


def _build_dungeon_start_embed(result, lang: str) -> discord.Embed:
    data = result.entry_embed_data if isinstance(result.entry_embed_data, dict) else {}
    mods = data.get("global_modifiers", []) if isinstance(data.get("global_modifiers"), list) else []
    mod_lines = []
    for m in mods[:3]:
        mid = str(m.get("mod_id", "modifier"))
        mod_lines.append(f"• `{mid}`")
    e = panel_embed(
        mode="Dungeon Mode",
        title=tr(lang, "rpg.dungeon.entry_title"),
        description=tr(lang, "rpg.dungeon.entry_desc"),
        theme="combat",
    )
    e.add_field(name=tr(lang, "rpg.dungeon.field.run_id"), value=f"`{result.run_id}`", inline=False)
    e.add_field(name=tr(lang, "rpg.dungeon.field.difficulty"), value=f"**{str(data.get('difficulty', 'normal')).title()}**", inline=True)
    e.add_field(name=tr(lang, "rpg.dungeon.field.floors"), value=f"**1/{int(data.get('total_floors', 12))}**", inline=True)
    e.add_field(name=tr(lang, "rpg.dungeon.field.boss_family"), value=f"**{data.get('boss_family', 'unknown')}**", inline=True)
    if mod_lines:
        e.add_field(name=tr(lang, "rpg.dungeon.field.global_mods"), value="\n".join(mod_lines), inline=False)
    e.add_field(name=tr(lang, "rpg.dungeon.field.next"), value=tr(lang, "rpg.dungeon.next_hint"), inline=False)
    return e


def _build_dungeon_state_embed(state, lang: str) -> discord.Embed:
    e = panel_embed(
        mode="Dungeon Mode",
        title=tr(lang, "rpg.dungeon.status_title", floor=state.floor, total=state.total_floors),
        description=tr(lang, "rpg.dungeon.status_desc"),
        theme="team",
    )
    alive = sum(1 for u in state.units if bool(u.get("alive", False)))
    total = len(state.units)
    avg_hp = 0
    if total > 0:
        avg_hp = int(sum(int(u.get("hp", 0)) for u in state.units) / total)
    e.add_field(name=tr(lang, "rpg.dungeon.field.phase"), value=f"**{state.phase}**", inline=True)
    e.add_field(name=tr(lang, "rpg.dungeon.field.difficulty"), value=f"**{state.difficulty.title()}**", inline=True)
    e.add_field(name=tr(lang, "rpg.dungeon.field.squad"), value=tr(lang, "rpg.dungeon.squad_alive", alive=alive, total=total), inline=True)
    e.add_field(name=tr(lang, "rpg.dungeon.field.score"), value=tr(lang, "rpg.dungeon.score_line", score=state.score, risk=state.risk_score), inline=True)
    e.add_field(name=tr(lang, "rpg.dungeon.field.resources"), value=tr(lang, "rpg.dungeon.resources_line", supply=state.supply, fatigue=state.fatigue, corruption=state.corruption), inline=True)
    e.add_field(name=tr(lang, "rpg.dungeon.field.avg_hp"), value=f"{avg_hp}", inline=True)

    if state.phase == "selecting_path":
        lines = []
        for n in state.nodes:
            if bool(n.get("resolved", False)):
                continue
            nid = str(n.get("node_id", ""))
            ntype = str(n.get("node_type", "combat"))
            danger = int(n.get("danger", 1))
            lines.append(f"{_dungeon_node_icon(ntype)} `{nid}` • {ntype} • danger {danger}")
        e.add_field(name=tr(lang, "rpg.dungeon.field.paths"), value="\n".join(lines) if lines else tr(lang, "rpg.dungeon.no_nodes"), inline=False)
        e.add_field(name=tr(lang, "rpg.dungeon.field.action"), value=tr(lang, "rpg.dungeon.action.path_hint"), inline=False)
    elif state.phase == "choice":
        options = state.pending_choice.get("options", []) if isinstance(state.pending_choice, dict) else []
        lines = []
        for o in options[:3]:
            cid = str(o.get("choice_id", ""))
            title = str(o.get("title", cid))
            tradeoff = str(o.get("tradeoff", ""))
            lines.append(f"`{cid}` • **{title}**\n{tradeoff}")
        e.add_field(name=tr(lang, "rpg.dungeon.field.choice"), value="\n\n".join(lines) if lines else tr(lang, "rpg.dungeon.no_options"), inline=False)
        e.add_field(name=tr(lang, "rpg.dungeon.field.action"), value=tr(lang, "rpg.dungeon.action.choice_hint"), inline=False)
    elif state.phase == "resolving_node":
        e.add_field(name=tr(lang, "rpg.dungeon.field.action"), value=tr(lang, "rpg.dungeon.action.refresh_hint"), inline=False)
    else:
        e.add_field(name=tr(lang, "rpg.dungeon.field.action"), value=tr(lang, "rpg.dungeon.action.claim_hint"), inline=False)
    return e


def _build_dungeon_node_result_embed(result, lang: str) -> discord.Embed:
    r = result.result if isinstance(result.result, dict) else {}
    node_type = str(result.node_type or r.get("node_type", "combat"))
    theme = "victory" if bool(r.get("win", True)) else "defeat"
    e = panel_embed(
        mode="Dungeon Mode",
        title=tr(lang, "rpg.dungeon.node_title", icon=_dungeon_node_icon(node_type), node_type=node_type),
        description=tr(lang, "rpg.dungeon.node_desc"),
        theme=theme,
    )
    e.add_field(name=tr(lang, "rpg.dungeon.field.floor"), value=f"{result.floor}", inline=True)
    e.add_field(name=tr(lang, "rpg.dungeon.field.node"), value=f"`{result.node_id}`", inline=True)
    e.add_field(name=tr(lang, "rpg.dungeon.field.outcome"), value=(tr(lang, "rpg.dungeon.victory") if bool(r.get("win", True)) else tr(lang, "rpg.dungeon.defeat")), inline=True)
    if r.get("rewards"):
        rw = r.get("rewards", {})
        e.add_field(name=tr(lang, "rpg.dungeon.field.rewards"), value=f"+{int(rw.get('gold', 0))} {CURRENCY_ICON} • +{int(rw.get('xp', 0))} {XP_ICON}", inline=False)
    if r.get("delta"):
        e.add_field(name=tr(lang, "rpg.dungeon.field.delta"), value=str(r.get("delta")), inline=False)
    if r.get("event"):
        e.add_field(name=tr(lang, "rpg.dungeon.field.event"), value=str(r.get("event")), inline=False)
    e.add_field(name=tr(lang, "rpg.dungeon.field.next_phase"), value=f"**{result.next_phase}**", inline=False)
    return e


def _build_dungeon_finish_embed(result, lang: str) -> discord.Embed:
    rewards = result.rewards if isinstance(result.rewards, dict) else {}
    e = panel_embed(
        mode="Dungeon Mode",
        title=tr(lang, "rpg.dungeon.finish_title", status=str(result.status).title()),
        description=tr(lang, "rpg.dungeon.finish_desc"),
        theme="victory" if str(result.status) in {"completed", "retreated"} else "defeat",
    )
    e.add_field(name=tr(lang, "rpg.dungeon.field.run_id"), value=f"`{result.run_id}`", inline=False)
    e.add_field(name=tr(lang, "rpg.dungeon.field.score"), value=f"{result.score}", inline=True)
    e.add_field(name=tr(lang, "rpg.dungeon.field.rank_points"), value=f"+{result.rank_points}", inline=True)
    e.add_field(name=tr(lang, "rpg.dungeon.field.status"), value=f"{str(result.status).title()}", inline=True)
    e.add_field(name=tr(lang, "rpg.dungeon.field.gold_xp"), value=f"+{int(rewards.get('gold', 0))} {CURRENCY_ICON} • +{int(rewards.get('xp', 0))} {XP_ICON}", inline=False)
    items = rewards.get("items", {}) if isinstance(rewards.get("items"), dict) else {}
    if items:
        e.add_field(name=tr(lang, "rpg.dungeon.field.drops"), value=", ".join(f"{_item_label(k)} x{v}" for k, v in items.items()), inline=False)
    shards = rewards.get("shards", {}) if isinstance(rewards.get("shards"), dict) else {}
    if shards:
        e.add_field(name=tr(lang, "rpg.dungeon.field.shards"), value=", ".join(f"{k} x{v}" for k, v in shards.items()), inline=False)
    return e


def _dungeon_units_for_card(units: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for u in (units or [])[:5]:
        if not isinstance(u, dict):
            continue
        cid = str(u.get("character_id", "") or "")
        meta = CHARACTERS.get(cid, {})
        name = str(meta.get("name", cid or "Unit"))
        form = str(meta.get("form", ""))
        display_name = f"{name} [{form}]" if form else name
        rows.append(
            {
                "name": display_name,
                "emoji": str(meta.get("emoji", "") or ""),
                "hp": int(u.get("hp", 0) or 0),
                "max_hp": max(1, int(u.get("max_hp", 1) or 1)),
                "alive": bool(u.get("alive", False)),
            }
        )
    return rows


def _dungeon_reward_lines(rewards: dict, lang: str) -> list[str]:
    out: list[str] = []
    rw = rewards if isinstance(rewards, dict) else {}
    gold = int(rw.get("gold", 0) or 0)
    xp = int(rw.get("xp", 0) or 0)
    rank = int(rw.get("rank_points", 0) or 0)
    if gold > 0 or xp > 0:
        out.append(f"+{gold} {CURRENCY_ICON}  +{xp} {XP_ICON}")
    if rank > 0:
        out.append(f"+{rank} rank points")

    items = rw.get("items", {}) if isinstance(rw.get("items", {}), dict) else {}
    for item_id, amount in list(items.items())[:4]:
        if int(amount) <= 0:
            continue
        item = ITEMS.get(str(item_id), {})
        out.append(f"{item.get('emoji', '📦')} {item.get('name', item_id)} x{int(amount)}")

    shards = rw.get("shards", {}) if isinstance(rw.get("shards", {}), dict) else {}
    for shard_id, amount in list(shards.items())[:3]:
        if int(amount) <= 0:
            continue
        out.append(f"🧩 {shard_id} x{int(amount)}")
    return out


def _dungeon_start_card_payload(result, state, lang: str) -> dict:
    data = result.entry_embed_data if isinstance(getattr(result, "entry_embed_data", {}), dict) else {}
    mods = data.get("global_modifiers", []) if isinstance(data.get("global_modifiers", []), list) else []
    detail_lines = [
        f"Difficulty: {str(data.get('difficulty', 'normal')).title()}",
        f"Floors: 1/{int(data.get('total_floors', 12) or 12)}",
        f"Boss family: {str(data.get('boss_family', 'unknown'))}",
    ]
    for m in mods[:3]:
        detail_lines.append(f"Global mod: {str(m.get('mod_id', 'modifier'))}")
    detail_lines.append("Next: Choose a path to begin.")

    units = _dungeon_units_for_card(getattr(state, "units", []) if state is not None else [])
    return {
        "mode": "start",
        "title": tr(lang, "rpg.dungeon.entry_title"),
        "subtitle": tr(lang, "rpg.dungeon.entry_desc"),
        "run_id": str(getattr(result, "run_id", "")),
        "difficulty": str(data.get("difficulty", "normal")),
        "floor": 1,
        "total_floors": int(data.get("total_floors", 12) or 12),
        "phase": "selecting_path",
        "boss_family": str(data.get("boss_family", "unknown")),
        "units": units,
        "detail_lines": detail_lines,
    }


def _dungeon_state_card_payload(state, lang: str) -> dict:
    detail_lines: list[str] = []
    phase = str(getattr(state, "phase", ""))
    if phase == "selecting_path":
        unresolved = [n for n in (getattr(state, "nodes", []) or []) if isinstance(n, dict) and not bool(n.get("resolved", False))]
        for n in unresolved[:6]:
            nid = str(n.get("node_id", ""))
            ntype = str(n.get("node_type", "combat"))
            danger = int(n.get("danger", 1) or 1)
            detail_lines.append(f"{_dungeon_node_icon(ntype)} {nid} | {ntype} | danger {danger}")
        if not detail_lines:
            detail_lines.append("No available nodes.")
    elif phase == "choice":
        options = getattr(state, "pending_choice", {}).get("options", []) if isinstance(getattr(state, "pending_choice", {}), dict) else []
        for o in options[:4]:
            cid = str(o.get("choice_id", ""))
            title = str(o.get("title", cid))
            tradeoff = str(o.get("tradeoff", ""))
            detail_lines.append(f"{cid}: {title}")
            if tradeoff:
                detail_lines.append(f"  {tradeoff}")
        if not detail_lines:
            detail_lines.append("No strategic options.")
    elif phase == "resolving_node":
        detail_lines.append("Resolving current node. Refresh for outcome.")
    elif phase == "claimable":
        detail_lines.append("Run is claimable. Use claim to collect rewards.")
    else:
        detail_lines.append("Review run status and continue operation.")

    return {
        "mode": "status",
        "title": tr(lang, "rpg.dungeon.status_title", floor=getattr(state, "floor", 1), total=getattr(state, "total_floors", 12)),
        "subtitle": tr(lang, "rpg.dungeon.status_desc"),
        "run_id": str(getattr(state, "run_id", "")),
        "difficulty": str(getattr(state, "difficulty", "normal")),
        "floor": int(getattr(state, "floor", 1) or 1),
        "total_floors": int(getattr(state, "total_floors", 12) or 12),
        "phase": phase,
        "score": int(getattr(state, "score", 0) or 0),
        "risk_score": int(getattr(state, "risk_score", 0) or 0),
        "supply": int(getattr(state, "supply", 0) or 0),
        "fatigue": int(getattr(state, "fatigue", 0) or 0),
        "corruption": int(getattr(state, "corruption", 0) or 0),
        "units": _dungeon_units_for_card(getattr(state, "units", [])),
        "detail_lines": detail_lines,
    }


def _dungeon_node_card_payload(result, state, lang: str) -> dict:
    r = result.result if isinstance(getattr(result, "result", {}), dict) else {}
    node_type = str(getattr(result, "node_type", "") or r.get("node_type", "combat"))
    won = bool(r.get("win", True))

    detail_lines = [
        f"Node: {str(getattr(result, 'node_id', ''))} ({node_type})",
        f"Outcome: {'Victory' if won else 'Defeat'}",
        f"Next phase: {str(getattr(result, 'next_phase', ''))}",
    ]
    casualties = int(r.get("casualties", 0) or 0)
    if casualties > 0:
        detail_lines.append(f"Casualties: {casualties}")
    if r.get("event"):
        detail_lines.append(f"Event: {str(r.get('event'))}")
    if r.get("delta"):
        detail_lines.append(f"Delta: {str(r.get('delta'))}")

    reward_lines = _dungeon_reward_lines(r.get("rewards", {}) if isinstance(r.get("rewards", {}), dict) else {}, lang)
    detail_lines.extend(reward_lines[:7])

    state_units = _dungeon_units_for_card(getattr(state, "units", [])) if state is not None else []
    return {
        "mode": "node",
        "title": tr(lang, "rpg.dungeon.node_title", icon=_dungeon_node_icon(node_type), node_type=node_type),
        "subtitle": tr(lang, "rpg.dungeon.node_desc"),
        "run_id": str(getattr(result, "run_id", "")),
        "difficulty": str(getattr(state, "difficulty", "normal")) if state is not None else "normal",
        "floor": int(getattr(result, "floor", 1) or 1),
        "total_floors": int(getattr(state, "total_floors", 12) or 12) if state is not None else 12,
        "phase": str(getattr(result, "next_phase", "")),
        "win": won,
        "score": int(getattr(state, "score", 0) or 0) if state is not None else 0,
        "risk_score": int(getattr(state, "risk_score", 0) or 0) if state is not None else 0,
        "supply": int(getattr(state, "supply", 0) or 0) if state is not None else 0,
        "fatigue": int(getattr(state, "fatigue", 0) or 0) if state is not None else 0,
        "corruption": int(getattr(state, "corruption", 0) or 0) if state is not None else 0,
        "units": state_units,
        "detail_lines": detail_lines,
    }


def _dungeon_choice_card_payload(result, state, lang: str) -> dict:
    rr = result.result if isinstance(getattr(result, "result", {}), dict) else {}
    effect = rr.get("effect", {}) if isinstance(rr.get("effect", {}), dict) else {}
    detail_lines = [
        f"Choice: {str(getattr(result, 'choice_id', ''))}",
        f"Title: {str(rr.get('title', 'Strategic Choice'))}",
    ]
    for k, v in list(effect.items())[:6]:
        detail_lines.append(f"{k}: {v}")
    if rr.get("ambush"):
        detail_lines.append("Ambush triggered during scavenge.")
    if rr.get("removed_curse"):
        detail_lines.append(f"Removed curse: {str(rr.get('removed_curse'))}")

    return {
        "mode": "choice",
        "title": tr(lang, "rpg.dungeon.choice_applied_title"),
        "subtitle": tr(lang, "rpg.dungeon.choice_applied_desc", choice_id=getattr(result, "choice_id", "")),
        "run_id": str(getattr(result, "run_id", "")),
        "difficulty": str(getattr(state, "difficulty", "normal")) if state is not None else "normal",
        "floor": int(getattr(state, "floor", 1) or 1) if state is not None else 1,
        "total_floors": int(getattr(state, "total_floors", 12) or 12) if state is not None else 12,
        "phase": str(getattr(result, "next_phase", "")),
        "score": int(getattr(state, "score", 0) or 0) if state is not None else 0,
        "risk_score": int(getattr(state, "risk_score", 0) or 0) if state is not None else 0,
        "supply": int(getattr(state, "supply", 0) or 0) if state is not None else 0,
        "fatigue": int(getattr(state, "fatigue", 0) or 0) if state is not None else 0,
        "corruption": int(getattr(state, "corruption", 0) or 0) if state is not None else 0,
        "units": _dungeon_units_for_card(getattr(state, "units", [])) if state is not None else [],
        "detail_lines": detail_lines,
    }


def _dungeon_finish_card_payload(result, lang: str) -> dict:
    rewards = result.rewards if isinstance(getattr(result, "rewards", {}), dict) else {}
    detail_lines = [
        f"Status: {str(getattr(result, 'status', 'completed')).title()}",
        f"Score: {int(getattr(result, 'score', 0) or 0)}",
        f"Rank points: +{int(getattr(result, 'rank_points', 0) or 0)}",
    ]
    detail_lines.extend(_dungeon_reward_lines(rewards, lang)[:10])
    return {
        "mode": "finish",
        "title": tr(lang, "rpg.dungeon.finish_title", status=str(getattr(result, "status", "completed")).title()),
        "subtitle": tr(lang, "rpg.dungeon.finish_desc"),
        "run_id": str(getattr(result, "run_id", "")),
        "difficulty": "-",
        "floor": 0,
        "total_floors": 0,
        "phase": "claimable",
        "status": str(getattr(result, "status", "completed")),
        "score": int(getattr(result, "score", 0) or 0),
        "risk_score": 0,
        "supply": 0,
        "fatigue": 0,
        "corruption": 0,
        "units": [],
        "detail_lines": detail_lines,
    }


async def _attach_dungeon_card(
    embed: discord.Embed,
    payload: dict,
    guild: discord.Guild | None,
    lang: str,
) -> discord.File | None:
    if guild is None:
        return None
    card_buffer = await render_dungeon_card(payload, guild, lang=lang)
    if card_buffer is None:
        return None
    card_file = discord.File(fp=card_buffer, filename="dungeon_card.png")
    embed.set_image(url="attachment://dungeon_card.png")
    return card_file


async def _dungeon_status_with_pending_resolution(guild_id: int, user_id: int, lang: str):
    state = await DungeonRunService.get_state(guild_id, user_id, lang=lang)
    resolved_embed = None
    if state.ok and str(state.phase) == "resolving_node":
        resolved = await DungeonRunService.resolve_current_node(guild_id, user_id, lang=lang)
        if resolved.ok:
            resolved_embed = _build_dungeon_node_result_embed(resolved, lang)
            state = await DungeonRunService.get_state(guild_id, user_id, lang=lang)
    return state, resolved_embed


def _rate_check(bucket: dict[int, deque[float]], key: int, now_ts: float, window: int, max_hits: int) -> float:
    q = bucket[key]
    threshold = now_ts - float(window)
    while q and q[0] <= threshold:
        q.popleft()
    if len(q) >= max_hits:
        return max(0.1, float(window) - (now_ts - q[0]))
    q.append(now_ts)
    return 0.0


RPG_STARTED_COMMANDS = {
    "hunt", "boss", "dungeon", "party_hunt",
    "rpg_daily", "rpg_pay", "rpg_shop", "rpg_buy", "rpg_sell",
    "rpg_inventory", "rpg_equipment", "equip", "unequip",
    "rpg_skills", "rpg_skill_unlock", "rpg_skill_use",
    "rpg_use", "open", "rpg_drop", "craft",
    "quest", "quest_claim", "profile", "stats",
    "create_character", "gacha", "my_characters", "roster", "team", "team_stats", "ascend_mythic",
}


def _normalize_gender_suffix(gender: str) -> str:
    g = str(gender or "").strip().lower()
    if g in {"male", "m", "nam"}:
        return "m"
    if g in {"female", "f", "nu"}:
        return "f"
    return ""


def normalize_role(role: str) -> str:
    r = str(role or "").strip().lower()
    if r in {"sp", "support"}:
        return "support"
    return r


STARTER_BY_ROLE = {
    "tank": "geld_orc_lord",
    "dps": "benimaru_ogre",
    "healer": "shuna_ogress",
    "support": "rimuru_slime",
}


def _hp_bar(current: int, maximum: int, width: int = 14) -> str:
    maximum = max(1, int(maximum))
    current = max(0, min(int(current), maximum))
    filled = int(round((current / maximum) * width))
    filled = max(0, min(width, filled))
    return "[" + ("#" * filled) + ("-" * (width - filled)) + "]"


def _meter_bar(current: int, maximum: int, width: int = 12) -> str:
    maximum = max(1, int(maximum))
    current = max(0, min(int(current), maximum))
    filled = int(round((current / maximum) * width))
    filled = max(0, min(width, filled))
    return ("█" * filled) + ("░" * (width - filled))


def _rank_from_level(level: int) -> str:
    if level >= 80:
        return "SS"
    if level >= 65:
        return "S"
    if level >= 50:
        return "A"
    if level >= 36:
        return "B"
    if level >= 24:
        return "C"
    if level >= 14:
        return "D"
    if level >= 7:
        return "E"
    return "F"


def _short_role(role: str) -> str:
    r = normalize_role(role)
    return {
        "tank": "TNK",
        "dps": "DPS",
        "healer": "HLR",
        "support": "SUP",
    }.get(r, r[:3].upper() if r else "N/A")


async def _team_snapshot_lines(guild_id: int, user_id: int) -> list[str]:
    async with open_db() as conn:
        main = await get_main_character(conn, guild_id, user_id)
        heroes = await get_team(conn, guild_id, user_id)

    lines: list[str] = []
    if main:
        lines.append(f"M  {main[7][:12]:12} Lv{int(main[3]):>2} *{int(main[5])} {_short_role(str(main[9]))}")
    for row in heroes[:4]:
        lines.append(f"H{int(row[0])} {str(row[2])[:12]:12} Lv{int(row[10]):>2} *{int(row[11])} {_short_role(str(row[4]))}")
    return lines[:5]


async def _profile_lore_meta(guild_id: int, user_id: int) -> dict:
    async with open_db() as conn:
        main = await get_main_character(conn, guild_id, user_id)
        team = await get_team(conn, guild_id, user_id)
        async with conn.execute(
            "SELECT progress, target FROM quests WHERE guild_id = ? AND user_id = ? AND objective = ? ORDER BY target DESC LIMIT 1",
            (guild_id, user_id, "team_hunt_runs"),
        ) as cur:
            q_row = await cur.fetchone()

    members: list[tuple[str, str, int, int, int, int, int]] = []
    team_members: list[dict] = []
    if main:
        main_form = str(CHARACTERS.get(str(main[1]), {}).get("form", "Base"))
        members.append(
            (
                str(main[7]),
                normalize_role(str(main[9])),
                int(main[10]),
                int(main[11]),
                int(main[12]),
                int(main[3]),
                int(main[5]),
            )
        )
        team_members.append(
            {
                "slot": 0,
                "is_main": True,
                "character_id": str(main[1]),
                "name": str(main[7]),
                "form": main_form,
                "rarity": str(main[8]),
                "role": str(main[9]),
                "level": int(main[3]),
                "star": int(main[5]),
                "hp": int(main[10]),
                "attack": int(main[11]),
                "defense": int(main[12]),
                "speed": int(main[13]),
                "passive_skill": str(main[14] or ""),
            }
        )
    for row in team[:4]:
        cid = str(row[1])
        form = str(CHARACTERS.get(cid, {}).get("form", "Base"))
        members.append((str(row[2]), normalize_role(str(row[4])), int(row[5]), int(row[6]), int(row[7]), int(row[10]), int(row[11])))
        team_members.append(
            {
                "slot": int(row[0]),
                "is_main": False,
                "character_id": cid,
                "name": str(row[2]),
                "form": form,
                "rarity": str(row[3]),
                "role": str(row[4]),
                "level": int(row[10]),
                "star": int(row[11]),
                "hp": int(row[5]),
                "attack": int(row[6]),
                "defense": int(row[7]),
                "speed": int(row[8]),
                "passive_skill": str(row[9] or ""),
            }
        )

    role_count: dict[str, int] = defaultdict(int)
    for _, role, *_ in members:
        role_count[role] += 1

    team_hp = sum(m[2] for m in members)
    team_atk = sum(m[3] for m in members)
    team_def = sum(m[4] for m in members)
    team_power = int(sum(calculate_team_power(m[2], m[3], m[4], m[5], m[6]) for m in members))
    role_line = " • ".join(f"{k}:{v}" for k, v in role_count.items()) or "n/a"
    team_preview = [f"• {name[:18]} ({_short_role(role)})" for name, role, *_ in members[:5]]

    hunt_progress = int(q_row[0]) if q_row else 0
    hunt_target = int(q_row[1]) if q_row else 5

    return {
        "team_size": len(members),
        "role_line": role_line,
        "team_hp": team_hp,
        "team_atk": team_atk,
        "team_def": team_def,
        "team_power": team_power,
        "team_preview": team_preview,
        "captain": str(main[7]) if main else "None",
        "hunt_progress": max(0, hunt_progress),
        "hunt_target": max(1, hunt_target),
        "team_members": team_members,
    }


async def _enrich_team_members_for_card(guild_id: int, user_id: int, team_members: list[dict]) -> list[dict]:
    if not team_members:
        return []

    enriched: list[dict] = []
    async with open_db() as conn:
        for member in team_members[:5]:
            m = dict(member)
            cid = str(m.get("character_id", "") or "")
            char_meta = CHARACTERS.get(cid, {})
            m.setdefault("emoji", str(char_meta.get("emoji", "") or ""))
            eq_profile = await equipped_profile(
                conn,
                guild_id,
                user_id,
                character_id=(cid or None),
                fallback_legacy=bool(m.get("is_main", False)),
            )
            m["equipment"] = dict(eq_profile.get("equipped", {}))
            enriched.append(m)
    return enriched


async def _try_ascend_mythic(conn, guild_id: int, user_id: int, legendary_id: str) -> str:
    c = CHARACTERS.get(str(legendary_id), {})
    if str(c.get("rarity", "")).lower() != "legendary":
        return ""

    line = str(c.get("evolution_line", ""))
    if not line:
        return ""
    mythic_id = get_mythic_form_for_line(line)
    if not mythic_id:
        return ""

    async with conn.execute(
        "SELECT 1 FROM player_characters WHERE guild_id = ? AND user_id = ? AND character_id = ?",
        (guild_id, user_id, mythic_id),
    ) as cur:
        has_mythic = await cur.fetchone()
    if has_mythic:
        return ""

    async with conn.execute(
        "SELECT shard_count FROM player_characters WHERE guild_id = ? AND user_id = ? AND character_id = ?",
        (guild_id, user_id, legendary_id),
    ) as cur:
        row = await cur.fetchone()
    shards = int(row[0]) if row else 0
    if shards < MYTHIC_ASCEND_LEGENDARY_SHARDS:
        return ""

    await conn.execute(
        "UPDATE player_characters SET shard_count = shard_count - ? WHERE guild_id = ? AND user_id = ? AND character_id = ?",
        (MYTHIC_ASCEND_LEGENDARY_SHARDS, guild_id, user_id, legendary_id),
    )
    await conn.execute(
        """
        INSERT OR IGNORE INTO player_characters(guild_id, user_id, character_id, is_main, level, exp, star, shard_count, obtained_at)
        VALUES (?, ?, ?, 0, 1, 0, 1, 0, ?)
        """,
        (guild_id, user_id, mythic_id, int(time.time())),
    )
    return mythic_id


def _legendary_ascend_status(character_id: str, shard_count: int, owned_ids: set[str]) -> str:
    c = CHARACTERS.get(str(character_id), {})
    if str(c.get("rarity", "")).lower() != "legendary":
        return ""
    line = str(c.get("evolution_line", ""))
    mythic_id = get_mythic_form_for_line(line)
    if not mythic_id:
        return ""
    if mythic_id in owned_ids:
        return " | ascended"
    return f" | ascend {int(shard_count)}/{MYTHIC_ASCEND_LEGENDARY_SHARDS}"


def _build_profile_embed(target: discord.Member, result, lore: dict, lang: str = "en") -> discord.Embed:
    eff_hp = min(result.max_hp, result.hp)
    eff_max_hp = result.max_hp
    hp_meter = hp_bar(eff_hp, eff_max_hp, 12)
    xp_meter = progress_bar(result.xp, result.xp_need, 12)
    team_hp = int(lore.get("team_hp", 0))
    team_atk = int(lore.get("team_atk", 0))
    team_def = int(lore.get("team_def", 0))
    team_power = int(lore.get("team_power", 0))
    team_size = int(lore.get("team_size", 0))
    role_line = str(lore.get("role_line", "n/a"))
    team_members = lore.get("team_members", []) if isinstance(lore.get("team_members"), list) else []
    rank = _rank_from_level(result.level)

    equip_text = []
    if isinstance(result.equipped, dict):
        for slot in ("weapon", "armor", "accessory"):
            item_id = result.equipped.get(slot)
            slot_name = "Relic" if slot == "accessory" else slot.title()
            equip_text.append(f"{slot_name:<9} {(_item_label(item_id) if item_id else 'None')}")
    else:
        equip_text.append("(no equipment data)")

    e = panel_embed(
        mode="Commander Profile",
        title=f"✠ {target.display_name} • Squad Command Panel",
        description="Command your captain, tune your lineup, and prepare your squad for the next operation.",
        theme="profile",
        thumbnail_url=target.display_avatar.url,
    )
    e.add_field(
        name="🜲 Command Core",
        value=(
            f"Commander Rank: **{rank}**\n"
            f"Captain: **{lore.get('captain', 'None')}**\n"
            f"Squad Size: **{team_size}/5**\n"
            f"Role Matrix: **{role_line}**"
        ),
        inline=False,
    )
    e.add_field(
        name="📈 Progress",
        value=(
            f"Level: **{result.level}**\n"
            f"👑 Crowns: **{result.gold}**\n"
            f"XP: **{result.xp}/{result.xp_need}**\n`{xp_meter}`"
        ),
        inline=True,
    )
    e.add_field(name="🩸 HP Status", value=f"**{eff_hp}/{eff_max_hp}**\n`{hp_meter}`", inline=True)
    front, back = split_formation(team_members)
    no_team_text = "Không có đội hình" if lang == "vi" else "No active formation"
    e.add_field(name="🛡️ Frontline", value="\n".join(front) if front else no_team_text, inline=True)
    e.add_field(name="🎯 Backline", value="\n".join(back) if back else no_team_text, inline=True)
    e.add_field(name="⚔️ Squad Metrics", value=f"Power **{team_power}**\nMight **{team_atk}**\nGuard **{team_def}**\nVitality **{team_hp}**", inline=True)
    e.add_field(name="🧰 Loadout", value="\n".join(equip_text), inline=False)
    if result.set_bonus:
        e.add_field(name="🔮 Set Resonance", value=f"{result.set_bonus}", inline=False)
    if result.passive_skills:
        e.add_field(name="🕯 Passive Traits", value="\n".join(f"• {name}" for name in result.passive_skills), inline=False)
    return e


def _build_formation_analysis_embed(target: discord.Member, result, lore: dict, lang: str = "en") -> discord.Embed:
    team_power = int(lore.get("team_power", 0))
    team_members = lore.get("team_members", []) if isinstance(lore.get("team_members"), list) else []
    team_size = int(lore.get("team_size", 0))
    team_hp = int(lore.get("team_hp", 0))
    team_atk = int(lore.get("team_atk", 0))
    team_def = int(lore.get("team_def", 0))
    avg_level = int(sum(int(m.get("level", 1) or 1) for m in team_members) / max(1, len(team_members)))
    role_count: dict[str, int] = defaultdict(int)
    for m in team_members:
        role_count[normalize_role(str(m.get("role", "")))] += 1
    role_line = " • ".join(f"{k}:{v}" for k, v in role_count.items()) or "n/a"

    front, back = split_formation(team_members)
    no_team_text = "Không có đội hình" if lang == "vi" else "No active formation"

    e = panel_embed(
        mode="Formation Analysis",
        title=f"🧭 {target.display_name} • Formation Analysis",
        description="Tactical readout of your current squad deployment and combat readiness.",
        theme="team",
        thumbnail_url=target.display_avatar.url,
    )
    e.add_field(name="👑 Captain", value=f"**{lore.get('captain', 'None')}**", inline=True)
    e.add_field(name="💪 Squad Power", value=f"**{team_power}**", inline=True)
    e.add_field(name="🧱 Squad Size", value=f"**{team_size}/5**", inline=True)
    e.add_field(name="🛡️ Frontline", value="\n".join(front) if front else no_team_text, inline=True)
    e.add_field(name="🎯 Backline", value="\n".join(back) if back else no_team_text, inline=True)
    e.add_field(name="🧩 Role Balance", value=role_line, inline=True)
    e.add_field(name="📊 Core Stats", value=f"Avg Lv **{avg_level}**\nMight **{team_atk}**\nGuard **{team_def}**\nVitality **{team_hp}**", inline=False)
    return e


def _build_member_detail_embed(member_data: dict, owner_name: str, lang: str = "en") -> discord.Embed:
    lang = "vi" if str(lang).lower().startswith("vi") else "en"
    is_main = bool(member_data.get("is_main"))
    slot = int(member_data.get("slot", 0) or 0)
    role = str(member_data.get("role", "unknown")).lower()
    rarity = str(member_data.get("rarity", "common")).lower()
    cid = str(member_data.get("character_id", ""))
    char_meta = CHARACTERS.get(cid, {})
    has_mythic_path = bool(get_mythic_form_for_line(str(char_meta.get("evolution_line", ""))))

    title = f"{rarity_icon(rarity)} {member_data.get('name', 'Unknown')} • Hero Card"
    desc = "Captain profile" if lang == "en" else "Hồ sơ Captain"
    if not is_main:
        desc = f"Hero slot {slot}" if lang == "en" else f"Ô đội hình {slot}"
    e = panel_embed(
        mode="Hero Inspect",
        title=title,
        description=desc,
        theme="team",
    )
    e.add_field(name="Identity", value=f"**{member_data.get('name', 'Unknown')}**\n{member_data.get('form', 'Base')}", inline=True)
    e.add_field(name="Rarity", value=f"{rarity_icon(rarity)} **{rarity.title()}**", inline=True)
    e.add_field(name="Role", value=f"{role_icon(role)} **{role.title()}**", inline=True)
    e.add_field(name="Level", value=f"**{int(member_data.get('level', 1) or 1)}**", inline=True)
    e.add_field(name="Star", value=f"**{int(member_data.get('star', 1) or 1)}**", inline=True)
    tags = []
    if is_main:
        tags.append("Captain")
    if rarity == "legendary":
        tags.append("Legendary")
    if rarity == "mythic":
        tags.append("Mythic")
    elif has_mythic_path and rarity in {"legendary", "epic"}:
        tags.append("Mythic Ready")
    if tags:
        e.add_field(name="Tags", value=" • ".join(tags), inline=True)
    e.add_field(name="HP", value=f"**{int(member_data.get('hp', 0) or 0)}**", inline=True)
    e.add_field(name="ATK", value=f"**{int(member_data.get('attack', 0) or 0)}**", inline=True)
    e.add_field(name="DEF", value=f"**{int(member_data.get('defense', 0) or 0)}**", inline=True)
    e.add_field(name="SPD", value=f"**{int(member_data.get('speed', 0) or 0)}**", inline=True)
    passive = str(member_data.get("passive_skill", "") or "")
    e.add_field(name="Passive Skill", value=passive if passive else "-", inline=False)
    e.set_footer(text=f"Squad System • Hero Inspect • {owner_name}")
    return e


async def _check_player_registered(interaction: discord.Interaction) -> bool:
    if interaction.guild is None:
        lang = await resolve_lang(interaction)
        await interaction.response.send_message(tr(lang, "common.server_only"), ephemeral=True)
        return False
    
    cmd = interaction.command
    cmd_name = str(getattr(cmd, "name", "")).strip().lower()
    if cmd_name not in RPG_STARTED_COMMANDS:
        return True
    
    await ensure_db_ready()
    async with open_db() as conn:
        async with conn.execute(
            "SELECT 1 FROM players WHERE guild_id = ? AND user_id = ?",
            (interaction.guild.id, interaction.user.id),
        ) as cur:
            row = await cur.fetchone()
    
    if not row:
        lang = await resolve_lang(interaction)
        await interaction.response.send_message(
            tr(lang, "rpg.not_started"),
            ephemeral=True,
        )
        return False
    return True


class CombatDetailView(discord.ui.View):
    def __init__(self, combat_log: str, lang: str = "en", timeout: float = 180.0):
        super().__init__(timeout=timeout)
        self.combat_log = combat_log
        self.lang = "vi" if str(lang).lower().startswith("vi") else "en"
        self.message: Optional[discord.Message] = None
        self.show_detail.label = "📜 Battle Replay" if self.lang == "en" else "📜 Phát lại trận"
        
    @discord.ui.button(label="detail", style=discord.ButtonStyle.secondary)
    async def show_detail(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = panel_embed(
            mode="Combat Replay",
            title="📜 Battle Replay" if self.lang == "en" else "📜 Nhật ký giao chiến",
            description=self.combat_log[:4000],
            theme="combat",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    async def on_timeout(self):
        for item in self.children:
            if hasattr(item, 'disabled'):
                item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except:
                pass


class BossCombatView(CombatDetailView):
    def __init__(self, guild_id: int, owner_user_id: int, combat_log: str, lang: str = "en", timeout: float = 180.0):
        super().__init__(combat_log=combat_log, lang=lang, timeout=timeout)
        self.guild_id = int(guild_id)
        self.owner_user_id = int(owner_user_id)
        self.fight_again.label = "⚔️ Engage" if self.lang == "en" else "⚔️ Vào trận"

    @discord.ui.button(label="fight", style=discord.ButtonStyle.primary)
    async def fight_again(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None:
            lang = await resolve_lang(interaction)
            return await interaction.response.send_message(tr(lang, "common.server_only"), ephemeral=True)

        lang = await resolve_lang(interaction)
        await interaction.response.defer()
        embed, view, err, card_file = await handle_boss(
            interaction.guild.id,
            interaction.user.id,
            interaction.user.display_name,
            guild=interaction.guild,
            lang=lang,
        )
        if err:
            return await _rpg_followup_send(interaction, err, ephemeral=True)

        if card_file is not None:
            sent = await _rpg_followup_send(interaction, embed=embed, view=view, file=card_file, wait=True)
        else:
            sent = await _rpg_followup_send(interaction, embed=embed, view=view, wait=True)
        if view is not None:
            view.message = sent


class TeamMemberDetailButton(discord.ui.Button):
    def __init__(self, member_data: dict, owner_name: str, lang: str = "en"):
        self.member_data = member_data
        self.owner_name = owner_name
        self.lang = "vi" if str(lang).lower().startswith("vi") else "en"
        is_main = bool(member_data.get("is_main"))
        role = str(member_data.get("role", "")).lower()
        name = str(member_data.get("name", "Hero")).strip() or "Hero"
        icon = role_icon(role)
        if is_main:
            label = (f"👑 {name[:20]}") if self.lang == "en" else (f"👑 {name[:20]}")
        else:
            label = f"{icon} {name[:20]}"
        slot = int(member_data.get("slot", 0) or 0)
        cid = str(member_data.get("character_id", "hero") or "hero").strip().lower()[:24]
        main_flag = "m" if is_main else "s"
        custom_id = f"rpg:hero_btn:{main_flag}:{slot}:{cid}"[:100]
        super().__init__(label=label[:80], style=discord.ButtonStyle.secondary, custom_id=custom_id)

    async def callback(self, interaction: discord.Interaction):
        embed = _build_member_detail_embed(self.member_data, self.owner_name, lang=self.lang)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class TeamMemberSelect(discord.ui.Select):
    def __init__(self, owner_name: str, team_members: list[dict], lang: str = "en"):
        self.owner_name = owner_name
        self.team_members = team_members
        self.lang = "vi" if str(lang).lower().startswith("vi") else "en"
        options: list[discord.SelectOption] = []
        for idx, m in enumerate(team_members[:25]):
            is_main = bool(m.get("is_main"))
            role = str(m.get("role", "")).lower()
            name = str(m.get("name", "Hero"))
            prefix = "👑" if is_main else role_icon(role)
            desc = f"Lv {int(m.get('level', 1) or 1)} • {str(m.get('rarity', 'common')).title()} • {str(m.get('form', 'Base'))}"
            options.append(discord.SelectOption(label=f"{name}"[:100], value=str(idx), description=desc[:100], emoji=prefix))
        placeholder = "🧾 Inspect Hero" if self.lang == "en" else "🧾 Xem Hero"
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options, custom_id="rpg:hero_select")

    async def callback(self, interaction: discord.Interaction):
        try:
            idx = int(self.values[0])
        except Exception:
            idx = 0
        if idx < 0 or idx >= len(self.team_members):
            idx = 0
        embed = _build_member_detail_embed(self.team_members[idx], self.owner_name, lang=self.lang)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class TeamMemberPageButton(discord.ui.Button):
    def __init__(self, direction: int):
        self.direction = -1 if direction < 0 else 1
        label = "◀" if self.direction < 0 else "▶"
        custom_id = "rpg:hero_page:prev" if self.direction < 0 else "rpg:hero_page:next"
        super().__init__(label=label, style=discord.ButtonStyle.secondary, custom_id=custom_id)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, TeamMemberDetailView):
            return await interaction.response.defer()
        max_page = max(0, (len(view.team_members) - 1) // max(1, view.page_size))
        view.page = max(0, min(max_page, view.page + self.direction))
        view._rebuild_items()
        await interaction.response.edit_message(view=view)


class TeamMemberDetailView(discord.ui.View):
    def __init__(self, owner_name: str, team_members: list[dict], lang: str = "en", timeout: float = 180.0):
        super().__init__(timeout=timeout)
        self.owner_name = owner_name
        self.lang = "vi" if str(lang).lower().startswith("vi") else "en"
        self.message: Optional[discord.Message] = None
        self.team_members = sorted(team_members or [], key=lambda x: (0 if x.get("is_main") else 1, int(x.get("slot", 99) or 99)))
        self.page = 0
        self.page_size = 3
        self._rebuild_items()

    def _rebuild_items(self):
        self.clear_items()
        if not self.team_members:
            return
        if len(self.team_members) > 1:
            self.add_item(TeamMemberSelect(self.owner_name, self.team_members, self.lang))
        start = self.page * self.page_size
        end = start + self.page_size
        for member_data in self.team_members[start:end]:
            self.add_item(TeamMemberDetailButton(member_data, self.owner_name, self.lang))
        if len(self.team_members) > self.page_size:
            prev_btn = TeamMemberPageButton(-1)
            next_btn = TeamMemberPageButton(1)
            max_page = max(0, (len(self.team_members) - 1) // self.page_size)
            prev_btn.disabled = self.page <= 0
            next_btn.disabled = self.page >= max_page
            self.add_item(prev_btn)
            self.add_item(next_btn)

    async def on_timeout(self):
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


class ShopCategoryButton(discord.ui.Button):
    def __init__(self, category: str, label: str, emoji: str):
        self.category = _normalize_shop_category_input(category)
        custom_id = f"rpg:shop:{self.category}"[:100]
        super().__init__(label=label[:80], emoji=emoji, style=discord.ButtonStyle.secondary, custom_id=custom_id)

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None:
            lang = await resolve_lang(interaction)
            return await interaction.response.send_message(tr(lang, "common.server_only"), ephemeral=True)

        view = self.view
        if not isinstance(view, ShopCategoryView):
            return await interaction.response.defer()

        lang = await resolve_lang(interaction)
        view.current_category = self.category
        view.refresh_styles()
        embed, card_file = await _build_shop_embed_and_card(self.category, interaction.guild, lang)
        if card_file is not None:
            await interaction.response.edit_message(embed=embed, view=view, attachments=[card_file])
        else:
            await interaction.response.edit_message(embed=embed, view=view, attachments=[])


class ShopCategoryView(discord.ui.View):
    def __init__(self, current_category: str = "main", lang: str = "en", timeout: float = 300.0):
        super().__init__(timeout=timeout)
        self.lang = "vi" if str(lang).lower().startswith("vi") else "en"
        self.current_category = _normalize_shop_category_input(current_category)
        self.message: Optional[discord.Message] = None
        self._build_items()

    def _category_buttons(self) -> list[tuple[str, str, str]]:
        if self.lang == "vi":
            return [
                ("main", "Tong quan", "🛒"),
                (ShopCategory.CONSUMABLES, "Tieu hao", "🧪"),
                (ShopCategory.EQUIPMENT, "Trang bi", "⚔️"),
                (ShopCategory.MATERIALS, "Vat lieu", "💎"),
                (ShopCategory.BLACK_MARKET, "Cho den", "🌑"),
            ]
        return [
            ("main", "Overview", "🛒"),
            (ShopCategory.CONSUMABLES, "Consumables", "🧪"),
            (ShopCategory.EQUIPMENT, "Equipment", "⚔️"),
            (ShopCategory.MATERIALS, "Materials", "💎"),
            (ShopCategory.BLACK_MARKET, "Black Market", "🌑"),
        ]

    def _build_items(self):
        self.clear_items()
        for cid, label, emoji in self._category_buttons():
            self.add_item(ShopCategoryButton(cid, label, emoji))
        self.refresh_styles()

    def refresh_styles(self):
        active = _normalize_shop_category_input(self.current_category)
        for item in self.children:
            if isinstance(item, ShopCategoryButton):
                item.style = discord.ButtonStyle.primary if item.category == active else discord.ButtonStyle.secondary

    async def on_timeout(self):
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


class DungeonNodeSelect(discord.ui.Select):
    def __init__(self, guild_id: int, user_id: int, lang: str, nodes: list[dict]):
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)
        self.lang = "vi" if str(lang).lower().startswith("vi") else "en"
        options: list[discord.SelectOption] = []
        for n in nodes[:25]:
            if bool(n.get("resolved", False)):
                continue
            nid = str(n.get("node_id", ""))
            ntype = str(n.get("node_type", "combat"))
            danger = int(n.get("danger", 1))
            options.append(
                discord.SelectOption(
                    label=f"{nid}"[:100],
                    value=nid,
                    description=f"{ntype} • danger {danger}"[:100],
                    emoji=_dungeon_node_icon(ntype),
                )
            )
        super().__init__(
            placeholder=tr(self.lang, "rpg.dungeon.select.node_placeholder"),
            min_values=1,
            max_values=1,
            options=options or [discord.SelectOption(label="-", value="-")],
            disabled=not bool(options),
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(tr(self.lang, "rpg.dungeon.author_only"), ephemeral=True)
        node_id = str(self.values[0])
        if node_id == "-":
            return await interaction.response.defer()
        result = await DungeonRunService.choose_node(self.guild_id, self.user_id, node_id=node_id, lang=self.lang)
        if not result.ok:
            return await interaction.response.send_message(f"❌ {result.error}", ephemeral=True)
        e = _build_dungeon_node_result_embed(result, self.lang)
        next_view = None
        state = await DungeonRunService.get_state(self.guild_id, self.user_id, lang=self.lang)
        if result.next_phase in {"selecting_path", "choice", "resolving_node"}:
            if state.ok:
                next_view = DungeonControlView(self.guild_id, self.user_id, self.lang, state)
        payload = _dungeon_node_card_payload(result, state if state.ok else None, self.lang)
        card_file = await _attach_dungeon_card(e, payload, interaction.guild, self.lang)
        if card_file is not None:
            await interaction.response.edit_message(embed=e, view=next_view, attachments=[card_file])
        else:
            await interaction.response.edit_message(embed=e, view=next_view, attachments=[])


class DungeonChoiceSelect(discord.ui.Select):
    def __init__(self, guild_id: int, user_id: int, lang: str, options_data: list[dict]):
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)
        self.lang = "vi" if str(lang).lower().startswith("vi") else "en"
        options: list[discord.SelectOption] = []
        for o in options_data[:25]:
            cid = str(o.get("choice_id", ""))
            title = str(o.get("title", cid))
            tradeoff = str(o.get("tradeoff", ""))
            options.append(discord.SelectOption(label=title[:100], value=cid, description=tradeoff[:100]))
        super().__init__(
            placeholder=tr(self.lang, "rpg.dungeon.select.choice_placeholder"),
            min_values=1,
            max_values=1,
            options=options or [discord.SelectOption(label="-", value="-")],
            disabled=not bool(options),
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(tr(self.lang, "rpg.dungeon.author_only"), ephemeral=True)
        choice_id = str(self.values[0])
        if choice_id == "-":
            return await interaction.response.defer()
        result = await DungeonRunService.apply_choice(self.guild_id, self.user_id, choice_id=choice_id, lang=self.lang)
        if not result.ok:
            return await interaction.response.send_message(f"❌ {result.error}", ephemeral=True)
        e = panel_embed(
            mode="Dungeon Mode",
            title=tr(self.lang, "rpg.dungeon.choice_applied_title"),
            description=tr(self.lang, "rpg.dungeon.choice_applied_desc", choice_id=result.choice_id),
            theme="victory",
        )
        state = await DungeonRunService.get_state(self.guild_id, self.user_id, lang=self.lang)
        next_view = DungeonControlView(self.guild_id, self.user_id, self.lang, state) if state.ok else None
        payload = _dungeon_choice_card_payload(result, state if state.ok else None, self.lang)
        card_file = await _attach_dungeon_card(e, payload, interaction.guild, self.lang)
        if card_file is not None:
            await interaction.response.edit_message(embed=e, view=next_view, attachments=[card_file])
        else:
            await interaction.response.edit_message(embed=e, view=next_view, attachments=[])


class DungeonPathModal(discord.ui.Modal):
    def __init__(self, guild_id: int, user_id: int, lang: str):
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)
        self.lang = "vi" if str(lang).lower().startswith("vi") else "en"
        super().__init__(title=tr(self.lang, "rpg.dungeon.modal.path.title"))
        self.node_id = discord.ui.TextInput(
            label=tr(self.lang, "rpg.dungeon.modal.path.label"),
            placeholder="F2-1",
            required=True,
            max_length=32,
        )
        self.add_item(self.node_id)

    async def on_submit(self, interaction: discord.Interaction):
        result = await DungeonRunService.choose_node(self.guild_id, self.user_id, node_id=str(self.node_id.value).strip(), lang=self.lang)
        if not result.ok:
            return await interaction.response.send_message(f"❌ {result.error}", ephemeral=True)
        e = _build_dungeon_node_result_embed(result, self.lang)
        state = await DungeonRunService.get_state(self.guild_id, self.user_id, lang=self.lang)
        payload = _dungeon_node_card_payload(result, state if state.ok else None, self.lang)
        card_file = await _attach_dungeon_card(e, payload, interaction.guild, self.lang)
        if card_file is not None:
            await interaction.response.send_message(embed=e, file=card_file, ephemeral=True)
        else:
            await interaction.response.send_message(embed=e, ephemeral=True)


class DungeonChoiceModal(discord.ui.Modal):
    def __init__(self, guild_id: int, user_id: int, lang: str):
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)
        self.lang = "vi" if str(lang).lower().startswith("vi") else "en"
        super().__init__(title=tr(self.lang, "rpg.dungeon.modal.choice.title"))
        self.choice_id = discord.ui.TextInput(
            label=tr(self.lang, "rpg.dungeon.modal.choice.label"),
            placeholder="campfire",
            required=True,
            max_length=40,
        )
        self.add_item(self.choice_id)

    async def on_submit(self, interaction: discord.Interaction):
        result = await DungeonRunService.apply_choice(self.guild_id, self.user_id, choice_id=str(self.choice_id.value).strip(), lang=self.lang)
        if not result.ok:
            return await interaction.response.send_message(f"❌ {result.error}", ephemeral=True)
        e = panel_embed(
            mode="Dungeon Mode",
            title=tr(self.lang, "rpg.dungeon.choice_applied_title"),
            description=tr(self.lang, "rpg.dungeon.choice_applied_desc", choice_id=result.choice_id),
            theme="victory",
        )
        state = await DungeonRunService.get_state(self.guild_id, self.user_id, lang=self.lang)
        payload = _dungeon_choice_card_payload(result, state if state.ok else None, self.lang)
        card_file = await _attach_dungeon_card(e, payload, interaction.guild, self.lang)
        if card_file is not None:
            await interaction.response.send_message(embed=e, file=card_file, ephemeral=True)
        else:
            await interaction.response.send_message(embed=e, ephemeral=True)


class DungeonActionButton(discord.ui.Button):
    def __init__(self, guild_id: int, user_id: int, lang: str, action: str):
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)
        self.lang = "vi" if str(lang).lower().startswith("vi") else "en"
        self.action = str(action)
        custom_id = f"rpg:dungeon:{self.action}"
        if self.action == "status":
            label = tr(self.lang, "rpg.dungeon.btn.status")
            style = discord.ButtonStyle.secondary
        elif self.action == "path":
            label = tr(self.lang, "rpg.dungeon.btn.path")
            style = discord.ButtonStyle.primary
        elif self.action == "choice":
            label = tr(self.lang, "rpg.dungeon.btn.choice")
            style = discord.ButtonStyle.primary
        elif self.action == "retreat":
            label = tr(self.lang, "rpg.dungeon.btn.retreat")
            style = discord.ButtonStyle.danger
        else:
            label = tr(self.lang, "rpg.dungeon.btn.claim")
            style = discord.ButtonStyle.success
        super().__init__(label=label[:80], style=style, custom_id=custom_id)

    async def callback(self, interaction: discord.Interaction):
        lang = self.lang
        try:
            lang = await resolve_lang(interaction)
        except Exception:
            pass

        guild_id = self.guild_id if self.guild_id > 0 else (interaction.guild.id if interaction.guild else 0)
        if guild_id <= 0:
            return await interaction.response.send_message(tr(lang, "common.server_only"), ephemeral=True)
        target_user = self.user_id if self.user_id > 0 else interaction.user.id

        if self.user_id > 0 and interaction.user.id != self.user_id:
            return await interaction.response.send_message(tr(lang, "rpg.dungeon.author_only"), ephemeral=True)

        if self.action == "path":
            return await interaction.response.send_modal(DungeonPathModal(guild_id, target_user, lang))

        if self.action == "choice":
            return await interaction.response.send_modal(DungeonChoiceModal(guild_id, target_user, lang))

        if self.action == "status":
            state, resolved_embed = await _dungeon_status_with_pending_resolution(guild_id, target_user, lang=lang)
            if not state.ok:
                return await interaction.response.send_message(tr(lang, "rpg.dungeon.no_active"), ephemeral=True)
            e = resolved_embed if resolved_embed is not None else _build_dungeon_state_embed(state, lang)
            next_view = DungeonControlView(guild_id, target_user, lang, state)
            payload = _dungeon_state_card_payload(state, lang)
            card_file = await _attach_dungeon_card(e, payload, interaction.guild, lang)
            if card_file is not None:
                await interaction.response.edit_message(embed=e, view=next_view, attachments=[card_file])
            else:
                await interaction.response.edit_message(embed=e, view=next_view, attachments=[])
            return

        if self.action == "retreat":
            result = await DungeonRunService.retreat(guild_id, target_user, lang=lang)
            if not result.ok:
                return await interaction.response.send_message(f"❌ {result.error}", ephemeral=True)
            e = _build_dungeon_finish_embed(result, lang)
            payload = _dungeon_finish_card_payload(result, lang)
            card_file = await _attach_dungeon_card(e, payload, interaction.guild, lang)
            if card_file is not None:
                await interaction.response.edit_message(embed=e, view=None, attachments=[card_file])
            else:
                await interaction.response.edit_message(embed=e, view=None, attachments=[])
            return

        if self.action == "claim":
            result = await DungeonRunService.claim_rewards(guild_id, target_user, lang=lang)
            if not result.ok:
                return await interaction.response.send_message(f"❌ {result.error}", ephemeral=True)
            e = _build_dungeon_finish_embed(result, lang)
            payload = _dungeon_finish_card_payload(result, lang)
            card_file = await _attach_dungeon_card(e, payload, interaction.guild, lang)
            if card_file is not None:
                await interaction.response.edit_message(embed=e, view=None, attachments=[card_file])
            else:
                await interaction.response.edit_message(embed=e, view=None, attachments=[])
            return

        await interaction.response.send_message(tr(lang, "rpg.dungeon.action_failed"), ephemeral=True)


class DungeonControlView(discord.ui.View):
    def __init__(self, guild_id: int, user_id: int, lang: str, state, timeout: float = 180.0):
        super().__init__(timeout=timeout)
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)
        self.lang = "vi" if str(lang).lower().startswith("vi") else "en"
        self.message: Optional[discord.Message] = None
        phase = str(getattr(state, "phase", ""))

        if phase == "selecting_path":
            self.add_item(DungeonNodeSelect(self.guild_id, self.user_id, self.lang, list(getattr(state, "nodes", []))))
        elif phase == "choice":
            pending = getattr(state, "pending_choice", {}) if isinstance(getattr(state, "pending_choice", {}), dict) else {}
            opts = pending.get("options", []) if isinstance(pending.get("options", []), list) else []
            self.add_item(DungeonChoiceSelect(self.guild_id, self.user_id, self.lang, opts))

        self.add_item(DungeonActionButton(self.guild_id, self.user_id, self.lang, "path"))
        self.add_item(DungeonActionButton(self.guild_id, self.user_id, self.lang, "choice"))
        self.add_item(DungeonActionButton(self.guild_id, self.user_id, self.lang, "status"))
        self.add_item(DungeonActionButton(self.guild_id, self.user_id, self.lang, "retreat"))
        self.add_item(DungeonActionButton(self.guild_id, self.user_id, self.lang, "claim"))

    async def on_timeout(self):
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


class DungeonPersistentRouterView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(DungeonActionButton(0, 0, "en", "path"))
        self.add_item(DungeonActionButton(0, 0, "en", "choice"))
        self.add_item(DungeonActionButton(0, 0, "en", "status"))
        self.add_item(DungeonActionButton(0, 0, "en", "retreat"))
        self.add_item(DungeonActionButton(0, 0, "en", "claim"))


async def _publish_combat_log(log_lines: list[str], lang: str = "en") -> str | None:
    text = "\n".join(log_lines or []).strip()
    if not text:
        return None
    try:
        import aiohttp

        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post("https://paste.rs", data=text.encode("utf-8")) as resp:
                if resp.status < 200 or resp.status >= 300:
                    return None
                url = (await resp.text()).strip()
                return url if url.startswith("http") else None
    except Exception:
        return None


def build_embed_from_result(
    result,
    log_url: str | None,
    lang: str = "en",
) -> discord.Embed:
    e = discord.Embed(
        title="⚔️ Team Hunt Report" if lang == "en" else "⚔️ Báo cáo săn đội",
        color=discord.Color.green() if result.kills == result.pack else discord.Color.orange(),
    )
    link_value = tr(lang, "rpg.log_link_hint")
    if log_url:
        link_value += f"\n{log_url}"
    e.add_field(name="📜 Battle Record", value=link_value, inline=False)
    return e


def build_hunt_response(
    result,
    log_url: str | None,
    lang: str = "en",
) -> tuple[discord.Embed, CombatDetailView]:
    embed = build_embed_from_result(result, log_url, lang=lang)
    detail_text = "\n".join((result.logs or [])[:20]) if result.logs else tr(lang, "rpg.no_combat_detail")
    view = CombatDetailView(detail_text, lang=lang)
    return embed, view


async def handle_hunt(
    guild_id: int,
    user_id: int,
    player_name: str,
    guild: discord.Guild | None = None,
    lang: str = "en",
) -> tuple[discord.Embed | None, CombatDetailView | None, str | None, discord.File | None]:
    result = await CombatService.hunt(guild_id, user_id, lang=lang)
    if not result.ok:
        if int(getattr(result, "cooldown_remain", 0)) > 0:
            return None, None, tr(lang, "rpg.hunt_cooldown", seconds=int(result.cooldown_remain)), None
        return None, None, tr(lang, "rpg.hunt_unavailable"), None

    log_url = await _publish_combat_log(result.logs or [], lang=lang)
    embed, view = build_hunt_response(result, log_url, lang=lang)

    card_file: discord.File | None = None
    if guild is not None:
        lore = await _profile_lore_meta(guild_id, user_id)
        card_members = await _enrich_team_members_for_card(
            guild_id,
            user_id,
            lore.get("team_members", []) if isinstance(lore.get("team_members", []), list) else [],
        )
        battle_data = convert_combat_result_to_battle_data(
            player_name=player_name,
            team_members=card_members,
            combat_result=result,
            lang=lang,
        )
        card_buffer = await render_battle_card(battle_data, guild)
        if card_buffer is not None:
            card_file = discord.File(fp=card_buffer, filename="battle_card.png")
            embed.set_image(url="attachment://battle_card.png")

    return embed, view, None, card_file


async def handle_profile(
    guild_id: int,
    target: discord.Member,
    lang: str = "en",
    stats_mode: bool = False,
) -> tuple[discord.Embed | None, TeamMemberDetailView | None, str | None]:
    result = await PlayerService.get_profile(guild_id, target.id)
    if not result.ok:
        return None, None, tr(lang, "rpg.profile_fetch_failed")
    lore = await _profile_lore_meta(guild_id, target.id)
    embed = _build_formation_analysis_embed(target, result, lore, lang=lang) if stats_mode else _build_profile_embed(target, result, lore, lang=lang)
    team_members = lore.get("team_members", []) if isinstance(lore.get("team_members"), list) else []
    view = TeamMemberDetailView(target.display_name, team_members, lang=lang) if team_members else None
    return embed, view, None


def _boss_rarity_from_id(boss_id: str) -> str:
    bid = str(boss_id or "").strip().lower()
    if bid in {"void_tyrant", "ashen_dragon", "ogre_king"}:
        return "mythic"
    if bid in {"ogre_chief"}:
        return "epic"
    return "rare"


def _boss_level_from_stats(hp: int, atk: int, defense: int) -> int:
    return max(1, int((max(1, hp) ** 0.5) / 2 + (atk + defense) / 18))


def _character_display_emoji(char_meta: dict, rarity: str | None = None, fallback: str = "🎮") -> str:
    raw = str((char_meta or {}).get("emoji", fallback) or fallback).strip()
    if not raw:
        return fallback
    if raw in RARITY_ICONS.values():
        return ""
    if rarity and raw == RARITY_ICONS.get(str(rarity).strip().lower(), ""):
        return ""
    return raw


_GUILD_EMOJI_ALIASES: dict[str, list[str]] = dict(RPG_EMOJI_ALIASES)


def _norm_emoji_key(name: str) -> str:
    raw = str(name or "").strip().lower()
    out = []
    for ch in raw:
        if ch.isalnum() or ch in {"_", "-"}:
            out.append(ch)
        elif ch.isspace():
            out.append("_")
    key = "".join(out).strip("_")
    return key


def _guild_emoji_index(guild: discord.Guild) -> dict[str, discord.Emoji]:
    idx: dict[str, discord.Emoji] = {}

    state = getattr(guild, "_state", None)
    client = state._get_client() if state is not None and hasattr(state, "_get_client") else None
    emoji_sources = getattr(client, "emojis", None)
    if emoji_sources is None:
        emoji_sources = []

    for e in list(emoji_sources):
        k = _norm_emoji_key(str(getattr(e, "name", "")))
        if k and k not in idx:
            idx[k] = e

    for e in getattr(guild, "emojis", []):
        k = _norm_emoji_key(str(getattr(e, "name", "")))
        if k and k not in idx:
            idx[k] = e

    return idx


def _guild_emoji_token(
    guild: discord.Guild,
    name: str,
    fallback: str = "",
    emoji_index: dict[str, discord.Emoji] | None = None,
) -> str:
    key = _norm_emoji_key(name)
    if not key:
        return fallback

    idx = emoji_index if isinstance(emoji_index, dict) else _guild_emoji_index(guild)
    candidates: list[str] = [
        key,
        key.replace("-", "_"),
        key.replace("_", "-"),
        key.replace("_", ""),
    ]
    for alias in _GUILD_EMOJI_ALIASES.get(key, []):
        a = _norm_emoji_key(alias)
        if a:
            candidates.append(a)

    seen: set[str] = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        e = idx.get(c)
        if e is None:
            continue
        prefix = "a" if bool(getattr(e, "animated", False)) else ""
        return f"<{prefix}:{e.name}:{e.id}>" if prefix else f"<:{e.name}:{e.id}>"
    return fallback


_EMOJI_SHORTCODE_RE = re.compile(r":([A-Za-z0-9_]+):")
_INTERACTION_RESPONSE_EMOJI_PATCHED = False


def _is_rpg_interaction(interaction: discord.Interaction | None) -> bool:
    if not isinstance(interaction, discord.Interaction):
        return False

    cmd = getattr(interaction, "command", None)
    cmd_name = str(getattr(cmd, "name", "")).strip().lower()
    root_parent = getattr(cmd, "root_parent", None)
    root_name = str(getattr(root_parent, "name", "")).strip().lower()
    if cmd_name in RPG_COMMAND_NAMES or root_name in RPG_COMMAND_NAMES:
        return True

    data = getattr(interaction, "data", None)
    if isinstance(data, dict):
        custom_id = str(data.get("custom_id", "")).strip().lower()
        if custom_id.startswith("rpg:"):
            return True
    return False


def _emojiify_text(text: str, guild: discord.Guild, emoji_index: dict[str, discord.Emoji] | None = None) -> str:
    if not isinstance(text, str) or ":" not in text:
        return text
    idx = emoji_index if isinstance(emoji_index, dict) else _guild_emoji_index(guild)

    def repl(match: re.Match[str]) -> str:
        return _guild_emoji_token(guild, match.group(1), match.group(0), idx)

    return _EMOJI_SHORTCODE_RE.sub(repl, text)


def _emojiify_embed(embed: discord.Embed, guild: discord.Guild, emoji_index: dict[str, discord.Emoji] | None = None) -> discord.Embed:
    idx = emoji_index if isinstance(emoji_index, dict) else _guild_emoji_index(guild)

    if isinstance(embed.title, str) and embed.title:
        embed.title = _emojiify_text(embed.title, guild, idx)
    if isinstance(embed.description, str) and embed.description:
        embed.description = _emojiify_text(embed.description, guild, idx)

    for i, field in enumerate(list(embed.fields)):
        field_name = _emojiify_text(str(field.name), guild, idx)
        field_value = _emojiify_text(str(field.value), guild, idx)
        if field_name != field.name or field_value != field.value:
            embed.set_field_at(i, name=field_name, value=field_value, inline=field.inline)

    footer_text = getattr(embed.footer, "text", None)
    if isinstance(footer_text, str) and footer_text:
        footer_icon = getattr(embed.footer, "icon_url", None)
        embed.set_footer(
            text=_emojiify_text(footer_text, guild, idx),
            icon_url=str(footer_icon) if footer_icon else None,
        )

    author_name = getattr(embed.author, "name", None)
    if isinstance(author_name, str) and author_name:
        author_url = getattr(embed.author, "url", None)
        author_icon = getattr(embed.author, "icon_url", None)
        embed.set_author(
            name=_emojiify_text(author_name, guild, idx),
            url=str(author_url) if author_url else None,
            icon_url=str(author_icon) if author_icon else None,
        )

    return embed


def _emojiify_interaction_payload(interaction: discord.Interaction | None, args: tuple, kwargs: dict) -> tuple[tuple, dict]:
    if not _is_rpg_interaction(interaction):
        return args, kwargs
    guild = getattr(interaction, "guild", None)
    if guild is None:
        return args, kwargs

    idx = _guild_emoji_index(guild)
    out_args = list(args)

    if out_args and isinstance(out_args[0], str):
        out_args[0] = _emojiify_text(out_args[0], guild, idx)

    content = kwargs.get("content")
    if isinstance(content, str):
        kwargs["content"] = _emojiify_text(content, guild, idx)

    embed = kwargs.get("embed")
    if isinstance(embed, discord.Embed):
        kwargs["embed"] = _emojiify_embed(embed, guild, idx)

    embeds = kwargs.get("embeds")
    if isinstance(embeds, (list, tuple)):
        kwargs["embeds"] = [
            _emojiify_embed(e, guild, idx) if isinstance(e, discord.Embed) else e
            for e in embeds
        ]

    return tuple(out_args), kwargs


def _patch_interaction_response_emoji_support() -> None:
    global _INTERACTION_RESPONSE_EMOJI_PATCHED
    if _INTERACTION_RESPONSE_EMOJI_PATCHED:
        return

    original_send_message = discord.InteractionResponse.send_message
    original_edit_message = discord.InteractionResponse.edit_message

    async def _send_message_with_emoji_patch(self, *args, **kwargs):
        patched_args, patched_kwargs = _emojiify_interaction_payload(getattr(self, "_parent", None), args, dict(kwargs))
        return await original_send_message(self, *patched_args, **patched_kwargs)

    async def _edit_message_with_emoji_patch(self, *args, **kwargs):
        patched_args, patched_kwargs = _emojiify_interaction_payload(getattr(self, "_parent", None), args, dict(kwargs))
        return await original_edit_message(self, *patched_args, **patched_kwargs)

    discord.InteractionResponse.send_message = _send_message_with_emoji_patch
    discord.InteractionResponse.edit_message = _edit_message_with_emoji_patch
    _INTERACTION_RESPONSE_EMOJI_PATCHED = True


async def _rpg_followup_send(interaction: discord.Interaction, *args, **kwargs):
    patched_args, patched_kwargs = _emojiify_interaction_payload(interaction, args, dict(kwargs))
    return await interaction.followup.send(*patched_args, **patched_kwargs)


async def _build_guild_boss_dashboard_data(
    guild: discord.Guild,
    guild_id: int,
    result,
    lang: str,
) -> dict:
    is_vi = str(lang).lower().startswith("vi")
    emoji_idx = _guild_emoji_index(guild)
    variants = [dict(v) for v in (BOSS_VARIANTS or []) if isinstance(v, dict)]
    by_id = {str(v.get("id", "")).lower(): v for v in variants}
    current_id = str(getattr(result, "boss_id", "") or "").lower()
    current_variant = by_id.get(current_id) or (variants[0] if variants else {"id": "boss", "name": "Boss", "hp": 300, "atk": 30, "def": 12, "drops": []})

    c_hp_max = max(1, int(getattr(result, "boss_max_hp", 0) or int(current_variant.get("hp", 300) or 300)))
    c_hp_now = max(0, int(getattr(result, "boss_current_hp", 0) or getattr(result, "base_hp", 0) or c_hp_max))
    c_atk = max(1, int(getattr(result, "boss_atk", 0) or int(current_variant.get("atk", 30) or 30)))
    c_def = max(1, int(getattr(result, "boss_def", 0) or int(current_variant.get("def", 12) or 12)))

    selected = [current_variant]
    for v in variants:
        vid = str(v.get("id", "")).lower()
        if vid and vid != current_id:
            selected.append(v)
        if len(selected) >= 3:
            break
    while len(selected) < 3:
        selected.append(dict(selected[-1]))

    bosses: list[dict] = []
    for idx, v in enumerate(selected[:3]):
        bid = str(v.get("id", f"boss_{idx}"))
        bhp = int(v.get("hp", 250) or 250)
        batk = int(v.get("atk", 25) or 25)
        bdef = int(v.get("def", 10) or 10)
        max_hp = max(1, int(bhp * (1.0 + 0.7 + idx * 0.15)))
        cur_hp = int(max_hp * (0.85 - idx * 0.12))
        if idx == 0:
            max_hp = c_hp_max
            cur_hp = c_hp_now
            batk = c_atk
            bdef = c_def

        drops = [str(item_id) for item_id, _ in (v.get("drops", []) or [])[:3]]
        crit = max(10, min(95, int(30 + batk * 0.45)))
        res = max(8, min(95, int(24 + bdef * 0.5)))
        bosses.append(
            {
                "name": str(v.get("name", bid.title())),
                "level": _boss_level_from_stats(max_hp, batk, bdef),
                "rarity": _boss_rarity_from_id(bid),
                "emoji": _guild_emoji_token(guild, bid, f":{bid}:", emoji_idx),
                "hp": cur_hp,
                "max_hp": max_hp,
                "stats": {
                    "hp": max_hp,
                    "atk": batk,
                    "def": bdef,
                    "crit": crit,
                    "res": res,
                },
                "icons": [_guild_emoji_token(guild, item_id, f":{item_id}:", emoji_idx) for item_id in drops],
            }
        )

    async with open_db() as conn:
        top_rows = await telemetry_repo.get_top_guild_boss_damage(conn, guild_id, limit=10)
        fighters, defeated = await telemetry_repo.get_guild_boss_summary(conn, guild_id)

    top_damage: list[dict] = []
    for idx, (uid, total_damage, _battles, _wins, _last_damage) in enumerate(top_rows, start=1):
        member = guild.get_member(int(uid))
        username = f"@{member.display_name}" if member is not None else f"<@{uid}>"
        top_damage.append(
            {
                "rank": idx,
                "damage": int(total_damage),
                "username": username,
                "emoji": str(member.display_avatar.url) if member is not None else "",
            }
        )

    drop_map = dict(getattr(result, "drops", {}) or {})
    rewards: list[dict] = [
        {
            "name": "Slime Coin" if not is_vi else "Slime Coin",
            "amount": int(getattr(result, "gold", 0) or 0),
            "emoji": _guild_emoji_token(guild, "slimecoin", ":slimecoin:", emoji_idx),
        },
        {
            "name": "Experience" if not is_vi else "Kinh nghiệm",
            "amount": int(getattr(result, "xp", 0) or 0),
            "emoji": _guild_emoji_token(guild, "xp", ":xp:", emoji_idx),
        },
        {
            "name": "Weapon Shards" if not is_vi else "Mảnh vũ khí",
            "amount": int(drop_map.get("rare_crystal", 0) or 0),
            "emoji": _guild_emoji_token(guild, "weapon_shards", _guild_emoji_token(guild, "rare_crystal", ":rare_crystal:", emoji_idx), emoji_idx),
        },
        {
            "name": "Weapon Crate" if not is_vi else "Thùng vũ khí",
            "amount": int(drop_map.get("lootbox", 0) or 0),
            "emoji": _guild_emoji_token(guild, "weapon_crate", _guild_emoji_token(guild, "lootbox", ":lootbox:", emoji_idx), emoji_idx),
        },
    ]
    if int(drop_map.get("phoenix_charm", 0) or 0) > 0:
        rewards.append(
            {
                "name": "Boss Weapon Crate" if not is_vi else "Rương vũ khí boss",
                "amount": int(drop_map.get("phoenix_charm", 0) or 0),
                "emoji": _guild_emoji_token(guild, "boss_weapon_crate", _guild_emoji_token(guild, "phoenix_charm", ":phoenix_charm:", emoji_idx), emoji_idx),
            }
        )

    for item_id, amount in drop_map.items():
        item_meta = ITEMS.get(str(item_id), {})
        rewards.append(
            {
                "name": str(item_meta.get("name", item_id)),
                "amount": int(amount),
                "emoji": _guild_emoji_token(guild, str(item_id), f":{str(item_id)}:", emoji_idx),
            }
        )

    runs_away = f"{max(1, int(RPG_BOSS_COOLDOWN // 60))} minutes"
    if is_vi:
        runs_away = f"{max(1, int(RPG_BOSS_COOLDOWN // 60))} phút"

    return {
        "title": ("A Guild Boss Appeared!" if not is_vi else "Guild Boss đã xuất hiện!"),
        "header_emoji": _guild_emoji_token(guild, current_id or "boss", f":{current_id}:" if current_id else ":boss:", emoji_idx),
        "decor_emoji": _guild_emoji_token(guild, "fight", _guild_emoji_token(guild, "boss", ":boss:", emoji_idx), emoji_idx),
        "bosses": bosses,
        "top_damage": top_damage,
        "rewards": rewards[:4],
        "runs_away_in": runs_away,
        "fighters": int(fighters),
        "defeated": int(defeated),
    }


def build_boss_embed_from_result(result, player_name: str, team_lines: list[str], log_url: str | None, lang: str = "en") -> discord.Embed:
    turns = int(getattr(result, "turns", 0) or 0)
    if turns <= 0:
        turns = max(1, sum(1 for line in (result.logs or []) if "attacks" in line or "takes" in line))
    embed = panel_embed(
        mode="Boss Assault",
        title=f"👑 Operation Report • {result.boss or 'Boss'}",
        description=("Đội hình đã giao chiến với boss tuyến cuối." if lang == "vi" else "Your squad has engaged the boss target."),
        theme="victory" if result.win else "defeat",
    )
    embed.add_field(name="🛡️ Squad", value="\n".join(team_lines or ["(no team data)"]), inline=False)
    embed.add_field(name="👹 Enemy", value=str(result.boss or "Boss"), inline=True)
    embed.add_field(name="🕒 Battle Tempo", value=f"{turns} turns", inline=True)
    embed.add_field(name="🏁 Result", value=("Victory" if result.win else "Defeat"), inline=True)
    embed.add_field(name="🎁 Rewards", value=f"+{result.gold} {CURRENCY_ICON} Slime Coin\n+{result.xp} {XP_ICON}", inline=True)
    link_value = tr(lang, "rpg.log_link_hint")
    if log_url:
        link_value += f"\n{log_url}"
    embed.add_field(name="📜 Battle Record", value=link_value, inline=False)
    if result.win:
        if result.drops:
            embed.add_field(name="💎 Drops", value=", ".join(f"{_item_label(k)} x{v}" for k, v in result.drops.items()), inline=False)
        if result.leveled_up:
            embed.add_field(name="🎉 Promotion", value=tr(lang, "rpg.level_up", level=result.level), inline=False)
    return embed


async def handle_boss(
    guild_id: int,
    user_id: int,
    player_name: str,
    guild: discord.Guild | None = None,
    lang: str = "en",
) -> tuple[discord.Embed | None, discord.ui.View | None, str | None, discord.File | None]:
    result = await CombatService.boss(guild_id, user_id, lang=lang)
    if not result.ok:
        if int(getattr(result, "cooldown_remain", 0)) > 0:
            return None, None, tr(lang, "rpg.boss_cooldown", seconds=int(result.cooldown_remain)), None
        return None, None, tr(lang, "rpg.boss_unavailable"), None
    team_lines = await _team_snapshot_lines(guild_id, user_id)
    log_url = await _publish_combat_log(result.logs or [], lang=lang)
    embed = build_boss_embed_from_result(result, player_name, team_lines, log_url, lang=lang)
    detail_text = "\n".join((result.logs or [])[:20]) if result.logs else tr(lang, "rpg.no_combat_detail")
    view = BossCombatView(guild_id, user_id, detail_text, lang=lang)

    card_file: discord.File | None = None
    if guild is not None:
        try:
            dashboard_data = await _build_guild_boss_dashboard_data(guild, guild_id, result, lang)
            card_buffer = await render_guild_boss_image(dashboard_data)
            card_file = discord.File(fp=card_buffer, filename="guild_boss_dashboard.png")
            embed.set_image(url="attachment://guild_boss_dashboard.png")
        except Exception:
            logger.exception("failed to render guild boss dashboard image guild=%s user=%s", guild_id, user_id)

    return embed, view, None, card_file


async def handle_quest(guild_id: int, user_id: int, owner_name: str | None = None, lang: str = "en") -> discord.Embed:
    quests = await QuestService.get_quests(guild_id, user_id)
    return _build_quest_board_embed(quests, owner_name=owner_name, lang=lang)


async def handle_quest_claim(guild_id: int, user_id: int, quest_id: str, lang: str = "en") -> str:
    result = await QuestService.claim_quest(guild_id, user_id, quest_id, lang=lang)
    return result.message


async def handle_rpg_start(guild_id: int, user_id: int, lang: str = "en") -> str:
    await ensure_db_ready()
    async with open_db() as conn:
        from .repositories import player_repo, quest_repo

        await player_repo.ensure_player_ready(conn, guild_id, user_id)
        await quest_repo.ensure_default_quests(conn, guild_id, user_id)
        await conn.commit()
    return tr(lang, "rpg.start_success")


async def handle_create_character(
    guild_id: int,
    user_id: int,
    role: str,
    gender: str = "any",
    lang: str = "en",
) -> tuple[discord.Embed | None, str | None, bool]:
    _ = _normalize_gender_suffix(gender)
    async with open_db() as conn:
        main_char = await get_main_character(conn, guild_id, user_id)
        if main_char:
            msg = "❌ Bạn đã có Captain rồi!" if lang == "vi" else "❌ You already have a Captain!"
            return None, msg, True

        normalized_role = normalize_role(role)
        char_id = STARTER_BY_ROLE.get(normalized_role, "")
        if char_id not in CHARACTERS:
            msg = "❌ Character không tồn tại." if lang == "vi" else "❌ Character does not exist."
            return None, msg, True

        player_row = await get_player(conn, guild_id, user_id)
        if not player_row:
            msg = "❌ Bạn chưa có player profile. Dùng `/rpg_start` trước." if lang == "vi" else "❌ You don't have a player profile yet. Use `/rpg_start` first."
            return None, msg, True

        level, _, _, _, _, _, _ = map(int, player_row)
        await conn.execute(
            """
            INSERT OR IGNORE INTO player_characters(guild_id, user_id, character_id, is_main, level, exp, star, shard_count, obtained_at)
            VALUES (?, ?, ?, 1, ?, 0, 1, 0, ?)
            """,
            (guild_id, user_id, char_id, level, int(time.time())),
        )
        await conn.commit()

    char_data = CHARACTERS[char_id]
    base_hp = int(char_data["hp"])
    base_atk = int(char_data["attack"])
    base_def = int(char_data["defense"])
    scale = 1 + (level - 1) * 0.1
    emoji = _character_display_emoji(char_data)
    embed = panel_embed(
        mode="Captain Deployment",
        title=f"{emoji} Captain Deployed",
        description=(
            (f"**{char_data['name']}** đã trở thành Captain của đội hình!" if lang == "vi" else f"**{char_data['name']}** is now your team Captain!")
            + "\n\n"
            + f"HP {int(base_hp * scale)} • ATK {int(base_atk * scale)} • DEF {int(base_def * scale)}"
        ),
        theme="victory",
    )
    embed.add_field(name="Role", value=f"{role_icon(str(char_data.get('role', '')))} **{str(char_data.get('role', 'unknown')).title()}**", inline=True)
    embed.add_field(name="Form", value=f"**{char_data.get('form', 'Base')}**", inline=True)
    return embed, None, False


def _target_hero_line(target_cid: str | None) -> str:
    cid = str(target_cid or "").strip().lower()
    if not cid:
        return "**Captain**"
    c = CHARACTERS.get(cid, {})
    hero_name = str(c.get("name", cid or "Captain"))
    hero_form = str(c.get("form", "Base"))
    hero_emoji = _character_display_emoji(c, str(c.get("rarity", "")), fallback="")
    return f"{hero_emoji + ' ' if hero_emoji else ''}**{hero_name} [{hero_form}]**"


async def handle_equip_action(
    guild_id: int,
    user_id: int,
    item: str,
    character_id: str | None,
    lang: str = "en",
) -> tuple[discord.Embed | None, str | None, bool]:
    selected_cid = str(character_id or "").strip().lower() or None
    ok, payload = await PlayerService.equip_item(guild_id, user_id, item, lang=lang, character_id=selected_cid)
    if not ok:
        return None, f"❌ {payload}", True

    slot = str(payload).split("|", 1)[0]
    target_cid = str(payload).split("|", 1)[1] if "|" in str(payload) else ""
    e = panel_embed(
        mode="Loadout Console",
        title=("✅ Equipment Assigned" if lang == "en" else "✅ Đã gán trang bị"),
        description=(f"{_item_label(item)} assigned to slot **{slot}**." if lang == "en" else f"{_item_label(item)} đã được gán vào slot **{slot}**."),
        theme="victory",
    )
    e.add_field(name="Target Hero", value=_target_hero_line(target_cid), inline=False)
    return e, None, False


async def handle_unequip_action(
    guild_id: int,
    user_id: int,
    slot: str,
    character_id: str | None,
    lang: str = "en",
) -> tuple[discord.Embed | None, str | None, bool]:
    selected_cid = str(character_id or "").strip().lower() or None
    ok, payload = await PlayerService.unequip_item(guild_id, user_id, slot, lang=lang, character_id=selected_cid)
    if not ok:
        return None, f"❌ {payload}", True

    item_id = str(payload).split("|", 1)[0]
    target_cid = str(payload).split("|", 1)[1] if "|" in str(payload) else ""
    e = panel_embed(
        mode="Loadout Console",
        title=("✅ Equipment Removed" if lang == "en" else "✅ Đã tháo trang bị"),
        description=(f"{_item_label(item_id)} removed from slot **{slot}**." if lang == "en" else f"{_item_label(item_id)} đã được tháo khỏi slot **{slot}**."),
        theme="victory",
    )
    e.add_field(name="Target Hero", value=_target_hero_line(target_cid), inline=False)
    return e, None, False


async def handle_gacha(
    guild_id: int,
    user_id: int,
    pulls: int = 1,
    banner: str = "none",
    lang: str = "en",
    guild: discord.Guild | None = None,
    player_name: str = "",
) -> tuple[discord.Embed | None, str | None, bool, discord.File | None]:
    pulls = max(1, min(10, int(pulls)))
    banner_id = str(banner or "none").lower()
    if banner_id not in GACHA_BANNERS:
        banner_id = "none"
    cost = GACHA_COST * pulls

    async with open_db() as conn:
        player_row = await get_player(conn, guild_id, user_id)
        if not player_row:
            msg = "❌ Bạn chưa có player profile." if lang == "vi" else "❌ You don't have a player profile yet."
            return None, msg, True, None

        _, _, _, _, _, _, gold = map(int, player_row)
        if gold < cost:
            msg = f"❌ Cần {cost} {CURRENCY_ICON} Slime Coin, bạn chỉ có {gold} {CURRENCY_ICON} Slime Coin." if lang == "vi" else f"❌ Need {cost} {CURRENCY_ICON} Slime Coin, you only have {gold}."
            return None, msg, True, None

        pity_count, _ = await get_gacha_pity(conn, guild_id, user_id)

        await conn.execute(
            "UPDATE players SET gold = gold - ? WHERE guild_id = ? AND user_id = ?",
            (cost, guild_id, user_id),
        )

        results: list[tuple[str, str]] = []
        duplicates: list[str] = []
        pull_rows: list[dict] = []
        legendary_progress_ids: list[str] = []
        seen_legendary_ids: set[str] = set()

        for idx in range(pulls):
            char_id, rarity = roll_character(pity_count, banner_id=banner_id)
            pity_count = 0 if rarity in {"legendary", "mythic"} else pity_count + 1
            char_meta = CHARACTERS.get(char_id, {})
            char_name = str(char_meta.get("name", char_id))
            char_form = str(char_meta.get("form", "Base"))
            char_emoji = _character_display_emoji(char_meta, rarity, fallback="")
            if str(char_meta.get("rarity", "")).lower() == "legendary" and char_id not in seen_legendary_ids:
                seen_legendary_ids.add(char_id)
                legendary_progress_ids.append(char_id)

            is_duplicate = False
            try:
                await conn.execute(
                    """
                    INSERT INTO player_characters(guild_id, user_id, character_id, is_main, level, exp, star, shard_count, obtained_at)
                    VALUES (?, ?, ?, 0, 1, 0, 1, 0, ?)
                    """,
                    (guild_id, user_id, char_id, int(time.time())),
                )
            except Exception:
                await conn.execute(
                    """
                    INSERT INTO player_characters(guild_id, user_id, character_id, is_main, level, exp, star, shard_count, obtained_at)
                    VALUES (?, ?, ?, 0, 1, 0, 1, ?, ?)
                    ON CONFLICT(guild_id, user_id, character_id)
                    DO UPDATE SET shard_count = shard_count + excluded.shard_count
                    """,
                    (guild_id, user_id, char_id, DUPLICATE_SHARD_VALUE, int(time.time())),
                )
                duplicates.append(char_id)
                is_duplicate = True

            results.append((char_id, rarity))
            pull_rows.append(
                {
                    "index": idx + 1,
                    "character_id": char_id,
                    "name": char_name,
                    "form": char_form,
                    "rarity": str(rarity).lower(),
                    "emoji": char_emoji,
                    "is_duplicate": is_duplicate,
                }
            )

        from .repositories import quest_repo

        await quest_repo.add_quest_progress(conn, guild_id, user_id, "summon_times", pulls)
        await update_gacha_pity(conn, guild_id, user_id, pity_count)
        await conn.commit()

        rarity_rank = {"mythic": 5, "legendary": 4, "epic": 3, "rare": 2, "uncommon": 1, "common": 0}
        sorted_results = sorted(results, key=lambda x: rarity_rank.get(str(x[1]).lower(), -1), reverse=True)
        top_id, top_rarity = sorted_results[0]
        top_meta = CHARACTERS.get(top_id, {})
        top_name = str(top_meta.get("name", top_id))
        top_form = str(top_meta.get("form", "Base"))
        top_emoji = _character_display_emoji(top_meta, top_rarity, fallback="")

        grouped_lines: dict[str, list[str]] = defaultdict(list)
        for char_id, rarity in sorted_results:
            char = CHARACTERS.get(char_id, {})
            name = str(char.get("name", char_id))
            form = str(char.get("form", "Base"))
            emoji = _character_display_emoji(char, rarity, fallback="")
            grouped_lines[str(rarity).lower()].append(f"{emoji + ' ' if emoji else ''}**{name} [{form}]**")

        pity_now = int(pity_count)
        pity_bar = progress_bar(pity_now, HARD_PITY, 12)

        embed = panel_embed(
            mode="Recruitment Portal",
            title=f"🌌 Dimensional Recruitment • {pulls}x",
            description=("A rift opens and heroes answer your summon." if lang == "en" else "Cổng không gian mở ra, các anh hùng đáp lại lời triệu hồi."),
            theme="gacha",
        )
        embed.add_field(
            name="⭐ Featured Pull",
            value=f"{rarity_icon(top_rarity)} {top_emoji + ' ' if top_emoji else ''}**{top_name} [{top_form}]** • {str(top_rarity).title()}",
            inline=False,
        )
        if banner_id != "none":
            banner_name = str(GACHA_BANNERS.get(banner_id, {}).get("name", banner_id))
            embed.add_field(name="🎯 Active Banner", value=f"**{banner_name}** (`{banner_id}`)", inline=False)

        for rarity in ("mythic", "legendary", "epic", "rare", "common"):
            rows = grouped_lines.get(rarity, [])
            if rows:
                embed.add_field(name=f"{rarity_icon(rarity)} {rarity.title()} • {len(rows)}", value="\n".join(rows[:6]), inline=False)

        if duplicates:
            shard_bonus = len(duplicates) * DUPLICATE_SHARD_VALUE
            embed.add_field(name="🧩 Duplicate Conversion", value=f"+{shard_bonus} shards", inline=False)

        if legendary_progress_ids:
            progress_lines: list[str] = []
            for lid in legendary_progress_ids:
                c = CHARACTERS.get(lid, {})
                line = str(c.get("evolution_line", ""))
                mythic_id = get_mythic_form_for_line(line)
                async with conn.execute(
                    "SELECT shard_count FROM player_characters WHERE guild_id = ? AND user_id = ? AND character_id = ?",
                    (guild_id, user_id, lid),
                ) as cur:
                    row = await cur.fetchone()
                shards = int(row[0]) if row else 0
                ascended = False
                if mythic_id:
                    async with conn.execute(
                        "SELECT 1 FROM player_characters WHERE guild_id = ? AND user_id = ? AND character_id = ?",
                        (guild_id, user_id, mythic_id),
                    ) as cur:
                        ascended = (await cur.fetchone()) is not None
                status = "ascended" if ascended else f"{shards}/{MYTHIC_ASCEND_LEGENDARY_SHARDS}"
                progress_lines.append(f"• {c.get('name', lid)}: {status}")
            embed.add_field(name="🌠 Mythic Path", value="\n".join(progress_lines), inline=False)

        embed.add_field(
            name="🧭 Pity Tracker",
            value=f"Current: **{pity_now}** • Soft: **{SOFT_PITY}** • Hard: **{HARD_PITY}**\n`{pity_bar}`",
            inline=False,
        )

        hint = "💡 Use `/ascend_mythic <legendary_id>` to manually ascend Mythic when ready."
        if lang == "vi":
            hint = "💡 Dùng `/ascend_mythic <legendary_id>` để ghép Mythic thủ công khi sẵn sàng."
        embed.add_field(name="Tip", value=hint, inline=False)

        card_file: discord.File | None = None
        if guild is not None:
            banner_name = str(GACHA_BANNERS.get(banner_id, {}).get("name", "Standard Rift"))
            card_buffer = await render_gacha_card(
                player_name=player_name,
                pulls=pull_rows,
                guild=guild,
                pull_count=pulls,
                banner_name=banner_name,
                pity_now=pity_now,
                soft_pity=SOFT_PITY,
                hard_pity=HARD_PITY,
                cost=cost,
                duplicate_shard_value=DUPLICATE_SHARD_VALUE,
                lang=lang,
            )
            if card_buffer is not None:
                card_file = discord.File(fp=card_buffer, filename="gacha_card.png")
                embed.set_image(url="attachment://gacha_card.png")

        return embed, None, False, card_file


async def handle_team(
    guild_id: int,
    user_id: int,
    owner_name: str,
    guild: discord.Guild | None = None,
    action: str = "view",
    character_id: str | None = None,
    slot: int = 1,
    lang: str = "en",
) -> tuple[discord.Embed | None, TeamMemberDetailView | None, str | None, bool, discord.File | None]:
    act = str(action or "view").strip().lower()
    if act == "deploy":
        act = "add"
    async with open_db() as conn:
        if act == "view":
            main = await get_main_character(conn, guild_id, user_id)
            team_chars = await get_team(conn, guild_id, user_id)
            if not main and not team_chars:
                msg = "❌ Bạn chưa có Captain. Dùng `/create_character` trước." if lang == "vi" else "❌ You don't have a Captain yet. Use `/create_character` first."
                return None, None, msg, True, None

            detail_members: list[dict] = []
            total_power = 0.0
            if main:
                m_power = calculate_team_power(int(main[10]), int(main[11]), int(main[12]), int(main[3]), int(main[5]))
                total_power += m_power
                mc = CHARACTERS.get(str(main[1]), {})
                mform = str(mc.get("form", "Base"))
                detail_members.append(
                    {
                        "slot": 0,
                        "is_main": True,
                        "character_id": str(main[1]),
                        "name": str(main[7]),
                        "form": mform,
                        "rarity": str(main[8]),
                        "role": str(main[9]),
                        "level": int(main[3]),
                        "star": int(main[5]),
                        "hp": int(main[10]),
                        "attack": int(main[11]),
                        "defense": int(main[12]),
                        "speed": int(main[13]),
                        "passive_skill": str(main[14] or ""),
                    }
                )

            for row in team_chars:
                s, cid, name, rarity, role, hp, atk, defn, spd, passive, lvl, star = row
                total_power += calculate_team_power(hp, atk, defn, lvl, star)
                cc = CHARACTERS.get(str(cid), {})
                form = str(cc.get("form", "Base"))
                detail_members.append(
                    {
                        "slot": int(s),
                        "is_main": False,
                        "character_id": str(cid),
                        "name": str(name),
                        "form": form,
                        "rarity": str(rarity),
                        "role": str(role),
                        "level": int(lvl),
                        "star": int(star),
                        "hp": int(hp),
                        "attack": int(atk),
                        "defense": int(defn),
                        "speed": int(spd),
                        "passive_skill": str(passive or ""),
                    }
                )

            front, back = split_formation(detail_members)
            captain_name = next((m.get("name", "None") for m in detail_members if m.get("is_main")), "None")
            embed = panel_embed(
                mode="Team Formation",
                title="⚔️ Squad Formation" if lang == "en" else "⚔️ Đội hình chiến đấu",
                description="Deploy your frontline and backline before entering hostile operations.",
                theme="team",
            )
            embed.add_field(name="👑 Captain", value=f"**{captain_name}**", inline=True)
            embed.add_field(name="💪 Team Power", value=f"**{int(total_power)}**", inline=True)
            embed.add_field(name="👥 Squad Size", value=f"**{len(detail_members)}/5**", inline=True)
            embed.add_field(name="🛡️ Frontline", value="\n".join(front) if front else "No frontline", inline=True)
            embed.add_field(name="🎯 Backline", value="\n".join(back) if back else "No backline", inline=True)
            view = TeamMemberDetailView(owner_name, detail_members, lang=lang) if detail_members else None
            card_file: discord.File | None = None
            if guild is not None:
                card_members = await _enrich_team_members_for_card(guild_id, user_id, detail_members)
                team_card_buffer = await render_team_card(owner_name, card_members, guild, lang=lang)
                if team_card_buffer is not None:
                    card_file = discord.File(fp=team_card_buffer, filename="team_card.png")
                    embed.set_image(url="attachment://team_card.png")
            return embed, view, None, False, card_file

        if act == "add":
            if not character_id:
                msg = "❌ Cần ID hero." if lang == "vi" else "❌ Hero ID is required."
                return None, None, msg, True, None

            main = await get_main_character(conn, guild_id, user_id)
            if not main:
                msg = "❌ Bạn chưa có Captain. Dùng `/create_character` trước." if lang == "vi" else "❌ You don't have a Captain yet. Use `/create_character` first."
                return None, None, msg, True, None

            owned = await get_player_characters(conn, guild_id, user_id)
            owned_ids = {str(row[1]) for row in owned}

            if character_id not in owned_ids:
                msg = "❌ Bạn không sở hữu hero này." if lang == "vi" else "❌ You don't own this hero."
                return None, None, msg, True, None

            if character_id == str(main[1]):
                msg = "❌ Captain đã cố định, không thêm vào hero slot." if lang == "vi" else "❌ Captain is fixed and cannot be added to hero slots."
                return None, None, msg, True, None

            team_chars = await get_team(conn, guild_id, user_id)
            if any(str(row[1]) == character_id for row in team_chars):
                msg = "❌ Hero này đã có trong team." if lang == "vi" else "❌ This hero is already in your team."
                return None, None, msg, True, None

            slot = max(1, min(4, slot))
            await set_team_character(conn, guild_id, user_id, slot, character_id)
            await conn.commit()

            char = CHARACTERS.get(character_id, {})
            msg = f"✅ Đã thêm **{char.get('name', character_id)}** vào hero slot {slot}." if lang == "vi" else f"✅ Added **{char.get('name', character_id)}** to hero slot {slot}."
            return None, None, msg, False, None

        if act == "reset":
            await clear_team(conn, guild_id, user_id)
            await conn.commit()
            msg = "✅ Đã reset team." if lang == "vi" else "✅ Team has been reset."
            return None, None, msg, False, None

        msg = "❌ Action không hợp lệ. Dùng: view, deploy, reset" if lang == "vi" else "❌ Invalid action. Use: view, deploy, reset"
        return None, None, msg, True, None


async def handle_my_characters(guild_id: int, user_id: int, lang: str = "en") -> tuple[discord.Embed | None, str | None, bool]:
    async with open_db() as conn:
        chars = await get_player_characters(conn, guild_id, user_id)
        if not chars:
            msg = "❌ Bạn chưa có hero nào. Dùng `/create_character` hoặc `/gacha`." if lang == "vi" else "❌ You don't own any heroes yet. Use `/create_character` or `/gacha`."
            return None, msg, True

        owned_ids = {str(r[1]) for r in chars}
        lines = []
        for row in chars:
            _, cid, is_main, level, _, star, shard, name, rarity, role, _ = row
            c = CHARACTERS.get(str(cid), {})
            form = str(c.get("form", "Base"))
            emoji = "⭐" if is_main else "  "
            ascend = _legendary_ascend_status(str(cid), int(shard), owned_ids)
            lines.append(
                f"{emoji} **{name} [{form}]** (`{cid}`) Lv.{level} ★{star} | {rarity.title()} | {role} | shard {int(shard)}{ascend}"
            )

        embed = discord.Embed(
            title="🎭 Hero Collection",
            description="\n".join(lines),
            color=discord.Color.blue(),
        )
        return embed, None, False


async def handle_ascend_mythic(guild_id: int, user_id: int, legendary_id: str, lang: str = "en") -> tuple[str, bool]:
    lid = str(legendary_id or "").strip().lower()
    char = CHARACTERS.get(lid)
    if not char:
        msg = "❌ Character ID không tồn tại." if lang == "vi" else "❌ Character ID does not exist."
        return msg, True
    if str(char.get("rarity", "")).lower() != "legendary":
        msg = "❌ Chỉ ghép từ bản **legendary**." if lang == "vi" else "❌ Only **legendary** form can ascend."
        return msg, True

    line = str(char.get("evolution_line", ""))
    mythic_id = get_mythic_form_for_line(line)
    if not mythic_id:
        msg = "❌ Character này chưa có mythic form." if lang == "vi" else "❌ This character has no mythic form yet."
        return msg, True

    async with open_db() as conn:
        async with conn.execute(
            "SELECT 1 FROM player_characters WHERE guild_id = ? AND user_id = ? AND character_id = ?",
            (guild_id, user_id, lid),
        ) as cur:
            has_legend = await cur.fetchone()
        if not has_legend:
            msg = "❌ Bạn chưa sở hữu bản legendary này." if lang == "vi" else "❌ You don't own this legendary yet."
            return msg, True

        async with conn.execute(
            "SELECT shard_count FROM player_characters WHERE guild_id = ? AND user_id = ? AND character_id = ?",
            (guild_id, user_id, lid),
        ) as cur:
            row = await cur.fetchone()
        shards = int(row[0]) if row else 0

        unlocked = await _try_ascend_mythic(conn, guild_id, user_id, lid)
        if not unlocked:
            await conn.commit()
            msg = f"❌ Chưa đủ mảnh hoặc đã có mythic. Tiến độ: **{shards}/{MYTHIC_ASCEND_LEGENDARY_SHARDS}**"
            if lang == "en":
                msg = f"❌ Not enough shards or mythic already unlocked. Progress: **{shards}/{MYTHIC_ASCEND_LEGENDARY_SHARDS}**"
            return msg, True

        await conn.commit()

    m = CHARACTERS.get(unlocked, {})
    ok_msg = (
        f"🌌 Ascension thành công: **{m.get('name', unlocked)} [{m.get('form', 'Mythic')}]**\n"
        f"Tiêu hao: {MYTHIC_ASCEND_LEGENDARY_SHARDS} mảnh từ `{lid}`"
    )
    if lang == "en":
        ok_msg = (
            f"🌌 Ascension success: **{m.get('name', unlocked)} [{m.get('form', 'Mythic')}]**\n"
            f"Cost: {MYTHIC_ASCEND_LEGENDARY_SHARDS} shards from `{lid}`"
        )
    return ok_msg, False


async def autocomplete_item(_: discord.Interaction, current: str):
    q = current.lower().strip()
    out: list[app_commands.Choice[str]] = []
    for key, item in ITEMS.items():
        label = f"{item['emoji']} {item['name']} ({key})"
        hay = f"{key} {item['name']}".lower()
        if q and q not in hay:
            continue
        out.append(app_commands.Choice(name=label[:100], value=key))
    return out[:25]


async def autocomplete_recipe(_: discord.Interaction, current: str):
    q = current.lower().strip()
    out: list[app_commands.Choice[str]] = []
    for r in CRAFT_RECIPES:
        rid = str(r.get("id", ""))
        name = str(r.get("name", rid))
        hay = f"{rid} {name}".lower()
        if q and q not in hay:
            continue
        out.append(app_commands.Choice(name=f"{name} ({rid})"[:100], value=rid))
    return out[:25]


async def autocomplete_skill(_: discord.Interaction, current: str):
    q = current.lower().strip()
    out: list[app_commands.Choice[str]] = []
    for sid, skill in SKILLS.items():
        name = str(skill.get("name", sid))
        hay = f"{sid} {name}".lower()
        if q and q not in hay:
            continue
        out.append(app_commands.Choice(name=f"{name} ({sid})"[:100], value=sid))
    return out[:25]


async def autocomplete_owned_character(interaction: discord.Interaction, current: str):
    if interaction.guild is None:
        return []
    q = str(current or "").lower().strip()
    async with open_db() as conn:
        rows = await get_player_characters(conn, interaction.guild.id, interaction.user.id)

    out: list[app_commands.Choice[str]] = []
    for row in rows:
        cid = str(row[1])
        name = str(row[7])
        rarity = str(row[8])
        role = normalize_role(str(row[9]))
        form = str(CHARACTERS.get(cid, {}).get("form", "Base"))
        hay = f"{cid} {name} {form} {role}".lower()
        if q and q not in hay:
            continue
        label = f"{rarity_icon(rarity)} {name} [{form}] ({cid})"
        out.append(app_commands.Choice(name=label[:100], value=cid))
    return out[:25]


async def autocomplete_dungeon_node_id(interaction: discord.Interaction, current: str):
    if interaction.guild is None:
        return []
    lang = await resolve_lang(interaction)
    state = await DungeonRunService.get_state(interaction.guild.id, interaction.user.id, lang=lang)
    if not state.ok:
        return []
    q = str(current or "").lower().strip()
    out: list[app_commands.Choice[str]] = []
    for n in state.nodes:
        if bool(n.get("resolved", False)):
            continue
        nid = str(n.get("node_id", ""))
        ntype = str(n.get("node_type", "combat"))
        danger = int(n.get("danger", 1))
        label = f"{_dungeon_node_icon(ntype)} {nid} • {ntype} • D{danger}"
        hay = f"{nid} {ntype} {danger}".lower()
        if q and q not in hay:
            continue
        out.append(app_commands.Choice(name=label[:100], value=nid))
    return out[:25]


async def autocomplete_dungeon_choice_id(interaction: discord.Interaction, current: str):
    if interaction.guild is None:
        return []
    lang = await resolve_lang(interaction)
    state = await DungeonRunService.get_state(interaction.guild.id, interaction.user.id, lang=lang)
    if not state.ok:
        return []
    opts = state.pending_choice.get("options", []) if isinstance(state.pending_choice, dict) else []
    q = str(current or "").lower().strip()
    out: list[app_commands.Choice[str]] = []
    for o in opts:
        cid = str(o.get("choice_id", ""))
        title = str(o.get("title", cid))
        tradeoff = str(o.get("tradeoff", ""))
        hay = f"{cid} {title} {tradeoff}".lower()
        if q and q not in hay:
            continue
        out.append(app_commands.Choice(name=f"{title} ({cid})"[:100], value=cid))
    return out[:25]


def setup(bot: commands.Bot, guilds: list = None):
    guilds = guilds or []
    _patch_interaction_response_emoji_support()

    async def _rpg_rate_limit_check(interaction: discord.Interaction) -> bool:
        cmd = interaction.command
        cmd_name = str(getattr(cmd, "name", "")).strip().lower()
        root_parent = getattr(cmd, "root_parent", None)
        root_name = str(getattr(root_parent, "name", "")).strip().lower()
        if cmd_name not in RPG_COMMAND_NAMES and root_name not in RPG_COMMAND_NAMES:
            return True

        now_ts = time.time()
        lang = await resolve_lang(interaction)
        user_wait = _rate_check(_USER_RATE_BUCKET, interaction.user.id, now_ts, RPG_COMMAND_RATE_USER_WINDOW, RPG_COMMAND_RATE_USER_MAX)
        if user_wait > 0:
            msg = (
                f"⏳ Bạn thao tác RPG quá nhanh. Thử lại sau {user_wait:.1f}s."
                if lang == "vi"
                else f"⏳ You're using RPG commands too fast. Try again in {user_wait:.1f}s."
            )
            raise app_commands.CheckFailure(msg)

        if interaction.guild is not None:
            guild_wait = _rate_check(_GUILD_RATE_BUCKET, interaction.guild.id, now_ts, RPG_COMMAND_RATE_GUILD_WINDOW, RPG_COMMAND_RATE_GUILD_MAX)
            if guild_wait > 0:
                msg = (
                    f"⏳ Server đang spam RPG command. Thử lại sau {guild_wait:.1f}s."
                    if lang == "vi"
                    else f"⏳ This server is spamming RPG commands. Try again in {guild_wait:.1f}s."
                )
                raise app_commands.CheckFailure(msg)
        
        cmd = interaction.command
        cmd_name = str(getattr(cmd, "name", "")).strip().lower()
        root_parent = getattr(cmd, "root_parent", None)
        root_name = str(getattr(root_parent, "name", "")).strip().lower()
        if cmd_name in RPG_STARTED_COMMANDS or root_name in RPG_STARTED_COMMANDS:
            if not await _check_player_registered(interaction):
                return False
        
        return True

    bot.tree.interaction_check = _rpg_rate_limit_check

    async def _on_ready_once():
        await ensure_db_ready()

    bot.add_listener(_on_ready_once, "on_ready")
    try:
        bot.add_view(DungeonPersistentRouterView())
    except Exception:
        pass

    @bot.tree.command(name="rpg_start", description=app_commands.locale_str("cmd.rpg_start.desc"))
    async def rpg_start(interaction: discord.Interaction):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await interaction.response.send_message(tr(lang, "common.server_only"), ephemeral=True)
        msg = await handle_rpg_start(interaction.guild.id, interaction.user.id, lang=lang)
        await interaction.response.send_message(msg, ephemeral=True)

    @bot.tree.command(name="profile", description=app_commands.locale_str("cmd.profile.desc"))
    @app_commands.describe(member=app_commands.locale_str("cmd.profile.param.member"))
    async def profile(interaction: discord.Interaction, member: Optional[discord.Member] = None):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await interaction.response.send_message(tr(lang, "common.server_only"), ephemeral=True)
        target = _member_or_self(interaction, member)
        if target is None:
            return await interaction.response.send_message(tr(lang, "common.member_unknown"), ephemeral=True)

        e, view, err = await handle_profile(interaction.guild.id, target, lang=lang, stats_mode=False)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        await interaction.response.send_message(embed=e, view=view)
        if view is not None:
            try:
                view.message = await interaction.original_response()
            except Exception:
                pass

    @bot.tree.command(name="stats", description=app_commands.locale_str("cmd.stats.desc"))
    @app_commands.describe(member=app_commands.locale_str("cmd.stats.param.member"))
    async def stats(interaction: discord.Interaction, member: Optional[discord.Member] = None):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await interaction.response.send_message(tr(lang, "common.server_only"), ephemeral=True)
        target = _member_or_self(interaction, member)
        if target is None:
            return await interaction.response.send_message(tr(lang, "common.member_unknown"), ephemeral=True)

        e, view, err = await handle_profile(interaction.guild.id, target, lang=lang, stats_mode=True)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        await interaction.response.send_message(embed=e, view=view)
        if view is not None:
            try:
                view.message = await interaction.original_response()
            except Exception:
                pass

    @bot.tree.command(name="rpg_daily", description=app_commands.locale_str("cmd.rpg_daily.desc"))
    async def rpg_daily(interaction: discord.Interaction):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await interaction.response.send_message(tr(lang, "common.server_only"), ephemeral=True)
        result = await EconomyService.claim_daily(interaction.guild.id, interaction.user.id, lang=lang)
        await interaction.response.send_message(result.message, ephemeral=True)

    @bot.tree.command(name="rpg_pay", description=app_commands.locale_str("cmd.rpg_pay.desc"))
    @app_commands.describe(member=app_commands.locale_str("cmd.rpg_pay.param.member"), amount=app_commands.locale_str("cmd.rpg_pay.param.amount"))
    async def rpg_pay(interaction: discord.Interaction, member: discord.Member, amount: int):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await interaction.response.send_message(tr(lang, "common.server_only"), ephemeral=True)
        if member.bot or member.id == interaction.user.id:
            msg = "❌ Người nhận không hợp lệ." if lang == "vi" else "❌ Invalid recipient."
            return await interaction.response.send_message(msg, ephemeral=True)
        if amount <= 0:
            msg = "❌ Amount phải > 0." if lang == "vi" else "❌ Amount must be > 0."
            return await interaction.response.send_message(msg, ephemeral=True)

        result = await EconomyService.transfer_gold(interaction.guild.id, interaction.user.id, member.id, amount, lang=lang)
        if result.ok:
            msg = f"💸 Đã chuyển **{amount}** {CURRENCY_ICON} Slime Coin cho {member.mention}" if lang == "vi" else f"💸 Transferred **{amount}** {CURRENCY_ICON} Slime Coin to {member.mention}"
            await interaction.response.send_message(msg)
        else:
            await interaction.response.send_message(result.message, ephemeral=True)

    @bot.tree.command(name="rpg_shop", description=app_commands.locale_str("cmd.rpg_shop.desc"))
    async def rpg_shop(interaction: discord.Interaction):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        category = "main"
        view = ShopCategoryView(current_category=category, lang=lang)
        e, card_file = await _build_shop_embed_and_card(category, interaction.guild, lang)
        if card_file is not None:
            await interaction.response.send_message(embed=e, view=view, file=card_file)
        else:
            await interaction.response.send_message(embed=e, view=view)
        try:
            view.message = await interaction.original_response()
        except Exception:
            pass

    @bot.tree.command(name="shop", description=app_commands.locale_str("cmd.shop.desc"))
    @app_commands.describe(category=app_commands.locale_str("cmd.shop.param.category"))
    async def rpg_shop_category(interaction: discord.Interaction, category: str = "main"):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        selected = _normalize_shop_category_input(category)
        view = ShopCategoryView(current_category=selected, lang=lang)
        e, card_file = await _build_shop_embed_and_card(selected, interaction.guild, lang)
        if card_file is not None:
            await interaction.response.send_message(embed=e, view=view, file=card_file)
        else:
            await interaction.response.send_message(embed=e, view=view)
        try:
            view.message = await interaction.original_response()
        except Exception:
            pass

    @bot.tree.command(name="craft_list", description=app_commands.locale_str("cmd.craft_list.desc"))
    async def craft_list(interaction: discord.Interaction):
        lang = await resolve_lang(interaction)
        e = _build_craft_recipes_embed(lang)
        await interaction.response.send_message(embed=e)

    @bot.tree.command(name="craft", description=app_commands.locale_str("cmd.craft.desc"))
    @app_commands.describe(recipe_id=app_commands.locale_str("cmd.craft.param.recipe_id"), amount=app_commands.locale_str("cmd.craft.param.amount"))
    @app_commands.autocomplete(recipe_id=autocomplete_recipe)
    async def craft(interaction: discord.Interaction, recipe_id: str, amount: int = 1):
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        lang = await resolve_lang(interaction)
        result = await EconomyService.craft_item(interaction.guild.id, interaction.user.id, recipe_id, amount, lang=lang)
        e = panel_embed(
            mode="Forge Recipes",
            title=("✅ Forge Complete" if result.ok else "❌ Forge Failed"),
            description=result.message,
            theme="victory" if result.ok else "defeat",
        )
        await interaction.response.send_message(embed=e, ephemeral=True)

    @bot.tree.command(name="rpg_buy", description=app_commands.locale_str("cmd.rpg_buy.desc"))
    @app_commands.describe(item=app_commands.locale_str("cmd.rpg_buy.param.item"), amount=app_commands.locale_str("cmd.rpg_buy.param.amount"))
    @app_commands.autocomplete(item=autocomplete_item)
    async def rpg_buy(interaction: discord.Interaction, item: str, amount: int = 1):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        ok, msg = await EconomyService.buy_item(interaction.guild.id, interaction.user.id, item, amount, lang=lang)
        if ok:
            e = panel_embed(
                mode="Quartermaster Bazaar",
                title=("✅ Supply Acquired" if lang == "en" else "✅ Tiếp tế thành công"),
                description=msg,
                theme="victory",
            )
            await interaction.response.send_message(embed=e)
        else:
            await interaction.response.send_message(f"❌ {msg}", ephemeral=True)

    @bot.tree.command(name="rpg_sell", description=app_commands.locale_str("cmd.rpg_sell.desc"))
    @app_commands.describe(item=app_commands.locale_str("cmd.rpg_sell.param.item"), amount=app_commands.locale_str("cmd.rpg_sell.param.amount"), location=app_commands.locale_str("cmd.rpg_sell.param.location"))
    @app_commands.autocomplete(item=autocomplete_item)
    async def rpg_sell(interaction: discord.Interaction, item: str, amount: int = 1, location: str = "normal"):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        
        from .shop import can_sell_normal, can_sell_blackmarket, get_sell_price
        
        if location == "blackmarket":
            if not can_sell_blackmarket(item):
                msg = "❌ Item này không thể bán ở chợ đen." if lang == "vi" else "❌ This item cannot be sold in black market."
                return await interaction.response.send_message(
                    msg, ephemeral=True
                )
            price = get_sell_price(item, black_market=True)
        else:
            if not can_sell_normal(item):
                msg = (
                    f"❌ Item này không thể bán ở shop thường.\nThử `/sell {item} blackmarket` để bán ở chợ đen với giá 60%."
                    if lang == "vi"
                    else f"❌ This item cannot be sold in normal shop.\nTry `/sell {item} blackmarket` to sell in black market at 60% price."
                )
                return await interaction.response.send_message(
                    msg,
                    ephemeral=True
                )
            price = get_sell_price(item)
        
        ok, msg, _ = await EconomyService.sell_item(
            interaction.guild.id, interaction.user.id, item, amount, 
            black_market=(location == "blackmarket"),
            lang=lang,
        )
        await interaction.response.send_message(msg if ok else f"❌ {msg}", ephemeral=not ok)

    @bot.tree.command(name="rpg_inventory", description=app_commands.locale_str("cmd.rpg_inventory.desc"))
    @app_commands.describe(member=app_commands.locale_str("cmd.rpg_inventory.param.member"))
    async def rpg_inventory(interaction: discord.Interaction, member: Optional[discord.Member] = None):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        target = _member_or_self(interaction, member)
        if target is None:
            lang = await resolve_lang(interaction)
            return await interaction.response.send_message(tr(lang, "common.member_unknown"), ephemeral=True)

        items = await PlayerService.get_inventory(interaction.guild.id, target.id)
        if not items:
            msg = f"🎒 {target.mention} chưa có item RPG." if lang == "vi" else f"🎒 {target.mention} has no RPG items."
            return await interaction.response.send_message(msg)

        e = _build_inventory_embed(target, items, lang)
        await interaction.response.send_message(embed=e)

    @bot.tree.command(name="rpg_equipment", description=app_commands.locale_str("cmd.rpg_equipment.desc"))
    @app_commands.describe(member=app_commands.locale_str("cmd.rpg_equipment.param.member"), character_id=app_commands.locale_str("cmd.team.param.character_id"))
    @app_commands.autocomplete(character_id=autocomplete_owned_character)
    async def rpg_equipment(interaction: discord.Interaction, member: Optional[discord.Member] = None, character_id: str = ""):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        target = _member_or_self(interaction, member)
        if target is None:
            return await interaction.response.send_message(tr(lang, "common.member_unknown"), ephemeral=True)

        selected_cid = str(character_id or "").strip().lower() or None
        result = await PlayerService.get_equipment(interaction.guild.id, target.id, character_id=selected_cid)
        if not result.ok and selected_cid:
            msg = "❌ Hero không tồn tại hoặc không thuộc người chơi này." if lang == "vi" else "❌ Hero does not exist or is not owned by this player."
            return await interaction.response.send_message(msg, ephemeral=True)
        hero_title = None
        if selected_cid:
            c = CHARACTERS.get(selected_cid, {})
            hero_title = f"{c.get('emoji', '🎮')} **{c.get('name', selected_cid)} [{c.get('form', 'Base')}]** (`{selected_cid}`)"
        e = _build_loadout_embed(target, result, lang="vi" if str(lang).lower().startswith("vi") else "en", character_title=hero_title)
        await interaction.response.send_message(embed=e)

    @bot.tree.command(name="equip", description=app_commands.locale_str("cmd.equip.desc"))
    @app_commands.describe(item=app_commands.locale_str("cmd.equip.param.item"), character_id=app_commands.locale_str("cmd.team.param.character_id"))
    @app_commands.autocomplete(item=autocomplete_item, character_id=autocomplete_owned_character)
    async def equip(interaction: discord.Interaction, item: str, character_id: str = ""):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        e, msg, ephemeral = await handle_equip_action(
            interaction.guild.id,
            interaction.user.id,
            item=item,
            character_id=character_id,
            lang=lang,
        )
        if msg:
            return await interaction.response.send_message(msg, ephemeral=ephemeral)
        await interaction.response.send_message(embed=e)

    @bot.tree.command(name="unequip", description=app_commands.locale_str("cmd.unequip.desc"))
    @app_commands.describe(slot=app_commands.locale_str("cmd.unequip.param.slot"), character_id=app_commands.locale_str("cmd.team.param.character_id"))
    @app_commands.autocomplete(character_id=autocomplete_owned_character)
    async def unequip(interaction: discord.Interaction, slot: str, character_id: str = ""):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        e, msg, ephemeral = await handle_unequip_action(
            interaction.guild.id,
            interaction.user.id,
            slot=slot,
            character_id=character_id,
            lang=lang,
        )
        if msg:
            return await interaction.response.send_message(msg, ephemeral=ephemeral)
        await interaction.response.send_message(embed=e)

    @bot.tree.command(name="rpg_skills", description=app_commands.locale_str("cmd.rpg_skills.desc"))
    async def rpg_skills(interaction: discord.Interaction):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        data = await PlayerService.get_skills(interaction.guild.id, interaction.user.id)
        level = data["level"]
        unlocked = data["unlocked"]
        e = _build_skills_embed(level, unlocked, lang)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @bot.tree.command(name="rpg_skill_unlock", description=app_commands.locale_str("cmd.rpg_skill_unlock.desc"))
    @app_commands.describe(skill_id=app_commands.locale_str("cmd.rpg_skill_unlock.param.skill_id"))
    @app_commands.autocomplete(skill_id=autocomplete_skill)
    async def rpg_skill_unlock(interaction: discord.Interaction, skill_id: str):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        result = await PlayerService.unlock_skill(interaction.guild.id, interaction.user.id, skill_id, lang=lang)
        await interaction.response.send_message(result.message, ephemeral=True)

    @bot.tree.command(name="rpg_skill_use", description=app_commands.locale_str("cmd.rpg_skill_use.desc"))
    @app_commands.describe(skill_id=app_commands.locale_str("cmd.rpg_skill_use.param.skill_id"))
    @app_commands.autocomplete(skill_id=autocomplete_skill)
    async def rpg_skill_use(interaction: discord.Interaction, skill_id: str):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        result = await PlayerService.use_skill(interaction.guild.id, interaction.user.id, skill_id, lang=lang)
        await interaction.response.send_message(result.message)

    @bot.tree.command(name="rpg_use", description=app_commands.locale_str("cmd.rpg_use.desc"))
    @app_commands.describe(item=app_commands.locale_str("cmd.rpg_use.param.item"), amount=app_commands.locale_str("cmd.rpg_use.param.amount"))
    @app_commands.autocomplete(item=autocomplete_item)
    async def rpg_use(interaction: discord.Interaction, item: str, amount: int = 1):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        ok, msg = await EconomyService.use_item(interaction.guild.id, interaction.user.id, item, amount, lang=lang)
        await interaction.response.send_message(msg if ok else f"❌ {msg}", ephemeral=not ok)

    @bot.tree.command(name="open", description=app_commands.locale_str("cmd.open.desc"))
    @app_commands.describe(amount=app_commands.locale_str("cmd.open.param.amount"))
    async def open_lootbox(interaction: discord.Interaction, amount: int = 1):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        result = await EconomyService.open_lootbox(interaction.guild.id, interaction.user.id, amount, lang=lang)
        await interaction.response.send_message(result.message if result.ok else f"❌ {result.message}", ephemeral=not result.ok)

    @bot.tree.command(name="rpg_drop", description=app_commands.locale_str("cmd.rpg_drop.desc"))
    @app_commands.describe(item=app_commands.locale_str("cmd.rpg_drop.param.item"), amount=app_commands.locale_str("cmd.rpg_drop.param.amount"))
    @app_commands.autocomplete(item=autocomplete_item)
    async def rpg_drop(interaction: discord.Interaction, item: str, amount: int = 1):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        ok, msg = await EconomyService.drop_item(interaction.guild.id, interaction.user.id, item, amount, lang=lang)
        await interaction.response.send_message(msg if ok else f"❌ {msg}", ephemeral=not ok)

    @bot.tree.command(name="hunt", description=app_commands.locale_str("cmd.hunt.desc"))
    async def slash_hunt(interaction: discord.Interaction):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await interaction.response.send_message(tr(lang, "common.server_only"), ephemeral=True)
        await interaction.response.defer()
        embed, view, err, card_file = await handle_hunt(
            interaction.guild.id,
            interaction.user.id,
            interaction.user.display_name,
            guild=interaction.guild,
            lang=lang,
        )
        if err:
            return await _rpg_followup_send(interaction, err, ephemeral=True)
        if card_file is not None:
            await _rpg_followup_send(interaction, embed=embed, view=view, file=card_file)
        else:
            await _rpg_followup_send(interaction, embed=embed, view=view)
        view.message = await interaction.original_response()

    @bot.tree.command(name="boss", description=app_commands.locale_str("cmd.boss.desc"))
    async def boss(interaction: discord.Interaction):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await interaction.response.send_message(tr(lang, "common.server_only"), ephemeral=True)
        await interaction.response.defer()
        embed, view, err, card_file = await handle_boss(
            interaction.guild.id,
            interaction.user.id,
            interaction.user.display_name,
            guild=interaction.guild,
            lang=lang,
        )
        if err:
            return await _rpg_followup_send(interaction, err, ephemeral=True)
        if card_file is not None:
            await _rpg_followup_send(interaction, embed=embed, view=view, file=card_file)
        else:
            await _rpg_followup_send(interaction, embed=embed, view=view)
        view.message = await interaction.original_response()

    dungeon_group = app_commands.Group(name="dungeon", description=app_commands.locale_str("cmd.dungeon_group.desc"))

    @dungeon_group.command(name="start", description=app_commands.locale_str("cmd.dungeon.start.desc"))
    @app_commands.describe(difficulty=app_commands.locale_str("cmd.dungeon.start.param.difficulty"))
    async def dungeon_start(interaction: discord.Interaction, difficulty: str = "normal"):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await interaction.response.send_message(tr(lang, "common.server_only"), ephemeral=True)
        await interaction.response.defer()
        try:
            result = await DungeonRunService.start_run(interaction.guild.id, interaction.user.id, difficulty=difficulty, lang=lang)
        except Exception:
            logger.exception(
                "dungeon start crashed guild=%s user=%s difficulty=%s",
                interaction.guild.id,
                interaction.user.id,
                difficulty,
            )
            return await _rpg_followup_send(interaction, tr(lang, "unknown_error"), ephemeral=True)
        if not result.ok:
            logger.warning(
                "dungeon start rejected guild=%s user=%s difficulty=%s error=%s",
                interaction.guild.id,
                interaction.user.id,
                difficulty,
                result.error,
            )
            return await _rpg_followup_send(interaction, f"❌ {result.error}", ephemeral=True)
        e = _build_dungeon_start_embed(result, lang)
        state = await DungeonRunService.get_state(interaction.guild.id, interaction.user.id, lang=lang)
        view = DungeonControlView(interaction.guild.id, interaction.user.id, lang, state) if state.ok else None
        payload = _dungeon_start_card_payload(result, state if state.ok else None, lang)
        card_file = await _attach_dungeon_card(e, payload, interaction.guild, lang)
        if card_file is not None:
            sent = await _rpg_followup_send(interaction, embed=e, view=view, file=card_file, wait=True)
        else:
            sent = await _rpg_followup_send(interaction, embed=e, view=view, wait=True)
        if view is not None:
            view.message = sent

    @dungeon_group.command(name="status", description=app_commands.locale_str("cmd.dungeon.status.desc"))
    async def dungeon_status(interaction: discord.Interaction):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await interaction.response.send_message(tr(lang, "common.server_only"), ephemeral=True)
        state, resolved_embed = await _dungeon_status_with_pending_resolution(interaction.guild.id, interaction.user.id, lang=lang)
        if not state.ok:
            return await interaction.response.send_message(tr(lang, "rpg.dungeon.no_active"), ephemeral=True)
        e = resolved_embed if resolved_embed is not None else _build_dungeon_state_embed(state, lang)
        view = DungeonControlView(interaction.guild.id, interaction.user.id, lang, state)
        payload = _dungeon_state_card_payload(state, lang)
        card_file = await _attach_dungeon_card(e, payload, interaction.guild, lang)
        if card_file is not None:
            await interaction.response.send_message(embed=e, view=view, file=card_file)
        else:
            await interaction.response.send_message(embed=e, view=view)
        try:
            view.message = await interaction.original_response()
        except Exception:
            pass

    @dungeon_group.command(name="path", description=app_commands.locale_str("cmd.dungeon.path.desc"))
    @app_commands.describe(node_id=app_commands.locale_str("cmd.dungeon.path.param.node_id"))
    @app_commands.autocomplete(node_id=autocomplete_dungeon_node_id)
    async def dungeon_path(interaction: discord.Interaction, node_id: str):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await interaction.response.send_message(tr(lang, "common.server_only"), ephemeral=True)
        result = await DungeonRunService.choose_node(interaction.guild.id, interaction.user.id, node_id=node_id, lang=lang)
        if not result.ok:
            return await interaction.response.send_message(f"❌ {result.error}", ephemeral=True)
        e = _build_dungeon_node_result_embed(result, lang)
        next_view = None
        state = await DungeonRunService.get_state(interaction.guild.id, interaction.user.id, lang=lang)
        if result.next_phase in {"selecting_path", "choice", "resolving_node"}:
            if state.ok:
                next_view = DungeonControlView(interaction.guild.id, interaction.user.id, lang, state)
        payload = _dungeon_node_card_payload(result, state if state.ok else None, lang)
        card_file = await _attach_dungeon_card(e, payload, interaction.guild, lang)
        if card_file is not None:
            await interaction.response.send_message(embed=e, view=next_view, file=card_file)
        else:
            await interaction.response.send_message(embed=e, view=next_view)
        if next_view is not None:
            try:
                next_view.message = await interaction.original_response()
            except Exception:
                pass

    @dungeon_group.command(name="choice", description=app_commands.locale_str("cmd.dungeon.choice.desc"))
    @app_commands.describe(choice_id=app_commands.locale_str("cmd.dungeon.choice.param.choice_id"))
    @app_commands.autocomplete(choice_id=autocomplete_dungeon_choice_id)
    async def dungeon_choice(interaction: discord.Interaction, choice_id: str):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await interaction.response.send_message(tr(lang, "common.server_only"), ephemeral=True)
        result = await DungeonRunService.apply_choice(interaction.guild.id, interaction.user.id, choice_id=choice_id, lang=lang)
        if not result.ok:
            return await interaction.response.send_message(f"❌ {result.error}", ephemeral=True)
        e = panel_embed(
            mode="Dungeon Mode",
            title=tr(lang, "rpg.dungeon.choice_applied_title"),
            description=tr(lang, "rpg.dungeon.choice_applied_desc", choice_id=result.choice_id),
            theme="victory",
        )
        state = await DungeonRunService.get_state(interaction.guild.id, interaction.user.id, lang=lang)
        view = DungeonControlView(interaction.guild.id, interaction.user.id, lang, state) if state.ok else None
        payload = _dungeon_choice_card_payload(result, state if state.ok else None, lang)
        card_file = await _attach_dungeon_card(e, payload, interaction.guild, lang)
        if card_file is not None:
            await interaction.response.send_message(embed=e, view=view, file=card_file)
        else:
            await interaction.response.send_message(embed=e, view=view)
        if view is not None:
            try:
                view.message = await interaction.original_response()
            except Exception:
                pass

    @dungeon_group.command(name="retreat", description=app_commands.locale_str("cmd.dungeon.retreat.desc"))
    async def dungeon_retreat(interaction: discord.Interaction):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await interaction.response.send_message(tr(lang, "common.server_only"), ephemeral=True)
        result = await DungeonRunService.retreat(interaction.guild.id, interaction.user.id, lang=lang)
        if not result.ok:
            return await interaction.response.send_message(f"❌ {result.error}", ephemeral=True)
        e = _build_dungeon_finish_embed(result, lang)
        payload = _dungeon_finish_card_payload(result, lang)
        card_file = await _attach_dungeon_card(e, payload, interaction.guild, lang)
        if card_file is not None:
            await interaction.response.send_message(embed=e, file=card_file)
        else:
            await interaction.response.send_message(embed=e)

    @dungeon_group.command(name="claim", description=app_commands.locale_str("cmd.dungeon.claim.desc"))
    async def dungeon_claim(interaction: discord.Interaction):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await interaction.response.send_message(tr(lang, "common.server_only"), ephemeral=True)
        result = await DungeonRunService.claim_rewards(interaction.guild.id, interaction.user.id, lang=lang)
        if not result.ok:
            return await interaction.response.send_message(f"❌ {result.error}", ephemeral=True)
        e = _build_dungeon_finish_embed(result, lang)
        payload = _dungeon_finish_card_payload(result, lang)
        card_file = await _attach_dungeon_card(e, payload, interaction.guild, lang)
        if card_file is not None:
            await interaction.response.send_message(embed=e, file=card_file)
        else:
            await interaction.response.send_message(embed=e)

    try:
        bot.tree.add_command(dungeon_group)
    except Exception:
        logger.exception("failed to register /dungeon command group")

    @bot.tree.command(name="party_hunt", description=app_commands.locale_str("cmd.party_hunt.desc"))
    @discord.app_commands.describe(member2=app_commands.locale_str("cmd.party_hunt.param.member2"), member3=app_commands.locale_str("cmd.party_hunt.param.member3"), member4=app_commands.locale_str("cmd.party_hunt.param.member4"))
    async def party_hunt(interaction: discord.Interaction, member2: discord.Member, member3: discord.Member | None = None, member4: discord.Member | None = None):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await interaction.response.send_message(tr(lang, "common.server_only"), ephemeral=True)

        party = [interaction.user, member2]
        if member3 is not None:
            party.append(member3)
        if member4 is not None:
            party.append(member4)

        unique_ids: set[int] = set()
        clean_party: list[discord.Member] = []
        for m in party:
            if m.bot or m.id in unique_ids:
                continue
            unique_ids.add(m.id)
            clean_party.append(m)
        if len(clean_party) < 2:
            msg = "❌ Party cần tối thiểu 2 người thật." if lang == "vi" else "❌ Party needs at least 2 real users."
            return await interaction.response.send_message(msg, ephemeral=True)

        await interaction.response.defer()
        result = await CombatService.party_hunt(interaction.guild.id, [m.id for m in clean_party], lang=lang)
        if not result.ok:
            msg = "❌ Party hunt lỗi." if lang == "vi" else "❌ Party hunt failed."
            return await _rpg_followup_send(interaction, msg, ephemeral=True)

        e = panel_embed(
            mode="Joint Operation",
            title="🤝 Joint Operation • Party Hunt",
            description=("Tổ đội đồng minh đã triển khai truy quét." if lang == "vi" else "Allied squads have deployed for a coordinated hunt."),
            theme="combat",
        )
        e.add_field(name="Alliance", value=", ".join(m.mention for m in clean_party), inline=False)
        log_url = await _publish_combat_log(result.logs or [], lang=lang)

        summary_parts = [f"Hạ: **{result.kills}/{result.pack}**"]
        summary_parts.append(f"+{result.gold} {CURRENCY_ICON} Slime Coin")
        summary_parts.append(f"+{result.xp} {XP_ICON}")
        clear_bar = progress_bar(result.kills, max(1, result.pack), 12)
        e.add_field(name="Operation Summary", value=" • ".join(summary_parts), inline=False)
        e.add_field(name="Clear Progress", value=f"`{clear_bar}`", inline=False)

        if result.members:
            lines = []
            for row in result.members[:4]:
                if not isinstance(row, dict):
                    continue
                uid = int(row.get("user_id", 0))
                m = interaction.guild.get_member(uid)
                name = m.display_name if m else str(uid)
                lines.append(f"**{name}**: {int(row.get('kills', 0))} kills, {int(row.get('hp', 1))} HP")
            if lines:
                e.add_field(name="Squad Reports", value="\n".join(lines), inline=False)

        drops = result.drops if isinstance(result.drops, dict) else {}
        if drops:
            drop_parts = [f"{_item_label(k)} x{v}" for k, v in drops.items()]
            e.add_field(name="💎 Drops", value=", ".join(drop_parts), inline=False)
        if log_url:
            e.add_field(name="📜 Battle Record", value=log_url, inline=False)

        logs = result.logs if isinstance(result.logs, list) else []
        combat_detail = "\n".join(logs[:15]) if logs else tr(lang, "rpg.no_combat_detail")
        view = CombatDetailView(combat_detail, lang=lang)
        
        await _rpg_followup_send(interaction, embed=e, view=view)
        view.message = await interaction.original_response()

    @bot.tree.command(name="quest", description=app_commands.locale_str("cmd.quest.desc"))
    async def quest(interaction: discord.Interaction):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        e = await handle_quest(interaction.guild.id, interaction.user.id, owner_name=interaction.user.display_name, lang=lang)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @bot.tree.command(name="quest_claim", description=app_commands.locale_str("cmd.quest_claim.desc"))
    @app_commands.describe(quest_id=app_commands.locale_str("cmd.quest_claim.param.quest_id"))
    async def quest_claim(interaction: discord.Interaction, quest_id: str):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        msg = await handle_quest_claim(interaction.guild.id, interaction.user.id, quest_id, lang=lang)
        ok = not str(msg).strip().startswith("❌")
        e = panel_embed(
            mode="Mission Board",
            title=("✅ Reward Claimed" if ok else "❌ Claim Failed"),
            description=msg,
            theme="victory" if ok else "defeat",
        )
        await interaction.response.send_message(embed=e, ephemeral=not ok)

    @bot.tree.command(name="rpg_loot", description=app_commands.locale_str("cmd.rpg_loot.desc"))
    async def rpg_loot(interaction: discord.Interaction):
        lang = await resolve_lang(interaction)
        e = _build_loot_codex_embed(lang)
        await interaction.response.send_message(embed=e)

    @bot.tree.command(name="create_character", description=app_commands.locale_str("cmd.create_character.desc"))
    @app_commands.describe(role=app_commands.locale_str("cmd.create_character.param.role"), gender=app_commands.locale_str("cmd.create_character.param.gender"))
    @app_commands.autocomplete(gender=autocomplete_gender, role=autocomplete_role)
    async def create_character(interaction: discord.Interaction, role: str, gender: str = "any"):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        embed, msg, ephemeral = await handle_create_character(
            interaction.guild.id,
            interaction.user.id,
            role=role,
            gender=gender,
            lang=lang,
        )
        if msg:
            return await interaction.response.send_message(msg, ephemeral=ephemeral)
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="gacha", description=app_commands.locale_str("cmd.gacha.desc"))
    @app_commands.describe(pulls=app_commands.locale_str("cmd.gacha.param.pulls"), banner=app_commands.locale_str("cmd.gacha.param.banner"))
    @app_commands.autocomplete(banner=autocomplete_banner)
    async def gacha(interaction: discord.Interaction, pulls: int = 1, banner: str = "none"):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)

        embed, err, ephemeral, card_file = await handle_gacha(
            interaction.guild.id,
            interaction.user.id,
            pulls=pulls,
            banner=banner,
            lang=lang,
            guild=interaction.guild,
            player_name=interaction.user.display_name,
        )
        if err:
            return await interaction.response.send_message(err, ephemeral=ephemeral)
        if card_file is not None:
            await interaction.response.send_message(embed=embed, file=card_file)
        else:
            await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="my_characters", description=app_commands.locale_str("cmd.my_characters.desc"))
    async def my_characters(interaction: discord.Interaction):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)

        e, msg, ephemeral = await handle_my_characters(interaction.guild.id, interaction.user.id, lang=lang)
        if msg:
            return await interaction.response.send_message(msg, ephemeral=ephemeral)
        await interaction.response.send_message(embed=e)

    @bot.tree.command(name="roster", description=app_commands.locale_str("cmd.roster.desc"))
    async def roster(interaction: discord.Interaction):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        async with open_db() as conn:
            chars = await get_player_characters(conn, interaction.guild.id, interaction.user.id)
            if not chars:
                msg = "❌ Bạn chưa có hero nào. Dùng `/create_character` hoặc `/gacha`." if lang == "vi" else "❌ You don't own any heroes yet. Use `/create_character` or `/gacha`."
                return await interaction.response.send_message(msg, ephemeral=True)

            by_rarity: dict[str, list[str]] = defaultdict(list)
            owned_ids = {str(r[1]) for r in chars}
            for row in chars:
                _, cid, is_main, level, exp, star, shard, name, rarity, role, passive = row
                c = CHARACTERS.get(str(cid), {})
                form = str(c.get("form", "Base"))
                marker = "⭐" if is_main else "•"
                ascend = _legendary_ascend_status(str(cid), int(shard), owned_ids)
                by_rarity[str(rarity).lower()].append(
                    f"{marker} **{name} [{form}]** (`{cid}`) Lv.{level} ★{star} [{role}] shard {int(shard)}{ascend}"
                )

        e = discord.Embed(title="🕯 Dark Roster", color=discord.Color.from_rgb(74, 31, 31))
        for rarity in ("mythic", "legendary", "epic", "rare", "common"):
            rows = by_rarity.get(rarity, [])
            if rows:
                e.add_field(name=f"{_rarity_emoji(rarity)} {rarity.title()}", value="\n".join(rows[:8]), inline=False)
        await interaction.response.send_message(embed=e)

    @bot.tree.command(name="ascend_mythic", description=app_commands.locale_str("cmd.ascend_mythic.desc"))
    @app_commands.describe(legendary_id=app_commands.locale_str("cmd.ascend_mythic.param.legendary_id"))
    async def ascend_mythic(interaction: discord.Interaction, legendary_id: str):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)

        msg, ephemeral = await handle_ascend_mythic(interaction.guild.id, interaction.user.id, legendary_id, lang=lang)
        await interaction.response.send_message(msg, ephemeral=ephemeral)

    @bot.tree.command(name="team", description=app_commands.locale_str("cmd.team.desc"))
    @app_commands.describe(action=app_commands.locale_str("cmd.team.param.action"), character_id=app_commands.locale_str("cmd.team.param.character_id"), slot=app_commands.locale_str("cmd.team.param.slot"))
    async def team(interaction: discord.Interaction, action: str = "view", character_id: str = None, slot: int = 1):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        embed, view, msg, ephemeral, card_file = await handle_team(
            interaction.guild.id,
            interaction.user.id,
            interaction.user.display_name,
            guild=interaction.guild,
            action=action,
            character_id=character_id,
            slot=slot,
            lang=lang,
        )
        if embed is not None:
            if card_file is not None:
                await interaction.response.send_message(embed=embed, view=view, file=card_file)
            else:
                await interaction.response.send_message(embed=embed, view=view)
            if view is not None:
                try:
                    view.message = await interaction.original_response()
                except Exception:
                    pass
            return
        fallback = "❌ Có lỗi xảy ra." if lang == "vi" else "❌ Something went wrong."
        await interaction.response.send_message(msg or fallback, ephemeral=ephemeral)

    @bot.tree.command(name="team_stats", description=app_commands.locale_str("cmd.team_stats.desc"))
    async def team_stats(interaction: discord.Interaction):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        result = await PlayerService.get_profile(interaction.guild.id, interaction.user.id)
        if not result.ok:
            return await interaction.response.send_message(tr(lang, "rpg.profile_fetch_failed"), ephemeral=True)
        lore = await _profile_lore_meta(interaction.guild.id, interaction.user.id)
        if int(lore.get("team_size", 0)) <= 0:
            msg = "❌ Bạn chưa có team. Dùng `/create_character` và `/team add` trước." if lang == "vi" else "❌ You don't have a team yet. Use `/create_character` and `/team add` first."
            return await interaction.response.send_message(msg, ephemeral=True)
        e = _build_formation_analysis_embed(interaction.user, result, lore, lang=lang)
        members = lore.get("team_members", []) if isinstance(lore.get("team_members"), list) else []
        view = TeamMemberDetailView(interaction.user.display_name, members, lang=lang) if members else None
        await interaction.response.send_message(embed=e, view=view)
        if view is not None:
            try:
                view.message = await interaction.original_response()
            except Exception:
                pass

    @bot.command(name="rs")
    async def text_rpg_start(ctx: commands.Context):
        lang = await _lang_for_ctx(ctx)
        if ctx.guild is None:
            return await _server_only_ctx(ctx)
        msg = await handle_rpg_start(ctx.guild.id, ctx.author.id, lang=lang)
        await ctx.reply(msg)

    @bot.command(name="cc")
    async def text_create_character(ctx: commands.Context, role: str, gender: str = "any"):
        lang = await _lang_for_ctx(ctx)
        if ctx.guild is None:
            return await _server_only_ctx(ctx)
        embed, msg, _ = await handle_create_character(
            ctx.guild.id,
            ctx.author.id,
            role=role,
            gender=gender,
            lang=lang,
        )
        if msg:
            return await ctx.reply(msg)
        await ctx.reply(embed=embed)

    @bot.command(name="p", aliases=["st"])
    async def text_profile(ctx: commands.Context, member: Optional[discord.Member] = None):
        lang = await _lang_for_ctx(ctx)
        if ctx.guild is None:
            return await ctx.reply(tr(lang, "common.server_only"))
        target = member or ctx.author
        e, view, err = await handle_profile(
            ctx.guild.id,
            target,
            lang=lang,
            stats_mode=(ctx.invoked_with == "st"),
        )
        if err:
            return await ctx.reply(err)
        msg = await ctx.reply(embed=e, view=view)
        if view is not None:
            view.message = msg

    @bot.command(name="h")
    async def text_hunt(ctx: commands.Context):
        lang = await _lang_for_ctx(ctx)
        if ctx.guild is None:
            return await ctx.reply(tr(lang, "common.server_only"))
        embed, view, err, card_file = await handle_hunt(
            ctx.guild.id,
            ctx.author.id,
            ctx.author.display_name,
            guild=ctx.guild,
            lang=lang,
        )
        if err:
            return await ctx.reply(err)
        if card_file is not None:
            msg = await ctx.reply(embed=embed, view=view, file=card_file)
        else:
            msg = await ctx.reply(embed=embed, view=view)
        view.message = msg

    @bot.command(name="b")
    async def text_boss(ctx: commands.Context):
        lang = await _lang_for_ctx(ctx)
        if ctx.guild is None:
            return await ctx.reply(tr(lang, "common.server_only"))
        embed, view, err, card_file = await handle_boss(
            ctx.guild.id,
            ctx.author.id,
            ctx.author.display_name,
            guild=ctx.guild,
            lang=lang,
        )
        if err:
            return await ctx.reply(err)
        if card_file is not None:
            msg = await ctx.reply(embed=embed, view=view, file=card_file)
        else:
            msg = await ctx.reply(embed=embed, view=view)
        view.message = msg

    @bot.command(name="d")
    async def text_dungeon(ctx: commands.Context, action: str = "status", value: str = ""):
        lang = await _lang_for_ctx(ctx)
        if ctx.guild is None:
            return await ctx.reply(tr(lang, "common.server_only"))
        act = str(action or "status").strip().lower()

        if act == "start":
            difficulty = str(value or "normal").strip().lower() or "normal"
            try:
                result = await DungeonRunService.start_run(ctx.guild.id, ctx.author.id, difficulty=difficulty, lang=lang)
            except Exception:
                logger.exception(
                    "text dungeon start crashed guild=%s user=%s difficulty=%s",
                    ctx.guild.id,
                    ctx.author.id,
                    difficulty,
                )
                return await ctx.reply(tr(lang, "unknown_error"))
            if not result.ok:
                logger.warning(
                    "text dungeon start rejected guild=%s user=%s difficulty=%s error=%s",
                    ctx.guild.id,
                    ctx.author.id,
                    difficulty,
                    result.error,
                )
                return await ctx.reply(f"❌ {result.error}")
            state = await DungeonRunService.get_state(ctx.guild.id, ctx.author.id, lang=lang)
            view = DungeonControlView(ctx.guild.id, ctx.author.id, lang, state) if state.ok else None
            e = _build_dungeon_start_embed(result, lang)
            payload = _dungeon_start_card_payload(result, state if state.ok else None, lang)
            card_file = await _attach_dungeon_card(e, payload, ctx.guild, lang)
            if card_file is not None:
                msg = await ctx.reply(embed=e, view=view, file=card_file)
            else:
                msg = await ctx.reply(embed=e, view=view)
            if view is not None:
                view.message = msg
            return

        if act == "status":
            state, resolved_embed = await _dungeon_status_with_pending_resolution(ctx.guild.id, ctx.author.id, lang=lang)
            if not state.ok:
                return await ctx.reply(f"{tr(lang, 'rpg.dungeon.no_active')}\n{tr(lang, 'rpg.dungeon.suggest.start')}")

            phase = str(getattr(state, "phase", ""))
            if phase == "selecting_path":
                hint = tr(lang, "rpg.dungeon.suggest.path")
            elif phase == "choice":
                hint = tr(lang, "rpg.dungeon.suggest.choice")
            elif phase == "claimable":
                hint = tr(lang, "rpg.dungeon.suggest.claim")
            elif phase == "resolving_node":
                hint = tr(lang, "rpg.dungeon.suggest.refresh")
            else:
                hint = tr(lang, "rpg.dungeon.suggest.status")

            view = DungeonControlView(ctx.guild.id, ctx.author.id, lang, state)
            e = resolved_embed if resolved_embed is not None else _build_dungeon_state_embed(state, lang)
            payload = _dungeon_state_card_payload(state, lang)
            card_file = await _attach_dungeon_card(e, payload, ctx.guild, lang)
            if card_file is not None:
                msg = await ctx.reply(content=hint, embed=e, view=view, file=card_file)
            else:
                msg = await ctx.reply(content=hint, embed=e, view=view)
            view.message = msg
            return

        if act == "path":
            node_id = str(value or "").strip()
            if not node_id:
                state = await DungeonRunService.get_state(ctx.guild.id, ctx.author.id, lang=lang)
                if not state.ok:
                    return await ctx.reply(tr(lang, "rpg.dungeon.no_active"))
                if str(state.phase) != "selecting_path":
                    tip = tr(lang, "rpg.dungeon.phase_path_required")
                else:
                    tip = tr(lang, "rpg.dungeon.path_auto_hint")
                view = DungeonControlView(ctx.guild.id, ctx.author.id, lang, state)
                e = _build_dungeon_state_embed(state, lang)
                payload = _dungeon_state_card_payload(state, lang)
                card_file = await _attach_dungeon_card(e, payload, ctx.guild, lang)
                if card_file is not None:
                    msg = await ctx.reply(content=tip, embed=e, view=view, file=card_file)
                else:
                    msg = await ctx.reply(content=tip, embed=e, view=view)
                view.message = msg
                return
            result = await DungeonRunService.choose_node(ctx.guild.id, ctx.author.id, node_id=node_id, lang=lang)
            if not result.ok:
                return await ctx.reply(f"❌ {result.error}")
            next_view = None
            state = await DungeonRunService.get_state(ctx.guild.id, ctx.author.id, lang=lang)
            if result.next_phase in {"selecting_path", "choice", "resolving_node"}:
                if state.ok:
                    next_view = DungeonControlView(ctx.guild.id, ctx.author.id, lang, state)
            e = _build_dungeon_node_result_embed(result, lang)
            payload = _dungeon_node_card_payload(result, state if state.ok else None, lang)
            card_file = await _attach_dungeon_card(e, payload, ctx.guild, lang)
            if card_file is not None:
                msg = await ctx.reply(embed=e, view=next_view, file=card_file)
            else:
                msg = await ctx.reply(embed=e, view=next_view)
            if next_view is not None:
                next_view.message = msg
            return

        if act == "choice":
            choice_id = str(value or "").strip()
            if not choice_id:
                state = await DungeonRunService.get_state(ctx.guild.id, ctx.author.id, lang=lang)
                if not state.ok:
                    return await ctx.reply(tr(lang, "rpg.dungeon.no_active"))
                if str(state.phase) != "choice":
                    tip = tr(lang, "rpg.dungeon.phase_choice_required")
                else:
                    tip = tr(lang, "rpg.dungeon.choice_auto_hint")
                view = DungeonControlView(ctx.guild.id, ctx.author.id, lang, state)
                e = _build_dungeon_state_embed(state, lang)
                payload = _dungeon_state_card_payload(state, lang)
                card_file = await _attach_dungeon_card(e, payload, ctx.guild, lang)
                if card_file is not None:
                    msg = await ctx.reply(content=tip, embed=e, view=view, file=card_file)
                else:
                    msg = await ctx.reply(content=tip, embed=e, view=view)
                view.message = msg
                return
            result = await DungeonRunService.apply_choice(ctx.guild.id, ctx.author.id, choice_id=choice_id, lang=lang)
            if not result.ok:
                return await ctx.reply(f"❌ {result.error}")
            e = panel_embed(
                mode="Dungeon Mode",
                title=tr(lang, "rpg.dungeon.choice_applied_title"),
                description=tr(lang, "rpg.dungeon.choice_applied_desc", choice_id=result.choice_id),
                theme="victory",
            )
            state = await DungeonRunService.get_state(ctx.guild.id, ctx.author.id, lang=lang)
            view = DungeonControlView(ctx.guild.id, ctx.author.id, lang, state) if state.ok else None
            payload = _dungeon_choice_card_payload(result, state if state.ok else None, lang)
            card_file = await _attach_dungeon_card(e, payload, ctx.guild, lang)
            if card_file is not None:
                msg = await ctx.reply(embed=e, view=view, file=card_file)
            else:
                msg = await ctx.reply(embed=e, view=view)
            if view is not None:
                view.message = msg
            return

        if act == "retreat":
            result = await DungeonRunService.retreat(ctx.guild.id, ctx.author.id, lang=lang)
            if not result.ok:
                return await ctx.reply(f"❌ {result.error}")
            e = _build_dungeon_finish_embed(result, lang)
            payload = _dungeon_finish_card_payload(result, lang)
            card_file = await _attach_dungeon_card(e, payload, ctx.guild, lang)
            if card_file is not None:
                return await ctx.reply(embed=e, file=card_file)
            return await ctx.reply(embed=e)

        if act == "claim":
            result = await DungeonRunService.claim_rewards(ctx.guild.id, ctx.author.id, lang=lang)
            if not result.ok:
                return await ctx.reply(f"❌ {result.error}")
            e = _build_dungeon_finish_embed(result, lang)
            payload = _dungeon_finish_card_payload(result, lang)
            card_file = await _attach_dungeon_card(e, payload, ctx.guild, lang)
            if card_file is not None:
                return await ctx.reply(embed=e, file=card_file)
            return await ctx.reply(embed=e)

        await ctx.reply(tr(lang, "rpg.dungeon.invalid_action"))

    @bot.command(name="g")
    async def text_gacha(ctx: commands.Context, pulls: int = 1, banner: str = "none"):
        lang = await _lang_for_ctx(ctx)
        if ctx.guild is None:
            return await _server_only_ctx(ctx)
        embed, err, _, card_file = await handle_gacha(
            ctx.guild.id,
            ctx.author.id,
            pulls=pulls,
            banner=banner,
            lang=lang,
            guild=ctx.guild,
            player_name=ctx.author.display_name,
        )
        if err:
            return await ctx.reply(err)
        if card_file is not None:
            await ctx.reply(embed=embed, file=card_file)
        else:
            await ctx.reply(embed=embed)

    @bot.command(name="mc")
    async def text_my_characters(ctx: commands.Context):
        lang = await _lang_for_ctx(ctx)
        if ctx.guild is None:
            return await _server_only_ctx(ctx)
        e, msg, _ = await handle_my_characters(ctx.guild.id, ctx.author.id, lang=lang)
        if msg:
            return await ctx.reply(msg)
        await ctx.reply(embed=e)

    @bot.command(name="tm")
    async def text_team(ctx: commands.Context, action: str = "view", character_id: str = "", slot: int = 1):
        lang = await _lang_for_ctx(ctx)
        if ctx.guild is None:
            return await _server_only_ctx(ctx)
        embed, view, msg, _, card_file = await handle_team(
            ctx.guild.id,
            ctx.author.id,
            ctx.author.display_name,
            guild=ctx.guild,
            action=action,
            character_id=character_id,
            slot=slot,
            lang=lang,
        )
        if embed is not None:
            if card_file is not None:
                sent = await ctx.reply(embed=embed, view=view, file=card_file)
            else:
                sent = await ctx.reply(embed=embed, view=view)
            if view is not None:
                view.message = sent
            return
        fallback = "❌ Có lỗi xảy ra." if lang == "vi" else "❌ Something went wrong."
        await ctx.reply(msg or fallback)

    @bot.command(name="eq")
    async def text_equip(ctx: commands.Context, item: str, character_id: str = ""):
        lang = await _lang_for_ctx(ctx)
        if ctx.guild is None:
            return await _server_only_ctx(ctx)
        e, msg, _ = await handle_equip_action(
            ctx.guild.id,
            ctx.author.id,
            item=item,
            character_id=character_id,
            lang=lang,
        )
        if msg:
            return await ctx.reply(msg)
        await ctx.reply(embed=e)

    @bot.command(name="uneq")
    async def text_unequip(ctx: commands.Context, slot: str, character_id: str = ""):
        lang = await _lang_for_ctx(ctx)
        if ctx.guild is None:
            return await _server_only_ctx(ctx)
        e, msg, _ = await handle_unequip_action(
            ctx.guild.id,
            ctx.author.id,
            slot=slot,
            character_id=character_id,
            lang=lang,
        )
        if msg:
            return await ctx.reply(msg)
        await ctx.reply(embed=e)

    @bot.command(name="q")
    async def text_quest(ctx: commands.Context):
        lang = await _lang_for_ctx(ctx)
        if ctx.guild is None:
            return await _server_only_ctx(ctx)
        e = await handle_quest(ctx.guild.id, ctx.author.id, owner_name=ctx.author.display_name, lang=lang)
        await ctx.reply(embed=e)

    @bot.command(name="qc")
    async def text_quest_claim(ctx: commands.Context, quest_id: str):
        lang = await _lang_for_ctx(ctx)
        if ctx.guild is None:
            return await _server_only_ctx(ctx)
        msg = await handle_quest_claim(ctx.guild.id, ctx.author.id, quest_id, lang=lang)
        ok = not str(msg).strip().startswith("❌")
        e = panel_embed(
            mode="Mission Board",
            title=("✅ Reward Claimed" if ok else "❌ Claim Failed"),
            description=msg,
            theme="victory" if ok else "defeat",
        )
        await ctx.reply(embed=e)

    @bot.command(name="am")
    async def text_ascend_mythic(ctx: commands.Context, legendary_id: str):
        lang = await _lang_for_ctx(ctx)
        if ctx.guild is None:
            return await _server_only_ctx(ctx)
        msg, _ = await handle_ascend_mythic(ctx.guild.id, ctx.author.id, legendary_id, lang=lang)
        await ctx.reply(msg)


async def autocomplete_gender(interaction: discord.Interaction, current: str):
    options = [
        app_commands.Choice(name="Any", value="any"),
        app_commands.Choice(name="Nam (Male)", value="male"),
        app_commands.Choice(name="Nữ (Female)", value="female"),
    ]
    return [o for o in options if current.lower() in o.name.lower()]


async def autocomplete_role(interaction: discord.Interaction, current: str):
    options = [
        app_commands.Choice(name="DPS", value="dps"),
        app_commands.Choice(name="Tank", value="tank"),
        app_commands.Choice(name="Healer", value="healer"),
        app_commands.Choice(name="Support (SP)", value="support"),
    ]
    return [o for o in options if current.lower() in o.name.lower()]


async def autocomplete_banner(interaction: discord.Interaction, current: str):
    options = [
        app_commands.Choice(name=f"{cfg['name']} ({bid})", value=bid)
        for bid, cfg in GACHA_BANNERS.items()
    ]
    low = current.lower()
    return [o for o in options if low in o.name.lower() or low in o.value.lower()][:25]
