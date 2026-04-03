import asyncio
import re
from datetime import datetime

import discord
from discord.ext import commands

from .config import DEADLINE_ALLOW_GLOBAL_GOOGLE_FALLBACK, VN_TZ
from .db import db_connect
from .google_service import create_deadline_doc, create_deadline_sheet
from .oauth_service import get_user_google_creds
from .utils import masked_link


_RESOURCE_LOCKS: dict[str, asyncio.Lock] = {}


def _get_resource_lock(deadline_id: int, action: str) -> asyncio.Lock:
    key = f"{deadline_id}:{action}"
    lock = _RESOURCE_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _RESOURCE_LOCKS[key] = lock
    return lock


def _resource_message(kind: str, url: str) -> str:
    if kind == "sheet":
        return f"📊 Link nộp bài (Google Sheet): {masked_link('link_sheet', url)}"
    return f"📝 Link nộp bài (Google Docs): {masked_link('link_docs', url)}"


async def _send_resource_message(
    target_channel: discord.abc.Messageable,
    kind: str,
    url: str,
) -> int | None:
    try:
        emoji = "📊" if kind == "sheet" else "📝"
        name = "Google Sheet" if kind == "sheet" else "Google Docs"
        embed = discord.Embed(
            title=f"{emoji} Link nộp bài",
            description=f"**{name}**: [Mở file]({url})",
            color=discord.Color.green(),
        )
        embed.set_footer(text=f"Deadline submission - {name}")
        msg = await target_channel.send(embed=embed)
        try:
            await msg.pin(reason=f"Deadline submission {kind}")
        except Exception:
            pass
        return msg.id
    except Exception:
        return None


async def add_member(guild: discord.Guild, role_id: int | None, user: discord.Member):
    if role_id:
        role = guild.get_role(role_id)
        if role:
            await user.add_roles(role, reason="Joined deadline")


async def remove_member(guild: discord.Guild, role_id: int | None, user: discord.Member):
    if role_id:
        role = guild.get_role(role_id)
        if role:
            await user.remove_roles(role, reason="Left deadline")


async def ensure_role_and_channel(
    guild: discord.Guild,
    title: str,
    deadline_id: int,
    announce_channel: discord.TextChannel,
):
    me = guild.me
    if me is None:
        return None, None

    perms = announce_channel.permissions_for(me)
    if not (perms.manage_roles and perms.manage_channels):
        return None, None

    safe_name = re.sub(r"[^a-zA-Z0-9-_]", "", title.replace(" ", "-"))[:20]
    role_name = f"DL-{safe_name}-{deadline_id}"

    role = await guild.create_role(
        name=role_name,
        mentionable=True,
        reason="Deadline group role",
    )

    ch_name = f"dl-{safe_name}-{deadline_id}".lower()

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True),
    }

    category = announce_channel.category
    channel = await guild.create_text_channel(
        name=ch_name,
        overwrites=overwrites,
        category=category,
        reason="Deadline private room",
    )

    return role, channel


def deadline_summary_embed(
    title: str,
    due_at_iso: str,
    deadline_id: int,
    role_id: int | None,
    channel_id: int | None,
    sheet_link: str | None = None,
    doc_link: str | None = None,
):
    try:
        dt = datetime.fromisoformat(due_at_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=VN_TZ)
        ts = int(dt.timestamp())
        due_str = f"<t:{ts}:F> • <t:{ts}:R>"
    except Exception:
        due_str = due_at_iso

    embed = discord.Embed(
        title=f"📌 Deadline #{deadline_id}",
        description=f"**{title}**\n⏰ Hạn: **{due_str}**",
        color=discord.Color.orange(),
    )

    if role_id:
        embed.add_field(name="👥 Nhóm", value=f"<@&{role_id}>", inline=True)
    if channel_id:
        embed.add_field(name="🏠 Phòng", value=f"<#{channel_id}>", inline=True)
    if sheet_link:
        embed.add_field(name="📊 Sheet", value=masked_link("link_sheet", sheet_link), inline=False)
    if doc_link:
        embed.add_field(name="📝 Docs", value=masked_link("link_docs", doc_link), inline=False)

    embed.set_footer(text="Bấm Join để tham gia nhóm deadline.")
    return embed


