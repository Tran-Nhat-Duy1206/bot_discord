import asyncio
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .config import (
    DEADLINE_LIST_LIMIT,
    DEADLINE_LOOP_BATCH_LIMIT,
    DEADLINE_MAX_ACTIVE_PER_GUILD,
    DEADLINE_RESTORE_VIEWS_LIMIT,
    VN_TZ,
)
from .db import db_connect, db_init
from .oauth_service import (
    import_global_token_for_user,
    list_user_google_accounts,
    set_user_google_default,
    start_user_google_link,
    unlink_user_google_account,
    verify_user_google_link,
)
from .ui import (
    DeadlineJoinView,
    DeadlineResourceView,
    add_member,
    cleanup_deadline_resources,
    deadline_summary_embed,
    ensure_role_and_channel,
    remove_member,
    view_for,
)
from .utils import autocomplete_due_date, autocomplete_due_time, autocomplete_notify, make_offsets, parse_due_date_time


def _ok(text: str) -> discord.Embed:
    return discord.Embed(description=f"✅ {text}", color=discord.Color.green())


def _err(text: str) -> discord.Embed:
    return discord.Embed(description=f"❌ {text}", color=discord.Color.red())


def _info(title: str, text: str) -> discord.Embed:
    return discord.Embed(title=title, description=text, color=discord.Color.blurple())


