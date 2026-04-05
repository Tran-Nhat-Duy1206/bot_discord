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


OBJECTIVE_NAMES = {
    "kill_monsters": "Hạ quái",
    "kill_slime": "Hạ Slime Jackpot",
    "hunt_runs": "Chạy hunt",
    "open_lootboxes": "Mở lootbox",
    "boss_wins": "Thắng boss",
}


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
    async def claim_quest(guild_id: int, user_id: int, quest_id: str) -> QuestClaimResult:
        async with BaseService.with_user_transaction(guild_id, user_id, "claim_quest") as conn:
            await player_repo.ensure_player_ready(conn, guild_id, user_id)
            await quest_repo.ensure_default_quests(conn, guild_id, user_id)
            await quest_repo.refresh_quests_if_needed(conn, guild_id, user_id)
            
            row = await quest_repo.get_quest(conn, guild_id, user_id, quest_id)
            if not row:
                return QuestClaimResult(ok=False, quest_id=quest_id, message="❌ Không tìm thấy quest.")

            target, progress, reward_gold, reward_xp, prereq, claimed = row
            prereq_str = str(prereq or "")

            if prereq_str:
                prereq_row = await quest_repo.get_quest(conn, guild_id, user_id, prereq_str)
                if not prereq_row or int(prereq_row[5]) == 0:
                    return QuestClaimResult(
                        ok=False,
                        quest_id=quest_id,
                        message=f"❌ Quest này chưa mở. Hoàn thành `{prereq_str}` trước.",
                    )

            if int(claimed) == 1:
                return QuestClaimResult(ok=False, quest_id=quest_id, message="❌ Quest đã claim rồi.")

            if int(progress) < int(target):
                return QuestClaimResult(ok=False, quest_id=quest_id, message="❌ Quest chưa hoàn thành.")

            await quest_repo.claim_quest(conn, guild_id, user_id, quest_id)
            await player_repo.add_gold(conn, guild_id, user_id, int(reward_gold))
            await telemetry_repo.record_gold_flow(conn, guild_id, user_id, int(reward_gold), "quest_claim")
            new_level, _, leveled = await player_repo.gain_xp_and_level(conn, guild_id, user_id, int(reward_xp))
            await conn.commit()

            msg = f"✅ Claim quest `{quest_id}`: +{reward_gold} gold, +{reward_xp} xp"
            if leveled:
                msg += f"\n🎉 Bạn đã lên level **{new_level}**"

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
    def format_quests(quests: list[QuestInfo]) -> str:
        import time
        now = int(time.time())
        lines: list[str] = []
        for q in quests:
            name = OBJECTIVE_NAMES.get(q.objective, q.objective)
            if q.is_locked:
                status = f"🔒 Locked (need `{q.prereq_quest_id}`)"
            else:
                status = "✅ Claimed" if q.claimed else ("🎯 Ready" if q.progress >= q.target else "⏳ In progress")
            
            period_txt = ""
            if q.period in {"daily", "weekly"} and q.reset_after > now:
                period_txt = f" • reset <t:{q.reset_after}:R>"
            
            lines.append(
                f"`{q.quest_id}` • **{name}** {q.progress}/{q.target}\n"
                f"Reward: {q.reward_gold} gold + {q.reward_xp} xp • {status}{period_txt}"
            )
        return "\n\n".join(lines)
