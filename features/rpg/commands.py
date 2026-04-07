import random
import time
from collections import defaultdict, deque
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from language import resolve_lang, resolve_lang_ctx, tr

from .utils.assets import apply_embed_asset, apply_item_asset, reload_assets
from .data import (
    ITEMS,
    CRAFT_RECIPES,
    SKILLS,
    CHARACTERS,
    GACHA_COST,
    GACHA_BANNERS,
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

from .shop import format_shop_embed, ShopCategory


RPG_COMMAND_RATE_USER_MAX = 12
RPG_COMMAND_RATE_USER_WINDOW = 20
RPG_COMMAND_RATE_GUILD_MAX = 120
RPG_COMMAND_RATE_GUILD_WINDOW = 20

_USER_RATE_BUCKET: dict[int, deque[float]] = defaultdict(deque)
_GUILD_RATE_BUCKET: dict[int, deque[float]] = defaultdict(deque)

RPG_COMMAND_NAMES = {
    "rpg_assets_reload", "rpg_start", "profile", "stats", "rpg_balance",
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


def _collect_files(*files: discord.File | None) -> list[discord.File]:
    return [f for f in files if f is not None]


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
    r = (rarity or "common").lower()
    return {"common": "⚪", "uncommon": "🟢", "rare": "🔵", "epic": "🟣", "legendary": "🟡", "mythic": "🔴"}.get(r, "⚫")


def _to_pct(value: float) -> int:
    return int(round(max(0.0, float(value)) * 100))


def _passive_text(lifesteal: float, crit_bonus: float, damage_reduction: float) -> str:
    return f"Lifesteal +{_to_pct(lifesteal)}% • Crit +{_to_pct(crit_bonus)}% • Damage Reduction {_to_pct(damage_reduction)}%"


def _as_str_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(x) for x in value]


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


def _normalize_role(value: str) -> str:
    r = str(value or "").strip().lower()
    if r in {"sp", "sup", "support"}:
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
    r = str(role or "").lower()
    if r == "sp":
        r = "support"
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
    if main:
        members.append(
            (
                str(main[7]),
                _normalize_role(str(main[9])),
                int(main[10]),
                int(main[11]),
                int(main[12]),
                int(main[3]),
                int(main[5]),
            )
        )
    for row in team[:4]:
        members.append((str(row[2]), _normalize_role(str(row[4])), int(row[5]), int(row[6]), int(row[7]), int(row[10]), int(row[11])))

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
    }


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
    hp_bar = _meter_bar(eff_hp, eff_max_hp, 12)
    xp_bar = _meter_bar(result.xp, result.xp_need, 12)
    hunt_prog = int(lore.get("hunt_progress", 0))
    hunt_target = int(lore.get("hunt_target", 5))
    hunt_bar = _meter_bar(hunt_prog, hunt_target, 12)
    team_hp = int(lore.get("team_hp", 0))
    team_atk = int(lore.get("team_atk", 0))
    team_def = int(lore.get("team_def", 0))
    team_power = int(lore.get("team_power", 0))
    team_size = int(lore.get("team_size", 0))
    role_line = str(lore.get("role_line", "n/a"))
    team_preview = lore.get("team_preview", []) if isinstance(lore.get("team_preview", []), list) else []
    rank = _rank_from_level(result.level)

    equip_text = []
    if isinstance(result.equipped, dict):
        for slot in ("weapon", "armor", "accessory"):
            item_id = result.equipped.get(slot)
            slot_name = "Relic" if slot == "accessory" else slot.title()
            equip_text.append(f"{slot_name:<9} {(_item_label(item_id) if item_id else 'None')}")
    else:
        equip_text.append("(no equipment data)")

    e = discord.Embed(
        title=f"✠ {target.display_name} — Team Dossier",
        description="Command status and squad combat readiness.",
        color=discord.Color.from_rgb(158, 42, 43),
    )
    e.set_thumbnail(url=target.display_avatar.url)
    e.add_field(
        name="═════ ✠ Formation ✠ ═════",
        value=(
            f"Commander Rank: **{rank}**\n"
            f"Captain: **{lore.get('captain', 'None')}**\n"
            f"Squad Size: **{team_size}/5**\n"
            f"Roles: **{role_line}**"
        ),
        inline=False,
    )
    e.add_field(
        name="☾ Progress",
        value=(
            f"⟡ Level: **{result.level}**\n"
            f"👑 Crowns: **{result.gold}**\n"
            f"✦ Soul EXP: **{result.xp}/{result.xp_need}**\n"
            f"`{xp_bar}`"
        ),
        inline=True,
    )
    e.add_field(name="🩸 Commander HP", value=f"**{eff_hp}/{eff_max_hp}**\n`{hp_bar}`", inline=True)
    e.add_field(
        name="🏹 Hunt Record",
        value=f"**{hunt_prog}/{hunt_target}**\n`{hunt_bar}`",
        inline=True,
    )
    e.add_field(name="⚔ Squad Power", value=f"Power **{team_power}**\nMight **{team_atk}**\nGuard **{team_def}**\nVitality **{team_hp}**", inline=True)
    no_team_text = "• Chưa có dữ liệu team" if lang == "vi" else "• No team data"
    e.add_field(name="🧩 Squad Members", value="\n".join(team_preview) if team_preview else no_team_text, inline=True)
    e.add_field(name="🕯 Commander Gear", value="\n".join(equip_text), inline=True)
    e.add_field(
        name="☾ Innate Traits",
        value=(
            f"Lifesteal       **{_to_pct(result.lifesteal)}%**\n"
            f"Critical Chance **{_to_pct(result.crit_bonus)}%**\n"
            f"Damage Reduction **{_to_pct(result.damage_reduction)}%**"
        ),
        inline=False,
    )
    if result.set_bonus:
        e.add_field(name="Blessings / Curses", value=f"🕸 {result.set_bonus}", inline=False)
    if result.passive_skills:
        e.add_field(name="Whispers", value="\n".join(f"• {name}" for name in result.passive_skills), inline=False)
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
        self.show_detail.label = "📜 Chi tiết" if self.lang == "vi" else "📜 Detail"
        
    @discord.ui.button(label="detail", style=discord.ButtonStyle.secondary)
    async def show_detail(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="📜 Chi tiết combat" if self.lang == "vi" else "📜 Combat Detail",
            description=self.combat_log[:4000],
            color=discord.Color.dark_embed(),
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


def setup(bot: commands.Bot, guilds: list = None):
    guilds = guilds or []

    async def _rpg_rate_limit_check(interaction: discord.Interaction) -> bool:
        cmd = interaction.command
        cmd_name = str(getattr(cmd, "name", "")).strip().lower()
        if cmd_name not in RPG_COMMAND_NAMES:
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
        if cmd_name in RPG_STARTED_COMMANDS:
            if not await _check_player_registered(interaction):
                raise app_commands.CheckFailure("Player not registered")
        
        return True

    bot.tree.interaction_check = _rpg_rate_limit_check

    async def _on_ready_once():
        await ensure_db_ready()
        reload_assets()

    bot.add_listener(_on_ready_once, "on_ready")

    @bot.tree.command(name="rpg_start", description=app_commands.locale_str("cmd.rpg_start.desc"))
    async def rpg_start(interaction: discord.Interaction):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await interaction.response.send_message(tr(lang, "common.server_only"), ephemeral=True)
        await ensure_db_ready()
        async with open_db() as conn:
            from .repositories import player_repo, quest_repo
            await player_repo.ensure_player_ready(conn, interaction.guild.id, interaction.user.id)
            await quest_repo.ensure_default_quests(conn, interaction.guild.id, interaction.user.id)
            await conn.commit()
        await interaction.response.send_message(tr(lang, "rpg.start_success"), ephemeral=True)

    @bot.tree.command(name="profile", description=app_commands.locale_str("cmd.profile.desc"))
    @app_commands.describe(member=app_commands.locale_str("cmd.profile.param.member"))
    async def profile(interaction: discord.Interaction, member: Optional[discord.Member] = None):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await interaction.response.send_message(tr(lang, "common.server_only"), ephemeral=True)
        target = _member_or_self(interaction, member)
        if target is None:
            return await interaction.response.send_message(tr(lang, "common.member_unknown"), ephemeral=True)

        result = await PlayerService.get_profile(interaction.guild.id, target.id)
        if not result.ok:
            return await interaction.response.send_message(tr(lang, "rpg.profile_fetch_failed"), ephemeral=True)
        lore = await _profile_lore_meta(interaction.guild.id, target.id)
        e = _build_profile_embed(target, result, lore, lang=lang)
        f = apply_embed_asset(e, "profile")
        await interaction.response.send_message(embed=e, files=_collect_files(f))

    @bot.tree.command(name="stats", description=app_commands.locale_str("cmd.stats.desc"))
    @app_commands.describe(member=app_commands.locale_str("cmd.stats.param.member"))
    async def stats(interaction: discord.Interaction, member: Optional[discord.Member] = None):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await interaction.response.send_message(tr(lang, "common.server_only"), ephemeral=True)
        target = _member_or_self(interaction, member)
        if target is None:
            return await interaction.response.send_message(tr(lang, "common.member_unknown"), ephemeral=True)

        result = await PlayerService.get_profile(interaction.guild.id, target.id)
        if not result.ok:
            return await interaction.response.send_message(tr(lang, "rpg.profile_fetch_failed"), ephemeral=True)

        lore = await _profile_lore_meta(interaction.guild.id, target.id)
        e = _build_profile_embed(target, result, lore, lang=lang)
        e.title = f"📊 Team Stats - {target.display_name}"
        f = apply_embed_asset(e, "profile")
        await interaction.response.send_message(embed=e, files=_collect_files(f))

    @bot.tree.command(name="rpg_balance", description=app_commands.locale_str("cmd.rpg_balance.desc"))
    async def rpg_balance(interaction: discord.Interaction):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await interaction.response.send_message(tr(lang, "common.server_only"), ephemeral=True)
        gold = await EconomyService.get_balance(interaction.guild.id, interaction.user.id)
        msg = f"💰 Bạn có **{gold}** gold RPG." if lang == "vi" else f"💰 You have **{gold}** RPG gold."
        await interaction.response.send_message(msg, ephemeral=True)

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
            msg = f"💸 Đã chuyển **{amount}** gold cho {member.mention}" if lang == "vi" else f"💸 Transferred **{amount}** gold to {member.mention}"
            await interaction.response.send_message(msg)
        else:
            await interaction.response.send_message(result.message, ephemeral=True)

    @bot.tree.command(name="rpg_shop", description=app_commands.locale_str("cmd.rpg_shop.desc"))
    async def rpg_shop(interaction: discord.Interaction):
        lang = await resolve_lang(interaction)
        content = format_shop_embed("main")
        e = discord.Embed(
            title="🛒 RPG SHOP",
            description=content,
            color=discord.Color.gold()
        )
        e.add_field(
            name=("📂 Danh mục" if lang == "vi" else "📂 Categories"),
            value=(
                "`/shop consumables` - Vật phẩm tiêu hao\n"
                "`/shop equipment` - Trang bị\n"
                "`/shop materials` - Vật liệu\n"
                "`/shop blackmarket` - Chợ đen"
            ) if lang == "vi" else (
                "`/shop consumables` - Consumables\n"
                "`/shop equipment` - Equipment\n"
                "`/shop materials` - Materials\n"
                "`/shop blackmarket` - Black Market"
            ),
            inline=False
        )
        await interaction.response.send_message(embed=e)

    @bot.tree.command(name="shop", description=app_commands.locale_str("cmd.shop.desc"))
    @app_commands.describe(category=app_commands.locale_str("cmd.shop.param.category"))
    async def rpg_shop_category(interaction: discord.Interaction, category: str = "main"):
        lang = await resolve_lang(interaction)
        valid_categories = ["main", ShopCategory.CONSUMABLES, ShopCategory.EQUIPMENT, ShopCategory.MATERIALS, ShopCategory.BLACK_MARKET]
        if category not in valid_categories:
            category = "main"
        
        content = format_shop_embed(category)
        
        title_map_vi = {
            "main": "🛒 RPG SHOP",
            ShopCategory.CONSUMABLES: "🧪 Shop - Vật Phẩm Tiêu Hao",
            ShopCategory.EQUIPMENT: "⚔️ Shop - Trang Bị",
            ShopCategory.MATERIALS: "💎 Shop - Vật Liệu",
            ShopCategory.BLACK_MARKET: "🌑 Chợ Đen",
        }
        title_map_en = {
            "main": "🛒 RPG SHOP",
            ShopCategory.CONSUMABLES: "🧪 Shop - Consumables",
            ShopCategory.EQUIPMENT: "⚔️ Shop - Equipment",
            ShopCategory.MATERIALS: "💎 Shop - Materials",
            ShopCategory.BLACK_MARKET: "🌑 Black Market",
        }
        
        color_map = {
            "main": discord.Color.gold(),
            ShopCategory.CONSUMABLES: discord.Color.green(),
            ShopCategory.EQUIPMENT: discord.Color.red(),
            ShopCategory.MATERIALS: discord.Color.blue(),
            ShopCategory.BLACK_MARKET: discord.Color.dark_gray(),
        }
        
        e = discord.Embed(
            title=(title_map_vi if lang == "vi" else title_map_en).get(category, "🛒 RPG Shop"),
            description=content,
            color=color_map.get(category, discord.Color.gold())
        )
        await interaction.response.send_message(embed=e)

    @bot.tree.command(name="craft_list", description=app_commands.locale_str("cmd.craft_list.desc"))
    async def craft_list(interaction: discord.Interaction):
        lines = []
        for r in CRAFT_RECIPES:
            rid = str(r.get("id", ""))
            name = str(r.get("name", rid))
            req = r.get("requires", {}) or {}
            req_txt = ", ".join(f"{_item_label(str(k))} x{int(v)}" for k, v in req.items()) if req else "(none)"
            gold = int(r.get("gold", 0))
            out = r.get("output", {}) or {}
            out_txt = ", ".join(f"{_item_label(str(k))} x{int(v)}" for k, v in out.items()) if out else "(none)"
            lines.append(f"`{rid}` • **{name}**\nNeed: {req_txt}\nCost: {gold} gold\nOutput: {out_txt}")
        e = discord.Embed(title="🛠️ Craft Recipes", description="\n\n".join(lines), color=discord.Color.orange())
        f = apply_embed_asset(e, "shop")
        await interaction.response.send_message(embed=e, files=_collect_files(f))

    @bot.tree.command(name="craft", description=app_commands.locale_str("cmd.craft.desc"))
    @app_commands.describe(recipe_id=app_commands.locale_str("cmd.craft.param.recipe_id"), amount=app_commands.locale_str("cmd.craft.param.amount"))
    @app_commands.autocomplete(recipe_id=autocomplete_recipe)
    async def craft(interaction: discord.Interaction, recipe_id: str, amount: int = 1):
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        lang = await resolve_lang(interaction)
        result = await EconomyService.craft_item(interaction.guild.id, interaction.user.id, recipe_id, amount, lang=lang)
        await interaction.response.send_message(result.message, ephemeral=True)

    @bot.tree.command(name="rpg_buy", description=app_commands.locale_str("cmd.rpg_buy.desc"))
    @app_commands.describe(item=app_commands.locale_str("cmd.rpg_buy.param.item"), amount=app_commands.locale_str("cmd.rpg_buy.param.amount"))
    @app_commands.autocomplete(item=autocomplete_item)
    async def rpg_buy(interaction: discord.Interaction, item: str, amount: int = 1):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        ok, msg = await EconomyService.buy_item(interaction.guild.id, interaction.user.id, item, amount, lang=lang)
        if ok:
            data = ITEMS.get(item, {})
            e = discord.Embed(title=("✅ Mua thành công" if lang == "vi" else "✅ Purchase successful"), description=msg, color=discord.Color.green())
            f = apply_item_asset(e, item)
            await interaction.response.send_message(embed=e, files=_collect_files(f))
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

        lines = [f"{_item_label(item_id)} x{amount}" for item_id, amount in items]
        e = discord.Embed(title=f"🎒 RPG Inventory - {target.display_name}", description="\n".join(lines), color=discord.Color.green())
        f = apply_embed_asset(e, "inventory")
        await interaction.response.send_message(embed=e, files=_collect_files(f))

    @bot.tree.command(name="rpg_equipment", description=app_commands.locale_str("cmd.rpg_equipment.desc"))
    @app_commands.describe(member=app_commands.locale_str("cmd.rpg_equipment.param.member"))
    async def rpg_equipment(interaction: discord.Interaction, member: Optional[discord.Member] = None):
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        target = _member_or_self(interaction, member)
        if target is None:
            lang = await resolve_lang(interaction)
            return await interaction.response.send_message(tr(lang, "common.member_unknown"), ephemeral=True)

        result = await PlayerService.get_equipment(interaction.guild.id, target.id)
        lines = []
        for slot in ("weapon", "armor", "accessory"):
            item_id = result.equipped.get(slot) if isinstance(result.equipped, dict) else None
            lines.append(f"**{slot}**: {_item_label(item_id) if item_id else '(empty)'}")

        e = discord.Embed(title=f"🧩 Equipment - {target.display_name}", description="\n".join(lines), color=discord.Color.purple())
        e.add_field(name="Bonus", value=f"ATK +{result.bonus_atk} • DEF +{result.bonus_def} • HP +{result.bonus_hp}", inline=False)
        e.add_field(name="Passive", value=_passive_text(result.lifesteal, result.crit_bonus, result.damage_reduction), inline=False)
        if result.set_bonus:
            e.add_field(name="Set Bonus", value=f"🧩 {result.set_bonus}", inline=False)
        if result.passive_skills:
            e.add_field(name="Skill Passive", value="\n".join(f"• {name}" for name in result.passive_skills), inline=False)
        await interaction.response.send_message(embed=e)

    @bot.tree.command(name="equip", description=app_commands.locale_str("cmd.equip.desc"))
    @app_commands.describe(item=app_commands.locale_str("cmd.equip.param.item"))
    @app_commands.autocomplete(item=autocomplete_item)
    async def equip(interaction: discord.Interaction, item: str):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        ok, payload = await PlayerService.equip_item(interaction.guild.id, interaction.user.id, item, lang=lang)
        if ok:
            msg = f"✅ Đã trang bị `{item}` vào slot **{payload}**." if lang == "vi" else f"✅ Equipped `{item}` to slot **{payload}**."
            await interaction.response.send_message(msg)
        else:
            await interaction.response.send_message(f"❌ {payload}", ephemeral=True)

    @bot.tree.command(name="unequip", description=app_commands.locale_str("cmd.unequip.desc"))
    @app_commands.describe(slot=app_commands.locale_str("cmd.unequip.param.slot"))
    async def unequip(interaction: discord.Interaction, slot: str):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        ok, payload = await PlayerService.unequip_item(interaction.guild.id, interaction.user.id, slot, lang=lang)
        if ok:
            msg = f"✅ Đã tháo `{payload}` khỏi slot `{slot}`." if lang == "vi" else f"✅ Unequipped `{payload}` from slot `{slot}`."
            await interaction.response.send_message(msg)
        else:
            await interaction.response.send_message(f"❌ {payload}", ephemeral=True)

    @bot.tree.command(name="rpg_skills", description=app_commands.locale_str("cmd.rpg_skills.desc"))
    async def rpg_skills(interaction: discord.Interaction):
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        data = await PlayerService.get_skills(interaction.guild.id, interaction.user.id)
        level = data["level"]
        unlocked = data["unlocked"]

        lines: list[str] = []
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
                status = "🟡 Ready to unlock"

            lines.append(f"`{sid}` • **{name}** ({stype})\n{desc}\n{status}")

        e = discord.Embed(title=f"🧠 RPG Skills - Lv {level}", description="\n\n".join(lines), color=discord.Color.dark_teal())
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
    async def hunt(interaction: discord.Interaction):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await interaction.response.send_message(tr(lang, "common.server_only"), ephemeral=True)
        await interaction.response.defer()
        result = await CombatService.hunt(interaction.guild.id, interaction.user.id, lang=lang)
        if not result.ok:
            return await interaction.followup.send(tr(lang, "rpg.hunt_unavailable"), ephemeral=True)

        team_lines = await _team_snapshot_lines(interaction.guild.id, interaction.user.id)
        enemy_text = ", ".join(f"{mid} x{cnt}" for mid, cnt in (result.encounters or {}).items()) or "unknown pack"
        progress_bar = _hp_bar(result.kills, max(1, result.pack), 18)
        drop_line = ", ".join(f"{k}x{v}" for k, v in (result.drops or {}).items()) if result.drops else "none"
        card = (
            "```text\n"
            + "+---------------- TEAM HUNT ----------------+\n"
            + f"| Player : {interaction.user.display_name[:27]:27} |\n"
            + "+-------------------------------------------+\n"
            + "| TEAM                                      |\n"
            + "\n".join(f"| {line[:41]:41} |" for line in (team_lines or ["(no team data)"]))
            + "\n+-------------------------------------------+\n"
            + f"| ENEMY : {enemy_text[:33]:33} |\n"
            + f"| CLEAR : {result.kills}/{result.pack} {progress_bar[:18]:18} |\n"
            + f"| REWARD: +{result.gold}g  +{result.xp}xp{' ' * 20} |\n"
            + f"| DROPS : {drop_line[:33]:33} |\n"
            + "+-------------------------------------------+\n"
            + "```"
        )

        e = discord.Embed(
            title="⚔️ Team Hunt Report" if lang == "en" else "⚔️ Báo cáo săn đội",
            color=discord.Color.green() if result.kills == result.pack else discord.Color.orange(),
        )
        e.add_field(name="Log Link", value=tr(lang, "rpg.log_link_hint"), inline=False)
        e.add_field(name="Battle Card", value=card, inline=False)
        if result.drops:
            e.add_field(name=tr(lang, "rpg.drops_field"), value=", ".join(f"{_item_label(k)} x{v}" for k, v in result.drops.items()), inline=False)
        if result.leveled_up:
            e.add_field(name="🎉", value=tr(lang, "rpg.level_up", level=result.level), inline=False)

        view = CombatDetailView("\n".join((result.logs or [])[:20]) if result.logs else tr(lang, "rpg.no_combat_detail"), lang=lang)
        await interaction.followup.send(embed=e, view=view)
        view.message = await interaction.original_response()

    @bot.tree.command(name="boss", description=app_commands.locale_str("cmd.boss.desc"))
    async def boss(interaction: discord.Interaction):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await interaction.response.send_message(tr(lang, "common.server_only"), ephemeral=True)
        await interaction.response.defer()
        result = await CombatService.boss(interaction.guild.id, interaction.user.id, lang=lang)
        if not result.ok:
            return await interaction.followup.send(tr(lang, "rpg.boss_unavailable"), ephemeral=True)

        team_lines = await _team_snapshot_lines(interaction.guild.id, interaction.user.id)
        turns = max(1, sum(1 for line in (result.logs or []) if "attacks" in line or "takes" in line))
        card = (
            "```text\n"
            f"{interaction.user.display_name[:18]} challenges boss\n"
            "\nTEAM\n"
            + "\n".join(team_lines or ["(no team data)"])
            + "\n\nENEMY TEAM\n"
            + f"{result.boss or 'Boss'}\n"
            + "\nRESULT\n"
            + f"{'WIN' if result.win else 'LOSE'} in {turns} turns\n"
            + f"Reward +{result.gold}g  +{result.xp}xp\n"
            + "```"
        )

        e = discord.Embed(
            title=f"👑 Boss Report - {result.boss or 'Boss'}",
            color=discord.Color.orange() if result.win else discord.Color.dark_red(),
            description=("✅ Team thắng!" if result.win else "❌ Team thua trận boss.") if lang == "vi" else ("✅ Team victory!" if result.win else "❌ Team defeated by boss."),
        )
        e.add_field(name="Log Link", value=tr(lang, "rpg.log_link_hint"), inline=False)
        e.add_field(name="Battle Card", value=card, inline=False)
        if result.win:
            if result.drops:
                e.add_field(name=tr(lang, "rpg.drops_field"), value=", ".join(f"{_item_label(k)} x{v}" for k, v in result.drops.items()), inline=False)
            if result.leveled_up:
                e.add_field(name="🎉", value=tr(lang, "rpg.level_up", level=result.level), inline=False)

        view = CombatDetailView("\n".join((result.logs or [])[:20]) if result.logs else tr(lang, "rpg.no_combat_detail"), lang=lang)
        await interaction.followup.send(embed=e, view=view)
        view.message = await interaction.original_response()

    @bot.tree.command(name="dungeon", description=app_commands.locale_str("cmd.dungeon.desc"))
    async def dungeon(interaction: discord.Interaction):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await interaction.response.send_message(tr(lang, "common.server_only"), ephemeral=True)
        await interaction.response.defer()
        result = await CombatService.dungeon(interaction.guild.id, interaction.user.id, lang=lang)
        if not result.ok:
            return await interaction.followup.send(tr(lang, "rpg.dungeon_unavailable"), ephemeral=True)

        team_lines = await _team_snapshot_lines(interaction.guild.id, interaction.user.id)
        floor_bar = _hp_bar(result.floors_cleared, max(1, result.total_floors), 18)
        card = (
            "```text\n"
            f"{interaction.user.display_name[:18]} enters dungeon\n"
            "\nTEAM\n"
            + "\n".join(team_lines or ["(no team data)"])
            + "\n\nENEMY TEAM\n"
            + f"Floors {result.total_floors} (boss at final floor)\n"
            + "\nRESULT\n"
            + f"{result.floors_cleared}/{result.total_floors} cleared {floor_bar}\n"
            + f"Reward +{result.gold}g  +{result.xp}xp\n"
            + "```"
        )

        e = discord.Embed(
            title="🏰 Team Dungeon Report",
            color=discord.Color.green() if result.cleared else discord.Color.dark_red(),
            description=(f"Tầng: **{result.floors_cleared}/{result.total_floors}**" if lang == "vi" else f"Floors: **{result.floors_cleared}/{result.total_floors}**"),
        )
        e.add_field(name="Log Link", value=tr(lang, "rpg.log_link_hint"), inline=False)
        e.add_field(name="Battle Card", value=card, inline=False)
        if result.drops:
            e.add_field(name=tr(lang, "rpg.drops_field"), value=", ".join(f"{_item_label(k)} x{v}" for k, v in result.drops.items()), inline=False)
        if result.leveled_up:
            e.add_field(name="🎉", value=tr(lang, "rpg.level_up", level=result.level), inline=False)

        view = CombatDetailView("\n".join((result.logs or [])[:20]) if result.logs else tr(lang, "rpg.no_combat_detail"), lang=lang)
        await interaction.followup.send(embed=e, view=view)
        view.message = await interaction.original_response()

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
            return await interaction.followup.send(msg, ephemeral=True)

        e = discord.Embed(title="🤝 Party Hunt", color=discord.Color.gold())
        e.add_field(name="Party", value=", ".join(m.mention for m in clean_party), inline=False)

        summary_parts = [f"Hạ: **{result.kills}/{result.pack}**"]
        summary_parts.append(f"+{result.gold} 💰")
        summary_parts.append(f"+{result.xp} ✨")
        e.add_field(name="Tổng", value=" • ".join(summary_parts), inline=False)

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
                e.add_field(name="Thành viên", value="\n".join(lines), inline=False)

        drops = result.drops if isinstance(result.drops, dict) else {}
        if drops:
            drop_parts = [f"{_item_label(k)} x{v}" for k, v in drops.items()]
            e.add_field(name=tr(lang, "rpg.drops_field"), value=", ".join(drop_parts), inline=False)

        logs = result.logs if isinstance(result.logs, list) else []
        combat_detail = "\n".join(logs[:15]) if logs else tr(lang, "rpg.no_combat_detail")
        view = CombatDetailView(combat_detail, lang=lang)
        
        await interaction.followup.send(embed=e, view=view)
        view.message = await interaction.original_response()

    @bot.tree.command(name="quest", description=app_commands.locale_str("cmd.quest.desc"))
    async def quest(interaction: discord.Interaction):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        quests = await QuestService.get_quests(interaction.guild.id, interaction.user.id)
        quest_text = QuestService.format_quests(quests, lang=lang)
        e = discord.Embed(title="📜 RPG Quests", description=quest_text, color=discord.Color.teal())
        await interaction.response.send_message(embed=e, ephemeral=True, files=_collect_files(apply_embed_asset(e, "quest")))

    @bot.tree.command(name="quest_claim", description=app_commands.locale_str("cmd.quest_claim.desc"))
    @app_commands.describe(quest_id=app_commands.locale_str("cmd.quest_claim.param.quest_id"))
    async def quest_claim(interaction: discord.Interaction, quest_id: str):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        result = await QuestService.claim_quest(interaction.guild.id, interaction.user.id, quest_id, lang=lang)
        await interaction.response.send_message(result.message)

    @bot.tree.command(name="rpg_loot", description=app_commands.locale_str("cmd.rpg_loot.desc"))
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
            e.add_field(name=f"{_rarity_emoji(rarity)} {rarity.title()}", value="\n".join(values[:8]), inline=False)
        f = apply_embed_asset(e, "inventory")
        await interaction.response.send_message(embed=e, files=_collect_files(f))

    @bot.tree.command(name="create_character", description=app_commands.locale_str("cmd.create_character.desc"))
    @app_commands.describe(role=app_commands.locale_str("cmd.create_character.param.role"), gender=app_commands.locale_str("cmd.create_character.param.gender"))
    @app_commands.autocomplete(gender=autocomplete_gender, role=autocomplete_role)
    async def create_character(interaction: discord.Interaction, role: str, gender: str = "any"):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        
        async with open_db() as conn:
            main_char = await get_main_character(conn, interaction.guild.id, interaction.user.id)
            if main_char:
                msg = "❌ Bạn đã có Captain rồi!" if lang == "vi" else "❌ You already have a Captain!"
                return await interaction.response.send_message(msg, ephemeral=True)
            
            normalized_role = _normalize_role(role)
            char_id = STARTER_BY_ROLE.get(normalized_role, "")
            if char_id not in CHARACTERS:
                msg = "❌ Character không tồn tại." if lang == "vi" else "❌ Character does not exist."
                return await interaction.response.send_message(msg, ephemeral=True)
            
            player_row = await get_player(conn, interaction.guild.id, interaction.user.id)
            if player_row:
                level, xp, hp, max_hp, attack, defense, gold = map(int, player_row)
                base_hp = CHARACTERS[char_id]["hp"]
                base_atk = CHARACTERS[char_id]["attack"]
                base_def = CHARACTERS[char_id]["defense"]
                scale = 1 + (level - 1) * 0.1
                
                await conn.execute(
                    """
                    INSERT OR IGNORE INTO player_characters(guild_id, user_id, character_id, is_main, level, exp, star, shard_count, obtained_at)
                    VALUES (?, ?, ?, 1, ?, 0, 1, 0, ?)
                    """,
                    (interaction.guild.id, interaction.user.id, char_id, level, int(time.time())),
                )
                await conn.commit()
                
                char_data = CHARACTERS[char_id]
                emoji = char_data.get("emoji", "🎮")
                e = discord.Embed(
                    title=f"{emoji} Captain Deployed!",
                    description=(
                        (
                            f"**{char_data['name']}** đã trở thành Captain của đội hình!\n\n"
                            if lang == "vi"
                            else f"**{char_data['name']}** is now your team Captain!\n\n"
                        )
                        + f"📊 Stats: HP {int(base_hp * scale)} | ATK {int(base_atk * scale)} | DEF {int(base_def * scale)}\n"
                        + f"⭐ Role: {char_data['role'].upper()}\n"
                        + f"🧬 Form: {char_data.get('form', 'Base')}"
                    ),
                    color=discord.Color.green()
                )
                return await interaction.response.send_message(embed=e)
            
            msg = "❌ Bạn chưa có player profile. Dùng `/rpg_start` trước." if lang == "vi" else "❌ You don't have a player profile yet. Use `/rpg_start` first."
            return await interaction.response.send_message(msg, ephemeral=True)

    @bot.tree.command(name="gacha", description=app_commands.locale_str("cmd.gacha.desc"))
    @app_commands.describe(pulls=app_commands.locale_str("cmd.gacha.param.pulls"), banner=app_commands.locale_str("cmd.gacha.param.banner"))
    @app_commands.autocomplete(banner=autocomplete_banner)
    async def gacha(interaction: discord.Interaction, pulls: int = 1, banner: str = "none"):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        
        pulls = max(1, min(10, pulls))
        banner_id = str(banner or "none").lower()
        if banner_id not in GACHA_BANNERS:
            banner_id = "none"
        cost = GACHA_COST * pulls
        
        async with open_db() as conn:
            player_row = await get_player(conn, interaction.guild.id, interaction.user.id)
            if not player_row:
                msg = "❌ Bạn chưa có player profile." if lang == "vi" else "❌ You don't have a player profile yet."
                return await interaction.response.send_message(msg, ephemeral=True)
            
            level, xp, hp, max_hp, attack, defense, gold = map(int, player_row)
            if gold < cost:
                msg = f"❌ Cần {cost} gold, bạn chỉ có {gold} gold." if lang == "vi" else f"❌ Need {cost} gold, you only have {gold}."
                return await interaction.response.send_message(msg, ephemeral=True)
            
            pity_count, _ = await get_gacha_pity(conn, interaction.guild.id, interaction.user.id)
            
            await conn.execute(
                "UPDATE players SET gold = gold - ? WHERE guild_id = ? AND user_id = ?",
                (cost, interaction.guild.id, interaction.user.id)
            )
            
            results = []
            new_chars = []
            duplicates = []
            legendary_progress_ids: list[str] = []
            seen_legendary_ids: set[str] = set()
            
            for _ in range(pulls):
                char_id, rarity = roll_character(pity_count, banner_id=banner_id)
                pity_count = 0 if rarity in {"legendary", "mythic"} else pity_count + 1
                char_meta = CHARACTERS.get(char_id, {})
                if str(char_meta.get("rarity", "")).lower() == "legendary" and char_id not in seen_legendary_ids:
                    seen_legendary_ids.add(char_id)
                    legendary_progress_ids.append(char_id)
                
                try:
                    await conn.execute(
                        """
                        INSERT INTO player_characters(guild_id, user_id, character_id, is_main, level, exp, star, shard_count, obtained_at)
                        VALUES (?, ?, ?, 0, 1, 0, 1, 0, ?)
                        """,
                        (interaction.guild.id, interaction.user.id, char_id, int(time.time())),
                    )
                    new_chars.append(char_id)
                except Exception:
                    await conn.execute(
                        """
                        INSERT INTO player_characters(guild_id, user_id, character_id, is_main, level, exp, star, shard_count, obtained_at)
                        VALUES (?, ?, ?, 0, 1, 0, 1, ?, ?)
                        ON CONFLICT(guild_id, user_id, character_id)
                        DO UPDATE SET shard_count = shard_count + excluded.shard_count
                        """,
                        (interaction.guild.id, interaction.user.id, char_id, DUPLICATE_SHARD_VALUE, int(time.time())),
                    )
                    duplicates.append(char_id)


                results.append((char_id, rarity))

            from .repositories import quest_repo
            await quest_repo.add_quest_progress(conn, interaction.guild.id, interaction.user.id, "summon_times", pulls)
            
            await update_gacha_pity(conn, interaction.guild.id, interaction.user.id, pity_count)
            await conn.commit()
            
            rarity_emoji = {"common": "⚪", "rare": "🔵", "epic": "🟣", "legendary": "🟡", "mythic": "🔴"}
            lines = []
            for char_id, rarity in results:
                char = CHARACTERS.get(char_id, {})
                name = char.get("name", char_id)
                form = char.get("form", "Base")
                emoji = char.get("emoji", "🎮")
                lines.append(f"{rarity_emoji.get(rarity, '⚪')} {emoji} **{name} [{form}]** — {rarity.title()}")
            
            desc = "\n".join(lines)
            if duplicates:
                shard_bonus = len(duplicates) * DUPLICATE_SHARD_VALUE
                desc += f"\n\n🔄 Duplicate: +{shard_bonus} shards"

            if legendary_progress_ids:
                progress_lines: list[str] = []
                for lid in legendary_progress_ids:
                    c = CHARACTERS.get(lid, {})
                    line = str(c.get("evolution_line", ""))
                    mythic_id = get_mythic_form_for_line(line)
                    async with conn.execute(
                        "SELECT shard_count FROM player_characters WHERE guild_id = ? AND user_id = ? AND character_id = ?",
                        (interaction.guild.id, interaction.user.id, lid),
                    ) as cur:
                        row = await cur.fetchone()
                    shards = int(row[0]) if row else 0
                    ascended = False
                    if mythic_id:
                        async with conn.execute(
                            "SELECT 1 FROM player_characters WHERE guild_id = ? AND user_id = ? AND character_id = ?",
                            (interaction.guild.id, interaction.user.id, mythic_id),
                        ) as cur:
                            ascended = (await cur.fetchone()) is not None

                    status = "ascended" if ascended else f"{shards}/{MYTHIC_ASCEND_LEGENDARY_SHARDS}"
                    progress_lines.append(f"• {c.get('name', lid)} (`{lid}`): {status}")

                desc += "\n\n🧩 Mythic shard progress:\n" + "\n".join(progress_lines)

            hint = "\n\n💡 Dùng `/ascend_mythic <legendary_id>` để ghép Mythic thủ công khi bạn muốn."
            if lang == "en":
                hint = "\n\n💡 Use `/ascend_mythic <legendary_id>` to manually ascend Mythic when you want."
            desc += hint
            
            e = discord.Embed(
                title=f"🎰 Gacha Results ({pulls}x)",
                description=desc,
                color=discord.Color.gold()
            )
            if banner_id != "none":
                e.set_footer(text=f"Banner: {GACHA_BANNERS[banner_id]['name']} • Legendary rate-up only")
            await interaction.response.send_message(embed=e)

    @bot.tree.command(name="my_characters", description=app_commands.locale_str("cmd.my_characters.desc"))
    async def my_characters(interaction: discord.Interaction):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        
        async with open_db() as conn:
            chars = await get_player_characters(conn, interaction.guild.id, interaction.user.id)
            
            if not chars:
                msg = "❌ Bạn chưa có hero nào. Dùng `/create_character` hoặc `/gacha`." if lang == "vi" else "❌ You don't own any heroes yet. Use `/create_character` or `/gacha`."
                return await interaction.response.send_message(msg, ephemeral=True)
            
            owned_ids = {str(r[1]) for r in chars}
            lines = []
            for row in chars:
                _, cid, is_main, level, exp, star, shard, name, rarity, role, passive = row
                c = CHARACTERS.get(str(cid), {})
                form = str(c.get("form", "Base"))
                emoji = "⭐" if is_main else "  "
                ascend = _legendary_ascend_status(str(cid), int(shard), owned_ids)
                lines.append(
                    f"{emoji} **{name} [{form}]** (`{cid}`) Lv.{level} ★{star} | {rarity.title()} | {role} | shard {int(shard)}{ascend}"
                )
            
            e = discord.Embed(
                title="🎭 Hero Collection",
                description="\n".join(lines),
                color=discord.Color.blue()
            )
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

        lid = str(legendary_id or "").strip().lower()
        char = CHARACTERS.get(lid)
        if not char:
            msg = "❌ Character ID không tồn tại." if lang == "vi" else "❌ Character ID does not exist."
            return await interaction.response.send_message(msg, ephemeral=True)
        if str(char.get("rarity", "")).lower() != "legendary":
            msg = "❌ Chỉ ghép từ bản **legendary**." if lang == "vi" else "❌ Only **legendary** form can ascend."
            return await interaction.response.send_message(msg, ephemeral=True)

        line = str(char.get("evolution_line", ""))
        mythic_id = get_mythic_form_for_line(line)
        if not mythic_id:
            msg = "❌ Character này chưa có mythic form." if lang == "vi" else "❌ This character has no mythic form yet."
            return await interaction.response.send_message(msg, ephemeral=True)

        async with open_db() as conn:
            async with conn.execute(
                "SELECT 1 FROM player_characters WHERE guild_id = ? AND user_id = ? AND character_id = ?",
                (interaction.guild.id, interaction.user.id, lid),
            ) as cur:
                has_legend = await cur.fetchone()
            if not has_legend:
                msg = "❌ Bạn chưa sở hữu bản legendary này." if lang == "vi" else "❌ You don't own this legendary yet."
                return await interaction.response.send_message(msg, ephemeral=True)

            async with conn.execute(
                "SELECT shard_count FROM player_characters WHERE guild_id = ? AND user_id = ? AND character_id = ?",
                (interaction.guild.id, interaction.user.id, lid),
            ) as cur:
                row = await cur.fetchone()
            shards = int(row[0]) if row else 0

            unlocked = await _try_ascend_mythic(conn, interaction.guild.id, interaction.user.id, lid)
            if not unlocked:
                await conn.commit()
                msg = f"❌ Chưa đủ mảnh hoặc đã có mythic. Tiến độ: **{shards}/{MYTHIC_ASCEND_LEGENDARY_SHARDS}**"
                if lang == "en":
                    msg = f"❌ Not enough shards or mythic already unlocked. Progress: **{shards}/{MYTHIC_ASCEND_LEGENDARY_SHARDS}**"
                return await interaction.response.send_message(
                    msg,
                    ephemeral=True,
                )

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
        await interaction.response.send_message(
            ok_msg
        )

    @bot.tree.command(name="team", description=app_commands.locale_str("cmd.team.desc"))
    @app_commands.describe(action=app_commands.locale_str("cmd.team.param.action"), character_id=app_commands.locale_str("cmd.team.param.character_id"), slot=app_commands.locale_str("cmd.team.param.slot"))
    async def team(interaction: discord.Interaction, action: str = "view", character_id: str = None, slot: int = 1):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)
        
        async with open_db() as conn:
            if action == "view":
                main = await get_main_character(conn, interaction.guild.id, interaction.user.id)
                team_chars = await get_team(conn, interaction.guild.id, interaction.user.id)
                if not main and not team_chars:
                    msg = "❌ Bạn chưa có Captain. Dùng `/create_character` trước." if lang == "vi" else "❌ You don't have a Captain yet. Use `/create_character` first."
                    return await interaction.response.send_message(msg, ephemeral=True)
                
                lines = []
                total_power = 0.0
                if main:
                    m_power = calculate_team_power(int(main[10]), int(main[11]), int(main[12]), int(main[3]), int(main[5]))
                    total_power += m_power
                    mc = CHARACTERS.get(str(main[1]), {})
                    mform = str(mc.get("form", "Base"))
                    lines.append(
                        f"Captain: **{main[7]} [{mform}]** (`{main[1]}`) Lv.{main[3]} ★{main[5]} | {str(main[8]).title()} | {main[9]}"
                    )

                for row in team_chars:
                    s, cid, name, rarity, role, hp, atk, defn, spd, passive, lvl, star = row
                    total_power += calculate_team_power(hp, atk, defn, lvl, star)
                    cc = CHARACTERS.get(str(cid), {})
                    form = str(cc.get("form", "Base"))
                    lines.append(
                        f"Hero Slot {s}: **{name} [{form}]** (`{cid}`) Lv.{lvl} ★{star} | {str(rarity).title()} | {role}"
                    )
                
                e = discord.Embed(
                    title="⚔️ My Team" if lang == "en" else "⚔️ Đội hình của tôi",
                    description="\n".join(lines) + (f"\n\n💪 Team Power: {int(total_power)}" if lang == "en" else f"\n\n💪 Sức mạnh đội: {int(total_power)}"),
                    color=discord.Color.orange()
                )
                return await interaction.response.send_message(embed=e)
            
            elif action == "add":
                if not character_id:
                    msg = "❌ Cần ID hero." if lang == "vi" else "❌ Hero ID is required."
                    return await interaction.response.send_message(msg, ephemeral=True)
                
                main = await get_main_character(conn, interaction.guild.id, interaction.user.id)
                if not main:
                    msg = "❌ Bạn chưa có Captain. Dùng `/create_character` trước." if lang == "vi" else "❌ You don't have a Captain yet. Use `/create_character` first."
                    return await interaction.response.send_message(msg, ephemeral=True)

                owned = await get_player_characters(conn, interaction.guild.id, interaction.user.id)
                owned_ids = {str(row[1]) for row in owned}
                
                if character_id not in owned_ids:
                    msg = "❌ Bạn không sở hữu hero này." if lang == "vi" else "❌ You don't own this hero."
                    return await interaction.response.send_message(msg, ephemeral=True)

                if character_id == str(main[1]):
                    msg = "❌ Captain đã cố định, không thêm vào hero slot." if lang == "vi" else "❌ Captain is fixed and cannot be added to hero slots."
                    return await interaction.response.send_message(msg, ephemeral=True)

                team_chars = await get_team(conn, interaction.guild.id, interaction.user.id)
                if any(str(row[1]) == character_id for row in team_chars):
                    msg = "❌ Hero này đã có trong team." if lang == "vi" else "❌ This hero is already in your team."
                    return await interaction.response.send_message(msg, ephemeral=True)
                
                slot = max(1, min(4, slot))
                await set_team_character(conn, interaction.guild.id, interaction.user.id, slot, character_id)
                await conn.commit()
                
                char = CHARACTERS.get(character_id, {})
                msg = f"✅ Đã thêm **{char.get('name', character_id)}** vào hero slot {slot}." if lang == "vi" else f"✅ Added **{char.get('name', character_id)}** to hero slot {slot}."
                return await interaction.response.send_message(msg)
            
            elif action == "reset":
                await clear_team(conn, interaction.guild.id, interaction.user.id)
                await conn.commit()
                msg = "✅ Đã reset team." if lang == "vi" else "✅ Team has been reset."
                return await interaction.response.send_message(msg)
            
            else:
                msg = "❌ Action không hợp lệ. Dùng: view, add, reset" if lang == "vi" else "❌ Invalid action. Use: view, add, reset"
                return await interaction.response.send_message(msg, ephemeral=True)

    @bot.tree.command(name="team_stats", description=app_commands.locale_str("cmd.team_stats.desc"))
    async def team_stats(interaction: discord.Interaction):
        lang = await resolve_lang(interaction)
        if interaction.guild is None:
            return await _server_only_interaction(interaction)

        async with open_db() as conn:
            main = await get_main_character(conn, interaction.guild.id, interaction.user.id)
            team_chars = await get_team(conn, interaction.guild.id, interaction.user.id)
            if not main and not team_chars:
                msg = "❌ Bạn chưa có team. Dùng `/create_character` và `/team add` trước." if lang == "vi" else "❌ You don't have a team yet. Use `/create_character` and `/team add` first."
                return await interaction.response.send_message(msg, ephemeral=True)

            members: list[tuple[str, str, str, int, int, int, int, int]] = []
            if main:
                mid = str(main[1])
                mc = CHARACTERS.get(mid, {})
                mform = str(mc.get("form", "Base"))
                members.append((str(main[7]), mform, str(main[9]), int(main[10]), int(main[11]), int(main[12]), int(main[3]), int(main[5])))
            for row in team_chars[:4]:
                cid = str(row[1])
                cc = CHARACTERS.get(cid, {})
                form = str(cc.get("form", "Base"))
                members.append((str(row[2]), form, str(row[4]), int(row[5]), int(row[6]), int(row[7]), int(row[10]), int(row[11])))

        total_hp = sum(m[3] for m in members)
        total_atk = sum(m[4] for m in members)
        total_def = sum(m[5] for m in members)
        avg_lvl = int(sum(m[6] for m in members) / max(1, len(members)))
        team_power = int(sum(calculate_team_power(m[3], m[4], m[5], m[6], m[7]) for m in members))

        role_count: dict[str, int] = defaultdict(int)
        for m in members:
            r = _normalize_role(m[2])
            role_count[r] += 1
        role_line = " • ".join(f"{k}:{v}" for k, v in role_count.items()) or "n/a"

        e = discord.Embed(
            title="⚔ Team Stats",
            description="═════ ✠ Battle Formation ✠ ═════",
            color=discord.Color.from_rgb(198, 161, 91),
        )
        e.add_field(name="Power", value=f"**{team_power}**", inline=True)
        e.add_field(name="Avg Level", value=f"**{avg_lvl}**", inline=True)
        e.add_field(name="Roles", value=role_line, inline=False)
        e.add_field(name="Vitality", value=str(total_hp), inline=True)
        e.add_field(name="Might", value=str(total_atk), inline=True)
        e.add_field(name="Guard", value=str(total_def), inline=True)
        e.add_field(name="Members", value="\n".join(f"• {m[0]} [{m[1]}] ({m[2]}) Lv.{m[6]} ★{m[7]}" for m in members[:5]), inline=False)
        await interaction.response.send_message(embed=e)

    @bot.command(name="rs")
    async def text_rpg_start(ctx: commands.Context):
        lang = await _lang_for_ctx(ctx)
        if ctx.guild is None:
            return await _server_only_ctx(ctx)
        await ensure_db_ready()
        async with open_db() as conn:
            from .repositories import player_repo, quest_repo
            await player_repo.ensure_player_ready(conn, ctx.guild.id, ctx.author.id)
            await quest_repo.ensure_default_quests(conn, ctx.guild.id, ctx.author.id)
            await conn.commit()
        msg = "✅ Đã tạo hồ sơ chỉ huy RPG. Dùng `s!cc <role>` (vd: `s!cc dps`) hoặc `/create_character`." if lang == "vi" else "✅ Commander profile created. Use `s!cc <role>` (e.g. `s!cc dps`) or `/create_character`."
        await ctx.reply(msg)

    @bot.command(name="cc")
    async def text_create_character(ctx: commands.Context, role: str):
        lang = await _lang_for_ctx(ctx)
        if ctx.guild is None:
            return await _server_only_ctx(ctx)
        async with open_db() as conn:
            main_char = await get_main_character(conn, ctx.guild.id, ctx.author.id)
            if main_char:
                msg = "❌ Bạn đã có Captain rồi." if lang == "vi" else "❌ You already have a Captain."
                return await ctx.reply(msg)
            char_id = STARTER_BY_ROLE.get(_normalize_role(role), "")
            if char_id not in CHARACTERS:
                msg = "❌ Role không hợp lệ. Dùng: `dps`, `tank`, `healer`, `support` hoặc `sp`." if lang == "vi" else "❌ Invalid role. Use: `dps`, `tank`, `healer`, `support` or `sp`."
                return await ctx.reply(msg)

            player_row = await get_player(conn, ctx.guild.id, ctx.author.id)
            if not player_row:
                msg = "❌ Bạn chưa có player profile. Dùng `s!rs` hoặc `/rpg_start` trước." if lang == "vi" else "❌ You don't have a player profile yet. Use `s!rs` or `/rpg_start` first."
                return await ctx.reply(msg)
            level = int(player_row[0])
            await conn.execute(
                """
                INSERT OR IGNORE INTO player_characters(guild_id, user_id, character_id, is_main, level, exp, star, shard_count, obtained_at)
                VALUES (?, ?, ?, 1, ?, 0, 1, 0, ?)
                """,
                (ctx.guild.id, ctx.author.id, char_id, level, int(time.time())),
            )
            await conn.commit()
        c = CHARACTERS[char_id]
        msg = f"✅ Captain: **{c.get('name', char_id)} [{c.get('form','Base')}]** ({c.get('role','unknown')})"
        if lang == "en":
            msg = f"✅ Captain set: **{c.get('name', char_id)} [{c.get('form','Base')}]** ({c.get('role','unknown')})"
        await ctx.reply(msg)

    @bot.command(name="p", aliases=["st"])
    async def text_profile(ctx: commands.Context, member: Optional[discord.Member] = None):
        lang = await _lang_for_ctx(ctx)
        if ctx.guild is None:
            return await ctx.reply(tr(lang, "common.server_only"))
        target = member or ctx.author
        result = await PlayerService.get_profile(ctx.guild.id, target.id)
        if not result.ok:
            return await ctx.reply(tr(lang, "rpg.profile_fetch_failed"))
        lore = await _profile_lore_meta(ctx.guild.id, target.id)
        e = _build_profile_embed(target, result, lore, lang=lang)
        if ctx.invoked_with == "st":
            e.title = f"📊 Team Stats - {target.display_name}"
        await ctx.reply(embed=e)

    @bot.command(name="h")
    async def text_hunt(ctx: commands.Context):
        lang = await _lang_for_ctx(ctx)
        if ctx.guild is None:
            return await ctx.reply(tr(lang, "common.server_only"))
        result = await CombatService.hunt(ctx.guild.id, ctx.author.id, lang=lang)
        if not result.ok:
            return await ctx.reply(tr(lang, "rpg.hunt_unavailable"))
        team_lines = await _team_snapshot_lines(ctx.guild.id, ctx.author.id)
        progress_bar = _hp_bar(result.kills, max(1, result.pack), 16)
        card = (
            "```text\n"
            + f"TEAM HUNT | {ctx.author.display_name[:18]}\n"
            + "\n".join(team_lines or ["(no team data)"])
            + f"\nClear: {result.kills}/{result.pack} {progress_bar}\n"
            + f"Reward: +{result.gold}g +{result.xp}xp\n"
            + "```"
        )
        await ctx.reply(card)

    @bot.command(name="b")
    async def text_boss(ctx: commands.Context):
        lang = await _lang_for_ctx(ctx)
        if ctx.guild is None:
            return await ctx.reply(tr(lang, "common.server_only"))
        result = await CombatService.boss(ctx.guild.id, ctx.author.id, lang=lang)
        if not result.ok:
            return await ctx.reply(tr(lang, "rpg.boss_unavailable"))
        verdict = "WIN" if result.win else "LOSE"
        await ctx.reply(f"👑 Boss `{result.boss}`: **{verdict}** | +{result.gold}g +{result.xp}xp")

    @bot.command(name="d")
    async def text_dungeon(ctx: commands.Context):
        lang = await _lang_for_ctx(ctx)
        if ctx.guild is None:
            return await ctx.reply(tr(lang, "common.server_only"))
        result = await CombatService.dungeon(ctx.guild.id, ctx.author.id, lang=lang)
        if not result.ok:
            return await ctx.reply(tr(lang, "rpg.dungeon_unavailable"))
        await ctx.reply(
            f"🏰 Dungeon: **{result.floors_cleared}/{result.total_floors}** | +{result.gold}g +{result.xp}xp"
        )

    @bot.command(name="g")
    async def text_gacha(ctx: commands.Context, pulls: int = 1, banner: str = "none"):
        lang = await _lang_for_ctx(ctx)
        if ctx.guild is None:
            return await _server_only_ctx(ctx)
        pulls = max(1, min(10, int(pulls)))
        banner_id = str(banner or "none").lower()
        if banner_id not in GACHA_BANNERS:
            banner_id = "none"
        async with open_db() as conn:
            player_row = await get_player(conn, ctx.guild.id, ctx.author.id)
            if not player_row:
                msg = "❌ Bạn chưa có player profile. Dùng `/rpg_start` trước." if lang == "vi" else "❌ You don't have a player profile yet. Use `/rpg_start` first."
                return await ctx.reply(msg)
            gold = int(player_row[6])
            total_cost = GACHA_COST * pulls
            if gold < total_cost:
                msg = f"❌ Không đủ gold. Cần {total_cost}, bạn có {gold}." if lang == "vi" else f"❌ Not enough gold. Need {total_cost}, you have {gold}."
                return await ctx.reply(msg)

            await conn.execute(
                "UPDATE players SET gold = gold - ? WHERE guild_id = ? AND user_id = ?",
                (total_cost, ctx.guild.id, ctx.author.id),
            )

            pity_count, _ = await get_gacha_pity(conn, ctx.guild.id, ctx.author.id)
            rolled: list[str] = []
            legendary_progress_ids: list[str] = []
            seen_legendary_ids: set[str] = set()
            for _ in range(pulls):
                char_id, rarity = roll_character(pity_count, banner_id=banner_id)
                pity_count = 0 if rarity in {"legendary", "mythic"} else pity_count + 1
                c = CHARACTERS.get(char_id, {})
                if str(c.get("rarity", "")).lower() == "legendary" and char_id not in seen_legendary_ids:
                    seen_legendary_ids.add(char_id)
                    legendary_progress_ids.append(char_id)
                rolled.append(f"{c.get('name', char_id)} [{c.get('form', 'Base')}] ({rarity})")
                await conn.execute(
                    """
                    INSERT INTO player_characters(guild_id, user_id, character_id, is_main, level, exp, star, shard_count, obtained_at)
                    VALUES (?, ?, ?, 0, 1, 0, 1, 0, ?)
                    ON CONFLICT(guild_id, user_id, character_id)
                    DO UPDATE SET shard_count = shard_count + ?
                    """,
                    (ctx.guild.id, ctx.author.id, char_id, int(time.time()), DUPLICATE_SHARD_VALUE),
                )
            from .repositories import quest_repo
            await quest_repo.add_quest_progress(conn, ctx.guild.id, ctx.author.id, "summon_times", pulls)
            await update_gacha_pity(conn, ctx.guild.id, ctx.author.id, pity_count)
            await conn.commit()
            progress_lines: list[str] = []
            for lid in legendary_progress_ids:
                c = CHARACTERS.get(lid, {})
                line = str(c.get("evolution_line", ""))
                mythic_id = get_mythic_form_for_line(line)
                async with conn.execute(
                    "SELECT shard_count FROM player_characters WHERE guild_id = ? AND user_id = ? AND character_id = ?",
                    (ctx.guild.id, ctx.author.id, lid),
                ) as cur:
                    row = await cur.fetchone()
                shards = int(row[0]) if row else 0
                ascended = False
                if mythic_id:
                    async with conn.execute(
                        "SELECT 1 FROM player_characters WHERE guild_id = ? AND user_id = ? AND character_id = ?",
                        (ctx.guild.id, ctx.author.id, mythic_id),
                    ) as cur:
                        ascended = (await cur.fetchone()) is not None
                status = "ascended" if ascended else f"{shards}/{MYTHIC_ASCEND_LEGENDARY_SHARDS}"
                progress_lines.append(f"- {c.get('name', lid)} ({lid}): {status}")
        banner_note = f" | banner={banner_id}" if banner_id != "none" else ""
        msg = "🎲 Gacha" + banner_note + ": " + ", ".join(rolled[:10])
        if progress_lines:
            msg += "\n🧩 Mythic shard progress:\n" + "\n".join(progress_lines)
        msg += "\n💡 Dùng `s!am <legendary_id>` để ghép Mythic thủ công khi bạn muốn." if lang == "vi" else "\n💡 Use `s!am <legendary_id>` to manually ascend Mythic when you want."
        await ctx.reply(msg)

    @bot.command(name="mc")
    async def text_my_characters(ctx: commands.Context):
        lang = await _lang_for_ctx(ctx)
        if ctx.guild is None:
            return await _server_only_ctx(ctx)
        async with open_db() as conn:
            chars = await get_player_characters(conn, ctx.guild.id, ctx.author.id)
        if not chars:
            msg = "❌ Bạn chưa có hero nào." if lang == "vi" else "❌ You don't own any heroes yet."
            return await ctx.reply(msg)
        lines = []
        for row in chars[:12]:
            _, cid, is_main, level, _, star, _, name, rarity, role, _ = row
            c = CHARACTERS.get(str(cid), {})
            form = str(c.get("form", "Base"))
            marker = "⭐" if is_main else "•"
            lines.append(f"{marker} {name} [{form}] Lv.{level} *{star} {rarity}")
        await ctx.reply("\n".join(lines))

    @bot.command(name="tm")
    async def text_team(ctx: commands.Context, action: str = "view", character_id: str = "", slot: int = 1):
        lang = await _lang_for_ctx(ctx)
        if ctx.guild is None:
            return await _server_only_ctx(ctx)
        async with open_db() as conn:
            if action == "view":
                main = await get_main_character(conn, ctx.guild.id, ctx.author.id)
                team_chars = await get_team(conn, ctx.guild.id, ctx.author.id)
                if not main and not team_chars:
                    msg = "❌ Team trống. Dùng `s!cc`/`s!g` trước." if lang == "vi" else "❌ Team is empty. Use `s!cc`/`s!g` first."
                    return await ctx.reply(msg)
                lines = await _team_snapshot_lines(ctx.guild.id, ctx.author.id)
                return await ctx.reply("```text\n" + "\n".join(lines) + "\n```")
            if action == "reset":
                await clear_team(conn, ctx.guild.id, ctx.author.id)
                await conn.commit()
                msg = "✅ Đã reset team hero slots." if lang == "vi" else "✅ Team hero slots reset."
                return await ctx.reply(msg)
            if action == "add":
                if not character_id:
                    msg = "❌ Dùng: `s!tm add <character_id> [slot]`" if lang == "vi" else "❌ Use: `s!tm add <character_id> [slot]`"
                    return await ctx.reply(msg)
                slot = max(1, min(4, int(slot)))
                await set_team_character(conn, ctx.guild.id, ctx.author.id, slot, character_id)
                await conn.commit()
                msg = f"✅ Đã thêm `{character_id}` vào slot {slot}." if lang == "vi" else f"✅ Added `{character_id}` to slot {slot}."
                return await ctx.reply(msg)
        msg = "❌ Action không hợp lệ. Dùng `view|add|reset`." if lang == "vi" else "❌ Invalid action. Use `view|add|reset`."
        await ctx.reply(msg)

    @bot.command(name="q")
    async def text_quest(ctx: commands.Context):
        lang = await _lang_for_ctx(ctx)
        if ctx.guild is None:
            return await _server_only_ctx(ctx)
        quests = await QuestService.get_quests(ctx.guild.id, ctx.author.id)
        await ctx.reply(QuestService.format_quests(quests, lang=lang)[:1800] or ("Không có quest." if lang == "vi" else "No quests found."))

    @bot.command(name="qc")
    async def text_quest_claim(ctx: commands.Context, quest_id: str):
        lang = await _lang_for_ctx(ctx)
        if ctx.guild is None:
            return await _server_only_ctx(ctx)
        result = await QuestService.claim_quest(ctx.guild.id, ctx.author.id, quest_id, lang=lang)
        await ctx.reply(result.message)

    @bot.command(name="am")
    async def text_ascend_mythic(ctx: commands.Context, legendary_id: str):
        lang = await _lang_for_ctx(ctx)
        if ctx.guild is None:
            return await _server_only_ctx(ctx)
        lid = str(legendary_id or "").strip().lower()
        c = CHARACTERS.get(lid)
        if not c:
            msg = "❌ Character ID không tồn tại." if lang == "vi" else "❌ Character ID does not exist."
            return await ctx.reply(msg)
        if str(c.get("rarity", "")).lower() != "legendary":
            msg = "❌ Chỉ ghép từ bản legendary." if lang == "vi" else "❌ Only legendary form can ascend."
            return await ctx.reply(msg)
        async with open_db() as conn:
            async with conn.execute(
                "SELECT shard_count FROM player_characters WHERE guild_id = ? AND user_id = ? AND character_id = ?",
                (ctx.guild.id, ctx.author.id, lid),
            ) as cur:
                row = await cur.fetchone()
            shards = int(row[0]) if row else 0
            unlocked = await _try_ascend_mythic(conn, ctx.guild.id, ctx.author.id, lid)
            await conn.commit()
        if not unlocked:
            msg = f"❌ Chưa ghép được. Tiến độ: {shards}/{MYTHIC_ASCEND_LEGENDARY_SHARDS}" if lang == "vi" else f"❌ Ascend failed. Progress: {shards}/{MYTHIC_ASCEND_LEGENDARY_SHARDS}"
            return await ctx.reply(msg)
        m = CHARACTERS.get(unlocked, {})
        await ctx.reply(f"🌌 Ascended: {m.get('name', unlocked)} [{m.get('form','Mythic')}]")


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
        app_commands.Choice(name="SP (short)", value="sp"),
    ]
    return [o for o in options if current.lower() in o.name.lower()]


async def autocomplete_banner(interaction: discord.Interaction, current: str):
    options = [
        app_commands.Choice(name=f"{cfg['name']} ({bid})", value=bid)
        for bid, cfg in GACHA_BANNERS.items()
    ]
    low = current.lower()
    return [o for o in options if low in o.name.lower() or low in o.value.lower()][:25]
