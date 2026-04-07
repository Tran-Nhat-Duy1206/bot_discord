import random
import time
from dataclasses import dataclass, field
from typing import Optional

from ..data import ITEMS, CRAFT_RECIPES

from ..repositories import player_repo, inventory_repo, telemetry_repo, quest_repo
from ..shop import get_sell_price
from .base import BaseService


RPG_LOOTBOX_DAILY_LIMIT = 25


def _is_vi(lang: str) -> bool:
    return str(lang).lower().startswith("vi")


@dataclass
class LootboxResult:
    ok: bool = False
    total_gold: int = 0
    bonus_items: list = field(default_factory=list)
    remaining_opens: int = 0
    message: str = ""


@dataclass
class CraftResult:
    ok: bool = False
    message: str = ""
    recipe_id: str = ""
    amount: int = 0


@dataclass
class DailyResult:
    ok: bool = False
    new_balance: int = 0
    reward_gold: int = 120
    message: str = ""


@dataclass
class TransferResult:
    ok: bool = False
    amount: int = 0
    message: str = ""


class EconomyService(BaseService):
    @staticmethod
    async def get_balance(guild_id: int, user_id: int) -> int:
        async with BaseService.with_user_transaction(guild_id, user_id, "get_balance") as conn:
            _, gold = await player_repo.get_player_level_gold(conn, guild_id, user_id)
        return gold

    @staticmethod
    async def claim_daily(guild_id: int, user_id: int, lang: str = "en") -> DailyResult:
        async with BaseService.with_user_transaction(guild_id, user_id, "daily") as conn:
            await player_repo.ensure_player_ready(conn, guild_id, user_id)
            
            from ..db.db import cooldown_remain
            remain = await cooldown_remain(conn, guild_id, user_id, "daily")
            if remain > 0:
                from ..db.db import fmt_secs
                msg = f"⏳ Daily cooldown: **{fmt_secs(remain)}**"
                if _is_vi(lang):
                    msg = f"⏳ Daily đang cooldown: **{fmt_secs(remain)}**"
                return DailyResult(ok=False, message=msg)

            reward = 120
            await player_repo.add_gold(conn, guild_id, user_id, reward)
            await telemetry_repo.record_gold_flow(conn, guild_id, user_id, reward, "daily_reward")
            await telemetry_repo.set_cooldown(conn, guild_id, user_id, "daily", 86400)
            await conn.commit()

            _, new_balance = await player_repo.get_player_level_gold(conn, guild_id, user_id)
            
            return DailyResult(
                ok=True,
                new_balance=new_balance,
                reward_gold=reward,
                message=(
                    f"🎁 Nhận **{reward}** gold. Số dư: **{new_balance}**"
                    if _is_vi(lang)
                    else f"🎁 Claimed **{reward}** gold. Balance: **{new_balance}**"
                ),
            )

    @staticmethod
    async def buy_item(guild_id: int, user_id: int, item_id: str, amount: int = 1, lang: str = "en") -> tuple[bool, str]:
        async with BaseService.with_user_transaction(guild_id, user_id, "buy") as conn:
            await player_repo.ensure_player_ready(conn, guild_id, user_id)
            
            data = ITEMS.get(item_id)
            if not data or int(data["buy"]) <= 0:
                return False, ("Item không thể mua." if _is_vi(lang) else "Item cannot be purchased.")

            total = int(data["buy"]) * amount
            ok = await player_repo.subtract_gold(conn, guild_id, user_id, total)
            if not ok:
                return False, ("Không đủ vàng." if _is_vi(lang) else "Not enough gold.")

            await inventory_repo.add_inventory(conn, guild_id, user_id, item_id, amount)
            await telemetry_repo.record_gold_flow(conn, guild_id, user_id, -total, "shop_buy")
            await conn.commit()

            if _is_vi(lang):
                return True, f"✅ Đã mua {data['emoji']} **{data['name']}** x{amount} với giá **{total}** gold."
            return True, f"✅ Purchased {data['emoji']} **{data['name']}** x{amount} for **{total}** gold."

    @staticmethod
    async def sell_item(guild_id: int, user_id: int, item_id: str, amount: int = 1, black_market: bool = False, lang: str = "en") -> tuple[bool, str, int]:
        async with BaseService.with_user_transaction(guild_id, user_id, "sell") as conn:
            await player_repo.ensure_player_ready(conn, guild_id, user_id)
            
            data = ITEMS.get(item_id)
            if not data:
                return False, ("Item không tồn tại." if _is_vi(lang) else "Item does not exist."), 0

            sell_price = get_sell_price(item_id, black_market=black_market)
            if sell_price <= 0:
                if _is_vi(lang):
                    location = "chợ đen" if black_market else "shop"
                    return False, f"Item này không thể bán ở {location}.", 0
                location = "black market" if black_market else "shop"
                return False, f"This item cannot be sold in {location}.", 0

            ok = await inventory_repo.remove_inventory(conn, guild_id, user_id, item_id, amount)
            if not ok:
                return False, ("Bạn không đủ item để bán." if _is_vi(lang) else "You don't have enough items to sell."), 0

            total = sell_price * amount
            await player_repo.add_gold(conn, guild_id, user_id, total)
            await telemetry_repo.record_gold_flow(conn, guild_id, user_id, total, "shop_sell" if not black_market else "blackmarket_sell")
            await conn.commit()

            if _is_vi(lang):
                location_label = "🌑 chợ đen" if black_market else "shop"
                return True, f"💰 Đã bán **{data['name']}** x{amount}, nhận **{total}** gold ({location_label}).", total
            location_label = "🌑 black market" if black_market else "shop"
            return True, f"💰 Sold **{data['name']}** x{amount}, received **{total}** gold ({location_label}).", total

    @staticmethod
    async def craft_item(guild_id: int, user_id: int, recipe_id: str, amount: int = 1, lang: str = "en") -> CraftResult:
        if amount <= 0:
            return CraftResult(ok=False, message=("Amount phải > 0." if _is_vi(lang) else "Amount must be > 0."))

        recipe = next((r for r in CRAFT_RECIPES if str(r.get("id")) == recipe_id), None)
        if not recipe:
            msg = f"Recipe `{recipe_id}` không tồn tại." if _is_vi(lang) else f"Recipe `{recipe_id}` does not exist."
            return CraftResult(ok=False, message=msg)

        async with BaseService.with_user_transaction(guild_id, user_id, "craft") as conn:
            await player_repo.ensure_player_ready(conn, guild_id, user_id)
            
            cost_gold = int(recipe.get("gold", 0)) * amount
            requires = recipe.get("requires", {}) or {}
            output = recipe.get("output", {}) or {}

            ok = await player_repo.subtract_gold(conn, guild_id, user_id, cost_gold)
            if not ok:
                return CraftResult(ok=False, message=("Không đủ gold để craft." if _is_vi(lang) else "Not enough gold to craft."))

            consumed: list[tuple[str, int]] = []
            for item_id, req in requires.items():
                need = int(req) * amount
                item_ok = await inventory_repo.remove_inventory(conn, guild_id, user_id, str(item_id), need)
                if not item_ok:
                    for rollback_item, rollback_qty in consumed:
                        await inventory_repo.add_inventory(conn, guild_id, user_id, rollback_item, rollback_qty)
                    msg = f"Thiếu nguyên liệu: `{item_id}` x{need}" if _is_vi(lang) else f"Missing materials: `{item_id}` x{need}"
                    return CraftResult(ok=False, message=msg)
                consumed.append((str(item_id), need))

            for item_id, qty in output.items():
                give = int(qty) * amount
                await inventory_repo.add_inventory(conn, guild_id, user_id, str(item_id), give)

            if cost_gold > 0:
                await telemetry_repo.record_gold_flow(conn, guild_id, user_id, -cost_gold, "craft_cost")
            await conn.commit()

            return CraftResult(
                ok=True,
                message=(
                    f"✅ Craft thành công `{recipe_id}` x{amount}."
                    if _is_vi(lang)
                    else f"✅ Crafted `{recipe_id}` x{amount} successfully."
                ),
                recipe_id=recipe_id,
                amount=amount,
            )

    @staticmethod
    async def open_lootbox(guild_id: int, user_id: int, amount: int = 1, lang: str = "en") -> LootboxResult:
        if amount <= 0:
            return LootboxResult(ok=False, message=("Amount phải > 0." if _is_vi(lang) else "Amount must be > 0."))

        async with BaseService.with_user_transaction(guild_id, user_id, "open_lootbox") as conn:
            await player_repo.ensure_player_ready(conn, guild_id, user_id)
            
            ok = await inventory_repo.remove_inventory(conn, guild_id, user_id, "lootbox", amount)
            if not ok:
                return LootboxResult(ok=False, message=("Bạn không đủ lootbox." if _is_vi(lang) else "You don't have enough lootboxes."))

            allowed, remain_after = await telemetry_repo.consume_lootbox_limit(
                conn, guild_id, user_id, amount, RPG_LOOTBOX_DAILY_LIMIT
            )
            if not allowed:
                await inventory_repo.add_inventory(conn, guild_id, user_id, "lootbox", amount)
                return LootboxResult(
                    ok=False,
                    message=(
                        f"Đã chạm limit mở lootbox trong ngày. Còn mở được: **{remain_after}**/{RPG_LOOTBOX_DAILY_LIMIT}"
                        if _is_vi(lang)
                        else f"Daily lootbox limit reached. Remaining opens: **{remain_after}**/{RPG_LOOTBOX_DAILY_LIMIT}"
                    ),
                )

            total_gold = 0
            bonus_items: list[str] = []
            for _ in range(amount):
                roll = random.random()
                if roll < 0.58:
                    total_gold += random.randint(45, 140)
                elif roll < 0.88:
                    await inventory_repo.add_inventory(conn, guild_id, user_id, "potion", 1)
                    bonus_items.append("🧪 Potion")
                elif roll < 0.98:
                    await inventory_repo.add_inventory(conn, guild_id, user_id, "rare_crystal", 1)
                    bonus_items.append("💎 Rare Crystal")
                else:
                    await inventory_repo.add_inventory(conn, guild_id, user_id, "lucky_ring", 1)
                    bonus_items.append("💍 Lucky Ring")

            if total_gold > 0:
                await player_repo.add_gold(conn, guild_id, user_id, total_gold)
                await telemetry_repo.record_gold_flow(conn, guild_id, user_id, total_gold, "lootbox_open")

            await quest_repo.add_quest_progress(conn, guild_id, user_id, "open_lootbox", amount)

            await conn.commit()

            msg = f"🎁 Mở lootbox x{amount}: +{total_gold} gold" if _is_vi(lang) else f"🎁 Opened lootbox x{amount}: +{total_gold} gold"
            if bonus_items:
                msg += "\n" + "\n".join(f"- {x}" for x in bonus_items)
            msg += (
                f"\nDaily limit còn lại: **{remain_after}**/{RPG_LOOTBOX_DAILY_LIMIT}"
                if _is_vi(lang)
                else f"\nDaily remaining: **{remain_after}**/{RPG_LOOTBOX_DAILY_LIMIT}"
            )

            return LootboxResult(
                ok=True,
                total_gold=total_gold,
                bonus_items=bonus_items,
                remaining_opens=remain_after,
                message=msg,
            )

    @staticmethod
    async def transfer_gold(
        guild_id: int,
        sender_id: int,
        receiver_id: int,
        amount: int,
        lang: str = "en",
    ) -> TransferResult:
        if amount <= 0:
            return TransferResult(ok=False, message=("Amount phải > 0." if _is_vi(lang) else "Amount must be > 0."))
        if sender_id == receiver_id:
            return TransferResult(ok=False, message=("Không thể tự chuyển cho mình." if _is_vi(lang) else "You cannot transfer to yourself."))

        async with BaseService.with_multi_user_transaction(guild_id, [sender_id, receiver_id], "transfer") as conn:
            await player_repo.ensure_player_ready(conn, guild_id, sender_id)
            await player_repo.ensure_player_ready(conn, guild_id, receiver_id)

            sender_level, sender_created = await player_repo.get_player_level_and_created(conn, guild_id, sender_id)
            receiver_level, receiver_created = await player_repo.get_player_level_and_created(conn, guild_id, receiver_id)

            min_level = 5
            min_age = 259200

            if sender_level < min_level or receiver_level < min_level:
                msg = f"Cả 2 người cần tối thiểu level **{min_level}**." if _is_vi(lang) else f"Both users need at least level **{min_level}**."
                return TransferResult(ok=False, message=msg)

            now_ts = int(time.time())
            if (now_ts - sender_created) < min_age or (now_ts - receiver_created) < min_age:
                return TransferResult(ok=False, message=("Tài khoản quá mới để giao dịch." if _is_vi(lang) else "Account is too new to trade."))

            ok = await player_repo.subtract_gold(conn, guild_id, sender_id, amount)
            if not ok:
                return TransferResult(ok=False, message=("Bạn không đủ vàng." if _is_vi(lang) else "You don't have enough gold."))

            await player_repo.add_gold(conn, guild_id, receiver_id, amount)
            await telemetry_repo.record_gold_flow(conn, guild_id, sender_id, -amount, "pay_sent")
            await telemetry_repo.record_gold_flow(conn, guild_id, receiver_id, amount, "pay_received")
            await conn.commit()

            return TransferResult(
                ok=True,
                amount=amount,
                message=(f"💸 Đã chuyển **{amount}** gold." if _is_vi(lang) else f"💸 Transferred **{amount}** gold."),
            )

    @staticmethod
    async def use_item(guild_id: int, user_id: int, item_id: str, amount: int = 1, lang: str = "en") -> tuple[bool, str]:
        if amount <= 0:
            return False, ("Amount phải > 0." if _is_vi(lang) else "Amount must be > 0.")

        data = ITEMS.get(item_id)
        if not data:
            return False, ("Item không tồn tại." if _is_vi(lang) else "Item does not exist.")
        if data.get("use") == "equip":
            return False, ("Đây là trang bị. Dùng `/equip` để mặc đồ." if _is_vi(lang) else "This is equipment. Use `/equip` to wear it.")
        if data.get("use") not in ("heal", "lootbox"):
            return False, ("Item này không dùng được." if _is_vi(lang) else "This item cannot be used.")

        if data.get("use") == "heal":
            async with BaseService.with_user_transaction(guild_id, user_id, "use_heal") as conn:
                ok = await inventory_repo.remove_inventory(conn, guild_id, user_id, item_id, amount)
                if not ok:
                    return False, ("Bạn không đủ item." if _is_vi(lang) else "You don't have enough items.")

                async with conn.execute(
                    "SELECT hp, max_hp FROM players WHERE guild_id = ? AND user_id = ?",
                    (guild_id, user_id),
                ) as cur:
                    row = await cur.fetchone()
                hp = int(row[0]) if row else 1
                max_hp = int(row[1]) if row else 100
                healed = min(max_hp - hp, int(data.get("value", 0)) * amount)
                new_hp = hp + max(0, healed)
                await player_repo.update_player_hp(conn, guild_id, user_id, new_hp)
                await conn.commit()

                return True, (f"❤️ Hồi **{healed} HP** ({new_hp}/{max_hp})" if _is_vi(lang) else f"❤️ Healed **{healed} HP** ({new_hp}/{max_hp})")

        if data.get("use") == "lootbox":
            result = await EconomyService.open_lootbox(guild_id, user_id, amount, lang=lang)
            return result.ok, result.message

        return False, ("Item này không dùng được." if _is_vi(lang) else "This item cannot be used.")

    @staticmethod
    async def drop_item(guild_id: int, user_id: int, item_id: str, amount: int = 1, lang: str = "en") -> tuple[bool, str]:
        if amount <= 0:
            return False, ("Amount phải > 0." if _is_vi(lang) else "Amount must be > 0.")

        async with BaseService.with_user_transaction(guild_id, user_id, "drop") as conn:
            ok = await inventory_repo.remove_inventory(conn, guild_id, user_id, item_id, amount)
            if not ok:
                return False, ("Bạn không đủ item để drop." if _is_vi(lang) else "You don't have enough items to drop.")
            await conn.commit()

        return True, (f"🗑️ Đã drop `{item_id}` x{amount}." if _is_vi(lang) else f"🗑️ Dropped `{item_id}` x{amount}.")
