import os
from dataclasses import dataclass
from typing import Optional

from features.emoji_registry import CURRENCY_ICON
from features.emoji_registry import RARITY_ICONS
from features.emoji_registry import rarity_icon as rarity_icon_token

from ..data import ITEMS


@dataclass
class ShopItem:
    id: str
    name: str
    emoji: str
    buy_price: int
    sell_price: int
    desc: str
    rarity: str
    category: str
    can_sell_normal: bool
    black_market_only: bool


class ShopCategory:
    CONSUMABLES = "consumables"
    EQUIPMENT = "equipment"
    MATERIALS = "materials"
    BLACK_MARKET = "black_market"


def _build_shop_items() -> dict[str, ShopItem]:
    items = {}
    for item_id, data in ITEMS.items():
        buy = int(data.get("buy", 0))
        sell = int(data.get("sell", 0))
        rarity = str(data.get("rarity", "common"))
        item_use = str(data.get("use", "none"))
        slot = str(data.get("slot", ""))
        
        if item_use == "heal" or item_use == "lootbox":
            category = ShopCategory.CONSUMABLES
            can_sell = sell > 0
        elif slot:
            category = ShopCategory.EQUIPMENT
            can_sell = sell > 0
        else:
            category = ShopCategory.MATERIALS
            can_sell = sell > 0
        
        items[item_id] = ShopItem(
            id=item_id,
            name=str(data.get("name", item_id)),
            emoji=str(data.get("emoji", "📦")),
            buy_price=buy,
            sell_price=sell,
            desc=str(data.get("desc", "")),
            rarity=rarity,
            category=category,
            can_sell_normal=can_sell and rarity not in ("epic", "legendary"),
            black_market_only=rarity in ("epic", "legendary"),
        )
    return items


SHOP_ITEMS = _build_shop_items()

RARITY_COLORS = {
    "common": 0xAAAAAA,
    "uncommon": 0x00AA00,
    "rare": 0x0088FF,
    "epic": 0xAA00AA,
    "legendary": 0xFFAA00,
}

RARITY_EMOJI = dict(RARITY_ICONS)

def get_item_by_id(item_id: str) -> Optional[ShopItem]:
    return SHOP_ITEMS.get(item_id)


def get_items_by_category(category: str) -> list[ShopItem]:
    if category == ShopCategory.BLACK_MARKET:
        return [i for i in SHOP_ITEMS.values() if i.black_market_only]
    return [i for i in SHOP_ITEMS.values() if i.category == category and i.buy_price > 0]


def get_sellable_items(normal_only: bool = True) -> list[ShopItem]:
    if normal_only:
        return [i for i in SHOP_ITEMS.values() if i.can_sell_normal and i.sell_price > 0]
    return [i for i in SHOP_ITEMS.values() if i.sell_price > 0]


def format_shop_embed(category: str) -> str:
    if category == "main":
        return _format_main_menu()
    elif category == ShopCategory.CONSUMABLES:
        return _format_category(ShopCategory.CONSUMABLES, "🧪 Vật Phẩm Tiêu Hao")
    elif category == ShopCategory.EQUIPMENT:
        return _format_category(ShopCategory.EQUIPMENT, "⚔️ Trang Bị")
    elif category == ShopCategory.MATERIALS:
        return _format_category(ShopCategory.MATERIALS, "💎 Vật Liệu")
    elif category == ShopCategory.BLACK_MARKET:
        return _format_black_market()
    return "Unknown category"


def _format_main_menu() -> str:
    lines = [
        "**🛒 CHÀO MỪNG ĐẾN SHOP!**",
        "",
        "Chọn danh mục để xem:",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        "🧪 **Vật Phẩm Tiêu Hao**",
        "   Potion, Mega Potion, Lootbox...",
        "",
        "⚔️ **Trang Bị**",
        "   Weapon, Armor, Accessory...",
        "",
        "💎 **Vật Liệu**",
        "   Nguyên liệu craft và các vật phẩm khác...",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        "🌑 **Chợ Đen**",
        "   Bán đồ hiếm (Epic/Legendary) không bán được ở shop thường",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        "📝 **Hướng dẫn:**",
        "• `/shop consumables` - Xem vật phẩm tiêu hao",
        "• `/shop equipment` - Xem trang bị",
        "• `/shop materials` - Xem vật liệu",
        "• `/shop blackmarket` - Xem chợ đen",
        "• `/buy <item>` - Mua item",
        "• `/sell <item>` - Bán item (shop thường)",
        "• `/sell <item> blackmarket` - Bán ở chợ đen",
    ]
    return "\n".join(lines)