async def refresh_deadline_announce_message(bot: commands.Bot, guild: discord.Guild, deadline_id: int):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT title, due_at, role_id, private_channel_id, sheet_link, doc_link, announce_message_id, channel_id
        FROM deadlines
        WHERE id=? AND guild_id=?
        """,
        (deadline_id, guild.id),
    )
    row = cur.fetchone()
    conn.close()

    if not row:
        return

    title, due_at, role_id, private_channel_id, sheet_link, doc_link, announce_message_id, channel_id = row
    if not announce_message_id:
        return

    channel = guild.get_channel(channel_id)
    if not channel:
        return

    try:
        msg = await channel.fetch_message(announce_message_id)
        embed = deadline_summary_embed(title, due_at, deadline_id, role_id, private_channel_id, sheet_link, doc_link)
        await msg.edit(embed=embed, view=DeadlineJoinView(bot, deadline_id))
    except Exception:
        pass


class DeadlineResourceButton(discord.ui.Button):
    def __init__(self, deadline_id: int, action: str, label: str, emoji: str):
        self.deadline_id = int(deadline_id)
        self.action = action
        super().__init__(
            label=label,
            style=discord.ButtonStyle.primary,
            emoji=emoji,
            custom_id=f"deadline_resource:{action}:{self.deadline_id}",
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild:
            embed = discord.Embed(description="❌ Chỉ dùng trong server.", color=discord.Color.red())
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        lock = _get_resource_lock(self.deadline_id, self.action)

        async with lock:
            conn = db_connect()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                    title,
                    owner_id,
                    google_account_email,
                    sheet_link, sheet_file_id, sheet_message_id,
                    doc_link, doc_file_id, doc_message_id,
                    private_channel_id
                FROM deadlines
                WHERE id=? AND guild_id=?
                """,
                (self.deadline_id, interaction.guild.id),
            )
            row = cur.fetchone()

            if not row:
                conn.close()
                embed = discord.Embed(description="❌ Deadline không tồn tại.", color=discord.Color.red())
                return await interaction.followup.send(embed=embed, ephemeral=True)

            (
                title,
                owner_id,
                google_account_email,
                sheet_link,
                sheet_file_id,
                sheet_message_id,
                doc_link,
                doc_file_id,
                doc_message_id,
                private_channel_id,
            ) = row

            if interaction.user.id != owner_id:
                conn.close()
                embed = discord.Embed(description="❌ Chỉ owner mới tạo file nộp bài.", color=discord.Color.red())
                return await interaction.followup.send(embed=embed, ephemeral=True)

            owner_creds = None
            owner_email = None
            try:
                owner_creds, owner_email = get_user_google_creds(
                    int(owner_id),
                    ["https://www.googleapis.com/auth/drive"],
                    str(google_account_email) if google_account_email else None,
                )
            except Exception as cred_err:
                if DEADLINE_ALLOW_GLOBAL_GOOGLE_FALLBACK:
                    owner_creds = None
                else:
                    conn.close()
                    embed = discord.Embed(description=f"❌ {cred_err}", color=discord.Color.red())
                    return await interaction.followup.send(embed=embed, ephemeral=True)

            target_channel = interaction.guild.get_channel(private_channel_id) if private_channel_id else None
            if target_channel is None:
                target_channel = interaction.channel

            if self.action == "sheet":
                if sheet_link:
                    conn.close()
                    embed = discord.Embed(
                        title="📊 Sheet đã tồn tại",
                        description=f"[Mở Google Sheet]({sheet_link})",
                        color=discord.Color.orange(),
                    )
                    return await interaction.followup.send(embed=embed, ephemeral=True)

                file_id, file_link = create_deadline_sheet(
                    f"[DL-{self.deadline_id}] {title} - Sheet",
                    owner_creds,
                )
                if not file_link:
                    conn.close()
                    embed = discord.Embed(description="❌ Không tạo được Google Sheet.", color=discord.Color.red())
                    return await interaction.followup.send(embed=embed, ephemeral=True)

                msg_id = await _send_resource_message(target_channel, "sheet", file_link)

                cur.execute(
                    """
                    UPDATE deadlines
                    SET sheet_link=?, sheet_file_id=?, sheet_message_id=?
                    WHERE id=? AND guild_id=?
                    """,
                    (file_link, file_id, msg_id, self.deadline_id, interaction.guild.id),
                )
                conn.commit()
                conn.close()

                await refresh_deadline_announce_message(interaction.client, interaction.guild, self.deadline_id)
                owner_note = f" (account: `{owner_email}`)" if owner_email else ""
                embed = discord.Embed(
                    title="✅ Đã tạo Google Sheet",
                    description=f"[Mở Google Sheet]({file_link}){owner_note}",
                    color=discord.Color.green(),
                )
                return await interaction.followup.send(embed=embed, ephemeral=True)

            if doc_link:
                conn.close()
                embed = discord.Embed(
                    title="📝 Docs đã tồn tại",
                    description=f"[Mở Google Docs]({doc_link})",
                    color=discord.Color.orange(),
                )
                return await interaction.followup.send(embed=embed, ephemeral=True)

            file_id, file_link = create_deadline_doc(
                f"[DL-{self.deadline_id}] {title} - Docs",
                owner_creds,
            )
            if not file_link:
                conn.close()
                embed = discord.Embed(description="❌ Không tạo được Google Docs.", color=discord.Color.red())
                return await interaction.followup.send(embed=embed, ephemeral=True)

            msg_id = await _send_resource_message(target_channel, "doc", file_link)

            cur.execute(
                """
                UPDATE deadlines
                SET doc_link=?, doc_file_id=?, doc_message_id=?
                WHERE id=? AND guild_id=?
                """,
                (file_link, file_id, msg_id, self.deadline_id, interaction.guild.id),
            )
            conn.commit()
            conn.close()

            await refresh_deadline_announce_message(interaction.client, interaction.guild, self.deadline_id)
            owner_note = f" (account: `{owner_email}`)" if owner_email else ""
            embed = discord.Embed(
                title="✅ Đã tạo Google Docs",
                description=f"[Mở Google Docs]({file_link}){owner_note}",
                color=discord.Color.green(),
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)


