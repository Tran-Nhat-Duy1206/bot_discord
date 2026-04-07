from dataclasses import dataclass, field
from typing import Optional

from ..repositories import player_repo, quest_repo, telemetry_repo
from .base import BaseService


@dataclass
class QuestClaimResult:
    ok: bool = False
    quest_id: str = ""
    reward_gold: int = 0
    reward_xp: int = 0
    leveled_up: bool = False
    new_level: int = 1
    message: str = ""


@dataclass
class QuestInfo:
    quest_id: str
    objective: str
    target: int
    progress: int
    reward_gold: int
    reward_xp: int
    period: str
    reset_after: int
    prereq_quest_id: str
    claimed: bool
    is_locked: bool = False


OBJECTIVE_NAMES_VI = {
    "team_hunt_runs": "Team hunt",
    "team_hunt_clears": "Clear trọn pack",
    "team_dungeon_clears": "Clear dungeon",
    "summon_times": "Triệu hồi gacha",
    "use_healer_battles": "Đánh trận có healer",
    "boss_wins": "Thắng boss",
    "kill_slime": "Hạ Slime Jackpot",
    "open_lootbox": "Mở lootbox",
}

OBJECTIVE_NAMES_EN = {
    "team_hunt_runs": "Team hunt",
    "team_hunt_clears": "Clear full pack",
    "team_dungeon_clears": "Clear dungeon",
    "summon_times": "Gacha summons",
    "use_healer_battles": "Battles with healer",
    "boss_wins": "Boss wins",
    "kill_slime": "Jackpot Slime kills",
    "open_lootbox": "Open lootbox",
}


def _is_vi(lang: str) -> bool:
    return str(lang).lower().startswith("vi")


class QuestService(BaseService):
    @staticmethod
    async def get_quests(guild_id: int, user_id: int) -> list[QuestInfo]:
        async with BaseService.with_user_transaction(guild_id, user_id, "get_quests") as conn:
            await player_repo.ensure_player_ready(conn, guild_id, user_id)
            rows = await quest_repo.get_quests(conn, guild_id, user_id)
            await conn.commit()

        claimed_map = {str(r[0]): int(r[9]) for r in rows}
        result: list[QuestInfo] = []
        for row in rows:
            qid, objective, target, progress, reward_gold, reward_xp, period, reset_after, prereq, claimed = row
            prereq_str = str(prereq or "")
            is_locked = bool(prereq_str) and claimed_map.get(prereq_str, 0) == 0
            result.append(QuestInfo(
                quest_id=str(qid),
                objective=str(objective),
                target=int(target),
                progress=int(progress),
                reward_gold=int(reward_gold),
                reward_xp=int(reward_xp),
                period=str(period),
                reset_after=int(reset_after),
                prereq_quest_id=prereq_str,
                claimed=bool(int(claimed)),
                is_locked=is_locked,
            ))
        return result

    @staticmethod
    async def claim_quest(guild_id: int, user_id: int, quest_id: str, lang: str = "en") -> QuestClaimResult:
        async with BaseService.with_user_transaction(guild_id, user_id, "claim_quest") as conn:
            await player_repo.ensure_player_ready(conn, guild_id, user_id)
            await quest_repo.ensure_default_quests(conn, guild_id, user_id)
            await quest_repo.refresh_quests_if_needed(conn, guild_id, user_id)
            
            row = await quest_repo.get_quest(conn, guild_id, user_id, quest_id)
            if not row:
                msg = "❌ Không tìm thấy quest." if _is_vi(lang) else "❌ Quest not found."
                return QuestClaimResult(ok=False, quest_id=quest_id, message=msg)

            target, progress, reward_gold, reward_xp, prereq, claimed = row
            prereq_str = str(prereq or "")

            if prereq_str:
                prereq_row = await quest_repo.get_quest(conn, guild_id, user_id, prereq_str)
                if not prereq_row or int(prereq_row[5]) == 0:
                    msg = (
                        f"❌ Quest này chưa mở. Hoàn thành `{prereq_str}` trước."
                        if _is_vi(lang)
                        else f"❌ This quest is locked. Complete `{prereq_str}` first."
                    )
                    return QuestClaimResult(
                        ok=False,
                        quest_id=quest_id,
                        message=msg,
                    )

            if int(claimed) == 1:
                msg = "❌ Quest đã claim rồi." if _is_vi(lang) else "❌ Quest already claimed."
                return QuestClaimResult(ok=False, quest_id=quest_id, message=msg)

            if int(progress) < int(target):
                msg = "❌ Quest chưa hoàn thành." if _is_vi(lang) else "❌ Quest not completed yet."
                return QuestClaimResult(ok=False, quest_id=quest_id, message=msg)

            await quest_repo.claim_quest(conn, guild_id, user_id, quest_id)
            await player_repo.add_gold(conn, guild_id, user_id, int(reward_gold))
            await telemetry_repo.record_gold_flow(conn, guild_id, user_id, int(reward_gold), "quest_claim")
            new_level, _, leveled = await player_repo.gain_xp_and_level(conn, guild_id, user_id, int(reward_xp))
            await conn.commit()

            msg = (
                f"✅ Claim quest `{quest_id}`: +{reward_gold} gold, +{reward_xp} xp"
                if _is_vi(lang)
                else f"✅ Claimed quest `{quest_id}`: +{reward_gold} gold, +{reward_xp} xp"
            )
            if leveled:
                msg += (
                    f"\n🎉 Bạn đã lên level **{new_level}**"
                    if _is_vi(lang)
                    else f"\n🎉 You reached level **{new_level}**"
                )

            return QuestClaimResult(
                ok=True,
                quest_id=quest_id,
                reward_gold=int(reward_gold),
                reward_xp=int(reward_xp),
                leveled_up=leveled,
                new_level=new_level,
                message=msg,
            )

    @staticmethod
    def format_quests(quests: list[QuestInfo], lang: str = "en") -> str:
        import time
        now = int(time.time())
        lines: list[str] = []
        names = OBJECTIVE_NAMES_VI if _is_vi(lang) else OBJECTIVE_NAMES_EN
        for q in quests:
            name = names.get(q.objective, q.objective)
            if q.is_locked:
                status = (
                    f"🔒 Chưa mở (cần `{q.prereq_quest_id}`)"
                    if _is_vi(lang)
                    else f"🔒 Locked (need `{q.prereq_quest_id}`)"
                )
            else:
                status = (
                    ("✅ Đã nhận" if q.claimed else ("🎯 Có thể nhận" if q.progress >= q.target else "⏳ Đang làm"))
                    if _is_vi(lang)
                    else ("✅ Claimed" if q.claimed else ("🎯 Ready" if q.progress >= q.target else "⏳ In progress"))
                )
            
            period_txt = ""
            if q.period in {"daily", "weekly"} and q.reset_after > now:
                period_txt = f" • reset <t:{q.reset_after}:R>"
            
            lines.append(
                f"`{q.quest_id}` • **{name}** {q.progress}/{q.target}\n"
                + (
                    f"Reward: {q.reward_gold} gold + {q.reward_xp} xp • {status}{period_txt}"
                    if not _is_vi(lang)
                    else f"Thưởng: {q.reward_gold} gold + {q.reward_xp} xp • {status}{period_txt}"
                )
            )
        return "\n\n".join(lines)
