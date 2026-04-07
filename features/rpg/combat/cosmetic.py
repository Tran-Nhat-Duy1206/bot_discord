import os
import random
from dataclasses import dataclass
from typing import Optional


COSMETIC_DB_KEY = os.getenv("RPG_DB", "data/rpg.db").replace(".db", "_cosmetics.db")


@dataclass
class Title:
    id: str
    name: str
    emoji: str
    description: str
    rarity: str
    cost: int


@dataclass  
class Aura:
    id: str
    name: str
    emoji: str
    color: str
    cost: int


TITLES: list[Title] = [
    Title("newbie", "Newbie", "🌱", "Bắt đầu cuộc phiêu lưu", "common", 0),
    Title("warrior", "Chiến Binh", "⚔️", "Kẻ diệt quái vật", "common", 500),
    Title("veteran", "Chiến Binh Dày Dạn", "🛡️", "Đã giết 100 con quái", "uncommon", 1500),
    Title("champion", "Á Quân", "🥈", "Top 2 server", "rare", 5000),
    Title("legend", "Huyền Thoại", "🏆", "Top 1 server", "legendary", 15000),
    Title("slayer", "Quái Vật Săn", "💀", "Đã tiêu diệt Ancient Ogre", "rare", 3000),
    Title("dragon_slayer", "Diệt Long Giả", "🐉", "Đã hạ Ashen Dragon", "epic", 8000),
    Title("lucky", "Người May Mắn", "🍀", "Trúng jackpot 10 lần", "uncommon", 2000),
    Title("rich", "Đại Gia", "💰", "Sở hữu 100,000 vàng", "rare", 6000),
    Title("craftsman", "Nghệ Nhân", "🔨", "Đã craft 50 item", "uncommon", 2500),
    Title("collector", "Nhà Sưu Tập", "📦", "Sở hữu 100 item khác nhau", "rare", 4000),
    Title("immortal", "Bất Tử", "♾️", "Không chết trong 100 trận", "epic", 10000),
]

AURAS: list[Aura] = [
    Aura("none", "Không", "", "", 0),
    Aura("fire", "Lửa", "🔥", "ff6600", 5000),
    Aura("ice", "Băng", "❄️", "00ccff", 5000),
    Aura("poison", "Thủy", "☠️", "00ff00", 6000),
    Aura("thunder", "Sấm", "⚡", "ffff00", 7000),
    Aura("shadow", "Bóng Tối", "🌑", "660066", 8000),
    Aura("divine", "Thần Thánh", "✨", "ffd700", 12000),
    Aura("rainbow", "Cầu Vồng", "🌈", "ff00ff", 20000),
]

RARITY_COLORS = {
    "common": 0xAAAAAA,
    "uncommon": 0x00AA00,
    "rare": 0x0088FF,
    "epic": 0xAA00AA,
    "legendary": 0xFFAA00,
}


def get_title_by_id(title_id: str) -> Optional[Title]:
    for t in TITLES:
        if t.id == title_id:
            return t
    return None


def get_aura_by_id(aura_id: str) -> Optional[Aura]:
    for a in AURAS:
        if a.id == aura_id:
            return a
    return None


def get_all_titles() -> list[Title]:
    return TITLES


def get_all_auras() -> list[Aura]:
    return AURAS


def get_buyable_titles(owned_ids: set[str]) -> list[Title]:
    return [t for t in TITLES if t.id not in owned_ids and t.cost > 0]


def get_buyable_auras(owned_ids: set[str]) -> list[Aura]:
    return [a for a in AURAS if a.id not in owned_ids and a.cost > 0]


def format_title_shop(buyable: list[Title]) -> str:
    if not buyable:
        return "🎨 Bạn đã sở hữu tất cả titles!"
    
    lines = ["**📜 SHOP TITLES**", ""]
    for t in buyable:
        emoji = "🟢" if t.cost < 1000 else "🔵" if t.cost < 5000 else "🟣" if t.cost < 10000 else "🟡"
        lines.append(f"{emoji} **{t.name}**")
        lines.append(f"   {t.emoji} {t.description}")
        lines.append(f"   💰 {t.cost:,} gold")
        lines.append("")
    
    return "\n".join(lines)


def format_aura_shop(buyable: list[Aura]) -> str:
    if not buyable:
        return "✨ Bạn đã sở hữu tất cả auras!"
    
    lines = ["**✨ SHOP AURAS**", ""]
    for a in buyable:
        lines.append(f"**{a.name}** {a.emoji}")
        lines.append(f"   💰 {a.cost:,} gold")
        lines.append("")
    
    return "\n".join(lines)


def format_inventory(titles: list[Title], auras: list[Aura], current_title: str, current_aura: str) -> str:
    lines = ["**🎨 COSMETICS INVENTORY**", ""]
    
    lines.append("📜 **Titles:**")
    for t in titles:
        active = " ✅" if t.id == current_title else ""
        lines.append(f"  {t.emoji} {t.name}{active}")
    
    lines.append("")
    lines.append("✨ **Auras:**")
    for a in auras:
        active = " ✅" if a.id == current_aura else ""
        lines.append(f"  {a.emoji} {a.name}{active}")
    
    return "\n".join(lines)


def check_achievement_title(user_stats: dict) -> Optional[Title]:
    if user_stats.get("jackpot_count", 0) >= 10:
        for t in TITLES:
            if t.id == "lucky":
                return t
    
    if user_stats.get("gold", 0) >= 100000:
        for t in TITLES:
            if t.id == "rich":
                return t
    
    if user_stats.get("craft_count", 0) >= 50:
        for t in TITLES:
            if t.id == "craftsman":
                return t
    
    if user_stats.get("unique_items", 0) >= 100:
        for t in TITLES:
            if t.id == "collector":
                return t
    
    if user_stats.get("deaths", 0) == 0 and user_stats.get("battles", 0) >= 100:
        for t in TITLES:
            if t.id == "immortal":
                return t
    
    return None


def format_profile_cosmetic(title: Optional[Title], aura: Optional[Aura], level: int, gold: int) -> str:
    if not title:
        title_name = f"Lv.{level}"
    else:
        title_name = f"[{title.emoji} {title.name}]"
    
    aura_display = f" {aura.emoji}" if aura and aura.id != "none" else ""
    
    return f"{title_name}{aura_display}"