class DeadlineResourceView(discord.ui.View):
    def __init__(self, deadline_id: int):
        super().__init__(timeout=None)
        self.add_item(DeadlineResourceButton(deadline_id, "sheet", "Sheet", "📊"))
        self.add_item(DeadlineResourceButton(deadline_id, "doc", "Docs", "📝"))


class DeadlineActionButton(discord.ui.Button):
    def __init__(
        self,
        deadline_id: int,
        action: str,
        *,
        label: str,
        style: discord.ButtonStyle,
        emoji: str,
    ):
        self.deadline_id = int(deadline_id)
        self.action = action
        super().__init__(
            label=label,
            style=style,
            emoji=emoji,
            custom_id=f"deadline:{action}:{self.deadline_id}",
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            embed = discord.Embed(description="❌ Chỉ dùng trong server.", color=discord.Color.red())
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        guild = interaction.guild
        deadline_id = self.deadline_id

        if self.action in ("join", "leave"):
            conn = db_connect()
            cur = conn.cursor()
            cur.execute(
                "SELECT role_id, sheet_file_id FROM deadlines WHERE id=? AND guild_id=?",
                (deadline_id, guild.id),
            )
            row = cur.fetchone()
            if not row:
                conn.close()
                embed = discord.Embed(description="❌ Deadline không tồn tại.", color=discord.Color.red())
                return await interaction.response.send_message(embed=embed, ephemeral=True)

            role_id, sheet_file_id = row

            if self.action == "join":
                cur.execute(
                    "INSERT OR IGNORE INTO deadline_members(deadline_id, user_id) VALUES(?, ?)",
                    (deadline_id, interaction.user.id),
                )
                conn.commit()
                conn.close()

                try:
                    await add_member(guild, role_id, interaction.user)
                except Exception:
                    pass

                embed = discord.Embed(
                    title="✅ Tham gia thành công",
                    description="Bạn đã tham gia deadline này.",
                    color=discord.Color.green(),
                )
                return await interaction.response.send_message(embed=embed, ephemeral=True)

            cur.execute(
                "DELETE FROM deadline_members WHERE deadline_id=? AND user_id=?",
                (deadline_id, interaction.user.id),
            )
            conn.commit()
            conn.close()
            try:
                await remove_member(guild, role_id, interaction.user)
            except Exception:
                pass
            embed = discord.Embed(
                title="👋 Đã rời deadline",
                description="Bạn đã rời deadline này.",
                color=discord.Color.orange(),
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        if self.action == "members":
            conn = db_connect()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT user_id FROM deadline_members
                WHERE deadline_id=?
                LIMIT 25
                """,
                (deadline_id,),
            )
            ids = [row[0] for row in cur.fetchall()]
            conn.close()

            if not ids:
                embed = discord.Embed(
                    title="👥 Thành viên",
                    description="Chưa có ai tham gia.",
                    color=discord.Color.orange(),
                )
                return await interaction.response.send_message(embed=embed, ephemeral=True)

            text = "\n".join(f"• <@{uid}>" for uid in ids)
            embed = discord.Embed(
                title="👥 Thành viên (tối đa 25)",
                description=text,
                color=discord.Color.blurple(),
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)


class DeadlineJoinView(discord.ui.View):
    def __init__(self, bot: commands.Bot, deadline_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.deadline_id = int(deadline_id)

        self.add_item(DeadlineActionButton(self.deadline_id, "join", label="Join", style=discord.ButtonStyle.success, emoji="✅"))
        self.add_item(DeadlineActionButton(self.deadline_id, "leave", label="Leave", style=discord.ButtonStyle.secondary, emoji="🚪"))
        self.add_item(DeadlineActionButton(self.deadline_id, "members", label="Members", style=discord.ButtonStyle.primary, emoji="👥"))

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        embed = discord.Embed(description="❌ Có lỗi khi xử lý nút.", color=discord.Color.red())
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception:
            pass


def view_for(deadline_id: int, bot: commands.Bot) -> discord.ui.View:
    return DeadlineJoinView(bot, deadline_id)


async def cleanup_deadline_resources(bot: commands.Bot, guild_id: int, deadline_id: int) -> tuple[bool, str]:
    guild = bot.get_guild(guild_id)
    if guild is None:
        return False, "Guild không tồn tại trong cache."

    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT role_id, private_channel_id, cleaned_up FROM deadlines WHERE id=? AND guild_id=?",
        (deadline_id, guild_id),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return False, "Deadline không tồn tại."

    role_id, channel_id, cleaned_up = row
    if cleaned_up:
        conn.close()
        return True, "Đã dọn trước đó."

    errors = []

    if channel_id:
        channel = guild.get_channel(int(channel_id))
        if channel:
            try:
                await channel.delete(reason=f"Deadline #{deadline_id} done - cleanup")
            except Exception as error:
                errors.append(f"Không xoá được kênh: {error!r}")

    if role_id:
        role = guild.get_role(int(role_id))
        if role:
            try:
                await role.delete(reason=f"Deadline #{deadline_id} done - cleanup")
            except Exception as error:
                errors.append(f"Không xoá được role: {error!r}")

    cur.execute(
        "UPDATE deadlines SET cleaned_up=1, cleaned_at=? WHERE id=? AND guild_id=?",
        (datetime.now(VN_TZ).isoformat(), deadline_id, guild_id),
    )
    conn.commit()
    conn.close()

    if errors:
        return False, " ; ".join(errors)
    return True, "Đã xoá role/kênh của deadline."