def _format_category(category: str, title: str) -> str:
    items = get_items_by_category(category)
    if not items:
        return f"{title}\n\nKhông có item nào trong danh mục này."
    
    lines = [f"**{title}**", ""]
    
    grouped: dict[str, list[ShopItem]] = {}
    for item in items:
        if item.rarity not in grouped:
            grouped[item.rarity] = []
        grouped[item.rarity].append(item)
    
    for rarity in ["common", "uncommon", "rare", "epic", "legendary"]:
        if rarity not in grouped:
            continue
        
        rarity_items = grouped[rarity]
        lines.append(f"\n{rarity_icon_token(rarity)} **{rarity.upper()}**")
        lines.append("─" * 20)
        
        for item in rarity_items:
            lines.append(
                f"{item.emoji} **{item.name}**"
            )
            lines.append(f"   💰 Buy: `{item.buy_price:,}` | Sell: `{item.sell_price:,}`")
            lines.append(f"   📝 {item.desc}")
            lines.append("")
    
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"📝 Dùng `/buy <item_id>` để mua")
    
    return "\n".join(lines)


def _format_black_market() -> str:
    items = get_items_by_category(ShopCategory.BLACK_MARKET)
    if not items:
        return "🌑 **Chợ Đen**\n\nKhông có item nào."
    
    lines = [
        "🌑 **CHỢ ĐEN**",
        "⚠️ *Nơi bán những món đồ hiếm không thể bán ở shop thường*",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    
    grouped: dict[str, list[ShopItem]] = {}
    for item in items:
        if item.rarity not in grouped:
            grouped[item.rarity] = []
        grouped[item.rarity].append(item)
    
    for rarity in ["epic", "legendary"]:
        if rarity not in grouped:
            continue
        
        rarity_items = grouped[rarity]
        lines.append(f"\n{rarity_icon_token(rarity)} **{rarity.upper()}**")
        lines.append("─" * 20)
        
        for item in rarity_items:
            sell_price = int(item.sell_price * 0.6)
            lines.append(
                f"{item.emoji} **{item.name}**"
            )
            lines.append(f"   💰 Sell: `~{sell_price:,}` {CURRENCY_ICON} Slime Coin (60% giá thường)")
            lines.append(f"   📝 {item.desc}")
            lines.append("")
    
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("📝 Dùng `/sell <item_id> blackmarket` để bán")
    
    return "\n".join(lines)


def get_sell_price(item_id: str, black_market: bool = False) -> int:
    item = get_item_by_id(item_id)
    if not item:
        return 0
    
    if black_market:
        return int(item.sell_price * 0.6)
    return item.sell_price


def can_sell_normal(item_id: str) -> bool:
    item = get_item_by_id(item_id)
    if not item:
        return False
    return item.can_sell_normal


def can_sell_blackmarket(item_id: str) -> bool:
    item = get_item_by_id(item_id)
    if not item:
        return False
    return item.black_market_only


def get_shop_categories() -> list[dict]:
    return [
        {"id": ShopCategory.CONSUMABLES, "name": "Vật Phẩm Tiêu Hao", "emoji": "🧪", "desc": "Potion, Lootbox..."},
        {"id": ShopCategory.EQUIPMENT, "name": "Trang Bị", "emoji": "⚔️", "desc": "Weapon, Armor, Accessory..."},
        {"id": ShopCategory.MATERIALS, "name": "Vật Liệu", "emoji": "💎", "desc": "Nguyên liệu craft..."},
        {"id": ShopCategory.BLACK_MARKET, "name": "Chợ Đen", "emoji": "🌑", "desc": "Bán đồ hiếm..."},
    ]
