import os
import time
import random
import asyncio
from typing import Optional

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands


DB_PATH = os.getenv("LEVELING_DB", "data/leveling.db")

DEFAULT_ENABLED = 1 if os.getenv("LEVELING_ENABLED", "1") == "1" else 0
DEFAULT_XP_MIN = int(os.getenv("LEVELING_XP_MIN", "8"))
DEFAULT_XP_MAX = int(os.getenv("LEVELING_XP_MAX", "18"))
DEFAULT_COOLDOWN = int(os.getenv("LEVELING_COOLDOWN", "45"))

TOP_DEFAULT = int(os.getenv("LEVELING_TOP_DEFAULT", "10"))
TOP_MAX = int(os.getenv("LEVELING_MAX_TOP", "25"))

_DB_READY = False
_DB_INIT_LOCK = asyncio.Lock()
_DB_WRITE_LOCK = asyncio.Lock()


def _ensure_db_dir():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)


def _open_db():
    return aiosqlite.connect(DB_PATH, timeout=30)


def xp_required_for_level(level: int) -> int:
    if level <= 1:
        return 0
    total = 0
    for i in range(1, level):
        total += 100 + (i - 1) * 25
    return total


def level_from_xp(xp: int) -> int:
    lvl = 1
    while xp >= xp_required_for_level(lvl + 1):
        lvl += 1
    return lvl


def _parse_ignored_channels(raw: Optional[str]) -> set[int]:
    if not raw:
        return set()
    out: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except Exception:
            pass
    return out


def _format_ignored_channels(ids: set[int]) -> str:
    if not ids:
        return ""
    return ",".join(str(i) for i in sorted(ids))


async def _db_init():
    _ensure_db_dir()
    async with _open_db() as conn:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute("PRAGMA busy_timeout=5000")

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS level_users (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                xp INTEGER NOT NULL DEFAULT 0,
                level INTEGER NOT NULL DEFAULT 1,
                last_msg_ts INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(guild_id, user_id)
            )
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS level_config (
                guild_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                xp_min INTEGER NOT NULL DEFAULT 8,
                xp_max INTEGER NOT NULL DEFAULT 18,
                cooldown_sec INTEGER NOT NULL DEFAULT 45,
                levelup_channel_id INTEGER,
                ignored_channel_ids TEXT
            )
            """
        )

        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_level_users_rank
            ON level_users(guild_id, level DESC, xp DESC)
            """
        )

        await conn.commit()


async def _ensure_db_ready():
    global _DB_READY
    if _DB_READY:
        return
    async with _DB_INIT_LOCK:
        if _DB_READY:
            return
        await _db_init()
        _DB_READY = True


async def _ensure_config(conn: aiosqlite.Connection, guild_id: int):
    await conn.execute(
        """
        INSERT OR IGNORE INTO level_config(
            guild_id, enabled, xp_min, xp_max, cooldown_sec, levelup_channel_id, ignored_channel_ids
        )
        VALUES (?, ?, ?, ?, ?, NULL, '')
        """,
        (guild_id, DEFAULT_ENABLED, DEFAULT_XP_MIN, DEFAULT_XP_MAX, DEFAULT_COOLDOWN),
    )


async def _get_config(conn: aiosqlite.Connection, guild_id: int) -> dict:
    await _ensure_config(conn, guild_id)
    async with conn.execute(
        """
        SELECT enabled, xp_min, xp_max, cooldown_sec, levelup_channel_id, ignored_channel_ids
        FROM level_config
        WHERE guild_id = ?
        """,
        (guild_id,),
    ) as cur:
        row = await cur.fetchone()

    if not row:
        return {
            "enabled": DEFAULT_ENABLED,
            "xp_min": DEFAULT_XP_MIN,
            "xp_max": DEFAULT_XP_MAX,
            "cooldown_sec": DEFAULT_COOLDOWN,
            "levelup_channel_id": None,
            "ignored_channel_ids": "",
        }

    return {
        "enabled": int(row[0]),
        "xp_min": int(row[1]),
        "xp_max": int(row[2]),
        "cooldown_sec": int(row[3]),
        "levelup_channel_id": int(row[4]) if row[4] else None,
        "ignored_channel_ids": row[5] or "",
    }


