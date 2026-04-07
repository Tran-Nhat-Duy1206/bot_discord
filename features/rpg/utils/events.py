import datetime


WEEKLY_EVENTS: list[dict] = [
    {
        "id": "double_drop",
        "name": "Double Drop Week",
        "desc": "Tăng mạnh tỉ lệ rơi item khi hunt/boss.",
        "hunt_drop_mult": 1.8,
        "boss_drop_mult": 1.8,
    },
    {
        "id": "boss_rush",
        "name": "Boss Rush Week",
        "desc": "Boss cho nhiều vàng/xp hơn.",
        "boss_reward_mult": 1.35,
        "boss_bonus_gold": 100,
    },
]


def current_weekly_event(now_ts: int | None = None) -> dict:
    now = datetime.datetime.utcfromtimestamp(now_ts) if now_ts is not None else datetime.datetime.utcnow()
    week_idx = int(now.strftime("%V"))
    event = WEEKLY_EVENTS[week_idx % len(WEEKLY_EVENTS)]
    out = dict(event)
    out["week"] = week_idx
    return out


def event_brief(event: dict) -> str:
    name = str(event.get("name", "Weekly Event"))
    desc = str(event.get("desc", ""))
    return f"{name} - {desc}".strip()
