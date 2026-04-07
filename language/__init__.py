import os
from typing import Any, Optional

import aiosqlite

from .en import HELP_CONTENT as EN_HELP_CONTENT
from .en import RPG_HELP_CONTENT as EN_RPG_HELP_CONTENT
from .en import TEXTS as EN_TEXTS
from .vi import HELP_CONTENT as VI_HELP_CONTENT
from .vi import RPG_HELP_CONTENT as VI_RPG_HELP_CONTENT
from .vi import TEXTS as VI_TEXTS


CMD_I18N = {
    "cmd.ping.desc": {"vi": "Kiểm tra bot sống", "en": "Check bot latency"},
    "cmd.hello.desc": {"vi": "Chào người dùng", "en": "Say hello"},
    "cmd.lang.desc": {"vi": "Chọn ngôn ngữ của bạn", "en": "Choose your language"},
    "cmd.lang.param.language": {"vi": "Chọn vi hoặc en", "en": "Pick vi or en"},
    "cmd.status.desc": {"vi": "Xem tình trạng bot", "en": "View bot status"},
    "cmd.nuke.desc": {"vi": "Xóa toàn bộ tin nhắn trong kênh (chỉ admin)", "en": "Delete all messages in channel (admin only)"},
    "cmd.help.desc": {"vi": "Hướng dẫn nhanh", "en": "Quick help"},
    "cmd.help_rpg.desc": {"vi": "Hướng dẫn RPG chi tiết", "en": "Detailed RPG guide"},
    "cmd.rpg_start.desc": {"vi": "Khởi tạo hồ sơ chỉ huy RPG", "en": "Initialize RPG commander profile"},
    "cmd.profile.desc": {"vi": "Xem hồ sơ team RPG", "en": "View RPG team profile"},
    "cmd.profile.param.member": {"vi": "Xem hồ sơ người khác", "en": "View another member profile"},
    "cmd.stats.desc": {"vi": "Xem chỉ số chiến đấu team RPG", "en": "View RPG team combat stats"},
    "cmd.stats.param.member": {"vi": "Xem stats người khác", "en": "View another member stats"},
    "cmd.rpg_balance.desc": {"vi": "Xem số vàng RPG", "en": "View RPG gold balance"},
    "cmd.rpg_daily.desc": {"vi": "Nhận daily vàng RPG", "en": "Claim RPG daily gold"},
    "cmd.rpg_pay.desc": {"vi": "Chuyển vàng RPG", "en": "Transfer RPG gold"},
    "cmd.rpg_pay.param.member": {"vi": "Người nhận", "en": "Receiver"},
    "cmd.rpg_pay.param.amount": {"vi": "Số vàng", "en": "Gold amount"},
    "cmd.rpg_shop.desc": {"vi": "Xem shop RPG", "en": "View RPG shop"},
    "cmd.shop.desc": {"vi": "Xem danh mục shop RPG", "en": "View RPG shop categories"},
    "cmd.shop.param.category": {"vi": "consumables | equipment | materials | blackmarket", "en": "consumables | equipment | materials | blackmarket"},
    "cmd.craft_list.desc": {"vi": "Xem công thức craft RPG", "en": "View RPG craft recipes"},
    "cmd.craft.desc": {"vi": "Craft item RPG", "en": "Craft RPG item"},
    "cmd.craft.param.recipe_id": {"vi": "ID recipe", "en": "Recipe ID"},
    "cmd.craft.param.amount": {"vi": "Số lần craft", "en": "Craft amount"},
    "cmd.rpg_buy.desc": {"vi": "Mua item RPG", "en": "Buy RPG item"},
    "cmd.rpg_buy.param.item": {"vi": "Mã item", "en": "Item ID"},
    "cmd.rpg_buy.param.amount": {"vi": "Số lượng", "en": "Amount"},
    "cmd.rpg_sell.desc": {"vi": "Bán item RPG", "en": "Sell RPG item"},
    "cmd.rpg_sell.param.item": {"vi": "Mã item", "en": "Item ID"},
    "cmd.rpg_sell.param.amount": {"vi": "Số lượng", "en": "Amount"},
    "cmd.rpg_sell.param.location": {"vi": "normal | blackmarket", "en": "normal | blackmarket"},
    "cmd.rpg_inventory.desc": {"vi": "Xem inventory RPG", "en": "View RPG inventory"},
    "cmd.rpg_inventory.param.member": {"vi": "Xem inventory người khác", "en": "View another member inventory"},
    "cmd.rpg_equipment.desc": {"vi": "Xem trang bị RPG", "en": "View RPG equipment"},
    "cmd.rpg_equipment.param.member": {"vi": "Xem trang bị người khác", "en": "View another member equipment"},
    "cmd.equip.desc": {"vi": "Trang bị item RPG", "en": "Equip RPG item"},
    "cmd.equip.param.item": {"vi": "Mã item (phải là equip)", "en": "Item ID (must be equip)"},
    "cmd.unequip.desc": {"vi": "Tháo trang bị theo slot", "en": "Unequip by slot"},
    "cmd.unequip.param.slot": {"vi": "weapon / armor / accessory", "en": "weapon / armor / accessory"},
    "cmd.rpg_skills.desc": {"vi": "Xem danh sách skill RPG", "en": "View RPG skill list"},
    "cmd.rpg_skill_unlock.desc": {"vi": "Mở khóa skill RPG", "en": "Unlock RPG skill"},
    "cmd.rpg_skill_unlock.param.skill_id": {"vi": "ID skill", "en": "Skill ID"},
    "cmd.rpg_skill_use.desc": {"vi": "Dùng active skill RPG", "en": "Use RPG active skill"},
    "cmd.rpg_skill_use.param.skill_id": {"vi": "ID active skill", "en": "Active skill ID"},
    "cmd.rpg_use.desc": {"vi": "Dùng item RPG", "en": "Use RPG item"},
    "cmd.rpg_use.param.item": {"vi": "Mã item", "en": "Item ID"},
    "cmd.rpg_use.param.amount": {"vi": "Số lượng", "en": "Amount"},
    "cmd.open.desc": {"vi": "Mở lootbox RPG", "en": "Open RPG lootbox"},
    "cmd.open.param.amount": {"vi": "Số lootbox muốn mở", "en": "Lootbox amount to open"},
    "cmd.rpg_drop.desc": {"vi": "Bỏ item RPG", "en": "Drop RPG item"},
    "cmd.rpg_drop.param.item": {"vi": "Mã item", "en": "Item ID"},
    "cmd.rpg_drop.param.amount": {"vi": "Số lượng", "en": "Amount"},
    "cmd.hunt.desc": {"vi": "Đi săn quái RPG (Team-based)", "en": "RPG hunt monsters (team-based)"},
    "cmd.boss.desc": {"vi": "Đánh boss RPG (Team-based)", "en": "RPG boss fight (team-based)"},
    "cmd.dungeon.desc": {"vi": "Chinh phục dungeon nhiều tầng (Team-based)", "en": "Conquer multi-floor dungeon (team-based)"},
    "cmd.party_hunt.desc": {"vi": "Co-op hunt 2-4 người", "en": "Co-op hunt for 2-4 players"},
    "cmd.party_hunt.param.member2": {"vi": "Thành viên thứ 2", "en": "Second member"},
    "cmd.party_hunt.param.member3": {"vi": "Thành viên thứ 3", "en": "Third member"},
    "cmd.party_hunt.param.member4": {"vi": "Thành viên thứ 4", "en": "Fourth member"},
    "cmd.quest.desc": {"vi": "Xem quest RPG", "en": "View RPG quests"},
    "cmd.quest_claim.desc": {"vi": "Nhận thưởng quest RPG", "en": "Claim RPG quest rewards"},
    "cmd.quest_claim.param.quest_id": {"vi": "ID quest, ví dụ: kill_10", "en": "Quest ID, e.g. kill_10"},
    "cmd.rpg_loot.desc": {"vi": "Xem loot table và rarity RPG", "en": "View RPG loot table and rarity"},
    "cmd.create_character.desc": {"vi": "Tạo Captain cho đội hình", "en": "Create team Captain"},
    "cmd.create_character.param.role": {"vi": "Chọn role (dps/tank/healer/support hoặc sp)", "en": "Choose role (dps/tank/healer/support or sp)"},
    "cmd.create_character.param.gender": {"vi": "Không bắt buộc, giữ để tương thích", "en": "Optional, kept for compatibility"},
    "cmd.gacha.desc": {"vi": "Gacha summons (mythic chỉ nhận qua ghép mảnh legendary)", "en": "Gacha summons (mythic only via legendary shard ascend)"},
    "cmd.gacha.param.pulls": {"vi": "Số lần quay (1-10)", "en": "Pull count (1-10)"},
    "cmd.gacha.param.banner": {"vi": "Banner rate-up legendary", "en": "Legendary rate-up banner"},
    "cmd.my_characters.desc": {"vi": "Xem danh sách hero sở hữu", "en": "View owned hero list"},
    "cmd.roster.desc": {"vi": "Xem roster hero gacha", "en": "View gacha hero roster"},
    "cmd.ascend_mythic.desc": {"vi": "Ghép mảnh legendary để mở mythic form", "en": "Use legendary shards to unlock mythic form"},
    "cmd.ascend_mythic.param.legendary_id": {"vi": "Character ID legendary (ví dụ: benimaru_oni_majin)", "en": "Legendary character ID (e.g. benimaru_oni_majin)"},
    "cmd.team.desc": {"vi": "Quản lý team (5 slots)", "en": "Manage team (5 slots)"},
    "cmd.team.param.action": {"vi": "Thêm/xem/reset", "en": "add/view/reset"},
    "cmd.team.param.character_id": {"vi": "ID hero", "en": "Hero ID"},
    "cmd.team.param.slot": {"vi": "Hero slot (1-4)", "en": "Hero slot (1-4)"},
    "cmd.team_stats.desc": {"vi": "Xem chỉ số tổng của team", "en": "View overall team stats"},
}


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANG_DB_PATH = os.path.join(BASE_DIR, "lang.db")


