import os
from typing import Optional

import aiosqlite

from .en import TEXTS as EN_TEXTS
from .vi import TEXTS as VI_TEXTS


CMD_I18N = {
    "cmd.ping.desc": {"vi": "Kiểm tra bot sống", "en": "Check bot latency"},
    "cmd.hello.desc": {"vi": "Chào người dùng", "en": "Say hello"},
    "cmd.lang.desc": {"vi": "Chọn ngôn ngữ của bạn", "en": "Choose your language"},
    "cmd.lang.param.language": {"vi": "Chọn vi hoặc en", "en": "Pick vi or en"},
    "cmd.status.desc": {"vi": "Xem tình trạng bot", "en": "View bot status"},
    "cmd.nuke.desc": {"vi": "Xóa toàn bộ tin nhắn trong kênh (chỉ admin)", "en": "Delete all messages in channel (admin only)"},
    "cmd.rpg_start.desc": {"vi": "Khởi tạo hồ sơ Chỉ Huy Squad", "en": "Initialize Squad Commander profile"},
    "cmd.profile.desc": {"vi": "Mở Squad Command Panel", "en": "Open Squad Command Panel"},
    "cmd.profile.param.member": {"vi": "Xem hồ sơ người khác", "en": "View another member profile"},
    "cmd.stats.desc": {"vi": "Mở Formation Analysis", "en": "Open Formation Analysis"},
    "cmd.stats.param.member": {"vi": "Xem stats người khác", "en": "View another member stats"},
    "cmd.rpg_daily.desc": {"vi": "Nhận trợ cấp hằng ngày", "en": "Claim daily squad stipend"},
    "cmd.rpg_pay.desc": {"vi": "Chuyển quỹ cho đồng minh", "en": "Transfer funds to an ally"},
    "cmd.rpg_pay.param.member": {"vi": "Người nhận", "en": "Receiver"},
    "cmd.rpg_pay.param.amount": {"vi": "Số vàng", "en": "Gold amount"},
    "cmd.rpg_shop.desc": {"vi": "Mở Quartermaster Bazaar", "en": "Open Quartermaster Bazaar"},
    "cmd.shop.desc": {"vi": "Xem các gian hàng bazaar", "en": "Browse bazaar wings"},
    "cmd.shop.param.category": {"vi": "consumables | equipment | materials | blackmarket", "en": "consumables | equipment | materials | blackmarket"},
    "cmd.craft_list.desc": {"vi": "Xem Forge Recipes", "en": "View Forge Recipes"},
    "cmd.craft.desc": {"vi": "Rèn hoặc ghép vật phẩm", "en": "Forge or craft an item"},
    "cmd.craft.param.recipe_id": {"vi": "ID recipe", "en": "Recipe ID"},
    "cmd.craft.param.amount": {"vi": "Số lần craft", "en": "Craft amount"},
    "cmd.rpg_buy.desc": {"vi": "Mua vật phẩm tiếp tế", "en": "Buy supply items"},
    "cmd.rpg_buy.param.item": {"vi": "Mã item", "en": "Item ID"},
    "cmd.rpg_buy.param.amount": {"vi": "Số lượng", "en": "Amount"},
    "cmd.rpg_sell.desc": {"vi": "Bán vật phẩm trong kho", "en": "Sell inventory items"},
    "cmd.rpg_sell.param.item": {"vi": "Mã item", "en": "Item ID"},
    "cmd.rpg_sell.param.amount": {"vi": "Số lượng", "en": "Amount"},
    "cmd.rpg_sell.param.location": {"vi": "normal | blackmarket", "en": "normal | blackmarket"},
    "cmd.rpg_inventory.desc": {"vi": "Mở Supply Bag", "en": "Open Supply Bag"},
    "cmd.rpg_inventory.param.member": {"vi": "Xem Supply Bag người khác", "en": "View another member Supply Bag"},
    "cmd.rpg_equipment.desc": {"vi": "Mở Loadout Console", "en": "Open Loadout Console"},
    "cmd.rpg_equipment.param.member": {"vi": "Xem loadout người khác", "en": "View another member loadout"},
    "cmd.equip.desc": {"vi": "Trang bị vào loadout", "en": "Equip into loadout"},
    "cmd.equip.param.item": {"vi": "Mã item (phải là equip)", "en": "Item ID (must be equip)"},
    "cmd.unequip.desc": {"vi": "Tháo trang bị theo slot", "en": "Unequip by slot"},
    "cmd.unequip.param.slot": {"vi": "weapon / armor / accessory", "en": "weapon / armor / accessory"},
    "cmd.rpg_skills.desc": {"vi": "Mở Skill Codex", "en": "Open Skill Codex"},
    "cmd.rpg_skill_unlock.desc": {"vi": "Mở khóa kỹ năng", "en": "Unlock a skill"},
    "cmd.rpg_skill_unlock.param.skill_id": {"vi": "ID skill", "en": "Skill ID"},
    "cmd.rpg_skill_use.desc": {"vi": "Kích hoạt kỹ năng chủ động", "en": "Activate an active skill"},
    "cmd.rpg_skill_use.param.skill_id": {"vi": "ID active skill", "en": "Active skill ID"},
    "cmd.rpg_use.desc": {"vi": "Dùng vật phẩm trong Supply Bag", "en": "Use an item from Supply Bag"},
    "cmd.rpg_use.param.item": {"vi": "Mã item", "en": "Item ID"},
    "cmd.rpg_use.param.amount": {"vi": "Số lượng", "en": "Amount"},
    "cmd.open.desc": {"vi": "Mở lootbox tiếp tế", "en": "Open a supply lootbox"},
    "cmd.open.param.amount": {"vi": "Số lootbox muốn mở", "en": "Lootbox amount to open"},
    "cmd.rpg_drop.desc": {"vi": "Loại bỏ vật phẩm", "en": "Discard an item"},
    "cmd.rpg_drop.param.item": {"vi": "Mã item", "en": "Item ID"},
    "cmd.rpg_drop.param.amount": {"vi": "Số lượng", "en": "Amount"},
    "cmd.hunt.desc": {"vi": "Triển khai squad đi săn", "en": "Deploy squad to hunt"},
    "cmd.boss.desc": {"vi": "Mở Boss Assault", "en": "Launch Boss Assault"},
    "cmd.dungeon.desc": {"vi": "Thực hiện Dungeon Raid", "en": "Run a Dungeon Raid"},
    "cmd.dungeon_group.desc": {"vi": "Abyssal Expedition dungeon mode", "en": "Abyssal Expedition dungeon mode"},
    "cmd.dungeon.start.desc": {"vi": "Bắt đầu dungeon run mới", "en": "Start a new dungeon run"},
    "cmd.dungeon.start.param.difficulty": {"vi": "normal | hard | nightmare", "en": "normal | hard | nightmare"},
    "cmd.dungeon.status.desc": {"vi": "Xem trạng thái run hiện tại", "en": "View current run status"},
    "cmd.dungeon.path.desc": {"vi": "Chọn node đường đi cho floor hiện tại", "en": "Choose a node path for current floor"},
    "cmd.dungeon.path.param.node_id": {"vi": "Node ID từ /dungeon status", "en": "Node ID from /dungeon status"},
    "cmd.dungeon.choice.desc": {"vi": "Chọn quyết định chiến thuật giữa floor", "en": "Apply strategic choice between floors"},
    "cmd.dungeon.choice.param.choice_id": {"vi": "Choice ID từ /dungeon status", "en": "Choice ID from /dungeon status"},
    "cmd.dungeon.retreat.desc": {"vi": "Rút lui khỏi run hiện tại", "en": "Retreat current dungeon run"},
    "cmd.dungeon.claim.desc": {"vi": "Nhận thưởng run đã kết thúc", "en": "Claim rewards from finished run"},
    "cmd.party_hunt.desc": {"vi": "Joint Operation 2-4 người", "en": "Start 2-4 player Joint Operation"},
    "cmd.party_hunt.param.member2": {"vi": "Thành viên thứ 2", "en": "Second member"},
    "cmd.party_hunt.param.member3": {"vi": "Thành viên thứ 3", "en": "Third member"},
    "cmd.party_hunt.param.member4": {"vi": "Thành viên thứ 4", "en": "Fourth member"},
    "cmd.quest.desc": {"vi": "Mở Mission Board", "en": "Open Mission Board"},
    "cmd.quest_claim.desc": {"vi": "Nhận thưởng nhiệm vụ", "en": "Claim mission rewards"},
    "cmd.quest_claim.param.quest_id": {"vi": "ID quest, ví dụ: kill_10", "en": "Quest ID, e.g. kill_10"},
    "cmd.rpg_loot.desc": {"vi": "Mở Drop Codex", "en": "Open Drop Codex"},
    "cmd.create_character.desc": {"vi": "Tạo Captain cho đội hình", "en": "Create team Captain"},
    "cmd.create_character.param.role": {"vi": "Chọn role (dps/tank/healer/support)", "en": "Choose role (dps/tank/healer/support)"},
    "cmd.create_character.param.gender": {"vi": "Không bắt buộc, giữ để tương thích", "en": "Optional, kept for compatibility"},
    "cmd.gacha.desc": {"vi": "Dimensional Recruitment", "en": "Dimensional Recruitment"},
    "cmd.gacha.param.pulls": {"vi": "Số lần quay (1-10)", "en": "Pull count (1-10)"},
    "cmd.gacha.param.banner": {"vi": "Banner rate-up legendary", "en": "Legendary rate-up banner"},
    "cmd.my_characters.desc": {"vi": "Mở Barracks Archive", "en": "Open Barracks Archive"},
    "cmd.roster.desc": {"vi": "Mở Roster Codex", "en": "Open Roster Codex"},
    "cmd.ascend_mythic.desc": {"vi": "Ghép mảnh legendary để mở mythic form", "en": "Use legendary shards to unlock mythic form"},
    "cmd.ascend_mythic.param.legendary_id": {"vi": "Character ID legendary (ví dụ: benimaru_oni_majin)", "en": "Legendary character ID (e.g. benimaru_oni_majin)"},
    "cmd.team.desc": {"vi": "Mở Formation Console", "en": "Open Formation Console"},
    "cmd.team.param.action": {"vi": "deploy/view/reset", "en": "deploy/view/reset"},
    "cmd.team.param.character_id": {"vi": "ID hero", "en": "Hero ID"},
    "cmd.team.param.slot": {"vi": "Deployment slot (1-4)", "en": "Deployment slot (1-4)"},
    "cmd.team_stats.desc": {"vi": "Mở Formation Analysis nâng cao", "en": "Open advanced Formation Analysis"},
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