def setup(bot: commands.Bot, guilds: list = None):
    guilds = guilds or []
    db_init()

    backoff_seconds = [60, 300, 1800, 7200, 43200]
    max_attempts = len(backoff_seconds)

    def add_seconds_iso(base: datetime, seconds: int) -> str:
        return (base + timedelta(seconds=seconds)).isoformat()

    @tasks.loop(seconds=30)
    async def deadline_loop():
        now = datetime.now(VN_TZ)
        now_iso = now.isoformat()

        conn = db_connect()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT n.id, n.deadline_id, n.notify_at, n.attempts, n.next_try_at,
                   d.guild_id, d.channel_id, d.owner_id, d.title, d.due_at, d.done, d.role_id
            FROM deadline_notifs n
            JOIN deadlines d ON d.id = n.deadline_id
            WHERE n.sent = 0
              AND n.notify_at <= ?
              AND (n.next_try_at IS NULL OR n.next_try_at = '' OR n.next_try_at <= ?)
            ORDER BY n.notify_at ASC
            LIMIT ?
            """,
            (now_iso, now_iso, max(1, DEADLINE_LOOP_BATCH_LIMIT)),
        )
        rows = cur.fetchall()

        for (notif_id, deadline_id, notify_at, attempts, next_try_at, guild_id, channel_id, owner_id, title, due_at, done, role_id) in rows:
            if done:
                cur.execute("UPDATE deadline_notifs SET sent=1 WHERE id=?", (notif_id,))
                continue

            try:
                notify_at_dt = datetime.fromisoformat(notify_at)
                if notify_at_dt.tzinfo is None:
                    notify_at_dt = notify_at_dt.replace(tzinfo=VN_TZ)
            except Exception:
                cur.execute("UPDATE deadline_notifs SET sent=1 WHERE id=?", (notif_id,))
                continue

            if now >= notify_at_dt:
                channel = bot.get_channel(channel_id)

                try:
                    due_at_dt = datetime.fromisoformat(due_at)
                    if due_at_dt.tzinfo is None:
                        due_at_dt = due_at_dt.replace(tzinfo=VN_TZ)
                    due_str = due_at_dt.strftime("%d/%m/%Y %H:%M")
                except Exception:
                    due_str = due_at

                mention = f"<@&{role_id}>" if role_id else f"<@{owner_id}>"

                try:
                    if not channel:
                        raise RuntimeError(f"Channel not found: {channel_id}")

                    embed = discord.Embed(
                        title="⏰ Nhắc Deadline",
                        description=f"{mention} deadline: **{title}**",
                        color=discord.Color.orange(),
                    )
                    embed.add_field(name="📌 Hạn", value=f"**{due_str}**", inline=True)
                    embed.add_field(name="ID", value=f"`{deadline_id}`", inline=True)
                    await channel.send(embed=embed)

                    print(f"[DEADLINE][OK] notif_id={notif_id} deadline_id={deadline_id}")
                    cur.execute(
                        "UPDATE deadline_notifs SET sent=1, last_error='', next_try_at=NULL WHERE id=?",
                        (notif_id,),
                    )

                except Exception as error:
                    attempts_count = int(attempts or 0) + 1
                    error_text = repr(error)[:500]
                    if attempts_count >= max_attempts:
                        print(
                            f"[DEADLINE][GIVE UP] notif_id={notif_id} deadline_id={deadline_id} "
                            f"attempt={attempts_count}/{max_attempts} error={error_text}"
                        )
                        cur.execute(
                            "UPDATE deadline_notifs SET sent=1, attempts=?, last_error=? WHERE id=?",
                            (attempts_count, error_text, notif_id),
                        )
                    else:
                        delay = backoff_seconds[attempts_count - 1]
                        next_try = add_seconds_iso(now, delay)
                        print(
                            f"[DEADLINE][FAIL] notif_id={notif_id} deadline_id={deadline_id} "
                            f"attempt={attempts_count}/{max_attempts} next_retry_in={delay}s error={error_text}"
                        )
                        cur.execute(
                            "UPDATE deadline_notifs SET attempts=?, next_try_at=?, last_error=? WHERE id=?",
                            (attempts_count, next_try, error_text, notif_id),
                        )

        conn.commit()
        conn.close()

    async def startup():
        if not deadline_loop.is_running():
            deadline_loop.start()

        try:
            conn = db_connect()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id FROM deadlines
                WHERE done=0
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, DEADLINE_RESTORE_VIEWS_LIMIT),),
            )
            ids = [row[0] for row in cur.fetchall()]
            conn.close()
            for deadline_id in ids:
                bot.add_view(view_for(int(deadline_id), bot))
                bot.add_view(DeadlineResourceView(int(deadline_id)))
        except Exception as error:
            print("[deadline] restore views error:", repr(error))

    async def on_ready_once():
        if getattr(bot, "_deadlines_startup_done", False):
            return
        bot._deadlines_startup_done = True
        asyncio.create_task(startup())

    bot.add_listener(on_ready_once, "on_ready")

    async def autocomplete_google_email(interaction: discord.Interaction, current: str):
        query = (current or "").strip().lower()
        rows = list_user_google_accounts(interaction.user.id)
        out: list[app_commands.Choice[str]] = []
        for google_sub, email, is_default, _updated_at in rows:
            email_text = str(email)
            if query and query not in email_text.lower():
                continue
            name = f"{email_text} {'(default)' if int(is_default) == 1 else ''}".strip()
            out.append(app_commands.Choice(name=name[:100], value=email_text))
        return out[:25]

    @bot.tree.command(name="deadline_google_login", description="Liên kết Google account cho deadline")
    async def deadline_google_login(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        auth_url, state = start_user_google_link(interaction.user.id)
        if not auth_url or not state:
            return await interaction.followup.send(embed=_err("Không tạo được link OAuth. Kiểm tra `GOOGLE_OAUTH_CLIENT_SECRET_FILE` và redirect URI."), ephemeral=True)

        embed = discord.Embed(
            title="🔐 Liên kết Google Account",
            description="Mở link bên dưới trong trình duyệt để đăng nhập Google.",
            color=discord.Color.blue(),
        )
        embed.add_field(name="🔗 Link đăng nhập", value=f"```\n{auth_url}\n```", inline=False)
        embed.add_field(
            name="📋 Hướng dẫn",
            value="1. Copy link bên trên và mở trong trình duyệt\n2. Đăng nhập và cấp quyền\n3. Sau khi redirect, copy URL và paste vào:\n`/deadline_google_verify oauth_data:<URL>`",
            inline=False
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.command(name="deadline_google_verify", description="Xác thực callback OAuth Google")
    @app_commands.describe(
        oauth_data="Paste callback URL hoặc mã code từ Google",
        state="State nếu bạn chỉ nhập code",
    )
    async def deadline_google_verify(interaction: discord.Interaction, oauth_data: str, state: str = ""):
        await interaction.response.defer(ephemeral=True)
        ok, msg = verify_user_google_link(interaction.user.id, oauth_data, state or None)
        if not ok:
            return await interaction.followup.send(embed=_err(msg), ephemeral=True)
        embed = discord.Embed(
            title="✅ Liên kết thành công",
            description=f"Google account: `{msg}`",
            color=discord.Color.green(),
        )
        embed.add_field(name="💡 Tiếp theo", value="Dùng `/deadline_google_accounts` để xem và đổi account mặc định.", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)



    @bot.tree.command(name="deadline_google_accounts", description="Xem các Google account đã liên kết")
    async def deadline_google_accounts(interaction: discord.Interaction):
        rows = list_user_google_accounts(interaction.user.id)
        if not rows:
            embed = discord.Embed(
                title="📭 Chưa có Google account",
                description="Bạn chưa liên kết Google account nào.\n\nSử dụng `/deadline_google_login` để bắt đầu.",
                color=discord.Color.orange(),
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        lines = []
        for email, is_default, updated_at in rows:
            prefix = "✅" if int(is_default) == 1 else "•"
            lines.append(f"{prefix} `{email}` (updated: {updated_at})")
        embed = discord.Embed(
            title="Google accounts đã liên kết",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

        @bot.tree.command(name="deadline_google_set_default", description="Đặt Google account mặc định")
        @app_commands.describe(email="Email account muốn đặt mặc định")
        @app_commands.autocomplete(email=autocomplete_google_email)
        async def deadline_google_set_default(interaction: discord.Interaction, email: str):
            ok, msg = set_user_google_default(interaction.user.id, email)
            if not ok:
                return await interaction.response.send_message(embed=_err(msg), ephemeral=True)
            await interaction.response.send_message(embed=_ok(f"Đã đặt mặc định: `{email}`"), ephemeral=True)

        @bot.tree.command(name="deadline_google_unlink", description="Gỡ liên kết một Google account")
        @app_commands.describe(email="Email account muốn gỡ")
        @app_commands.autocomplete(email=autocomplete_google_email)
        async def deadline_google_unlink(interaction: discord.Interaction, email: str):
            ok, msg = unlink_user_google_account(interaction.user.id, email)
            if not ok:
                return await interaction.response.send_message(embed=_err(msg), ephemeral=True)
            await interaction.response.send_message(embed=_ok(f"Đã gỡ liên kết account `{email}`"), ephemeral=True)

    @bot.tree.command(name="deadline_google_import_global", description="Import token global hiện tại vào account của bạn")
    async def deadline_google_import_global(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ok, msg = import_global_token_for_user(interaction.user.id)
        if not ok:
            return await interaction.followup.send(embed=_err(msg), ephemeral=True)
        embed = discord.Embed(
            title="✅ Import thành công",
            description=f"Đã import token global thành account `{msg}` cho user của bạn.",
            color=discord.Color.green(),
        )
        embed.add_field(name="💡 Lưu ý", value="Account này sẽ được đặt làm mặc định nếu đây là account đầu tiên.", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.command(name="deadline_google_help", description="Hướng dẫn liên kết Google account")
    async def deadline_google_help(interaction: discord.Interaction):
        embed = discord.Embed(
            title="🔐 Hướng dẫn liên kết Google account",
            description="Để tạo Google Sheet/Docs cho deadline, bạn cần liên kết Google account của mình.",
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="📝 Các bước thực hiện",
            value=(
                "**1.** Dùng `/deadline_google_login` để nhận link đăng nhập Google\n"
                "**2.** Mở link trong trình duyệt và đăng nhập Google account của bạn\n"
                "**3.** Sau khi Google redirect, copy toàn bộ URL (bắt đầu bằng `https://localhost/...`)\n"
                "**4.** Dùng `/deadline_google_verify` và paste URL đã copy vào tham số `oauth_data`\n"
                "**5.** Hoàn tất! Dùng `/deadline_google_accounts` để xem các account đã liên kết"
            ),
            inline=False,
        )
        embed.add_field(
            name="💡 Mẹo",
            value=(
                "• Bạn có thể liên kết nhiều Google account\n"
                "• Dùng `/deadline_google_set_default` để đổi account mặc định\n"
                "• Dùng `/deadline_google_use_account` để chọn account cho từng deadline cụ thể"
            ),
            inline=False,
        )
        embed.add_field(
            name="⚠️ Lưu ý",
            value="Nếu gặp lỗi từ Discord khi mở link, hãy copy link và mở trong trình duyệt khác (Chrome, Edge...) thay vì dùng Discord built-in browser.",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def autocomplete_my_deadline(interaction: discord.Interaction, current: str):
        if interaction.guild_id is None:
            return []
        query = (current or "").strip().lower()
        conn = db_connect()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, title
            FROM deadlines
            WHERE guild_id=? AND owner_id=? AND done=0
            ORDER BY id DESC
            LIMIT 25
            """,
            (int(interaction.guild_id), int(interaction.user.id)),
        )
        rows = cur.fetchall()
        conn.close()
        out: list[app_commands.Choice[int]] = []
        for deadline_id, title in rows:
            text = f"{deadline_id} {title}".lower()
            if query and query not in text:
                continue
            out.append(app_commands.Choice(name=f"#{deadline_id} - {str(title)[:80]}", value=int(deadline_id)))
        return out[:25]

    @bot.tree.command(name="deadline_google_use_account", description="Chọn Google account dùng cho deadline")
    @app_commands.describe(deadline_id="Deadline của bạn", email="Google email đã liên kết")
    @app_commands.autocomplete(email=autocomplete_google_email)
    async def deadline_google_use_account(interaction: discord.Interaction, deadline_id: int, email: str):
        if interaction.guild_id is None:
            return await interaction.response.send_message(embed=_err("Chỉ dùng trong server."), ephemeral=True)

        conn = db_connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT owner_id FROM deadlines WHERE id=? AND guild_id=?",
            (int(deadline_id), int(interaction.guild_id)),
        )
        row = cur.fetchone()
        if not row:
            conn.close()
            return await interaction.response.send_message(embed=_err("Deadline không tồn tại."), ephemeral=True)
        if int(row[0]) != int(interaction.user.id):
            conn.close()
            return await interaction.response.send_message(embed=_err("Chỉ owner deadline mới đổi account."), ephemeral=True)

        cur.execute(
            "SELECT 1 FROM user_google_accounts WHERE user_id=? AND lower(google_email)=lower(?)",
            (int(interaction.user.id), str(email)),
        )
        if not cur.fetchone():
            conn.close()
            return await interaction.response.send_message(embed=_err("Email chưa được liên kết với bạn."), ephemeral=True)

        cur.execute(
            "UPDATE deadlines SET google_account_email=? WHERE id=? AND guild_id=?",
            (str(email).strip().lower(), int(deadline_id), int(interaction.guild_id)),
        )
        conn.commit()
        conn.close()
        embed = discord.Embed(
            title="✅ Đã cập nhật Google account",
            description=f"Deadline `#{deadline_id}` sẽ dùng account `{email}` để tạo Sheet/Docs.",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(name="deadline_add", description="Tạo deadline + bắt buộc tạo room/role để join")
    @app_commands.describe(
        title="Tên deadline",
        due_date="VD: 07/03/2026 hoặc 2026-03-07",
        due_time="VD: 21:30",
        notify="VD: 1d,1h,10m",
    )
    @app_commands.autocomplete(
        due_date=autocomplete_due_date,
        due_time=autocomplete_due_time,
        notify=autocomplete_notify,
    )
    async def deadline_add(
        interaction: discord.Interaction,
        title: str,
        due_date: str,
        due_time: str,
        notify: str = "1d,1h,10m",
    ):
        await interaction.response.defer(ephemeral=True)

        if not interaction.guild or not interaction.channel:
            return await interaction.followup.send(embed=_err("Chỉ dùng trong server."), ephemeral=True)

        dt = parse_due_date_time(due_date, due_time)
        if not dt:
            embed = discord.Embed(
                title="❌ Sai định dạng ngày giờ",
                description="Ví dụ định dạng đúng:\n• due_date: `07/03/2026` hoặc `2026-03-07`\n• due_time: `21:30`",
                color=discord.Color.red(),
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        if dt <= datetime.now(VN_TZ):
            return await interaction.followup.send(embed=_err("Deadline phải ở tương lai."), ephemeral=True)

        conn = db_connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(1) FROM deadlines WHERE guild_id=? AND done=0",
            (interaction.guild_id,),
        )
        active_count = int((cur.fetchone() or [0])[0])
        if active_count >= max(1, DEADLINE_MAX_ACTIVE_PER_GUILD):
            conn.close()
            embed = discord.Embed(
                title="❌ Đã đạt giới hạn",
                description=f"Server đã có {active_count}/{DEADLINE_MAX_ACTIVE_PER_GUILD} deadline active.\n\nHãy `/deadline_done` hoặc `/deadline_delete` bớt trước.",
                color=discord.Color.red(),
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        cur.execute(
            """
            INSERT INTO deadlines (
                guild_id, channel_id, owner_id, title, due_at, created_at, done,
                role_id, private_channel_id,
                sheet_link, sheet_file_id, sheet_message_id,
                doc_link, doc_file_id, doc_message_id
            )
            VALUES (?, ?, ?, ?, ?, ?, 0, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
            """,
            (
                interaction.guild_id,
                interaction.channel_id,
                interaction.user.id,
                title,
                dt.isoformat(),
                datetime.now(VN_TZ).isoformat(),
            ),
        )
        deadline_id = cur.lastrowid
        conn.commit()

        role_id = None
        private_channel_id = None

        role, channel = await ensure_role_and_channel(
            interaction.guild,
            title,
            deadline_id,
            interaction.channel if isinstance(interaction.channel, discord.TextChannel) else interaction.guild.system_channel,
        )

        if role and channel:
            role_id = role.id
            private_channel_id = channel.id

            try:
                if isinstance(interaction.user, discord.Member):
                    await interaction.user.add_roles(role, reason="Owner created deadline")
            except Exception:
                pass

            cur.execute(
                "UPDATE deadlines SET role_id=?, private_channel_id=? WHERE id=?",
                (role_id, private_channel_id, deadline_id),
            )
            conn.commit()
        else:
            cur.execute("DELETE FROM deadlines WHERE id=?", (deadline_id,))
            conn.commit()
            conn.close()
            return await interaction.followup.send(
                "❌ Không tạo được room/role. Kiểm tra quyền Manage Roles và Manage Channels của bot.",
                ephemeral=True,
            )

        target_room = interaction.guild.get_channel(private_channel_id)
        if target_room:
            try:
                panel_embed = discord.Embed(
                    title="📁 Tạo file nộp bài",
                    description="Owner chọn 1 trong 2 nút bên dưới để tạo file nộp bài cho deadline này.",
                    color=discord.Color.blurple(),
                )
                await target_room.send(embed=panel_embed, view=DeadlineResourceView(deadline_id))
            except Exception:
                pass

        cur.execute(
            "INSERT OR IGNORE INTO deadline_members(deadline_id, user_id) VALUES(?, ?)",
            (deadline_id, interaction.user.id),
        )

        offsets = make_offsets(notify)
        notify_times = []
        now = datetime.now(VN_TZ)

        for offset in offsets:
            notify_at = dt - offset
            if notify_at > now:
                notify_times.append(notify_at)

        notify_times.append(dt)
        notify_times = sorted({notify_at.isoformat() for notify_at in notify_times})
        for notify_iso in notify_times:
            cur.execute(
                "INSERT INTO deadline_notifs (deadline_id, notify_at, sent) VALUES (?, ?, 0)",
                (deadline_id, notify_iso),
            )

        conn.commit()
        conn.close()

        embed = deadline_summary_embed(
            title,
            dt.isoformat(),
            deadline_id,
            role_id,
            private_channel_id,
            None,
            None,
        )
        view = DeadlineJoinView(bot, deadline_id)

        embed = discord.Embed(
            title="✅ Deadline đã được tạo",
            description=f"Đã tạo deadline `#{deadline_id}`. Mình gửi bảng Join ra kênh để mọi người tham gia.",
            color=discord.Color.green(),
        )
        embed.add_field(name="📝 Tiêu đề", value=title, inline=True)
        embed.add_field(name="📅 Hạn", value=dt.strftime("%d/%m/%Y %H:%M"), inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)
        sent = await interaction.channel.send(embed=embed, view=view)

        try:
            conn = db_connect()
            cur = conn.cursor()
            cur.execute(
                "UPDATE deadlines SET announce_message_id=? WHERE id=?",
                (sent.id, deadline_id),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    @bot.tree.command(name="deadline_add_member", description="Chủ deadline add thành viên vào group")
    async def deadline_add_member(interaction: discord.Interaction, deadline_id: int, member: discord.Member):
        if not interaction.guild:
            return await interaction.response.send_message(embed=_err("Chỉ dùng trong server."), ephemeral=True)

        conn = db_connect()
        cur = conn.cursor()
        cur.execute("SELECT owner_id, role_id FROM deadlines WHERE id=? AND guild_id=?", (deadline_id, interaction.guild_id))
        row = cur.fetchone()
        if not row:
            conn.close()
            return await interaction.response.send_message(embed=_err("Deadline không tồn tại."), ephemeral=True)

        owner_id, role_id = row
        if interaction.user.id != owner_id:
            conn.close()
            return await interaction.response.send_message(embed=_err("Chỉ chủ deadline mới add được."), ephemeral=True)

        cur.execute("INSERT OR IGNORE INTO deadline_members(deadline_id, user_id) VALUES(?, ?)", (deadline_id, member.id))
        conn.commit()
        conn.close()

        try:
            await add_member(interaction.guild, role_id, member)
        except Exception:
            pass

        embed = discord.Embed(
            title="✅ Đã thêm thành viên",
            description=f"Đã thêm {member.mention} vào deadline `#{deadline_id}`.",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(name="deadline_list", description="Xem deadline của bạn trong server")
    async def deadline_list(interaction: discord.Interaction):
        conn = db_connect()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT d.id, d.title, d.due_at, d.done
            FROM deadlines d
            JOIN deadline_members m ON m.deadline_id = d.id
            WHERE d.guild_id=? AND m.user_id=?
            ORDER BY d.done ASC, d.due_at ASC
            LIMIT ?
            """,
            (interaction.guild_id, interaction.user.id, max(1, DEADLINE_LIST_LIMIT)),
        )
        rows = cur.fetchall()
        conn.close()

        if not rows:
            embed = discord.Embed(
                title="📭 Không có deadline",
                description="Bạn chưa tham gia deadline nào.",
                color=discord.Color.orange(),
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        lines = []
        for (deadline_id, title, due_at, done) in rows:
            try:
                dt = datetime.fromisoformat(due_at)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=VN_TZ)
                ts = int(dt.timestamp())
                due_str = f"<t:{ts}:F> • <t:{ts}:R>"
            except Exception:
                due_str = due_at
            status = "✅" if done else "⏳"
            lines.append(f"{status} `{deadline_id}` • **{title}** • {due_str}")

        embed = discord.Embed(title="📌 Deadline bạn tham gia", description="\n".join(lines), color=discord.Color.orange())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(name="deadline_info", description="Xem chi tiết 1 deadline")
    async def deadline_info(interaction: discord.Interaction, deadline_id: int):
        if not interaction.guild:
            return await interaction.response.send_message(embed=_err("Chỉ dùng trong server."), ephemeral=True)

        conn = db_connect()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, title, due_at, done, role_id, private_channel_id, sheet_link, doc_link, owner_id, created_at, cleaned_up, google_account_email
            FROM deadlines
            WHERE id=? AND guild_id=?
            """,
            (deadline_id, interaction.guild_id),
        )
        row = cur.fetchone()
        conn.close()

        if not row:
            return await interaction.response.send_message(embed=_err("Deadline không tồn tại."), ephemeral=True)

        (deadline_id, title, due_at, done, role_id, channel_id, sheet_link, doc_link, owner_id, created_at, cleaned_up, google_account_email) = row
        embed = deadline_summary_embed(title, due_at, deadline_id, role_id, channel_id, sheet_link, doc_link)
        embed.add_field(name="👤 Owner", value=f"<@{owner_id}>", inline=True)
        embed.add_field(name="🧹 Cleaned", value="✅" if cleaned_up else "❌", inline=True)
        embed.add_field(name="📅 Created", value=created_at, inline=False)
        embed.add_field(name="📌 Status", value="✅ Done" if done else "⏳ Active", inline=True)
        if google_account_email:
            embed.add_field(name="🔐 Google account", value=f"`{google_account_email}`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(name="deadline_delete", description="Xoá deadline (owner) + dọn role/kênh")
    async def deadline_delete(interaction: discord.Interaction, deadline_id: int):
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild:
            return await interaction.followup.send(embed=_err("Chỉ dùng trong server."), ephemeral=True)

        conn = db_connect()
        cur = conn.cursor()
        cur.execute("SELECT owner_id FROM deadlines WHERE id=? AND guild_id=?", (deadline_id, interaction.guild_id))
        row = cur.fetchone()
        if not row:
            conn.close()
            return await interaction.followup.send(embed=_err("Deadline không tồn tại."), ephemeral=True)

        if interaction.user.id != row[0]:
            conn.close()
            return await interaction.followup.send(embed=_err("Chỉ owner mới xoá được."), ephemeral=True)

        cur.execute("UPDATE deadlines SET done=1 WHERE id=? AND guild_id=?", (deadline_id, interaction.guild_id))
        conn.commit()
        conn.close()

        ok, msg = await cleanup_deadline_resources(bot, interaction.guild_id, deadline_id)

        conn = db_connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM deadline_notifs WHERE deadline_id=?", (deadline_id,))
        cur.execute("DELETE FROM deadline_members WHERE deadline_id=?", (deadline_id,))
        cur.execute("DELETE FROM deadlines WHERE id=? AND guild_id=?", (deadline_id, interaction.guild_id))
        conn.commit()
        conn.close()

        try:
            embed = discord.Embed(
                title="✅ Đã xoá deadline",
                description=f"Đã xoá deadline `#{deadline_id}`.",
                color=discord.Color.green(),
            )
            if msg:
                embed.add_field(name="🧹 Cleanup", value=msg, inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except discord.NotFound:
            if interaction.channel:
                embed = discord.Embed(
                    title="✅ Đã xoá deadline",
                    description=f"Đã xoá deadline `#{deadline_id}`.",
                    color=discord.Color.green(),
                )
                if msg:
                    embed.add_field(name="🧹 Cleanup", value=msg, inline=False)
                await interaction.channel.send(embed=embed)

    @bot.tree.command(name="deadline_done", description="Chủ deadline đánh dấu xong")
    async def deadline_done(interaction: discord.Interaction, deadline_id: int):
        await interaction.response.defer(ephemeral=True)
        conn = db_connect()
        cur = conn.cursor()
        cur.execute("SELECT owner_id FROM deadlines WHERE id=? AND guild_id=?", (deadline_id, interaction.guild_id))
        row = cur.fetchone()
        if not row:
            conn.close()
            return await interaction.followup.send(embed=_err("Deadline không tồn tại."), ephemeral=True)

        if interaction.user.id != row[0]:
            conn.close()
            return await interaction.followup.send(embed=_err("Chỉ chủ deadline mới đánh dấu xong."), ephemeral=True)

        cur.execute("UPDATE deadlines SET done=1 WHERE id=? AND guild_id=?", (deadline_id, interaction.guild_id))
        conn.commit()
        conn.close()

        ok, msg = await cleanup_deadline_resources(bot, interaction.guild_id, deadline_id)
        embed = discord.Embed(
            title="✅ Deadline hoàn thành",
            description=f"Đã đánh dấu xong deadline `#{deadline_id}`.",
            color=discord.Color.green(),
        )
        if msg:
            embed.add_field(name="🧹 Cleanup", value=msg, inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)