def normalize_lang(lang: str) -> str:
    return "vi" if str(lang).lower().startswith("vi") else "en"


def _locale_to_lang(locale_obj) -> str:
    if locale_obj is None:
        return "en"
    value = getattr(locale_obj, "value", str(locale_obj))
    return normalize_lang(str(value))


def tr(lang: str, key: str, **kwargs) -> str:
    code = normalize_lang(lang)
    source = VI_TEXTS if code == "vi" else EN_TEXTS
    fallback = EN_TEXTS
    template = source.get(key, fallback.get(key, key))
    return template.format(**kwargs)


def help_content(lang: str) -> dict[str, Any]:
    return VI_HELP_CONTENT if normalize_lang(lang) == "vi" else EN_HELP_CONTENT


def rpg_help_content(lang: str) -> dict[str, Any]:
    return VI_RPG_HELP_CONTENT if normalize_lang(lang) == "vi" else EN_RPG_HELP_CONTENT


async def ensure_lang_db_ready() -> None:
    async with aiosqlite.connect(LANG_DB_PATH) as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_lang (
                user_id INTEGER PRIMARY KEY,
                lang TEXT NOT NULL
            )
            """
        )
        await conn.commit()


async def get_saved_lang(user_id: int) -> Optional[str]:
    try:
        async with aiosqlite.connect(LANG_DB_PATH) as conn:
            async with conn.execute("SELECT lang FROM user_lang WHERE user_id = ?", (int(user_id),)) as cur:
                row = await cur.fetchone()
        if row and row[0] in {"vi", "en"}:
            return str(row[0])
    except Exception:
        return None
    return None


async def save_lang(user_id: int, lang: str) -> None:
    code = normalize_lang(lang)
    async with aiosqlite.connect(LANG_DB_PATH) as conn:
        await conn.execute(
            "INSERT INTO user_lang(user_id, lang) VALUES(?, ?) ON CONFLICT(user_id) DO UPDATE SET lang = excluded.lang",
            (int(user_id), code),
        )
        await conn.commit()


async def resolve_lang(interaction) -> str:
    saved = await get_saved_lang(interaction.user.id)
    if saved in {"vi", "en"}:
        return saved
    user_locale = _locale_to_lang(getattr(interaction, "locale", None))
    if user_locale == "vi":
        return "vi"
    guild_locale = _locale_to_lang(getattr(interaction, "guild_locale", None))
    if guild_locale == "vi":
        return "vi"
    return "en"


async def resolve_lang_ctx(user_id: int, guild_locale=None) -> str:
    saved = await get_saved_lang(user_id)
    if saved in {"vi", "en"}:
        return saved
    if _locale_to_lang(guild_locale) == "vi":
        return "vi"
    return "en"
