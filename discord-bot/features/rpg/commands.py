import random
import time
from collections import defaultdict, deque
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from .assets import apply_embed_asset, apply_item_asset, apply_monster_asset, reload_assets
from .combatlog import build_combat_log_text, publish_combat_log
from .data import ITEMS, MONSTERS, BOSS_VARIANTS, CRAFT_RECIPES, SKILLS, xp_need_for_next
from .hunt import simulate_hunt
from .boss import simulate_boss
from .dungeon import simulate_dungeon
from .coop import simulate_party_hunt
from .events import current_weekly_event, event_brief
from .crafting import list_recipes, get_recipe, craft_recipe
from .equipment import equipped_profile, equip_item, unequip_slot
from .commands_reports import register_reports_commands
from .commands_season import register_season_commands
from .commands_combat import register_combat_commands
from .commands_quests import register_quest_commands
from .db import (
    DB_WRITE_LOCK,
    RPG_HUNT_COOLDOWN,
    RPG_DAILY_COOLDOWN,
    RPG_DAILY_GOLD,
    RPG_BOSS_COOLDOWN,
    RPG_DUNGEON_COOLDOWN,
    RPG_PARTY_HUNT_COOLDOWN,
    RPG_LOOTBOX_DAILY_LIMIT,
    RPG_PAY_MIN_LEVEL,
    RPG_PAY_MIN_ACCOUNT_AGE_SECS,
    RPG_PAY_DAILY_SEND_LIMIT,
    RPG_PAY_DAILY_PAIR_LIMIT,
    ensure_db_ready,
    open_db,
    ensure_player,
    ensure_default_quests,
    refresh_quests_if_needed,
    get_player,
    get_unlocked_skills,
    unlock_skill,
    get_rpg_transfer_stats,
    record_rpg_transfer,
    record_gold_flow,
    utc_day_start,
    consume_lootbox_open_limit,
    set_cooldown,
    cooldown_remain,
    add_inventory,
    remove_inventory,
    gain_xp_and_level,
    fmt_secs,
)
from .skills import skill_profile, use_active_skill


RPG_COMMAND_RATE_USER_MAX = 12
RPG_COMMAND_RATE_USER_WINDOW = 20
RPG_COMMAND_RATE_GUILD_MAX = 120
RPG_COMMAND_RATE_GUILD_WINDOW = 20

_USER_RATE_BUCKET: dict[int, deque[float]] = defaultdict(deque)
_GUILD_RATE_BUCKET: dict[int, deque[float]] = defaultdict(deque)

