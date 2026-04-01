import os
import time
import random
import asyncio
from dataclasses import dataclass, field
from typing import Optional

import aiosqlite
import discord
from discord.ext import commands
from discord import app_commands


DB_PATH = os.getenv("ECONOMY_DB", "data/economy.db")
SQLITE_TIMEOUT = float(os.getenv("ECONOMY_SQLITE_TIMEOUT", "30"))

DAILY_REWARD = int(os.getenv("ECONOMY_DAILY_REWARD", "50"))
WORK_MIN_REWARD = int(os.getenv("ECONOMY_WORK_MIN", "35"))
WORK_MAX_REWARD = int(os.getenv("ECONOMY_WORK_MAX", "120"))
WORK_COOLDOWN_SEC = int(os.getenv("ECONOMY_WORK_COOLDOWN", "3600"))
BJ_MIN_BET = int(os.getenv("BJ_MIN_BET", "10"))
BJ_MAX_BET = int(os.getenv("BJ_MAX_BET", "100000"))
BJ_COMMAND_COOLDOWN = int(os.getenv("BJ_COMMAND_COOLDOWN", "5"))
BJ_VIEW_TIMEOUT = int(os.getenv("BJ_VIEW_TIMEOUT", "300"))

BACK_EMOJI_NAME = os.getenv("BJ_BACK_EMOJI_NAME", "back")
BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID", "745686280146387033"))

SHOP_ITEMS = {
    "coffee": {"name": "Cà phê", "emoji": "☕", "price": 80, "desc": "Tăng tỉnh táo đi farm coin"},
    "lucky_charm": {"name": "Bùa may mắn", "emoji": "🍀", "price": 240, "desc": "Vật phẩm sưu tầm"},
    "energy_drink": {"name": "Nước tăng lực", "emoji": "⚡", "price": 150, "desc": "Nạp pin cho ngày mới"},
    "mystery_box": {"name": "Hộp bí ẩn", "emoji": "🎁", "price": 500, "desc": "Không biết mở ra gì"},
    "golden_ticket": {"name": "Vé vàng", "emoji": "🎫", "price": 950, "desc": "Vật phẩm hiếm để khoe"},
}

SUIT_TO_WORD = {
    "S": "spades",
    "H": "hearts",
    "D": "diamonds",
    "C": "clubs",
}

RANK_TO_WORD = {
    "A": "ace",
    "K": "king",
    "Q": "queen",
    "J": "jack",
    "10": "10",
    "9": "9",
    "8": "8",
    "7": "7",
    "6": "6",
    "5": "5",
    "4": "4",
    "3": "3",
    "2": "2",
}

ALL_RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
ALL_SUITS = ["S", "H", "D", "C"]

BJ_COMMAND_LAST_USED: dict[int, float] = {}
BOT_INSTANCE: Optional[commands.Bot] = None

DB_WRITE_LOCK = asyncio.Lock()


def _open_db():
    return aiosqlite.connect(DB_PATH, timeout=SQLITE_TIMEOUT)


async def _ensure_user_in_conn(conn: aiosqlite.Connection, user_id: int):
    await conn.execute(
        """
        INSERT OR IGNORE INTO economy_users(user_id, balance)
        VALUES (?, 0)
        """,
        (user_id,),
    )


def ensure_db_dir():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)


