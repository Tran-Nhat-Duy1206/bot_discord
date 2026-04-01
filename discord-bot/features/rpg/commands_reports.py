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


def register_reports_commands(bot: commands.Bot):
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

    @bot.tree.command(name="rpg_balance_dashboard", description="Dashboard cân bằng combat RPG")
    @app_commands.describe(mode="all / hunt / boss / dungeon")
    async def rpg_balance_dashboard(interaction: discord.Interaction, mode: str = "all"):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)

        mode = (mode or "all").lower().strip()
        allowed = {"all", "hunt", "boss", "dungeon"}
        if mode not in allowed:
            mode = "all"

        await ensure_db_ready()
        async with open_db() as conn:
            rows = await get_combat_telemetry(conn, interaction.guild.id, None if mode == "all" else mode)

        if not rows:
            return await interaction.response.send_message("Chưa có dữ liệu telemetry combat.", ephemeral=True)

        summary: dict[str, dict[str, int]] = {}
        bracket_lines: list[str] = []
        for row in rows:
            r_mode = str(row[0])
            bracket = str(row[1])
            wins = int(row[2])
            losses = int(row[3])
            total_gold = int(row[4])
            total_xp = int(row[5])
            total_turns = int(row[6])
            total_damage_dealt = int(row[7])
            total_damage_taken = int(row[8])
            total_drop_qty = int(row[9])
            samples = int(row[10])

            slot = summary.setdefault(
                r_mode,
                {
                    "wins": 0,
                    "losses": 0,
                    "gold": 0,
                    "xp": 0,
                    "turns": 0,
                    "damage_dealt": 0,
                    "damage_taken": 0,
                    "drop_qty": 0,
                    "samples": 0,
                },
            )
            slot["wins"] += wins
            slot["losses"] += losses
            slot["gold"] += total_gold
            slot["xp"] += total_xp
            slot["turns"] += total_turns
            slot["damage_dealt"] += total_damage_dealt
            slot["damage_taken"] += total_damage_taken
            slot["drop_qty"] += total_drop_qty
            slot["samples"] += samples

            attempts = wins + losses
            wr = (wins * 100.0 / attempts) if attempts > 0 else 0.0
            avg_ttk = _safe_avg(total_turns, attempts)
            avg_drop = _safe_avg(total_drop_qty, samples)
            bracket_lines.append(
                f"`{r_mode}` • Lv {bracket} • WR {wr:.1f}% • TTK {avg_ttk:.2f} • Drops/run {avg_drop:.2f}"
            )

        e = discord.Embed(title="📈 RPG Balance Dashboard", color=discord.Color.dark_gold())
        e.description = f"Mode filter: **{mode}**"

        for m in sorted(summary.keys()):
            item = summary[m]
            wins = int(item["wins"])
            losses = int(item["losses"])
            attempts = wins + losses
            samples = int(item["samples"])
            wr = (wins * 100.0 / attempts) if attempts > 0 else 0.0
            avg_dmg = _safe_avg(int(item["damage_dealt"]), samples)
            avg_ttk = _safe_avg(int(item["turns"]), attempts)
            avg_drop = _safe_avg(int(item["drop_qty"]), samples)
            avg_gold = _safe_avg(int(item["gold"]), samples)
            avg_xp = _safe_avg(int(item["xp"]), samples)

            e.add_field(
                name=f"{m.title()} ({samples} runs)",
                value=(
                    f"WR: **{wr:.1f}%** ({wins}W/{losses}L)\n"
                    f"Avg Damage: **{avg_dmg:.1f}**\n"
                    f"Avg TTK: **{avg_ttk:.2f} turns**\n"
                    f"Drop rate thực tế: **{avg_drop:.2f} items/run**\n"
                    f"Avg reward: **{avg_gold:.1f}g / {avg_xp:.1f}xp**"
                ),
                inline=False,
            )

        if bracket_lines:
            e.add_field(name="Theo level bracket", value="\n".join(bracket_lines[:12]), inline=False)

        await interaction.response.send_message(embed=e, ephemeral=True)

    @bot.tree.command(name="rpg_economy_audit", description="Rà soát nguồn/sink gold RPG")
    @app_commands.describe(days="Số ngày cần thống kê (1-30)")
    async def rpg_economy_audit(interaction: discord.Interaction, days: int = 7):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Chỉ admin mới dùng lệnh này.", ephemeral=True)

        days = max(1, min(30, int(days)))
        now_ts = int(time.time())
        since_ts = now_ts - days * 86400

        await ensure_db_ready()
        async with open_db() as conn:
            rows = await get_gold_flow_summary(conn, interaction.guild.id, since_ts)

        if not rows:
            return await interaction.response.send_message("Chưa có dữ liệu gold flow trong khoảng thời gian này.", ephemeral=True)

        src_lines: list[str] = []
        sink_lines: list[str] = []
        total_src = 0
        total_sink = 0

        for flow_type, source, total_delta, n in rows:
            ftype = str(flow_type)
            src = str(source)
            amount = int(total_delta)
            count = int(n)
            if ftype == "source":
                total_src += amount
                src_lines.append(f"`{src}`: +{amount} ({count} tx)")
            else:
                abs_amt = abs(amount)
                total_sink += abs_amt
                sink_lines.append(f"`{src}`: -{abs_amt} ({count} tx)")

        net = total_src - total_sink
        e = discord.Embed(title="🧮 RPG Economy Audit", color=discord.Color.orange())
        e.description = f"Window: **{days}** ngày"
        e.add_field(name="Tổng source", value=f"+{total_src}", inline=True)
        e.add_field(name="Tổng sink", value=f"-{total_sink}", inline=True)
        e.add_field(name="Net", value=f"{net:+d}", inline=True)
        e.add_field(name="Top source", value="\n".join(src_lines[:8]) if src_lines else "(none)", inline=False)
        e.add_field(name="Top sink", value="\n".join(sink_lines[:8]) if sink_lines else "(none)", inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @bot.tree.command(name="rpg_jackpot", description="Xem thống kê slime jackpot")
    @app_commands.describe(member="Xem thống kê người khác")
    async def rpg_jackpot(interaction: discord.Interaction, member: Optional[discord.Member] = None):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        target = _member_or_self(interaction, member)
        if target is None:
            return await interaction.response.send_message("❌ Không xác định được member.", ephemeral=True)

        await ensure_db_ready()
        async with open_db() as conn:
            hits, total_gold, best_gold, last_ts = await get_jackpot_stats(conn, interaction.guild.id, target.id)

        last_txt = "Never"
        if last_ts > 0:
            last_txt = f"<t:{last_ts}:R>"

        e = discord.Embed(title=f"✨ Slime Jackpot - {target.display_name}", color=discord.Color.fuchsia())
        e.add_field(name="Hits", value=str(hits), inline=True)
        e.add_field(name="Total Gold", value=str(total_gold), inline=True)
        e.add_field(name="Best Jackpot", value=str(best_gold), inline=True)
        e.add_field(name="Last Jackpot", value=last_txt, inline=False)
        await interaction.response.send_message(embed=e)

    @bot.tree.command(name="rpg_leaderboard", description="Leaderboard RPG")
    @app_commands.describe(mode="gold / level / kills")
    async def rpg_leaderboard(interaction: discord.Interaction, mode: str = "gold"):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)

        mode = (mode or "gold").lower().strip()
        if mode not in {"gold", "level", "kills"}:
            mode = "gold"

        await ensure_db_ready()
        async with open_db() as conn:
            if mode == "gold":
                async with conn.execute(
                    "SELECT user_id, gold FROM players WHERE guild_id = ? ORDER BY gold DESC LIMIT 10",
                    (interaction.guild.id,),
                ) as cur:
                    rows = await cur.fetchall()
                title = "🏆 RPG Richest"
                lines = []
                for i, (uid, val) in enumerate(rows, start=1):
                    m = interaction.guild.get_member(int(uid))
                    name = m.display_name if m else f"<@{uid}>"
                    lines.append(f"**{i}.** {name} — **{val}** gold")
            elif mode == "level":
                async with conn.execute(
                    "SELECT user_id, level, xp FROM players WHERE guild_id = ? ORDER BY level DESC, xp DESC LIMIT 10",
                    (interaction.guild.id,),
                ) as cur:
                    rows = await cur.fetchall()
                title = "🏆 RPG Highest Level"
                lines = []
                for i, (uid, lvl, xp) in enumerate(rows, start=1):
                    m = interaction.guild.get_member(int(uid))
                    name = m.display_name if m else f"<@{uid}>"
                    lines.append(f"**{i}.** {name} — Lv **{lvl}** ({xp}/{xp_need_for_next(int(lvl))} xp)")
            else:
                async with conn.execute(
                    """
                    SELECT user_id, SUM(kills) AS total
                    FROM monsters_killed
                    WHERE guild_id = ?
                    GROUP BY user_id
                    ORDER BY total DESC
                    LIMIT 10
                    """,
                    (interaction.guild.id,),
                ) as cur:
                    rows = await cur.fetchall()
                title = "🏆 RPG Monster Kills"
                lines = []
                for i, (uid, total) in enumerate(rows, start=1):
                    m = interaction.guild.get_member(int(uid))
                    name = m.display_name if m else f"<@{uid}>"
                    lines.append(f"**{i}.** {name} — **{total}** kills")

        if not lines:
            return await interaction.response.send_message("Chưa có dữ liệu leaderboard RPG.", ephemeral=True)

        e = discord.Embed(title=title, description="\n".join(lines), color=discord.Color.gold())
        f = apply_embed_asset(e, "leaderboard")
        await interaction.response.send_message(embed=e, files=_collect_files(f))
