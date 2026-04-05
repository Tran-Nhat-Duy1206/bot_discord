import random
import time
from collections import defaultdict, deque
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from .utils.assets import apply_embed_asset, apply_item_asset, apply_monster_asset, reload_assets
from .utils.combatlog import build_combat_log_text, publish_combat_log
from .data.data import ITEMS, CRAFT_RECIPES, SKILLS, xp_need_for_next
from .utils.events import event_brief
from .db.db import ensure_db_ready, open_db

from .services.combat_service import CombatService
from .services.economy_service import EconomyService
from .services.quest_service import QuestService
from .services.player_service import PlayerService


RPG_COMMAND_RATE_USER_MAX = 12
RPG_COMMAND_RATE_USER_WINDOW = 20
RPG_COMMAND_RATE_GUILD_MAX = 120
RPG_COMMAND_RATE_GUILD_WINDOW = 20

_USER_RATE_BUCKET: dict[int, deque[float]] = defaultdict(deque)
_GUILD_RATE_BUCKET: dict[int, deque[float]] = defaultdict(deque)

RPG_COMMAND_NAMES = {
    "rpg_assets_reload", "rpg_start", "profile", "stats", "rpg_balance",
    "rpg_daily", "rpg_pay", "rpg_shop", "craft_list", "craft",
    "rpg_buy", "rpg_sell", "rpg_inventory", "rpg_equipment",
    "equip", "unequip", "rpg_skills", "rpg_skill_unlock", "rpg_skill_use",
    "rpg_use", "open", "rpg_drop", "rpg_event", "hunt", "boss",
    "dungeon", "party_hunt", "quest", "quest_claim",
    "rpg_loot", "rpg_balance_dashboard", "rpg_economy_audit",
    "rpg_season_status", "rpg_season_rollover", "rpg_jackpot", "rpg_leaderboard",
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


def _rarity_emoji(rarity: str) -> str:
    r = (rarity or "common").lower()
    return {"common": "⚪", "uncommon": "🟢", "rare": "🔵", "epic": "🟣", "legendary": "🟡"}.get(r, "⚫")


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


def _build_hunt_embed(result, interaction: discord.Interaction) -> tuple[discord.Embed, list[discord.File]]:
    drops = result.drops if isinstance(result.drops, dict) else {}
    drop_txt = ", ".join(f"{_item_label(item_id)} x{amount}" for item_id, amount in drops.items()) if drops else "Không có"
    rarity_map = result.drop_rarity if isinstance(result.drop_rarity, dict) else {}
    rarity_txt = ", ".join(f"{_rarity_emoji(str(k))} {str(k)} x{int(v)}" for k, v in rarity_map.items()) if rarity_map else "(none)"

    e = discord.Embed(title="⚔️ Kết quả Hunt", color=discord.Color.red())
    e.add_field(name="Đã gặp", value=f"{result.pack} quái", inline=True)
    e.add_field(name="Hạ gục", value=str(result.kills), inline=True)
    e.add_field(name="Slime", value=str(result.slime_kills), inline=True)
    e.add_field(name="Reward", value=f"+{result.gold} gold\n+{result.xp} xp", inline=False)
    e.add_field(name="Combat Passive", value=_passive_text(result.combat_effects.lifesteal, result.combat_effects.crit_bonus, result.combat_effects.damage_reduction), inline=False)
    if result.set_bonus:
        e.add_field(name="Set Bonus", value=f"🧩 {result.set_bonus}", inline=False)
    if result.weekly_event:
        e.add_field(name="Weekly Event", value=str(result.weekly_event.get("name", "Weekly Event")), inline=False)
    if result.passive_skills:
        e.add_field(name="Skill Passive", value="\n".join(f"• {s}" for s in result.passive_skills[:3]), inline=False)
    if result.lifesteal_heal > 0 or result.damage_blocked > 0:
        e.add_field(name="Passive Impact", value=f"❤️ +{result.lifesteal_heal} HP lifesteal • 🛡️ chặn {result.damage_blocked} dmg", inline=False)
    e.add_field(name="Drops", value=drop_txt, inline=False)
    e.add_field(name="Drop Rarity", value=rarity_txt, inline=False)
    if result.jackpot_hits > 0:
        e.add_field(name="Slime Jackpot", value=f"✨ {result.jackpot_hits} hit(s), +{result.jackpot_gold} gold", inline=False)
    e.add_field(name="HP còn lại", value=str(result.hp), inline=True)
    if result.leveled_up:
        e.add_field(name="Level Up", value=f"🎉 Lên level **{result.level}**", inline=True)
    if result.logs:
        e.add_field(name="Chi tiết", value="\n".join(result.logs[:10]), inline=False)

    encounters = result.encounters if isinstance(result.encounters, dict) else {}
    encounter_ids = list(encounters.keys())
    hunt_asset_file = apply_monster_asset(e, encounter_ids[0]) if encounter_ids else None
    if hunt_asset_file is None:
        hunt_asset_file = apply_embed_asset(e, "hunt")

    return e, _collect_files(hunt_asset_file)


def _build_boss_embed(result, interaction: discord.Interaction) -> tuple[discord.Embed, list[discord.File]]:
    is_win = result.win
    e = discord.Embed(title="👑 Boss Victory" if is_win else "💀 Boss Defeat", color=discord.Color.orange() if is_win else discord.Color.dark_red())
    if not is_win:
        e.description = f"Bạn đã thua trước **{result.boss}**.\nHP còn lại: **{result.base_hp}**"
    else:
        e.add_field(name="Boss", value=str(result.boss), inline=True)
        e.add_field(name="Reward", value=f"+{result.gold} gold\n+{result.xp} xp", inline=False)

    e.add_field(name="Combat Passive", value=_passive_text(result.combat_effects.lifesteal, result.combat_effects.crit_bonus, result.combat_effects.damage_reduction), inline=False)
    if result.set_bonus:
        e.add_field(name="Set Bonus", value=f"🧩 {result.set_bonus}", inline=False)
    if result.weekly_event:
        e.add_field(name="Weekly Event", value=str(result.weekly_event.get("name", "Weekly Event")), inline=False)
    if result.passive_skills:
        e.add_field(name="Skill Passive", value="\n".join(f"• {s}" for s in result.passive_skills[:3]), inline=False)
    if result.lifesteal_heal > 0 or result.damage_blocked > 0:
        e.add_field(name="Passive Impact", value=f"❤️ +{result.lifesteal_heal} HP lifesteal • 🛡️ chặn {result.damage_blocked} dmg", inline=False)
    e.add_field(name="Boss Mechanics", value=f"Rage: {'Yes' if result.rage_triggered else 'No'} • Shield turns: {result.shield_turns} • Summons: {result.summon_count}", inline=False)
    if result.phase_events:
        e.add_field(name="Mechanic Timeline", value="\n".join(result.phase_events[:4]), inline=False)
    drops = result.drops if isinstance(result.drops, dict) else {}
    if drops:
        e.add_field(name="Drops", value=", ".join(f"{_item_label(k)} x{v}" for k, v in drops.items()), inline=False)
    e.add_field(name="HP còn lại", value=str(result.base_hp), inline=True)
    if result.leveled_up:
        e.add_field(name="Level Up", value=f"🎉 Lên level **{result.level}**", inline=True)
    if result.logs:
        e.add_field(name="Chi tiết", value="\n".join(result.logs[:8]), inline=False)

    boss_asset_file = apply_monster_asset(e, result.boss_id)
    if boss_asset_file is None:
        boss_asset_file = apply_embed_asset(e, "boss")

    return e, _collect_files(boss_asset_file)


def setup(bot: commands.Bot, guilds: list = None):
    guilds = guilds or []

    async def _rpg_rate_limit_check(interaction: discord.Interaction) -> bool:
        cmd = interaction.command
        cmd_name = str(getattr(cmd, "name", "")).strip().lower()
        if cmd_name not in RPG_COMMAND_NAMES:
            return True

        now_ts = time.time()
        user_wait = _rate_check(_USER_RATE_BUCKET, interaction.user.id, now_ts, RPG_COMMAND_RATE_USER_WINDOW, RPG_COMMAND_RATE_USER_MAX)
        if user_wait > 0:
            raise app_commands.CheckFailure(f"⏳ Bạn thao tác RPG quá nhanh. Thử lại sau {user_wait:.1f}s.")

        if interaction.guild is not None:
            guild_wait = _rate_check(_GUILD_RATE_BUCKET, interaction.guild.id, now_ts, RPG_COMMAND_RATE_GUILD_WINDOW, RPG_COMMAND_RATE_GUILD_MAX)
            if guild_wait > 0:
                raise app_commands.CheckFailure(f"⏳ Server đang spam RPG command. Thử lại sau {guild_wait:.1f}s.")
        return True

    bot.tree.interaction_check = _rpg_rate_limit_check

    async def _on_ready_once():
        await ensure_db_ready()
        reload_assets()

    bot.add_listener(_on_ready_once, "on_ready")

    @bot.tree.command(name="rpg_start", description="Khởi tạo nhân vật RPG")
    async def rpg_start(interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        await ensure_db_ready()
        async with open_db() as conn:
            from .repositories import player_repo, quest_repo
            await player_repo.ensure_player_ready(conn, interaction.guild.id, interaction.user.id)
            await quest_repo.ensure_default_quests(conn, interaction.guild.id, interaction.user.id)
            await conn.commit()
        await interaction.response.send_message("✅ Đã tạo nhân vật RPG! Dùng `/profile` hoặc `/hunt`.", ephemeral=True)

    @bot.tree.command(name="profile", description="Xem hồ sơ RPG")
    @app_commands.describe(member="Xem hồ sơ người khác")
    async def profile(interaction: discord.Interaction, member: Optional[discord.Member] = None):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        target = _member_or_self(interaction, member)
        if target is None:
            return await interaction.response.send_message("❌ Không xác định được member.", ephemeral=True)

        result = await PlayerService.get_profile(interaction.guild.id, target.id)
        if not result.ok:
            return await interaction.response.send_message("❌ Không lấy được dữ liệu nhân vật.", ephemeral=True)

        eff_hp = min(result.max_hp, result.hp)
        eff_max_hp = result.max_hp
        eff_attack = result.attack + int(result.equipped.get("attack", 0)) if isinstance(result.equipped, dict) else result.attack
        eff_defense = result.defense + int(result.equipped.get("defense", 0)) if isinstance(result.equipped, dict) else result.defense

        equip_text = []
        if isinstance(result.equipped, dict):
            for slot in ("weapon", "armor", "accessory"):
                item_id = result.equipped.get(slot)
                equip_text.append(f"{slot}: {_item_label(item_id) if item_id else '(empty)'}")
        else:
            equip_text.append("(no equipment data)")

        e = discord.Embed(title=f"🧙 RPG Profile - {target.display_name}", color=discord.Color.blurple())
        e.add_field(name="Level", value=str(result.level), inline=True)
        e.add_field(name="XP", value=f"{result.xp}/{result.xp_need}", inline=True)
        e.add_field(name="Gold", value=str(result.gold), inline=True)
        e.add_field(name="HP", value=f"{eff_hp}/{eff_max_hp}", inline=True)
        e.add_field(name="Attack", value=f"{eff_attack} (base {result.attack})", inline=True)
        e.add_field(name="Defense", value=f"{eff_defense} (base {result.defense})", inline=True)
        e.add_field(name="Equipment", value="\n".join(equip_text), inline=False)
        e.add_field(name="Combat Passive", value=_passive_text(result.lifesteal, result.crit_bonus, result.damage_reduction), inline=False)
        if result.set_bonus:
            e.add_field(name="Set Bonus", value=f"🧩 {result.set_bonus}", inline=False)
        if result.passive_skills:
            e.add_field(name="Skill Passive", value="\n".join(f"• {name}" for name in result.passive_skills), inline=False)
        f = apply_embed_asset(e, "profile")
        await interaction.response.send_message(embed=e, files=_collect_files(f))

    @bot.tree.command(name="stats", description="Xem chỉ số chiến đấu RPG")
    @app_commands.describe(member="Xem stats người khác")
    async def stats(interaction: discord.Interaction, member: Optional[discord.Member] = None):
        await profile(interaction, member)

    @bot.tree.command(name="rpg_balance", description="Xem số vàng RPG")
    async def rpg_balance(interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        gold = await EconomyService.get_balance(interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(f"💰 Bạn có **{gold}** gold RPG.", ephemeral=True)

    @bot.tree.command(name="rpg_daily", description="Nhận daily vàng RPG")
    async def rpg_daily(interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        result = await EconomyService.claim_daily(interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(result.message, ephemeral=True)

    @bot.tree.command(name="rpg_pay", description="Chuyển vàng RPG")
    @app_commands.describe(member="Người nhận", amount="Số vàng")
    async def rpg_pay(interaction: discord.Interaction, member: discord.Member, amount: int):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        if member.bot or member.id == interaction.user.id:
            return await interaction.response.send_message("❌ Người nhận không hợp lệ.", ephemeral=True)
        if amount <= 0:
            return await interaction.response.send_message("❌ Amount phải > 0.", ephemeral=True)

        result = await EconomyService.transfer_gold(interaction.guild.id, interaction.user.id, member.id, amount)
        if result.ok:
            await interaction.response.send_message(f"💸 Đã chuyển **{amount}** gold cho {member.mention}")
        else:
            await interaction.response.send_message(result.message, ephemeral=True)

    @bot.tree.command(name="rpg_shop", description="Xem shop RPG")
    async def rpg_shop(interaction: discord.Interaction):
        lines = []
        for key, item in ITEMS.items():
            if int(item["buy"]) <= 0:
                continue
            lines.append(
                f"`{key}` • {item['emoji']} **{item['name']}**\n"
                f"Buy: **{item['buy']}** | Sell: **{item['sell']}**\n{item['desc']}"
            )
        e = discord.Embed(title="🛒 RPG Shop", description="\n\n".join(lines), color=discord.Color.gold())
        f = apply_embed_asset(e, "shop")
        await interaction.response.send_message(embed=e, files=_collect_files(f))

    @bot.tree.command(name="craft_list", description="Xem công thức craft RPG")
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

    @bot.tree.command(name="craft", description="Craft item RPG")
    @app_commands.describe(recipe_id="ID recipe", amount="Số lần craft")
    @app_commands.autocomplete(recipe_id=autocomplete_recipe)
    async def craft(interaction: discord.Interaction, recipe_id: str, amount: int = 1):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        result = await EconomyService.craft_item(interaction.guild.id, interaction.user.id, recipe_id, amount)
        await interaction.response.send_message(result.message, ephemeral=True)

    @bot.tree.command(name="rpg_buy", description="Mua item RPG")
    @app_commands.describe(item="Mã item", amount="Số lượng")
    @app_commands.autocomplete(item=autocomplete_item)
    async def rpg_buy(interaction: discord.Interaction, item: str, amount: int = 1):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        ok, msg = await EconomyService.buy_item(interaction.guild.id, interaction.user.id, item, amount)
        if ok:
            data = ITEMS.get(item, {})
            e = discord.Embed(title="✅ Mua thành công", description=msg, color=discord.Color.green())
            f = apply_item_asset(e, item)
            await interaction.response.send_message(embed=e, files=_collect_files(f))
        else:
            await interaction.response.send_message(f"❌ {msg}", ephemeral=True)

    @bot.tree.command(name="rpg_sell", description="Bán item RPG")
    @app_commands.describe(item="Mã item", amount="Số lượng")
    @app_commands.autocomplete(item=autocomplete_item)
    async def rpg_sell(interaction: discord.Interaction, item: str, amount: int = 1):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        ok, msg, _ = await EconomyService.sell_item(interaction.guild.id, interaction.user.id, item, amount)
        if ok:
            await interaction.response.send_message(msg)
        else:
            await interaction.response.send_message(f"❌ {msg}", ephemeral=True)

    @bot.tree.command(name="rpg_inventory", description="Xem inventory RPG")
    @app_commands.describe(member="Xem inventory người khác")
    async def rpg_inventory(interaction: discord.Interaction, member: Optional[discord.Member] = None):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        target = _member_or_self(interaction, member)
        if target is None:
            return await interaction.response.send_message("❌ Không xác định được member.", ephemeral=True)

        items = await PlayerService.get_inventory(interaction.guild.id, target.id)
        if not items:
            return await interaction.response.send_message(f"🎒 {target.mention} chưa có item RPG.")

        lines = [f"{_item_label(item_id)} x{amount}" for item_id, amount in items]
        e = discord.Embed(title=f"🎒 RPG Inventory - {target.display_name}", description="\n".join(lines), color=discord.Color.green())
        f = apply_embed_asset(e, "inventory")
        await interaction.response.send_message(embed=e, files=_collect_files(f))

    @bot.tree.command(name="rpg_equipment", description="Xem trang bị RPG")
    @app_commands.describe(member="Xem trang bị người khác")
    async def rpg_equipment(interaction: discord.Interaction, member: Optional[discord.Member] = None):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        target = _member_or_self(interaction, member)
        if target is None:
            return await interaction.response.send_message("❌ Không xác định được member.", ephemeral=True)

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

    @bot.tree.command(name="equip", description="Trang bị item RPG")
    @app_commands.describe(item="Mã item (phải là equip)")
    @app_commands.autocomplete(item=autocomplete_item)
    async def equip(interaction: discord.Interaction, item: str):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        ok, payload = await PlayerService.equip_item(interaction.guild.id, interaction.user.id, item)
        if ok:
            await interaction.response.send_message(f"✅ Đã trang bị `{item}` vào slot **{payload}**.")
        else:
            await interaction.response.send_message(f"❌ {payload}", ephemeral=True)

    @bot.tree.command(name="unequip", description="Tháo trang bị theo slot")
    @app_commands.describe(slot="weapon / armor / accessory")
    async def unequip(interaction: discord.Interaction, slot: str):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        ok, payload = await PlayerService.unequip_item(interaction.guild.id, interaction.user.id, slot)
        if ok:
            await interaction.response.send_message(f"✅ Đã tháo `{payload}` khỏi slot `{slot}`.")
        else:
            await interaction.response.send_message(f"❌ {payload}", ephemeral=True)

    @bot.tree.command(name="rpg_skills", description="Xem danh sách skill RPG")
    async def rpg_skills(interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
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

    @bot.tree.command(name="rpg_skill_unlock", description="Mở khóa skill RPG")
    @app_commands.describe(skill_id="ID skill")
    @app_commands.autocomplete(skill_id=autocomplete_skill)
    async def rpg_skill_unlock(interaction: discord.Interaction, skill_id: str):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        result = await PlayerService.unlock_skill(interaction.guild.id, interaction.user.id, skill_id)
        await interaction.response.send_message(result.message, ephemeral=True)

    @bot.tree.command(name="rpg_skill_use", description="Dùng active skill RPG")
    @app_commands.describe(skill_id="ID active skill")
    @app_commands.autocomplete(skill_id=autocomplete_skill)
    async def rpg_skill_use(interaction: discord.Interaction, skill_id: str):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        result = await PlayerService.use_skill(interaction.guild.id, interaction.user.id, skill_id)
        await interaction.response.send_message(result.message)

    @bot.tree.command(name="rpg_use", description="Dùng item RPG")
    @app_commands.describe(item="Mã item", amount="Số lượng")
    @app_commands.autocomplete(item=autocomplete_item)
    async def rpg_use(interaction: discord.Interaction, item: str, amount: int = 1):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        ok, msg = await EconomyService.use_item(interaction.guild.id, interaction.user.id, item, amount)
        await interaction.response.send_message(msg if ok else f"❌ {msg}", ephemeral=not ok)

    @bot.tree.command(name="open", description="Mở lootbox RPG")
    @app_commands.describe(amount="Số lootbox muốn mở")
    async def open_lootbox(interaction: discord.Interaction, amount: int = 1):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        result = await EconomyService.open_lootbox(interaction.guild.id, interaction.user.id, amount)
        await interaction.response.send_message(result.message if result.ok else f"❌ {result.message}", ephemeral=not result.ok)

    @bot.tree.command(name="rpg_drop", description="Bỏ item RPG")
    @app_commands.describe(item="Mã item", amount="Số lượng")
    @app_commands.autocomplete(item=autocomplete_item)
    async def rpg_drop(interaction: discord.Interaction, item: str, amount: int = 1):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        ok, msg = await EconomyService.drop_item(interaction.guild.id, interaction.user.id, item, amount)
        await interaction.response.send_message(msg if ok else f"❌ {msg}", ephemeral=not ok)

    @bot.tree.command(name="hunt", description="Đi săn quái RPG")
    async def hunt(interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        await interaction.response.defer()
        result = await CombatService.hunt(interaction.guild.id, interaction.user.id)
        if not result.ok:
            return await interaction.followup.send("❌ Hunt lỗi.", ephemeral=True)
        e, files = _build_hunt_embed(result, interaction)
        log_url = await publish_combat_log(build_combat_log_text(str(interaction.user), {
            "pack": result.pack, "kills": result.kills, "slime_kills": result.slime_kills,
            "gold": result.gold, "xp": result.xp, "hp": result.hp,
            "encounters": result.encounters, "drops": result.drops, "logs": result.logs,
        }))
        e.add_field(name="Combat Log", value=f"🔗 {log_url}" if log_url else "(web log unavailable)", inline=False)
        await interaction.followup.send(embed=e, files=files)

    @bot.tree.command(name="boss", description="Đánh boss RPG")
    async def boss(interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        await interaction.response.defer()
        result = await CombatService.boss(interaction.guild.id, interaction.user.id)
        if not result.ok:
            return await interaction.followup.send("❌ Boss battle lỗi.", ephemeral=True)
        e, files = _build_boss_embed(result, interaction)
        log_url = await publish_combat_log(build_combat_log_text(f"{interaction.user} [BOSS]", {
            "gold": result.gold, "xp": result.xp, "drops": result.drops, "logs": result.logs,
        }))
        if log_url:
            e.add_field(name="Combat Log", value=f"🔗 {log_url}", inline=False)
        await interaction.followup.send(embed=e, files=files)

    @bot.tree.command(name="dungeon", description="Chinh phục dungeon nhiều tầng")
    async def dungeon(interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        await interaction.response.defer()
        result = await CombatService.dungeon(interaction.guild.id, interaction.user.id)
        if not result.ok:
            return await interaction.followup.send("❌ Dungeon lỗi.", ephemeral=True)

        e = discord.Embed(
            title="🏰 Dungeon Cleared" if result.cleared else "🩸 Dungeon Failed",
            color=discord.Color.green() if result.cleared else discord.Color.dark_red(),
        )
        e.add_field(name="Progress", value=f"{result.floors_cleared}/{result.total_floors} tầng", inline=True)
        e.add_field(name="HP còn lại", value=str(result.hp), inline=True)
        e.add_field(name="Reward", value=f"+{result.gold} gold\n+{result.xp} xp", inline=False)
        drops = result.drops if isinstance(result.drops, dict) else {}
        e.add_field(name="Drops", value=", ".join(f"{_item_label(k)} x{v}" for k, v in drops.items()) if drops else "Không có", inline=False)
        e.add_field(name="Combat Passive", value=_passive_text(result.combat_effects.lifesteal, result.combat_effects.crit_bonus, result.combat_effects.damage_reduction), inline=False)
        if result.set_bonus:
            e.add_field(name="Set Bonus", value=f"🧩 {result.set_bonus}", inline=False)
        if result.weekly_event:
            e.add_field(name="Weekly Event", value=str(result.weekly_event.get("name", "Weekly Event")), inline=False)
        if result.passive_skills:
            e.add_field(name="Skill Passive", value="\n".join(f"• {s}" for s in result.passive_skills[:3]), inline=False)
        if result.leveled_up:
            e.add_field(name="Level Up", value=f"🎉 Lên level **{result.level}**", inline=True)
        if result.logs:
            e.add_field(name="Chi tiết", value="\n".join(result.logs[:8]), inline=False)
        await interaction.followup.send(embed=e, files=_collect_files(apply_embed_asset(e, "hunt")))

    @bot.tree.command(name="party_hunt", description="Co-op hunt 2-4 người")
    @discord.app_commands.describe(member2="Thành viên thứ 2", member3="Thành viên thứ 3", member4="Thành viên thứ 4")
    async def party_hunt(interaction: discord.Interaction, member2: discord.Member, member3: discord.Member | None = None, member4: discord.Member | None = None):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)

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
            return await interaction.response.send_message("❌ Party cần tối thiểu 2 người thật.", ephemeral=True)

        await interaction.response.defer()
        result = await CombatService.party_hunt(interaction.guild.id, [m.id for m in clean_party])
        if not result.ok:
            return await interaction.followup.send("❌ Party hunt lỗi.", ephemeral=True)

        e = discord.Embed(title="🤝 Party Hunt", color=discord.Color.gold())
        e.add_field(name="Party", value=", ".join(m.mention for m in clean_party), inline=False)
        e.add_field(name="Kết quả", value=f"Kills: {result.kills}/{result.pack}\nGold tổng: +{result.gold}\nXP tổng: +{result.xp}", inline=False)
        if result.members:
            lines = []
            for row in result.members[:4]:
                if not isinstance(row, dict):
                    continue
                uid = int(row.get("user_id", 0))
                m = interaction.guild.get_member(uid)
                name = m.display_name if m else str(uid)
                lines.append(f"**{name}**: +{int(row.get('gold', 0))}g, +{int(row.get('xp', 0))}xp, kills {int(row.get('kills', 0))}, hp {int(row.get('hp', 1))}")
            if lines:
                e.add_field(name="Theo thành viên", value="\n".join(lines), inline=False)
        drops = result.drops if isinstance(result.drops, dict) else {}
        e.add_field(name="Drops", value=", ".join(f"{_item_label(k)} x{v}" for k, v in drops.items()) if drops else "Không có", inline=False)
        if result.weekly_event:
            e.add_field(name="Weekly Event", value=str(result.weekly_event.get("name", "Weekly Event")), inline=False)
        if result.logs:
            e.add_field(name="Chi tiết", value="\n".join(result.logs[:8]), inline=False)
        await interaction.followup.send(embed=e, files=_collect_files(apply_embed_asset(e, "hunt")))

    @bot.tree.command(name="quest", description="Xem quest RPG")
    async def quest(interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        quests = await QuestService.get_quests(interaction.guild.id, interaction.user.id)
        quest_text = QuestService.format_quests(quests)
        e = discord.Embed(title="📜 RPG Quests", description=quest_text, color=discord.Color.teal())
        await interaction.response.send_message(embed=e, ephemeral=True, files=_collect_files(apply_embed_asset(e, "quest")))

    @bot.tree.command(name="quest_claim", description="Nhận thưởng quest RPG")
    @app_commands.describe(quest_id="ID quest, ví dụ: kill_10")
    async def quest_claim(interaction: discord.Interaction, quest_id: str):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        result = await QuestService.claim_quest(interaction.guild.id, interaction.user.id, quest_id)
        await interaction.response.send_message(result.message)

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
            e.add_field(name=f"{_rarity_emoji(rarity)} {rarity.title()}", value="\n".join(values[:8]), inline=False)
        f = apply_embed_asset(e, "inventory")
        await interaction.response.send_message(embed=e, files=_collect_files(f))