async def _ensure_user(conn: aiosqlite.Connection, guild_id: int, user_id: int):
    await conn.execute(
        """
        INSERT OR IGNORE INTO level_users(guild_id, user_id, xp, level, last_msg_ts)
        VALUES (?, ?, 0, 1, 0)
        """,
        (guild_id, user_id),
    )


async def _award_xp(guild_id: int, user_id: int, channel_id: int) -> tuple[bool, int, int, int | None]:
    now = int(time.time())
    async with _DB_WRITE_LOCK:
        async with _open_db() as conn:
            cfg = await _get_config(conn, guild_id)
            if int(cfg["enabled"]) != 1:
                return False, 0, 0, None

            ignored = _parse_ignored_channels(cfg["ignored_channel_ids"])
            if channel_id in ignored:
                return False, 0, 0, None

            await _ensure_user(conn, guild_id, user_id)

            async with conn.execute(
                """
                SELECT xp, level, last_msg_ts
                FROM level_users
                WHERE guild_id = ? AND user_id = ?
                """,
                (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()

            if not row:
                return False, 0, 0, None

            old_xp = int(row[0])
            old_level = int(row[1])
            last_ts = int(row[2])

            cooldown_sec = max(0, int(cfg["cooldown_sec"]))
            if now - last_ts < cooldown_sec:
                return False, old_xp, old_level, cfg["levelup_channel_id"]

            xp_min = int(cfg["xp_min"])
            xp_max = int(cfg["xp_max"])
            if xp_min < 1:
                xp_min = 1
            if xp_max < xp_min:
                xp_max = xp_min

            gained = random.randint(xp_min, xp_max)
            new_xp = old_xp + gained
            new_level = level_from_xp(new_xp)

            await conn.execute(
                """
                UPDATE level_users
                SET xp = ?, level = ?, last_msg_ts = ?
                WHERE guild_id = ? AND user_id = ?
                """,
                (new_xp, new_level, now, guild_id, user_id),
            )
            await conn.commit()

            leveled_up = new_level > old_level
            return leveled_up, new_xp, new_level, cfg["levelup_channel_id"]


async def _get_user_stats(guild_id: int, user_id: int) -> tuple[int, int, int]:
    async with _DB_WRITE_LOCK:
        async with _open_db() as conn:
            await _ensure_user(conn, guild_id, user_id)
            await conn.commit()

            async with conn.execute(
                """
                SELECT xp, level
                FROM level_users
                WHERE guild_id = ? AND user_id = ?
                """,
                (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()

            xp = int(row[0]) if row else 0
            level = int(row[1]) if row else 1

            async with conn.execute(
                """
                SELECT COUNT(1)
                FROM level_users
                WHERE guild_id = ?
                  AND (level > ? OR (level = ? AND xp > ?))
                """,
                (guild_id, level, level, xp),
            ) as cur:
                row_rank = await cur.fetchone()
            rank = int(row_rank[0]) + 1 if row_rank else 1

            return xp, level, rank


async def _get_top(guild_id: int, limit: int):
    limit = max(1, min(limit, TOP_MAX))
    async with _open_db() as conn:
        async with conn.execute(
            """
            SELECT user_id, xp, level
            FROM level_users
            WHERE guild_id = ?
            ORDER BY level DESC, xp DESC, user_id ASC
            LIMIT ?
            """,
            (guild_id, limit),
        ) as cur:
            return await cur.fetchall()


async def _update_config(
    guild_id: int,
    enabled: Optional[bool],
    xp_min: Optional[int],
    xp_max: Optional[int],
    cooldown_sec: Optional[int],
    levelup_channel_id: Optional[int],
):
    async with _DB_WRITE_LOCK:
        async with _open_db() as conn:
            cfg = await _get_config(conn, guild_id)

            enabled_v = int(enabled) if enabled is not None else int(cfg["enabled"])
            xp_min_v = int(xp_min) if xp_min is not None else int(cfg["xp_min"])
            xp_max_v = int(xp_max) if xp_max is not None else int(cfg["xp_max"])
            cooldown_v = int(cooldown_sec) if cooldown_sec is not None else int(cfg["cooldown_sec"])
            lvlup_channel_v = levelup_channel_id if levelup_channel_id is not None else cfg["levelup_channel_id"]

            if xp_min_v < 1:
                xp_min_v = 1
            if xp_max_v < xp_min_v:
                xp_max_v = xp_min_v
            if cooldown_v < 0:
                cooldown_v = 0

            await conn.execute(
                """
                UPDATE level_config
                SET enabled = ?, xp_min = ?, xp_max = ?, cooldown_sec = ?, levelup_channel_id = ?
                WHERE guild_id = ?
                """,
                (enabled_v, xp_min_v, xp_max_v, cooldown_v, lvlup_channel_v, guild_id),
            )
            await conn.commit()


async def _set_ignored_channel(guild_id: int, channel_id: int, add: bool):
    async with _DB_WRITE_LOCK:
        async with _open_db() as conn:
            cfg = await _get_config(conn, guild_id)
            ids = _parse_ignored_channels(cfg["ignored_channel_ids"])
            if add:
                ids.add(channel_id)
            else:
                ids.discard(channel_id)
            raw = _format_ignored_channels(ids)
            await conn.execute(
                "UPDATE level_config SET ignored_channel_ids = ? WHERE guild_id = ?",
                (raw, guild_id),
            )
            await conn.commit()


def setup(bot: commands.Bot, guilds: list = None):
    guilds = guilds or []
    async def _on_ready_once():
        await _ensure_db_ready()

    async def _on_message(message: discord.Message):
        if message.author.bot:
            return
        if message.guild is None:
            return

        await _ensure_db_ready()

        leveled_up, xp, level, levelup_channel_id = await _award_xp(
            message.guild.id,
            message.author.id,
            message.channel.id,
        )

        if leveled_up:
            target_channel = message.channel
            if levelup_channel_id:
                cfg_channel = message.guild.get_channel(levelup_channel_id)
                if isinstance(cfg_channel, discord.TextChannel):
                    target_channel = cfg_channel
            try:
                await target_channel.send(
                    f"🎉 {message.author.mention} đã lên **Level {level}**! (XP: {xp})"
                )
            except Exception:
                pass

    bot.add_listener(_on_ready_once, "on_ready")
    bot.add_listener(_on_message, "on_message")

    @bot.tree.command(name="rank", description="Xem rank/level của bạn hoặc thành viên khác")
    @app_commands.describe(member="Member muốn xem")
    async def rank(interaction: discord.Interaction, member: Optional[discord.Member] = None):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)

        await _ensure_db_ready()

        target = member or (interaction.user if isinstance(interaction.user, discord.Member) else None)
        if target is None:
            return await interaction.response.send_message("❌ Không xác định được member.", ephemeral=True)

        xp, level, rank_no = await _get_user_stats(interaction.guild.id, target.id)
        cur_level_floor = xp_required_for_level(level)
        next_level_floor = xp_required_for_level(level + 1)
        progress = xp - cur_level_floor
        need = max(1, next_level_floor - cur_level_floor)

        e = discord.Embed(title=f"📈 Rank của {target.display_name}", color=discord.Color.blue())
        e.add_field(name="Level", value=str(level), inline=True)
        e.add_field(name="XP", value=str(xp), inline=True)
        e.add_field(name="Rank", value=f"#{rank_no}", inline=True)
        e.add_field(name="Progress", value=f"{progress}/{need}", inline=False)
        await interaction.response.send_message(embed=e)

    @bot.tree.command(name="level_top", description="Bảng xếp hạng level trong server")
    @app_commands.describe(limit="Số lượng hiển thị")
    async def level_top(interaction: discord.Interaction, limit: int = TOP_DEFAULT):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)

        await _ensure_db_ready()

        rows = await _get_top(interaction.guild.id, limit)
        if not rows:
            return await interaction.response.send_message("Chưa có dữ liệu leveling.", ephemeral=True)

        lines = []
        for i, (uid, xp, lvl) in enumerate(rows, start=1):
            m = interaction.guild.get_member(int(uid))
            name = m.display_name if m else f"<@{uid}>"
            lines.append(f"**{i}.** {name} — Lv **{lvl}** | XP **{xp}**")

        e = discord.Embed(
            title="🏆 Level Leaderboard",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=e)

    @bot.tree.command(name="level_config", description="Cấu hình leveling (admin)")
    @app_commands.describe(
        enabled="Bật/tắt leveling",
        xp_min="XP tối thiểu mỗi tin nhắn",
        xp_max="XP tối đa mỗi tin nhắn",
        cooldown_sec="Cooldown cộng XP (giây)",
        levelup_channel="Kênh gửi thông báo level up",
    )
    async def level_config(
        interaction: discord.Interaction,
        enabled: Optional[bool] = None,
        xp_min: Optional[int] = None,
        xp_max: Optional[int] = None,
        cooldown_sec: Optional[int] = None,
        levelup_channel: Optional[discord.TextChannel] = None,
    ):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Bạn không có quyền Manage Server.", ephemeral=True)

        await _ensure_db_ready()

        await _update_config(
            guild_id=interaction.guild.id,
            enabled=enabled,
            xp_min=xp_min,
            xp_max=xp_max,
            cooldown_sec=cooldown_sec,
            levelup_channel_id=levelup_channel.id if levelup_channel else None,
        )

        async with _open_db() as conn:
            cfg = await _get_config(conn, interaction.guild.id)

        ch_txt = f"<#{cfg['levelup_channel_id']}>" if cfg["levelup_channel_id"] else "(same channel)"
        await interaction.response.send_message(
            "✅ Đã cập nhật leveling config:\n"
            f"- enabled: **{bool(cfg['enabled'])}**\n"
            f"- xp range: **{cfg['xp_min']} - {cfg['xp_max']}**\n"
            f"- cooldown: **{cfg['cooldown_sec']}s**\n"
            f"- level up channel: **{ch_txt}**",
            ephemeral=True,
        )

    @bot.tree.command(name="level_ignore_add", description="Thêm kênh vào ignore XP (admin)")
    @app_commands.describe(channel="Kênh cần bỏ qua XP")
    async def level_ignore_add(interaction: discord.Interaction, channel: discord.TextChannel):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Bạn không có quyền Manage Server.", ephemeral=True)

        await _ensure_db_ready()
        await _set_ignored_channel(interaction.guild.id, channel.id, add=True)
        await interaction.response.send_message(f"✅ Đã thêm {channel.mention} vào danh sách ignore XP.", ephemeral=True)

    @bot.tree.command(name="level_ignore_remove", description="Xóa kênh khỏi ignore XP (admin)")
    @app_commands.describe(channel="Kênh cần bật lại XP")
    async def level_ignore_remove(interaction: discord.Interaction, channel: discord.TextChannel):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Bạn không có quyền Manage Server.", ephemeral=True)

        await _ensure_db_ready()
        await _set_ignored_channel(interaction.guild.id, channel.id, add=False)
        await interaction.response.send_message(f"✅ Đã gỡ {channel.mention} khỏi danh sách ignore XP.", ephemeral=True)

    @bot.tree.command(name="level_ignore_list", description="Xem danh sách kênh ignore XP")
    async def level_ignore_list(interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)

        await _ensure_db_ready()
        async with _open_db() as conn:
            cfg = await _get_config(conn, interaction.guild.id)

        ids = sorted(_parse_ignored_channels(cfg["ignored_channel_ids"]))
        if not ids:
            return await interaction.response.send_message("Hiện chưa có kênh nào bị ignore XP.", ephemeral=True)

        lines = [f"- <#{cid}>" for cid in ids]
        await interaction.response.send_message(
            "📌 Kênh ignore XP:\n" + "\n".join(lines),
            ephemeral=True,
        )
