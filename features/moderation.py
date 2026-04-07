import os
import asyncio
import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands
from datetime import timedelta


DB_PATH = os.getenv("MODERATION_DB", "data/moderation.db")
WARN_LIMIT = int(os.getenv("MOD_WARN_LIMIT", "3"))
WARN_TIMEOUT_MINUTES = int(os.getenv("MOD_WARN_TIMEOUT_MINUTES", "10"))
_MOD_DB_INIT_LOCK = asyncio.Lock()
_MOD_DB_READY = False


def _ensure_db_dir():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)


async def _db_init():
    _ensure_db_dir()
    async with aiosqlite.connect(DB_PATH, timeout=30) as conn:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute("PRAGMA busy_timeout=5000")

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS moderation_warns (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                warn_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS moderation_config (
                guild_id INTEGER PRIMARY KEY,
                auto_role_id INTEGER,
                mod_log_channel_id INTEGER
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS moderation_warn_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        for ddl in (
            "ALTER TABLE moderation_config ADD COLUMN mod_log_channel_id INTEGER",
        ):
            try:
                await conn.execute(ddl)
            except Exception:
                pass
        await conn.commit()


def _reason_with_actor(reason: str, actor: discord.abc.User) -> str:
    return f"{reason} | by {actor} ({actor.id})"


def _can_target(
    actor: discord.Member,
    target: discord.Member,
    bot_member: discord.Member,
) -> tuple[bool, str | None]:
    if target.id == actor.id:
        return False, "❌ Bạn không thể tự thao tác lên chính mình."
    if target.id == bot_member.id:
        return False, "❌ Bạn không thể thao tác lên bot."
    if target == target.guild.owner:
        return False, "❌ Không thể thao tác lên server owner."
    if actor.top_role <= target.top_role and actor != target.guild.owner:
        return False, "❌ Role của bạn phải cao hơn role của người bị thao tác."
    if bot_member.top_role <= target.top_role:
        return False, "❌ Role của bot không đủ cao để thao tác người này."
    return True, None


async def _get_warn_count(guild_id: int, user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH, timeout=30) as conn:
        async with conn.execute(
            "SELECT warn_count FROM moderation_warns WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0


async def _add_warn(guild_id: int, user_id: int) -> int:
    now = discord.utils.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH, timeout=30) as conn:
        await conn.execute(
            """
            INSERT INTO moderation_warns(guild_id, user_id, warn_count, updated_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(guild_id, user_id)
            DO UPDATE SET warn_count = warn_count + 1, updated_at = excluded.updated_at
            """,
            (guild_id, user_id, now),
        )
        await conn.commit()

    return await _get_warn_count(guild_id, user_id)


async def _add_warn_log(guild_id: int, user_id: int, moderator_id: int, reason: str):
    now = discord.utils.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH, timeout=30) as conn:
        await conn.execute(
            """
            INSERT INTO moderation_warn_logs(guild_id, user_id, moderator_id, reason, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (guild_id, user_id, moderator_id, reason, now),
        )
        await conn.commit()


async def _get_warn_logs(guild_id: int, user_id: int, limit: int = 10):
    async with aiosqlite.connect(DB_PATH, timeout=30) as conn:
        async with conn.execute(
            """
            SELECT moderator_id, reason, created_at
            FROM moderation_warn_logs
            WHERE guild_id = ? AND user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (guild_id, user_id, limit),
        ) as cur:
            return await cur.fetchall()


async def _clear_warns(guild_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH, timeout=30) as conn:
        await conn.execute(
            "DELETE FROM moderation_warns WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        await conn.execute(
            "DELETE FROM moderation_warn_logs WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        await conn.commit()


async def _reset_warn_count(guild_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH, timeout=30) as conn:
        await conn.execute(
            "DELETE FROM moderation_warns WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        await conn.commit()


async def _set_auto_role(guild_id: int, role_id: int | None):
    async with aiosqlite.connect(DB_PATH, timeout=30) as conn:
        await conn.execute(
            """
            INSERT INTO moderation_config(guild_id, auto_role_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id)
            DO UPDATE SET auto_role_id = excluded.auto_role_id
            """,
            (guild_id, role_id),
        )
        await conn.commit()


async def _set_mod_log_channel(guild_id: int, channel_id: int | None):
    async with aiosqlite.connect(DB_PATH, timeout=30) as conn:
        await conn.execute(
            """
            INSERT INTO moderation_config(guild_id, mod_log_channel_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id)
            DO UPDATE SET mod_log_channel_id = excluded.mod_log_channel_id
            """,
            (guild_id, channel_id),
        )
        await conn.commit()


async def _get_auto_role(guild_id: int) -> int | None:
    async with aiosqlite.connect(DB_PATH, timeout=30) as conn:
        async with conn.execute(
            "SELECT auto_role_id FROM moderation_config WHERE guild_id = ?",
            (guild_id,),
        ) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row and row[0] else None


async def _get_mod_log_channel(guild_id: int) -> int | None:
    async with aiosqlite.connect(DB_PATH, timeout=30) as conn:
        async with conn.execute(
            "SELECT mod_log_channel_id FROM moderation_config WHERE guild_id = ?",
            (guild_id,),
        ) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row and row[0] else None


async def _send_mod_log(guild: discord.Guild, embed: discord.Embed):
    channel_id = await _get_mod_log_channel(guild.id)
    if not channel_id:
        return
    channel = guild.get_channel(channel_id)
    if channel is None or not isinstance(channel, discord.TextChannel):
        return
    try:
        await channel.send(embed=embed)
    except Exception:
        pass


def setup(bot: commands.Bot, guilds: list = None):
    guilds = guilds or []
    async def _on_ready_once():
        global _MOD_DB_READY
        if _MOD_DB_READY:
            return
        async with _MOD_DB_INIT_LOCK:
            if _MOD_DB_READY:
                return
            await _db_init()
            _MOD_DB_READY = True

    async def _on_member_join(member: discord.Member):
        role_id = await _get_auto_role(member.guild.id)
        if not role_id:
            return
        role = member.guild.get_role(role_id)
        if role is None:
            return
        me = member.guild.me
        if me is None or not me.guild_permissions.manage_roles:
            return
        if me.top_role <= role:
            return
        try:
            await member.add_roles(role, reason="Auto role on join")
        except Exception:
            pass

    bot.add_listener(_on_ready_once, "on_ready")
    bot.add_listener(_on_member_join, "on_member_join")

    @bot.tree.command(name="kick", description="Kick một thành viên")
    @app_commands.describe(member="Người cần kick", reason="Lý do")
    async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        if not interaction.user.guild_permissions.kick_members:
            return await interaction.response.send_message("❌ Bạn không có quyền kick.", ephemeral=True)
        me = interaction.guild.me
        if me is None or not me.guild_permissions.kick_members:
            return await interaction.response.send_message("❌ Bot thiếu quyền Kick Members.", ephemeral=True)

        ok, err = _can_target(interaction.user, member, me)
        if not ok:
            return await interaction.response.send_message(err or "❌ Không thể kick người này.", ephemeral=True)

        try:
            await member.kick(reason=_reason_with_actor(reason, interaction.user))
            await interaction.response.send_message(f"👢 Đã kick {member.mention}\nLý do: {reason}")
            e = discord.Embed(title="👢 Member Kicked", color=discord.Color.orange())
            e.add_field(name="Member", value=f"{member} ({member.id})", inline=False)
            e.add_field(name="Moderator", value=f"{interaction.user} ({interaction.user.id})", inline=False)
            e.add_field(name="Reason", value=reason, inline=False)
            await _send_mod_log(interaction.guild, e)
        except Exception:
            await interaction.response.send_message("❌ Không thể kick người này.", ephemeral=True)

    @bot.tree.command(name="ban", description="Ban một thành viên")
    @app_commands.describe(member="Người cần ban", reason="Lý do", delete_days="Xóa lịch sử chat trong bao nhiêu ngày")
    async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason", delete_days: int = 0):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        if not interaction.user.guild_permissions.ban_members:
            return await interaction.response.send_message("❌ Bạn không có quyền ban.", ephemeral=True)
        me = interaction.guild.me
        if me is None or not me.guild_permissions.ban_members:
            return await interaction.response.send_message("❌ Bot thiếu quyền Ban Members.", ephemeral=True)

        ok, err = _can_target(interaction.user, member, me)
        if not ok:
            return await interaction.response.send_message(err or "❌ Không thể ban người này.", ephemeral=True)

        delete_days = max(0, min(delete_days, 7))
        try:
            await interaction.guild.ban(
                member,
                reason=_reason_with_actor(reason, interaction.user),
                delete_message_seconds=delete_days * 86400,
            )
            await interaction.response.send_message(
                f"🔨 Đã ban {member.mention}\nLý do: {reason}\nXóa lịch sử: {delete_days} ngày"
            )
            e = discord.Embed(title="🔨 Member Banned", color=discord.Color.red())
            e.add_field(name="Member", value=f"{member} ({member.id})", inline=False)
            e.add_field(name="Moderator", value=f"{interaction.user} ({interaction.user.id})", inline=False)
            e.add_field(name="Delete History", value=f"{delete_days} day(s)", inline=True)
            e.add_field(name="Reason", value=reason, inline=False)
            await _send_mod_log(interaction.guild, e)
        except Exception:
            await interaction.response.send_message("❌ Không thể ban người này.", ephemeral=True)

    @bot.tree.command(name="timeout", description="Timeout thành viên")
    @app_commands.describe(member="Người bị timeout", minutes="Số phút", reason="Lý do")
    async def timeout(interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "No reason"):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        if not interaction.user.guild_permissions.moderate_members:
            return await interaction.response.send_message("❌ Bạn không có quyền timeout.", ephemeral=True)
        me = interaction.guild.me
        if me is None or not me.guild_permissions.moderate_members:
            return await interaction.response.send_message("❌ Bot thiếu quyền Moderate Members.", ephemeral=True)

        ok, err = _can_target(interaction.user, member, me)
        if not ok:
            return await interaction.response.send_message(err or "❌ Không thể timeout người này.", ephemeral=True)
        if minutes < 1 or minutes > 40320:
            return await interaction.response.send_message("❌ Minutes phải trong khoảng 1-40320 (28 ngày).", ephemeral=True)

        until = discord.utils.utcnow() + timedelta(minutes=minutes)
        try:
            await member.timeout(until, reason=_reason_with_actor(reason, interaction.user))
            await interaction.response.send_message(
                f"⏳ {member.mention} bị timeout {minutes} phút\nLý do: {reason}"
            )
            e = discord.Embed(title="⏳ Member Timed Out", color=discord.Color.gold())
            e.add_field(name="Member", value=f"{member} ({member.id})", inline=False)
            e.add_field(name="Moderator", value=f"{interaction.user} ({interaction.user.id})", inline=False)
            e.add_field(name="Duration", value=f"{minutes} minute(s)", inline=True)
            e.add_field(name="Reason", value=reason, inline=False)
            await _send_mod_log(interaction.guild, e)
        except Exception:
            await interaction.response.send_message("❌ Không thể timeout người này.", ephemeral=True)

    @bot.tree.command(name="untimeout", description="Gỡ timeout cho thành viên")
    @app_commands.describe(member="Người cần gỡ timeout", reason="Lý do")
    async def untimeout(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        if not interaction.user.guild_permissions.moderate_members:
            return await interaction.response.send_message("❌ Bạn không có quyền untimeout.", ephemeral=True)
        me = interaction.guild.me
        if me is None or not me.guild_permissions.moderate_members:
            return await interaction.response.send_message("❌ Bot thiếu quyền Moderate Members.", ephemeral=True)

        ok, err = _can_target(interaction.user, member, me)
        if not ok:
            return await interaction.response.send_message(err or "❌ Không thể thao tác người này.", ephemeral=True)

        try:
            await member.timeout(None, reason=_reason_with_actor(reason, interaction.user))
            await interaction.response.send_message(f"✅ Đã gỡ timeout cho {member.mention}")
            e = discord.Embed(title="✅ Timeout Removed", color=discord.Color.green())
            e.add_field(name="Member", value=f"{member} ({member.id})", inline=False)
            e.add_field(name="Moderator", value=f"{interaction.user} ({interaction.user.id})", inline=False)
            e.add_field(name="Reason", value=reason, inline=False)
            await _send_mod_log(interaction.guild, e)
        except Exception:
            await interaction.response.send_message("❌ Không thể gỡ timeout.", ephemeral=True)

    @bot.tree.command(name="clear", description="Xóa tin nhắn")
    @app_commands.describe(amount="Số tin nhắn cần xóa")
    async def clear(interaction: discord.Interaction, amount: int):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Bạn không có quyền xóa tin nhắn.", ephemeral=True)
        me = interaction.guild.me
        if me is None or not me.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Bot thiếu quyền Manage Messages.", ephemeral=True)
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("❌ Lệnh này chỉ dùng trong text channel.", ephemeral=True)
        if amount < 1 or amount > 200:
            return await interaction.response.send_message("❌ Chỉ được xóa 1-200 tin nhắn mỗi lần.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        try:
            deleted = await interaction.channel.purge(limit=amount)
        except Exception:
            return await interaction.followup.send("❌ Không thể xóa tin nhắn trong kênh này.", ephemeral=True)
        await interaction.followup.send(f"🧹 Đã xóa {len(deleted)} tin nhắn.", ephemeral=True)
        e = discord.Embed(title="🧹 Messages Cleared", color=discord.Color.blurple())
        e.add_field(name="Moderator", value=f"{interaction.user} ({interaction.user.id})", inline=False)
        e.add_field(name="Channel", value=f"{interaction.channel.mention}", inline=True)
        e.add_field(name="Count", value=str(len(deleted)), inline=True)
        await _send_mod_log(interaction.guild, e)

    @bot.tree.command(name="warn", description="Cảnh cáo thành viên")
    @app_commands.describe(member="Người bị warn", reason="Lý do")
    async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Bạn không có quyền warn.", ephemeral=True)
        me = interaction.guild.me
        if me is None:
            return await interaction.response.send_message("❌ Không lấy được thông tin bot trong server.", ephemeral=True)

        ok, err = _can_target(interaction.user, member, me)
        if not ok:
            return await interaction.response.send_message(err or "❌ Không thể warn người này.", ephemeral=True)

        count = await _add_warn(interaction.guild.id, member.id)
        await _add_warn_log(interaction.guild.id, member.id, interaction.user.id, reason)
        shown_count = min(count, WARN_LIMIT)
        await interaction.response.send_message(
            f"⚠️ {member.mention} bị cảnh cáo ({shown_count}/{WARN_LIMIT})\nLý do: {reason}"
        )
        e = discord.Embed(title="⚠️ Member Warned", color=discord.Color.orange())
        e.add_field(name="Member", value=f"{member} ({member.id})", inline=False)
        e.add_field(name="Moderator", value=f"{interaction.user} ({interaction.user.id})", inline=False)
        e.add_field(name="Warn Count", value=f"{shown_count}/{WARN_LIMIT}", inline=True)
        e.add_field(name="Reason", value=reason, inline=False)
        await _send_mod_log(interaction.guild, e)

        if count >= WARN_LIMIT and me.guild_permissions.moderate_members:
            until = discord.utils.utcnow() + timedelta(minutes=WARN_TIMEOUT_MINUTES)
            try:
                await member.timeout(
                    until,
                    reason=_reason_with_actor(f"Auto-timeout after {count} warns", interaction.user),
                )
                await interaction.followup.send(
                    f"⛔ {member.mention} bị timeout {WARN_TIMEOUT_MINUTES} phút (đủ {WARN_LIMIT} warns)."
                )
                await _reset_warn_count(interaction.guild.id, member.id)
            except Exception:
                await interaction.followup.send(
                    "⚠️ Đạt ngưỡng warn nhưng bot không timeout được (thiếu quyền/role).",
                    ephemeral=True,
                )

    @bot.tree.command(name="warnings", description="Xem số warn của thành viên")
    @app_commands.describe(member="Người cần xem warn")
    async def warnings(interaction: discord.Interaction, member: discord.Member):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        count = await _get_warn_count(interaction.guild.id, member.id)
        await interaction.response.send_message(
            f"📋 {member.mention} đang có **{count}** warn(s).",
            ephemeral=True,
        )

    @bot.tree.command(name="warnhistory", description="Xem lịch sử warn chi tiết của thành viên")
    @app_commands.describe(member="Người cần xem", limit="Số dòng lịch sử")
    async def warnhistory(interaction: discord.Interaction, member: discord.Member, limit: int = 10):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)

        limit = max(1, min(limit, 20))
        rows = await _get_warn_logs(interaction.guild.id, member.id, limit)
        if not rows:
            return await interaction.response.send_message(
                f"📭 {member.mention} chưa có lịch sử warn.",
                ephemeral=True,
            )

        lines = []
        for idx, (moderator_id, reason, created_at) in enumerate(rows, start=1):
            try:
                ts = int(discord.utils.parse_time(created_at).timestamp())
                t_txt = f"<t:{ts}:F>"
            except Exception:
                t_txt = created_at
            lines.append(f"**{idx}.** {t_txt} • <@{moderator_id}>\n- {reason}")

        e = discord.Embed(
            title=f"📒 Warn history - {member}",
            description="\n".join(lines),
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=e, ephemeral=True)

    @bot.tree.command(name="clearwarn", description="Xóa toàn bộ warn của thành viên")
    @app_commands.describe(member="Người cần xóa warn")
    async def clearwarn(interaction: discord.Interaction, member: discord.Member):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Bạn không có quyền clear warn.", ephemeral=True)

        await _clear_warns(interaction.guild.id, member.id)
        await interaction.response.send_message(f"✅ Đã xóa toàn bộ warn của {member.mention}.")
        e = discord.Embed(title="✅ Warns Cleared", color=discord.Color.green())
        e.add_field(name="Member", value=f"{member} ({member.id})", inline=False)
        e.add_field(name="Moderator", value=f"{interaction.user} ({interaction.user.id})", inline=False)
        await _send_mod_log(interaction.guild, e)

    @bot.tree.command(name="setautorole", description="Đặt auto role cho member mới")
    @app_commands.describe(role="Role tự động gán")
    async def setautorole(interaction: discord.Interaction, role: discord.Role):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Bạn không có quyền Manage Server.", ephemeral=True)
        me = interaction.guild.me
        if me is None or not me.guild_permissions.manage_roles:
            return await interaction.response.send_message("❌ Bot thiếu quyền Manage Roles.", ephemeral=True)
        if me.top_role <= role:
            return await interaction.response.send_message("❌ Role bot phải cao hơn role auto.", ephemeral=True)

        await _set_auto_role(interaction.guild.id, role.id)
        await interaction.response.send_message(f"✅ Đã đặt auto role: {role.mention}")

    @bot.tree.command(name="autorole_off", description="Tắt auto role")
    async def autorole_off(interaction: discord.Interaction):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Bạn không có quyền Manage Server.", ephemeral=True)

        await _set_auto_role(interaction.guild.id, None)
        await interaction.response.send_message("✅ Đã tắt auto role.")

    @bot.tree.command(name="setmodlog", description="Đặt kênh log moderation")
    @app_commands.describe(channel="Kênh nhận log moderation")
    async def setmodlog(interaction: discord.Interaction, channel: discord.TextChannel):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Bạn không có quyền Manage Server.", ephemeral=True)
        me = interaction.guild.me
        if me is None:
            return await interaction.response.send_message("❌ Không lấy được thông tin bot.", ephemeral=True)

        perms = channel.permissions_for(me)
        if not perms.send_messages:
            return await interaction.response.send_message("❌ Bot không có quyền gửi tin nhắn ở kênh đó.", ephemeral=True)

        await _set_mod_log_channel(interaction.guild.id, channel.id)
        await interaction.response.send_message(f"✅ Đã đặt kênh mod log: {channel.mention}")

    @bot.tree.command(name="modlog_off", description="Tắt log moderation")
    async def modlog_off(interaction: discord.Interaction):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Bạn không có quyền Manage Server.", ephemeral=True)

        await _set_mod_log_channel(interaction.guild.id, None)
        await interaction.response.send_message("✅ Đã tắt moderation log.")