async def db_init():
    ensure_db_dir()
    async with _open_db() as conn:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute("PRAGMA busy_timeout=5000")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS economy_users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER NOT NULL DEFAULT 0,
                last_daily_ts INTEGER NOT NULL DEFAULT 0,
                last_work_ts INTEGER NOT NULL DEFAULT 0,
                total_earned INTEGER NOT NULL DEFAULT 0,
                total_lost INTEGER NOT NULL DEFAULT 0,
                total_bj_played INTEGER NOT NULL DEFAULT 0,
                total_bj_won INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        try:
            await conn.execute("ALTER TABLE economy_users ADD COLUMN last_work_ts INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS economy_inventory (
                user_id INTEGER NOT NULL,
                item_key TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(user_id, item_key)
            )
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_inventory_user
            ON economy_inventory(user_id)
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_economy_users_balance
            ON economy_users(balance DESC, user_id ASC)
            """
        )
        await conn.commit()


async def ensure_user(user_id: int):
    async with DB_WRITE_LOCK:
        async with _open_db() as conn:
            await _ensure_user_in_conn(conn, user_id)
            await conn.commit()


async def get_balance(user_id: int) -> int:
    async with DB_WRITE_LOCK:
        async with _open_db() as conn:
            await _ensure_user_in_conn(conn, user_id)
            await conn.commit()

            async with conn.execute(
                """
                SELECT balance
                FROM economy_users
                WHERE user_id = ?
                """,
                (user_id,),
            ) as cur:
                row = await cur.fetchone()
                return int(row[0]) if row else 0


async def add_balance(user_id: int, amount: int):
    if amount <= 0:
        return

    async with DB_WRITE_LOCK:
        async with _open_db() as conn:
            await _ensure_user_in_conn(conn, user_id)
            await conn.execute(
                """
                UPDATE economy_users
                SET balance = balance + ?,
                    total_earned = total_earned + ?
                WHERE user_id = ?
                """,
                (amount, amount, user_id),
            )
            await conn.commit()


async def refund_balance(user_id: int, amount: int):
    if amount <= 0:
        return

    async with DB_WRITE_LOCK:
        async with _open_db() as conn:
            await _ensure_user_in_conn(conn, user_id)
            await conn.execute(
                """
                UPDATE economy_users
                SET balance = balance + ?
                WHERE user_id = ?
                """,
                (amount, user_id),
            )
            await conn.commit()


async def remove_balance(user_id: int, amount: int) -> bool:
    if amount <= 0:
        return False

    async with DB_WRITE_LOCK:
        async with _open_db() as conn:
            await conn.execute("SAVEPOINT econ_remove")
            await _ensure_user_in_conn(conn, user_id)

            async with conn.execute(
                """
                SELECT balance
                FROM economy_users
                WHERE user_id = ?
                """,
                (user_id,),
            ) as cur:
                row = await cur.fetchone()
                balance = int(row[0]) if row else 0

            if balance < amount:
                await conn.execute("ROLLBACK TO econ_remove")
                await conn.execute("RELEASE econ_remove")
                return False

            await conn.execute(
                """
                UPDATE economy_users
                SET balance = balance - ?,
                    total_lost = total_lost + ?
                WHERE user_id = ?
                """,
                (amount, amount, user_id),
            )
            await conn.execute("RELEASE econ_remove")
            await conn.commit()
            return True


async def transfer_balance(from_user_id: int, to_user_id: int, amount: int) -> bool:
    if amount <= 0:
        return False

    async with DB_WRITE_LOCK:
        async with _open_db() as conn:
            try:
                await conn.execute("SAVEPOINT econ_transfer")
                await _ensure_user_in_conn(conn, from_user_id)
                await _ensure_user_in_conn(conn, to_user_id)

                async with conn.execute(
                    """
                    SELECT balance
                    FROM economy_users
                    WHERE user_id = ?
                    """,
                    (from_user_id,),
                ) as cur:
                    row = await cur.fetchone()
                    balance = int(row[0]) if row else 0

                if balance < amount:
                    await conn.execute("ROLLBACK TO econ_transfer")
                    await conn.execute("RELEASE econ_transfer")
                    return False

                await conn.execute(
                    """
                    UPDATE economy_users
                    SET balance = balance - ?,
                        total_lost = total_lost + ?
                    WHERE user_id = ?
                    """,
                    (amount, amount, from_user_id),
                )

                await conn.execute(
                    """
                    UPDATE economy_users
                    SET balance = balance + ?,
                        total_earned = total_earned + ?
                    WHERE user_id = ?
                    """,
                    (amount, amount, to_user_id),
                )

                await conn.execute("RELEASE econ_transfer")
                await conn.commit()
                return True

            except Exception as e:
                print(f"transfer_balance error: {e}")
                try:
                    await conn.execute("ROLLBACK TO econ_transfer")
                    await conn.execute("RELEASE econ_transfer")
                except Exception:
                    pass
                await conn.rollback()
                return False


async def claim_daily(user_id: int) -> tuple[bool, int, int]:
    now = int(time.time())

    async with DB_WRITE_LOCK:
        async with _open_db() as conn:
            await conn.execute("SAVEPOINT econ_daily")
            await _ensure_user_in_conn(conn, user_id)

            async with conn.execute(
                """
                SELECT last_daily_ts
                FROM economy_users
                WHERE user_id = ?
                """,
                (user_id,),
            ) as cur:
                row = await cur.fetchone()
                last_daily = int(row[0] or 0) if row else 0

            remain = 86400 - (now - last_daily)
            if last_daily > 0 and remain > 0:
                await conn.execute("ROLLBACK TO econ_daily")
                await conn.execute("RELEASE econ_daily")
                return False, 0, remain

            await conn.execute(
                """
                UPDATE economy_users
                SET balance = balance + ?,
                    total_earned = total_earned + ?,
                    last_daily_ts = ?
                WHERE user_id = ?
                """,
                (DAILY_REWARD, DAILY_REWARD, now, user_id),
            )

            async with conn.execute(
                """
                SELECT balance
                FROM economy_users
                WHERE user_id = ?
                """,
                (user_id,),
            ) as cur:
                row = await cur.fetchone()
                balance = int(row[0]) if row else 0

            await conn.execute("RELEASE econ_daily")
            await conn.commit()
            return True, balance, 0


async def claim_work(user_id: int) -> tuple[bool, int, int, int]:
    now = int(time.time())

    async with DB_WRITE_LOCK:
        async with _open_db() as conn:
            await conn.execute("SAVEPOINT econ_work")
            await _ensure_user_in_conn(conn, user_id)

            async with conn.execute(
                """
                SELECT last_work_ts
                FROM economy_users
                WHERE user_id = ?
                """,
                (user_id,),
            ) as cur:
                row = await cur.fetchone()
                last_work = int(row[0] or 0) if row else 0

            remain = WORK_COOLDOWN_SEC - (now - last_work)
            if last_work > 0 and remain > 0:
                await conn.execute("ROLLBACK TO econ_work")
                await conn.execute("RELEASE econ_work")
                return False, 0, 0, remain

            reward_min = max(1, WORK_MIN_REWARD)
            reward_max = max(reward_min, WORK_MAX_REWARD)
            reward = random.randint(reward_min, reward_max)

            await conn.execute(
                """
                UPDATE economy_users
                SET balance = balance + ?,
                    total_earned = total_earned + ?,
                    last_work_ts = ?
                WHERE user_id = ?
                """,
                (reward, reward, now, user_id),
            )

            async with conn.execute(
                """
                SELECT balance
                FROM economy_users
                WHERE user_id = ?
                """,
                (user_id,),
            ) as cur:
                row = await cur.fetchone()
                balance = int(row[0]) if row else 0

            await conn.execute("RELEASE econ_work")
            await conn.commit()
            return True, reward, balance, 0


async def record_bj_result(user_id: int, won: bool):
    async with DB_WRITE_LOCK:
        async with _open_db() as conn:
            await _ensure_user_in_conn(conn, user_id)
            await conn.execute(
                """
                UPDATE economy_users
                SET total_bj_played = total_bj_played + 1,
                    total_bj_won = total_bj_won + ?
                WHERE user_id = ?
                """,
                (1 if won else 0, user_id),
            )
            await conn.commit()


async def get_top_balances(limit: int = 10):
    async with _open_db() as conn:
        async with conn.execute(
            """
            SELECT user_id, balance
            FROM economy_users
            ORDER BY balance DESC, user_id ASC
            LIMIT ?
            """,
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
            return rows


async def buy_item(user_id: int, item_key: str, quantity: int) -> tuple[bool, str | None, int]:
    if quantity <= 0:
        return False, "Số lượng phải lớn hơn 0.", 0

    item = SHOP_ITEMS.get(item_key)
    if item is None:
        return False, "Vật phẩm không tồn tại.", 0

    total_price = int(item["price"]) * quantity

    async with DB_WRITE_LOCK:
        async with _open_db() as conn:
            await conn.execute("SAVEPOINT econ_buy")
            await _ensure_user_in_conn(conn, user_id)

            async with conn.execute(
                "SELECT balance FROM economy_users WHERE user_id = ?",
                (user_id,),
            ) as cur:
                row = await cur.fetchone()
                bal = int(row[0]) if row else 0

            if bal < total_price:
                await conn.execute("ROLLBACK TO econ_buy")
                await conn.execute("RELEASE econ_buy")
                return False, "Không đủ coin để mua.", bal

            await conn.execute(
                """
                UPDATE economy_users
                SET balance = balance - ?,
                    total_lost = total_lost + ?
                WHERE user_id = ?
                """,
                (total_price, total_price, user_id),
            )

            await conn.execute(
                """
                INSERT INTO economy_inventory(user_id, item_key, quantity)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, item_key)
                DO UPDATE SET quantity = quantity + excluded.quantity
                """,
                (user_id, item_key, quantity),
            )

            async with conn.execute(
                "SELECT balance FROM economy_users WHERE user_id = ?",
                (user_id,),
            ) as cur:
                row = await cur.fetchone()
                new_balance = int(row[0]) if row else 0

            await conn.execute("RELEASE econ_buy")
            await conn.commit()
            return True, None, new_balance


async def get_inventory(user_id: int):
    async with _open_db() as conn:
        await _ensure_user_in_conn(conn, user_id)
        await conn.commit()
        async with conn.execute(
            """
            SELECT item_key, quantity
            FROM economy_inventory
            WHERE user_id = ? AND quantity > 0
            ORDER BY quantity DESC, item_key ASC
            """,
            (user_id,),
        ) as cur:
            return await cur.fetchall()


async def autocomplete_shop_item(_: discord.Interaction, current: str):
    q = current.lower().strip()
    out: list[app_commands.Choice[str]] = []
    for key, data in SHOP_ITEMS.items():
        label = f"{data['emoji']} {data['name']} ({data['price']} 🪙)"
        hay = f"{key} {data['name']}".lower()
        if q and q not in hay:
            continue
        out.append(app_commands.Choice(name=label[:100], value=key))
    return out[:25]


def build_deck() -> list[str]:
    deck = [f"{rank}{suit}" for suit in ALL_SUITS for rank in ALL_RANKS]
    random.shuffle(deck)
    return deck


def draw_card(deck: list[str]) -> str:
    if not deck:
        deck.extend(build_deck())
    return deck.pop()


def card_value(card: str) -> int:
    rank = card[:-1]
    if rank in ("J", "Q", "K"):
        return 10
    if rank == "A":
        return 11
    return int(rank)


def hand_value(hand: list[str]) -> int:
    total = 0
    aces = 0

    for card in hand:
        rank = card[:-1]
        if rank == "A":
            aces += 1
            total += 11
        elif rank in ("J", "Q", "K"):
            total += 10
        else:
            total += int(rank)

    while total > 21 and aces > 0:
        total -= 10
        aces -= 1

    return total


def is_blackjack(hand: list[str]) -> bool:
    return len(hand) == 2 and hand_value(hand) == 21


def rank_display(card: str) -> str:
    return card[:-1]


def suit_display(card: str) -> str:
    suit = card[-1]
    return {
        "S": "♠",
        "H": "♥",
        "D": "♦",
        "C": "♣",
    }.get(suit, "?")


def dealer_visible_value(hand: list[str]) -> str:
    if not hand:
        return "?"
    return f"{card_value(hand[0])} + ?"


def card_to_emoji_name(card: str) -> str:
    rank = card[:-1]
    suit = card[-1]
    return f"{RANK_TO_WORD[rank]}_of_{SUIT_TO_WORD[suit]}"


def find_emoji_by_name(name: str) -> Optional[discord.Emoji]:
    if BOT_INSTANCE is None:
        return None

    for emoji in BOT_INSTANCE.emojis:
        if emoji.name == name:
            return emoji
    return None


def emoji_or_fallback(name: str, fallback: str) -> str:
    emoji = find_emoji_by_name(name)
    return str(emoji) if emoji else fallback


def card_to_emoji(card: str) -> str:
    name = card_to_emoji_name(card)
    fallback = f"`{rank_display(card)}{suit_display(card)}`"
    return emoji_or_fallback(name, fallback)


def back_emoji() -> str:
    return emoji_or_fallback(BACK_EMOJI_NAME, "`[ÚP]`")


def hand_to_emojis(hand: list[str], hide_after_first: bool = False) -> str:
    parts = []
    for i, card in enumerate(hand):
        if hide_after_first and i >= 1:
            parts.append(back_emoji())
        else:
            parts.append(card_to_emoji(card))
    return " ".join(parts) if parts else "-"


@dataclass
class BlackjackGame:
    user_id: int
    channel_id: int
    bet: int
    original_bet: int
    player_hand: list[str]
    dealer_hand: list[str]
    deck: list[str]
    doubled: bool = False
    finished: bool = False
    result: Optional[str] = None
    payout: int = 0
    created_at: float = field(default_factory=time.time)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    message_id: Optional[int] = None


ACTIVE_GAMES_BY_USER: dict[int, BlackjackGame] = {}
ACTIVE_GAMES_BY_MESSAGE: dict[int, BlackjackGame] = {}


def register_game(game: BlackjackGame):
    ACTIVE_GAMES_BY_USER[game.user_id] = game
    if game.message_id is not None:
        ACTIVE_GAMES_BY_MESSAGE[game.message_id] = game


def unregister_game(game: BlackjackGame):
    ACTIVE_GAMES_BY_USER.pop(game.user_id, None)
    if game.message_id is not None:
        ACTIVE_GAMES_BY_MESSAGE.pop(game.message_id, None)


def has_active_game(user_id: int) -> bool:
    game = ACTIVE_GAMES_BY_USER.get(user_id)
    return game is not None and not game.finished


def format_seconds(sec: int) -> str:
    sec = max(0, int(sec))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def dealer_play(game: BlackjackGame):
    while hand_value(game.dealer_hand) < 16:
        game.dealer_hand.append(draw_card(game.deck))


async def resolve_blackjack(game: BlackjackGame):
    if game.finished:
        return

    player_total = hand_value(game.player_hand)
    dealer_total = hand_value(game.dealer_hand)
    natural_blackjack = is_blackjack(game.player_hand)

    player_bust = player_total > 21
    dealer_bust = dealer_total > 21

    if player_bust:
        if dealer_bust:
            game.result = "push"
            game.payout = game.bet
            await refund_balance(game.user_id, game.bet)
            await record_bj_result(game.user_id, won=False)
        else:
            game.result = "bust"
            game.payout = 0
            await record_bj_result(game.user_id, won=False)

        game.finished = True
        return

    if dealer_bust:
        if natural_blackjack:
            game.result = "blackjack"
            game.payout = int(game.bet * 2.5)
        else:
            game.result = "win"
            game.payout = game.bet * 2

        await add_balance(game.user_id, game.payout)
        await record_bj_result(game.user_id, won=True)

    elif natural_blackjack and dealer_total != 21:
        game.result = "blackjack"
        game.payout = int(game.bet * 2.5)
        await add_balance(game.user_id, game.payout)
        await record_bj_result(game.user_id, won=True)

    elif player_total > dealer_total:
        game.result = "win"
        game.payout = game.bet * 2
        await add_balance(game.user_id, game.payout)
        await record_bj_result(game.user_id, won=True)

    elif player_total < dealer_total:
        game.result = "lose"
        game.payout = 0
        await record_bj_result(game.user_id, won=False)

    else:
        game.result = "push"
        game.payout = game.bet
        await refund_balance(game.user_id, game.bet)
        await record_bj_result(game.user_id, won=False)

    game.finished = True


async def build_blackjack_embed(
    user: discord.abc.User,
    game: BlackjackGame,
    reveal_dealer: bool,
) -> discord.Embed:
    player_total = hand_value(game.player_hand)

    if reveal_dealer:
        dealer_label = str(hand_value(game.dealer_hand))
    else:
        dealer_label = dealer_visible_value(game.dealer_hand)

    if not game.finished:
        color = discord.Color.orange()
    elif game.result in ("win", "blackjack"):
        color = discord.Color.green()
    elif game.result in ("push", "timeout"):
        color = discord.Color.gold()
    else:
        color = discord.Color.red()

    player_status = ""
    if game.finished:
        if game.result == "bust":
            player_status = " • Quắc"
        elif game.result == "blackjack":
            player_status = " • Xì dách"
        elif game.result == "win":
            player_status = " • Thắng"
        elif game.result == "push":
            player_status = " • Hòa"
        elif game.result == "timeout":
            player_status = " • Hủy ván"
        elif game.result == "lose":
            player_status = " • Thua"

    lines = []
    lines.append("## 🃏 BlackJack")
    lines.append("")
    lines.append(f"**Bạn | {player_total}{player_status}**")
    lines.append(hand_to_emojis(game.player_hand))
    lines.append("")
    lines.append(f"**Nhà cái | {dealer_label}**")
    lines.append(hand_to_emojis(game.dealer_hand, hide_after_first=not reveal_dealer))
    lines.append("")
    lines.append(f"**Tiền cược:** `{game.bet}` 🪙")

    if game.doubled:
        lines.append("**Gấp đôi:** `Có`")

    if game.finished:
        balance_now = await get_balance(game.user_id)

        if game.result == "blackjack":
            net = game.payout - game.bet
            lines.append("")
            lines.append("### ✨ Xì dách!")
            lines.append(f"Bạn thắng **{net}** 🪙")
            lines.append(f"Số dư hiện tại: **{balance_now}** 🪙")

        elif game.result == "win":
            net = game.payout - game.bet
            lines.append("")
            lines.append("### 🎉 Bạn thắng")
            lines.append(f"Bạn nhận được **{net}** 🪙")
            lines.append(f"Số dư hiện tại: **{balance_now}** 🪙")

        elif game.result == "push":
            lines.append("")
            lines.append("### 🤝 Hòa")
            lines.append("Hai bên hòa nhau, tiền cược đã được hoàn lại.")
            lines.append(f"Số dư hiện tại: **{balance_now}** 🪙")

        elif game.result == "timeout":
            lines.append("")
            lines.append("### ⏰ Hết thời gian")
            lines.append("Ván bài đã bị hủy do không có thao tác.")
            lines.append(f"Tiền cược **{game.bet}** 🪙 đã được hoàn lại.")
            lines.append(f"Số dư hiện tại: **{balance_now}** 🪙")

        elif game.result == "bust":
            lines.append("")
            lines.append("### 💥 Quắc")
            lines.append(f"Bạn đã thua **{game.bet}** 🪙")
            lines.append(f"Số dư hiện tại: **{balance_now}** 🪙")

        else:
            lines.append("")
            lines.append("### ❌ Bạn thua")
            lines.append(f"Bạn đã thua **{game.bet}** 🪙")
            lines.append(f"Số dư hiện tại: **{balance_now}** 🪙")
    else:
        lines.append("")
        lines.append("### 🎮 Hành động")
        lines.append("- **Rút** để lấy thêm 1 lá")
        lines.append("- **Dằn** để nhà cái rút bài")
        lines.append("- **Gấp đôi** để cược thêm và rút đúng 1 lá")

    embed = discord.Embed(
        description="\n".join(lines),
        color=color,
    )
    embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)

    foot_text = (
        f"User ID: {game.user_id} | "
        f"Game created at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(game.created_at))}"
    )
    embed.set_footer(text=foot_text)

    return embed


class BlackjackView(discord.ui.View):
    def __init__(self, bot: commands.Bot, game: BlackjackGame):
        super().__init__(timeout=BJ_VIEW_TIMEOUT)
        self.bot = bot
        self.game = game

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.game.user_id:
            await interaction.response.send_message("❌ Đây không phải ván của bạn.", ephemeral=True)
            return False
        return True

    async def disable_all(self):
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    async def finish_and_edit(self, interaction: discord.Interaction):
        await self.disable_all()
        embed = await build_blackjack_embed(interaction.user, self.game, reveal_dealer=True)
        await interaction.response.edit_message(embed=embed, view=self)
        unregister_game(self.game)
        self.stop()

    @discord.ui.button(label="Rút", style=discord.ButtonStyle.success, emoji="🟩")
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with self.game.lock:
            if self.game.finished:
                return await interaction.response.send_message("Ván này đã kết thúc.", ephemeral=True)

            self.game.player_hand.append(draw_card(self.game.deck))

            if hand_value(self.game.player_hand) > 21:
                dealer_play(self.game)
                await resolve_blackjack(self.game)
                return await self.finish_and_edit(interaction)

            embed = await build_blackjack_embed(interaction.user, self.game, reveal_dealer=False)
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Dằn", style=discord.ButtonStyle.danger, emoji="🛑")
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with self.game.lock:
            if self.game.finished:
                return await interaction.response.send_message("Ván này đã kết thúc.", ephemeral=True)

            dealer_play(self.game)
            await resolve_blackjack(self.game)
            return await self.finish_and_edit(interaction)

    @discord.ui.button(label="Gấp đôi", style=discord.ButtonStyle.secondary, emoji="💥")
    async def double_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with self.game.lock:
            if self.game.finished:
                return await interaction.response.send_message("Ván này đã kết thúc.", ephemeral=True)

            if self.game.doubled:
                return await interaction.response.send_message("❌ Bạn đã gấp đôi rồi.", ephemeral=True)

            if len(self.game.player_hand) != 2:
                return await interaction.response.send_message(
                    "❌ Chỉ được gấp đôi khi đang có đúng 2 lá.",
                    ephemeral=True,
                )

            if not await remove_balance(self.game.user_id, self.game.original_bet):
                return await interaction.response.send_message(
                    "❌ Bạn không đủ tiền để gấp đôi.",
                    ephemeral=True,
                )

            self.game.bet += self.game.original_bet
            self.game.doubled = True
            self.game.player_hand.append(draw_card(self.game.deck))

            dealer_play(self.game)
            await resolve_blackjack(self.game)
            return await self.finish_and_edit(interaction)

    async def on_timeout(self):
        async with self.game.lock:
            if self.game.finished:
                return

            self.game.finished = True
            self.game.result = "timeout"
            self.game.payout = self.game.bet

            await refund_balance(self.game.user_id, self.game.bet)
            await self.disable_all()

            try:
                channel = self.bot.get_channel(self.game.channel_id)
                if channel is None:
                    unregister_game(self.game)
                    self.stop()
                    return

                if self.game.message_id is None:
                    unregister_game(self.game)
                    self.stop()
                    return

                message = await channel.fetch_message(self.game.message_id)
                user = self.bot.get_user(self.game.user_id)
                if user is None:
                    user = await self.bot.fetch_user(self.game.user_id)

                embed = await build_blackjack_embed(user, self.game, reveal_dealer=True)
                await message.edit(embed=embed, view=self)
            except Exception as e:
                print(f"blackjack timeout edit error: {e}")

            unregister_game(self.game)
            self.stop()


async def setup_economy(bot: commands.Bot):
    global BOT_INSTANCE
    BOT_INSTANCE = bot
    await db_init()

    economy_group = app_commands.Group(name="economy", description="Các lệnh economy")

    @economy_group.command(name="balance", description="Xem số dư của bạn")
    async def balance(interaction: discord.Interaction):
        bal = await get_balance(interaction.user.id)
        await interaction.response.send_message(
            f"💰 {interaction.user.mention} hiện có **{bal}** 🪙",
            ephemeral=True,
        )

    @economy_group.command(name="daily", description="Nhận thưởng hằng ngày")
    async def daily(interaction: discord.Interaction):
        ok, balance_now, remain = await claim_daily(interaction.user.id)
        if not ok:
            return await interaction.response.send_message(
                f"⏳ Bạn đã nhận daily rồi. Quay lại sau **{format_seconds(remain)}**.",
                ephemeral=True,
            )

        await interaction.response.send_message(
            f"🎁 {interaction.user.mention} nhận được **{DAILY_REWARD}** 🪙 từ daily.\n"
            f"Bạn hiện có: **{balance_now}** 🪙"
        )

    @economy_group.command(name="work", description="Đi làm để kiếm coin")
    async def work(interaction: discord.Interaction):
        ok, reward, balance_now, remain = await claim_work(interaction.user.id)
        if not ok:
            return await interaction.response.send_message(
                f"⏳ Bạn vừa đi làm xong. Quay lại sau **{format_seconds(remain)}**.",
                ephemeral=True,
            )

        await interaction.response.send_message(
            f"💼 {interaction.user.mention} đi làm nhận **{reward}** 🪙\n"
            f"Số dư hiện tại: **{balance_now}** 🪙"
        )

    @economy_group.command(name="shop", description="Xem cửa hàng vật phẩm")
    async def shop(interaction: discord.Interaction):
        lines = []
        for key, data in SHOP_ITEMS.items():
            lines.append(
                f"`{key}` • {data['emoji']} **{data['name']}** — **{data['price']}** 🪙\n{data['desc']}"
            )

        e = discord.Embed(
            title="🛒 Economy Shop",
            description="\n\n".join(lines),
            color=discord.Color.blurple(),
        )
        e.set_footer(text="Dùng /economy buy item:<id> quantity:<số lượng>")
        await interaction.response.send_message(embed=e)

    @economy_group.command(name="buy", description="Mua vật phẩm trong shop")
    @app_commands.describe(item="Mã vật phẩm trong /shop", quantity="Số lượng muốn mua")
    @app_commands.autocomplete(item=autocomplete_shop_item)
    async def buy(interaction: discord.Interaction, item: str, quantity: int = 1):
        ok, err, balance_now = await buy_item(interaction.user.id, item, quantity)
        if not ok:
            return await interaction.response.send_message(f"❌ {err}", ephemeral=True)

        data = SHOP_ITEMS[item]
        total = int(data["price"]) * quantity
        await interaction.response.send_message(
            f"✅ Đã mua {data['emoji']} **{data['name']}** x{quantity} với giá **{total}** 🪙\n"
            f"Số dư còn lại: **{balance_now}** 🪙"
        )

    @economy_group.command(name="inventory", description="Xem kho đồ của bạn hoặc member")
    @app_commands.describe(member="Member muốn xem inventory")
    async def inventory(interaction: discord.Interaction, member: discord.Member | None = None):
        target = member or (interaction.user if isinstance(interaction.user, discord.Member) else None)
        if target is None:
            return await interaction.response.send_message("❌ Không xác định được người dùng.", ephemeral=True)

        rows = await get_inventory(target.id)
        if not rows:
            return await interaction.response.send_message(
                f"🎒 {target.mention} chưa có vật phẩm nào.",
                ephemeral=(target.id == interaction.user.id),
            )

        lines = []
        for item_key, qty in rows:
            data = SHOP_ITEMS.get(item_key, {"emoji": "📦", "name": item_key})
            lines.append(f"{data['emoji']} **{data['name']}** x{qty}")

        e = discord.Embed(
            title=f"🎒 Inventory - {target.display_name}",
            description="\n".join(lines),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=e)

    @economy_group.command(name="give", description="Chuyển coin cho người khác")
    @app_commands.describe(member="Người nhận", amount="Số coin muốn chuyển")
    async def give(interaction: discord.Interaction, member: discord.Member, amount: int):
        if member.bot:
            return await interaction.response.send_message("❌ Không thể chuyển coin cho bot.", ephemeral=True)

        if member.id == interaction.user.id:
            return await interaction.response.send_message("❌ Không thể tự chuyển coin cho chính mình.", ephemeral=True)

        if amount <= 0:
            return await interaction.response.send_message("❌ Số coin phải lớn hơn 0.", ephemeral=True)

        success = await transfer_balance(interaction.user.id, member.id, amount)
        if not success:
            return await interaction.response.send_message("❌ Bạn không đủ coin.", ephemeral=True)

        sender_balance = await get_balance(interaction.user.id)
        await interaction.response.send_message(
            f"💸 {interaction.user.mention} đã chuyển **{amount}** 🪙 cho {member.mention}.\n"
            f"Số dư còn lại: **{sender_balance}** 🪙"
        )

    @economy_group.command(name="leaderboard", description="Xem top coin toàn bộ bot")
    async def leaderboard(interaction: discord.Interaction):
        rows = await get_top_balances(limit=10)
        if not rows:
            return await interaction.response.send_message("Chưa có dữ liệu.", ephemeral=True)

        lines = []
        for idx, (user_id, balance_value) in enumerate(rows, start=1):
            user = bot.get_user(user_id)
            name = user.display_name if user else f"<@{user_id}>"
            lines.append(f"**{idx}.** {name} — **{balance_value}** 🪙")

        embed = discord.Embed(
            title="🏆 Global Coin Leaderboard",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed)

    @economy_group.command(name="blackjack", description="Chơi blackjack cược coin")
    @app_commands.describe(bet="Số coin muốn cược")
    async def blackjack(interaction: discord.Interaction, bet: int):
        if interaction.guild is None:
            return await interaction.response.send_message("❌ Chỉ dùng trong server.", ephemeral=True)

        if bet < BJ_MIN_BET:
            return await interaction.response.send_message(
                f"❌ Cược tối thiểu là **{BJ_MIN_BET}** 🪙",
                ephemeral=True,
            )

        if bet > BJ_MAX_BET:
            return await interaction.response.send_message(
                f"❌ Cược tối đa là **{BJ_MAX_BET}** 🪙",
                ephemeral=True,
            )

        if has_active_game(interaction.user.id):
            return await interaction.response.send_message(
                "❌ Bạn đang có một ván blackjack chưa kết thúc.",
                ephemeral=True,
            )

        now = time.time()
        last_used = BJ_COMMAND_LAST_USED.get(interaction.user.id, 0.0)
        remain = BJ_COMMAND_COOLDOWN - (now - last_used)
        if remain > 0:
            return await interaction.response.send_message(
                f"⏳ Hãy đợi **{remain:.1f}s** rồi chơi tiếp.",
                ephemeral=True,
            )

        balance_now = await get_balance(interaction.user.id)
        if balance_now < bet:
            return await interaction.response.send_message(
                f"❌ Bạn không đủ coin. Số dư hiện tại: **{balance_now}** 🪙",
                ephemeral=True,
            )

        if not await remove_balance(interaction.user.id, bet):
            return await interaction.response.send_message("❌ Không thể trừ tiền cược.", ephemeral=True)

        BJ_COMMAND_LAST_USED[interaction.user.id] = now

        deck = build_deck()
        player_hand = [draw_card(deck), draw_card(deck)]
        dealer_hand = [draw_card(deck), draw_card(deck)]

        game = BlackjackGame(
            user_id=interaction.user.id,
            channel_id=interaction.channel_id,
            bet=bet,
            original_bet=bet,
            player_hand=player_hand,
            dealer_hand=dealer_hand,
            deck=deck,
        )

        register_game(game)

        if is_blackjack(player_hand):
            dealer_play(game)
            await resolve_blackjack(game)
            embed = await build_blackjack_embed(interaction.user, game, reveal_dealer=True)
            unregister_game(game)
            return await interaction.response.send_message(embed=embed)

        view = BlackjackView(bot, game)
        embed = await build_blackjack_embed(interaction.user, game, reveal_dealer=False)
        await interaction.response.send_message(embed=embed, view=view)

        msg = await interaction.original_response()
        game.message_id = msg.id
        ACTIVE_GAMES_BY_MESSAGE[msg.id] = game

    @economy_group.command(name="addcoins", description="Thêm coin cho một người (chỉ chủ bot)")
    @app_commands.describe(member="Người nhận", amount="Số coin muốn thêm")
    async def addcoins(interaction: discord.Interaction, member: discord.Member, amount: int):
        if interaction.user.id != BOT_OWNER_ID:
            return await interaction.response.send_message(
                "❌ Chỉ chủ bot mới dùng được lệnh này.",
                ephemeral=True,
            )

        if amount <= 0:
            return await interaction.response.send_message("❌ Số coin phải lớn hơn 0.", ephemeral=True)

        if member.bot:
            return await interaction.response.send_message("❌ Không thể thêm coin cho bot.", ephemeral=True)

        await add_balance(member.id, amount)
        balance_now = await get_balance(member.id)

        await interaction.response.send_message(
            f"✅ Đã thêm **{amount}** 🪙 cho {member.mention}.\n"
            f"Số dư hiện tại của {member.mention}: **{balance_now}** 🪙"
        )

    bot.tree.add_command(economy_group)