RPG_COMMAND_NAMES = {
    "rpg_assets_reload",
    "rpg_start",
    "profile",
    "stats",
    "rpg_balance",
    "rpg_daily",
    "rpg_pay",
    "rpg_shop",
    "craft_list",
    "craft",
    "rpg_buy",
    "rpg_sell",
    "rpg_inventory",
    "rpg_equipment",
    "equip",
    "unequip",
    "rpg_skills",
    "rpg_skill_unlock",
    "rpg_skill_use",
    "rpg_use",
    "open",
    "rpg_drop",
    "rpg_event",
    "hunt",
    "boss",
    "dungeon",
    "party_hunt",
    "quest",
    "quest_claim",
    "rpg_loot",
    "rpg_balance_dashboard",
    "rpg_economy_audit",
    "rpg_season_status",
    "rpg_season_rollover",
    "rpg_jackpot",
    "rpg_leaderboard",
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


_MONSTER_NAME = {str(m.get("id")): str(m.get("name")) for m in (MONSTERS + BOSS_VARIANTS)}


def _collect_files(*files: discord.File | None) -> list[discord.File]:
    return [f for f in files if f is not None]


def _quest_lines(rows) -> list[str]:
    names = {
        "kill_monsters": "Hạ quái",
        "kill_slime": "Hạ Slime Jackpot",
        "hunt_runs": "Chạy hunt",
        "open_lootboxes": "Mở lootbox",
        "boss_wins": "Thắng boss",
    }
    lines: list[str] = []
    now = int(time.time())
    claimed_map = {str(r[0]): int(r[9]) for r in rows}
    for qid, objective, target, progress, reward_gold, reward_xp, period, reset_after, prereq_quest_id, claimed in rows:
        prereq = str(prereq_quest_id or "")
        is_locked = bool(prereq) and claimed_map.get(prereq, 0) == 0
        if is_locked:
            status = f"🔒 Locked (need `{prereq}`)"
        else:
            status = "✅ Claimed" if int(claimed) == 1 else ("🎯 Ready" if int(progress) >= int(target) else "⏳ In progress")
        period_txt = ""
        if str(period) in {"daily", "weekly"} and int(reset_after or 0) > now:
            period_txt = f" • reset <t:{int(reset_after)}:R>"
        lines.append(
            f"`{qid}` • **{names.get(objective, objective)}** {progress}/{target}\n"
            f"Reward: {reward_gold} gold + {reward_xp} xp • {status}{period_txt}"
        )
    return lines


async def _open_lootboxes(conn, guild_id: int, user_id: int, amount: int) -> tuple[bool, str]:
    if amount <= 0:
        return False, "Amount phải > 0."

    ok = await remove_inventory(conn, guild_id, user_id, "lootbox", amount)
    if not ok:
        return False, "Bạn không đủ lootbox."

    allowed, remain_after = await consume_lootbox_open_limit(conn, guild_id, user_id, amount)
    if not allowed:
        await add_inventory(conn, guild_id, user_id, "lootbox", amount)
        return False, f"Đã chạm limit mở lootbox trong ngày. Còn mở được: **{remain_after}**/{RPG_LOOTBOX_DAILY_LIMIT}"

    total_gold = 0
    bonus_items: list[str] = []
    for _ in range(amount):
        roll = random.random()
        if roll < 0.58:
            total_gold += random.randint(45, 140)
        elif roll < 0.88:
            await add_inventory(conn, guild_id, user_id, "potion", 1)
            bonus_items.append("🧪 Potion")
        elif roll < 0.98:
            await add_inventory(conn, guild_id, user_id, "rare_crystal", 1)
            bonus_items.append("💎 Rare Crystal")
        else:
            await add_inventory(conn, guild_id, user_id, "lucky_ring", 1)
            bonus_items.append("💍 Lucky Ring")

    if total_gold > 0:
        await conn.execute(
            "UPDATE players SET gold = gold + ? WHERE guild_id = ? AND user_id = ?",
            (total_gold, guild_id, user_id),
        )
        await record_gold_flow(conn, guild_id, user_id, total_gold, "lootbox_open")

    await add_quest_progress(conn, guild_id, user_id, "open_lootboxes", amount)

    msg = f"🎁 Mở lootbox x{amount}: +{total_gold} gold"
    if bonus_items:
        msg += "\n" + "\n".join(f"- {x}" for x in bonus_items)
    msg += f"\nDaily limit còn lại: **{remain_after}**/{RPG_LOOTBOX_DAILY_LIMIT}"
    return True, msg


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


def _to_pct(value: float) -> int:
    return int(round(max(0.0, float(value)) * 100))


def _passive_text(lifesteal: float, crit_bonus: float, damage_reduction: float) -> str:
    return (
        f"Lifesteal +{_to_pct(lifesteal)}% • "
        f"Crit +{_to_pct(crit_bonus)}% • "
        f"Damage Reduction {_to_pct(damage_reduction)}%"
    )


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


async def _profile_embed(guild: discord.Guild, target: discord.Member) -> tuple[discord.Embed | None, list[discord.File]]:
    await ensure_db_ready()
    async with open_db() as conn:
        await ensure_player(conn, guild.id, target.id)
        await ensure_default_quests(conn, guild.id, target.id)
        await refresh_quests_if_needed(conn, guild.id, target.id)
        row = await get_player(conn, guild.id, target.id)
        profile = await equipped_profile(conn, guild.id, target.id)
        sprofile = await skill_profile(conn, guild.id, target.id)
        bonus_atk = int(profile["attack"])
        bonus_def = int(profile["defense"])
        bonus_hp = int(profile["hp"])
        equipped = profile["equipped"]
        lifesteal = float(profile["lifesteal"])
        crit_bonus = float(profile["crit_bonus"])
        damage_reduction = float(profile["damage_reduction"])
        active_set = profile.get("set_bonus") if isinstance(profile.get("set_bonus"), dict) else None
        passive_skills = sprofile.get("passives", []) if isinstance(sprofile.get("passives"), list) else []
        await conn.commit()

    if not row:
        return None, []

    level, xp, hp, max_hp, attack, defense, gold = map(int, row)
    eff_hp = min(max_hp + bonus_hp, hp + bonus_hp)
    eff_max_hp = max_hp + bonus_hp
    eff_attack = attack + bonus_atk
    eff_defense = defense + bonus_def

    equip_text = []
    for slot in ("weapon", "armor", "accessory"):
        item_id = equipped.get(slot)
        equip_text.append(f"{slot}: {_item_label(item_id) if item_id else '(empty)'}")

    e = discord.Embed(title=f"🧙 RPG Profile - {target.display_name}", color=discord.Color.blurple())
    e.add_field(name="Level", value=str(level), inline=True)
    e.add_field(name="XP", value=f"{xp}/{xp_need_for_next(level)}", inline=True)
    e.add_field(name="Gold", value=str(gold), inline=True)
    e.add_field(name="HP", value=f"{eff_hp}/{eff_max_hp}", inline=True)
    e.add_field(name="Attack", value=f"{eff_attack} (base {attack})", inline=True)
    e.add_field(name="Defense", value=f"{eff_defense} (base {defense})", inline=True)
    e.add_field(name="Equipment", value="\n".join(equip_text), inline=False)
    e.add_field(name="Combat Passive", value=_passive_text(lifesteal, crit_bonus, damage_reduction), inline=False)
    if active_set:
        e.add_field(name="Set Bonus", value=f"🧩 {active_set.get('name', 'Unknown Set')}", inline=False)
    if passive_skills:
        e.add_field(name="Skill Passive", value="\n".join(f"• {name}" for name in passive_skills), inline=False)
    f = apply_embed_asset(e, "profile")
    return e, _collect_files(f)


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
        user_wait = _rate_check(
            _USER_RATE_BUCKET,
            interaction.user.id,
            now_ts,
            RPG_COMMAND_RATE_USER_WINDOW,
            RPG_COMMAND_RATE_USER_MAX,
        )
        if user_wait > 0:
            raise app_commands.CheckFailure(f"⏳ Bạn thao tác RPG quá nhanh. Thử lại sau {user_wait:.1f}s.")

        if interaction.guild is not None:
            guild_wait = _rate_check(
                _GUILD_RATE_BUCKET,
                interaction.guild.id,
                now_ts,
                RPG_COMMAND_RATE_GUILD_WINDOW,
                RPG_COMMAND_RATE_GUILD_MAX,
            )
            if guild_wait > 0:
                raise app_commands.CheckFailure(
                    f"⏳ Server đang spam RPG command. Thử lại sau {guild_wait:.1f}s."
                )

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
        async with DB_WRITE_LOCK:
            async with open_db() as conn:
                await ensure_player(conn, interaction.guild.id, interaction.user.id)
                await ensure_default_quests(conn, interaction.guild.id, interaction.user.id)
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

        e, files = await _profile_embed(interaction.guild, target)
        if e is None:
            return await interaction.response.send_message("❌ Không lấy được dữ liệu nhân vật.", ephemeral=True)
        await interaction.response.send_message(embed=e, files=files)

    @bot.tree.command(name="stats", description="Xem chỉ số chiến đấu RPG")
    @app_commands.describe(member="Xem stats người khác")
    async def stats(interaction: discord.Interaction, member: Optional[discord.Member] = None):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        target = _member_or_self(interaction, member)
        if target is None:
            return await interaction.response.send_message("❌ Không xác định được member.", ephemeral=True)
        e, files = await _profile_embed(interaction.guild, target)
        if e is None:
            return await interaction.response.send_message("❌ Không lấy được dữ liệu nhân vật.", ephemeral=True)
        await interaction.response.send_message(embed=e, files=files)

    @bot.tree.command(name="rpg_balance", description="Xem số vàng RPG")
    async def rpg_balance(interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        await ensure_db_ready()
        async with open_db() as conn:
            row = await get_player(conn, interaction.guild.id, interaction.user.id)
        gold = int(row[6]) if row else 0
        await interaction.response.send_message(f"💰 Bạn có **{gold}** gold RPG.", ephemeral=True)

    @bot.tree.command(name="rpg_daily", description="Nhận daily vàng RPG")
    async def rpg_daily(interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        await ensure_db_ready()

        async with DB_WRITE_LOCK:
            async with open_db() as conn:
                await ensure_player(conn, interaction.guild.id, interaction.user.id)
                remain = await cooldown_remain(conn, interaction.guild.id, interaction.user.id, "daily")
                if remain > 0:
                    return await interaction.response.send_message(
                        f"⏳ Daily cooldown: **{fmt_secs(remain)}**",
                        ephemeral=True,
                    )

                await conn.execute(
                    "UPDATE players SET gold = gold + ? WHERE guild_id = ? AND user_id = ?",
                    (RPG_DAILY_GOLD, interaction.guild.id, interaction.user.id),
                )
                await record_gold_flow(
                    conn,
                    interaction.guild.id,
                    interaction.user.id,
                    RPG_DAILY_GOLD,
                    "daily_reward",
                )
                await set_cooldown(conn, interaction.guild.id, interaction.user.id, "daily", RPG_DAILY_COOLDOWN)
                row = await get_player(conn, interaction.guild.id, interaction.user.id)
                await conn.commit()
        balance_now = int(row[6]) if row else 0
        await interaction.response.send_message(
            f"🎁 Nhận **{RPG_DAILY_GOLD}** gold. Số dư: **{balance_now}**",
            ephemeral=True,
        )

    @bot.tree.command(name="rpg_pay", description="Chuyển vàng RPG")
    @app_commands.describe(member="Người nhận", amount="Số vàng")
    async def rpg_pay(interaction: discord.Interaction, member: discord.Member, amount: int):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        if member.bot or member.id == interaction.user.id:
            return await interaction.response.send_message("❌ Người nhận không hợp lệ.", ephemeral=True)
        if amount <= 0:
            return await interaction.response.send_message("❌ Amount phải > 0.", ephemeral=True)

        await ensure_db_ready()
        async with DB_WRITE_LOCK:
            async with open_db() as conn:
                await conn.execute("SAVEPOINT rpg_pay")
                await ensure_player(conn, interaction.guild.id, interaction.user.id)
                await ensure_player(conn, interaction.guild.id, member.id)

                async with conn.execute(
                    "SELECT user_id, level, gold, created_at FROM players WHERE guild_id = ? AND user_id IN (?, ?)",
                    (interaction.guild.id, interaction.user.id, member.id),
                ) as cur:
                    rows = await cur.fetchall()

                pmap = {int(uid): (int(level), int(gold), int(created_at)) for uid, level, gold, created_at in rows}
                sender = pmap.get(interaction.user.id)
                receiver = pmap.get(member.id)
                if sender is None or receiver is None:
                    await conn.execute("ROLLBACK TO rpg_pay")
                    await conn.execute("RELEASE rpg_pay")
                    return await interaction.response.send_message("❌ Không đọc được dữ liệu người chơi.", ephemeral=True)

                sender_level, bal, sender_created_at = sender
                receiver_level, _, receiver_created_at = receiver
                if sender_level < RPG_PAY_MIN_LEVEL or receiver_level < RPG_PAY_MIN_LEVEL:
                    await conn.execute("ROLLBACK TO rpg_pay")
                    await conn.execute("RELEASE rpg_pay")
                    return await interaction.response.send_message(
                        f"❌ Cả 2 người cần tối thiểu level **{RPG_PAY_MIN_LEVEL}** để dùng `/rpg_pay`.",
                        ephemeral=True,
                    )

                now_ts = int(time.time())
                sender_age = now_ts - sender_created_at
                receiver_age = now_ts - receiver_created_at
                if sender_age < RPG_PAY_MIN_ACCOUNT_AGE_SECS or receiver_age < RPG_PAY_MIN_ACCOUNT_AGE_SECS:
                    await conn.execute("ROLLBACK TO rpg_pay")
                    await conn.execute("RELEASE rpg_pay")
                    return await interaction.response.send_message(
                        "❌ Tài khoản RPG quá mới để giao dịch. Hãy chơi thêm trước khi chuyển vàng.",
                        ephemeral=True,
                    )

                day_since = utc_day_start(now_ts)
                sent_today, pair_today = await get_rpg_transfer_stats(
                    conn,
                    interaction.guild.id,
                    interaction.user.id,
                    member.id,
                    day_since,
                )
                if sent_today + amount > RPG_PAY_DAILY_SEND_LIMIT:
                    await conn.execute("ROLLBACK TO rpg_pay")
                    await conn.execute("RELEASE rpg_pay")
                    remain = max(0, RPG_PAY_DAILY_SEND_LIMIT - sent_today)
                    return await interaction.response.send_message(
                        f"❌ Chạm giới hạn chuyển vàng/ngày. Còn lại hôm nay: **{remain}**.",
                        ephemeral=True,
                    )
                if pair_today + amount > RPG_PAY_DAILY_PAIR_LIMIT:
                    await conn.execute("ROLLBACK TO rpg_pay")
                    await conn.execute("RELEASE rpg_pay")
                    remain = max(0, RPG_PAY_DAILY_PAIR_LIMIT - pair_today)
                    return await interaction.response.send_message(
                        f"❌ Giao dịch với người này đã chạm limit/ngày. Còn lại: **{remain}**.",
                        ephemeral=True,
                    )

                if bal < amount:
                    await conn.execute("ROLLBACK TO rpg_pay")
                    await conn.execute("RELEASE rpg_pay")
                    return await interaction.response.send_message("❌ Bạn không đủ vàng.", ephemeral=True)

                await conn.execute(
                    "UPDATE players SET gold = gold - ? WHERE guild_id = ? AND user_id = ?",
                    (amount, interaction.guild.id, interaction.user.id),
                )
                await conn.execute(
                    "UPDATE players SET gold = gold + ? WHERE guild_id = ? AND user_id = ?",
                    (amount, interaction.guild.id, member.id),
                )
                await record_rpg_transfer(conn, interaction.guild.id, interaction.user.id, member.id, amount)
                await conn.execute("RELEASE rpg_pay")
                await conn.commit()

        await interaction.response.send_message(f"💸 Đã chuyển **{amount}** gold cho {member.mention}")

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
        recipes = list_recipes()
        lines = []
        for r in recipes:
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
        if amount <= 0:
            return await interaction.response.send_message("❌ Amount phải > 0.", ephemeral=True)

        await ensure_db_ready()
        async with DB_WRITE_LOCK:
            async with open_db() as conn:
                await ensure_player(conn, interaction.guild.id, interaction.user.id)
                ok, payload = await craft_recipe(conn, interaction.guild.id, interaction.user.id, recipe_id, amount)
                if not ok:
                    await conn.rollback()
                    return await interaction.response.send_message(f"❌ {payload}", ephemeral=True)
                recipe = get_recipe(recipe_id)
                if recipe:
                    cost_gold = int(recipe.get("gold", 0)) * amount
                    if cost_gold > 0:
                        await record_gold_flow(
                            conn,
                            interaction.guild.id,
                            interaction.user.id,
                            -cost_gold,
                            "craft_cost",
                        )
                await conn.commit()

        await interaction.response.send_message(f"✅ Craft thành công `{recipe_id}` x{amount}.")

    @bot.tree.command(name="rpg_buy", description="Mua item RPG")
    @app_commands.describe(item="Mã item", amount="Số lượng")
    @app_commands.autocomplete(item=autocomplete_item)
    async def rpg_buy(interaction: discord.Interaction, item: str, amount: int = 1):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        if amount <= 0:
            return await interaction.response.send_message("❌ Amount phải > 0.", ephemeral=True)
        data = ITEMS.get(item)
        if not data or int(data["buy"]) <= 0:
            return await interaction.response.send_message("❌ Item không thể mua.", ephemeral=True)

        total = int(data["buy"]) * amount
        await ensure_db_ready()
        async with DB_WRITE_LOCK:
            async with open_db() as conn:
                await conn.execute("SAVEPOINT rpg_buy")
                await ensure_player(conn, interaction.guild.id, interaction.user.id)

                async with conn.execute(
                    "SELECT gold FROM players WHERE guild_id = ? AND user_id = ?",
                    (interaction.guild.id, interaction.user.id),
                ) as cur:
                    row = await cur.fetchone()
                gold = int(row[0]) if row else 0
                if gold < total:
                    await conn.execute("ROLLBACK TO rpg_buy")
                    await conn.execute("RELEASE rpg_buy")
                    return await interaction.response.send_message("❌ Không đủ vàng.", ephemeral=True)

                await conn.execute(
                    "UPDATE players SET gold = gold - ? WHERE guild_id = ? AND user_id = ?",
                    (total, interaction.guild.id, interaction.user.id),
                )
                await record_gold_flow(conn, interaction.guild.id, interaction.user.id, -total, "shop_buy")
                await add_inventory(conn, interaction.guild.id, interaction.user.id, item, amount)
                await conn.execute("RELEASE rpg_buy")
                await conn.commit()

        e = discord.Embed(
            title="✅ Mua thành công",
            description=f"Đã mua {data['emoji']} **{data['name']}** x{amount} với giá **{total}** gold.",
            color=discord.Color.green(),
        )
        f = apply_item_asset(e, item)
        await interaction.response.send_message(embed=e, files=_collect_files(f))

    @bot.tree.command(name="rpg_sell", description="Bán item RPG")
    @app_commands.describe(item="Mã item", amount="Số lượng")
    @app_commands.autocomplete(item=autocomplete_item)
    async def rpg_sell(interaction: discord.Interaction, item: str, amount: int = 1):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        if amount <= 0:
            return await interaction.response.send_message("❌ Amount phải > 0.", ephemeral=True)
        data = ITEMS.get(item)
        if not data:
            return await interaction.response.send_message("❌ Item không tồn tại.", ephemeral=True)
        sell_price = int(data["sell"])
        if sell_price <= 0:
            return await interaction.response.send_message("❌ Item này không thể bán.", ephemeral=True)

        await ensure_db_ready()
        async with DB_WRITE_LOCK:
            async with open_db() as conn:
                await ensure_player(conn, interaction.guild.id, interaction.user.id)
                ok = await remove_inventory(conn, interaction.guild.id, interaction.user.id, item, amount)
                if not ok:
                    return await interaction.response.send_message("❌ Bạn không đủ item để bán.", ephemeral=True)
                total = sell_price * amount
                await conn.execute(
                    "UPDATE players SET gold = gold + ? WHERE guild_id = ? AND user_id = ?",
                    (total, interaction.guild.id, interaction.user.id),
                )
                await record_gold_flow(conn, interaction.guild.id, interaction.user.id, total, "shop_sell")
                await conn.commit()
        await interaction.response.send_message(f"💰 Đã bán **{data['name']}** x{amount}, nhận **{total}** gold.")

    @bot.tree.command(name="rpg_inventory", description="Xem inventory RPG")
    @app_commands.describe(member="Xem inventory người khác")
    async def rpg_inventory(interaction: discord.Interaction, member: Optional[discord.Member] = None):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        target = _member_or_self(interaction, member)
        if target is None:
            return await interaction.response.send_message("❌ Không xác định được member.", ephemeral=True)

        await ensure_db_ready()
        async with open_db() as conn:
            await ensure_player(conn, interaction.guild.id, target.id)
            async with conn.execute(
                """
                SELECT item_id, amount FROM inventory
                WHERE guild_id = ? AND user_id = ? AND amount > 0
                ORDER BY amount DESC, item_id ASC
                """,
                (interaction.guild.id, target.id),
            ) as cur:
                rows = await cur.fetchall()

        if not rows:
            return await interaction.response.send_message(f"🎒 {target.mention} chưa có item RPG.")

        lines = [f"{_item_label(item_id)} x{amount}" for item_id, amount in rows]
        e = discord.Embed(
            title=f"🎒 RPG Inventory - {target.display_name}",
            description="\n".join(lines),
            color=discord.Color.green(),
        )
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

        await ensure_db_ready()
        async with open_db() as conn:
            await ensure_player(conn, interaction.guild.id, target.id)
            profile = await equipped_profile(conn, interaction.guild.id, target.id)
            sprofile = await skill_profile(conn, interaction.guild.id, target.id)

        bonus_atk = int(profile["attack"])
        bonus_def = int(profile["defense"])
        bonus_hp = int(profile["hp"])
        equipped = profile["equipped"]
        lifesteal = float(profile["lifesteal"])
        crit_bonus = float(profile["crit_bonus"])
        damage_reduction = float(profile["damage_reduction"])
        active_set = profile.get("set_bonus") if isinstance(profile.get("set_bonus"), dict) else None
        skill_passives = sprofile.get("passives", []) if isinstance(sprofile.get("passives"), list) else []

        lines = []
        for slot in ("weapon", "armor", "accessory"):
            item_id = equipped.get(slot)
            lines.append(f"**{slot}**: {_item_label(item_id) if item_id else '(empty)'}")

        e = discord.Embed(
            title=f"🧩 Equipment - {target.display_name}",
            description="\n".join(lines),
            color=discord.Color.purple(),
        )
        e.add_field(name="Bonus", value=f"ATK +{bonus_atk} • DEF +{bonus_def} • HP +{bonus_hp}", inline=False)
        e.add_field(name="Passive", value=_passive_text(lifesteal, crit_bonus, damage_reduction), inline=False)
        if active_set:
            e.add_field(name="Set Bonus", value=f"🧩 {active_set.get('name', 'Unknown Set')}", inline=False)
        if skill_passives:
            e.add_field(name="Skill Passive", value="\n".join(f"• {name}" for name in skill_passives), inline=False)
        await interaction.response.send_message(embed=e)

    @bot.tree.command(name="equip", description="Trang bị item RPG")
    @app_commands.describe(item="Mã item (phải là equip)")
    @app_commands.autocomplete(item=autocomplete_item)
    async def equip(interaction: discord.Interaction, item: str):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)

        await ensure_db_ready()
        async with DB_WRITE_LOCK:
            async with open_db() as conn:
                await ensure_player(conn, interaction.guild.id, interaction.user.id)
                ok, payload = await equip_item(conn, interaction.guild.id, interaction.user.id, item)
                if not ok:
                    return await interaction.response.send_message(f"❌ {payload}", ephemeral=True)
                await conn.commit()

        await interaction.response.send_message(f"✅ Đã trang bị `{item}` vào slot **{payload}**.")

    @bot.tree.command(name="unequip", description="Tháo trang bị theo slot")
    @app_commands.describe(slot="weapon / armor / accessory")
    async def unequip(interaction: discord.Interaction, slot: str):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)

        await ensure_db_ready()
        async with DB_WRITE_LOCK:
            async with open_db() as conn:
                await ensure_player(conn, interaction.guild.id, interaction.user.id)
                ok, payload = await unequip_slot(conn, interaction.guild.id, interaction.user.id, slot)
                if not ok:
                    return await interaction.response.send_message(f"❌ {payload}", ephemeral=True)

                # clamp base hp to max_hp after unequip
                async with conn.execute(
                    "SELECT hp, max_hp FROM players WHERE guild_id = ? AND user_id = ?",
                    (interaction.guild.id, interaction.user.id),
                ) as cur:
                    row = await cur.fetchone()
                hp = int(row[0]) if row else 1
                max_hp = int(row[1]) if row else 100
                if hp > max_hp:
                    await conn.execute(
                        "UPDATE players SET hp = ? WHERE guild_id = ? AND user_id = ?",
                        (max_hp, interaction.guild.id, interaction.user.id),
                    )
                await conn.commit()

        await interaction.response.send_message(f"✅ Đã tháo `{payload}` khỏi slot `{slot}`.")

    @bot.tree.command(name="rpg_skills", description="Xem danh sách skill RPG")
    async def rpg_skills(interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)

        await ensure_db_ready()
        async with open_db() as conn:
            row = await get_player(conn, interaction.guild.id, interaction.user.id)
            level = int(row[0]) if row else 1
            unlocked = await get_unlocked_skills(conn, interaction.guild.id, interaction.user.id)

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

        e = discord.Embed(
            title=f"🧠 RPG Skills - Lv {level}",
            description="\n\n".join(lines),
            color=discord.Color.dark_teal(),
        )
        await interaction.response.send_message(embed=e, ephemeral=True)

    @bot.tree.command(name="rpg_skill_unlock", description="Mở khóa skill RPG")
    @app_commands.describe(skill_id="ID skill")
    @app_commands.autocomplete(skill_id=autocomplete_skill)
    async def rpg_skill_unlock(interaction: discord.Interaction, skill_id: str):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)

        skill = SKILLS.get(skill_id)
        if not skill:
            return await interaction.response.send_message("❌ Skill không tồn tại.", ephemeral=True)

        await ensure_db_ready()
        async with DB_WRITE_LOCK:
            async with open_db() as conn:
                row = await get_player(conn, interaction.guild.id, interaction.user.id)
                level = int(row[0]) if row else 1
                req = int(skill.get("level_req", 1))
                if level < req:
                    return await interaction.response.send_message(
                        f"❌ Cần level **{req}** để unlock `{skill_id}`.",
                        ephemeral=True,
                    )

                ok = await unlock_skill(conn, interaction.guild.id, interaction.user.id, skill_id)
                if not ok:
                    return await interaction.response.send_message("❌ Skill đã unlock trước đó.", ephemeral=True)
                await conn.commit()

        await interaction.response.send_message(
            f"✅ Đã unlock skill **{skill.get('name', skill_id)}** (`{skill_id}`).",
            ephemeral=True,
        )

    @bot.tree.command(name="rpg_skill_use", description="Dùng active skill RPG")
    @app_commands.describe(skill_id="ID active skill")
    @app_commands.autocomplete(skill_id=autocomplete_skill)
    async def rpg_skill_use(interaction: discord.Interaction, skill_id: str):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)

        await ensure_db_ready()
        async with DB_WRITE_LOCK:
            async with open_db() as conn:
                row = await get_player(conn, interaction.guild.id, interaction.user.id)
                level = int(row[0]) if row else 1
                ok, msg = await use_active_skill(conn, interaction.guild.id, interaction.user.id, skill_id, level)
                if not ok:
                    await conn.rollback()
                    return await interaction.response.send_message(f"❌ {msg}", ephemeral=True)
                await conn.commit()

        await interaction.response.send_message(msg)

    @bot.tree.command(name="rpg_use", description="Dùng item RPG")
    @app_commands.describe(item="Mã item", amount="Số lượng")
    @app_commands.autocomplete(item=autocomplete_item)
    async def rpg_use(interaction: discord.Interaction, item: str, amount: int = 1):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        if amount <= 0:
            return await interaction.response.send_message("❌ Amount phải > 0.", ephemeral=True)
        data = ITEMS.get(item)
        if not data:
            return await interaction.response.send_message("❌ Item không tồn tại.", ephemeral=True)
        if data.get("use") == "equip":
            return await interaction.response.send_message(
                "❌ Đây là trang bị. Dùng `/equip` để mặc đồ.",
                ephemeral=True,
            )

        await ensure_db_ready()
        async with DB_WRITE_LOCK:
            async with open_db() as conn:
                await ensure_player(conn, interaction.guild.id, interaction.user.id)
                ok = await remove_inventory(conn, interaction.guild.id, interaction.user.id, item, amount)
                if not ok:
                    return await interaction.response.send_message("❌ Bạn không đủ item.", ephemeral=True)

                use_type = data.get("use")
                val = int(data.get("value", 0))

                if use_type == "heal":
                    async with conn.execute(
                        "SELECT hp, max_hp FROM players WHERE guild_id = ? AND user_id = ?",
                        (interaction.guild.id, interaction.user.id),
                    ) as cur:
                        row = await cur.fetchone()
                    hp = int(row[0]) if row else 1
                    max_hp = int(row[1]) if row else 100
                    healed = min(max_hp - hp, val * amount)
                    new_hp = hp + max(0, healed)
                    await conn.execute(
                        "UPDATE players SET hp = ? WHERE guild_id = ? AND user_id = ?",
                        (new_hp, interaction.guild.id, interaction.user.id),
                    )
                    msg = f"❤️ Hồi **{healed} HP** ({new_hp}/{max_hp})"
                elif use_type == "lootbox":
                    ok_open, payload = await _open_lootboxes(conn, interaction.guild.id, interaction.user.id, amount)
                    if not ok_open:
                        await conn.rollback()
                        return await interaction.response.send_message(f"❌ {payload}", ephemeral=True)
                    msg = payload
                else:
                    return await interaction.response.send_message("❌ Item này không dùng được.", ephemeral=True)

                await conn.commit()

        await interaction.response.send_message(msg)

    @bot.tree.command(name="open", description="Mở lootbox RPG")
    @app_commands.describe(amount="Số lootbox muốn mở")
    async def open_lootbox(interaction: discord.Interaction, amount: int = 1):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        if amount <= 0:
            return await interaction.response.send_message("❌ Amount phải > 0.", ephemeral=True)

        await ensure_db_ready()
        async with DB_WRITE_LOCK:
            async with open_db() as conn:
                await ensure_player(conn, interaction.guild.id, interaction.user.id)
                ok_open, payload = await _open_lootboxes(conn, interaction.guild.id, interaction.user.id, amount)
                if not ok_open:
                    await conn.rollback()
                    return await interaction.response.send_message(f"❌ {payload}", ephemeral=True)
                await conn.commit()

        await interaction.response.send_message(payload)

    @bot.tree.command(name="rpg_drop", description="Bỏ item RPG")
    @app_commands.describe(item="Mã item", amount="Số lượng")
    @app_commands.autocomplete(item=autocomplete_item)
    async def rpg_drop(interaction: discord.Interaction, item: str, amount: int = 1):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        if amount <= 0:
            return await interaction.response.send_message("❌ Amount phải > 0.", ephemeral=True)
        await ensure_db_ready()

        async with DB_WRITE_LOCK:
            async with open_db() as conn:
                ok = await remove_inventory(conn, interaction.guild.id, interaction.user.id, item, amount)
                if not ok:
                    return await interaction.response.send_message("❌ Bạn không đủ item để drop.", ephemeral=True)
                await conn.commit()
        await interaction.response.send_message(f"🗑️ Đã drop `{item}` x{amount}.")

    register_combat_commands(bot, guilds)
    register_quest_commands(bot, guilds)
    register_reports_commands(bot, guilds)
    register_season_commands(bot, guilds)
