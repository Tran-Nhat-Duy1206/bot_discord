import re
from datetime import datetime, timedelta

from discord import app_commands

from .config import VN_TZ


def parse_due_date_time(date_str: str, time_str: str):
    date_str = date_str.strip()
    time_str = time_str.strip()

    date_formats = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"]
    parsed_date = None

    for fmt in date_formats:
        try:
            parsed_date = datetime.strptime(date_str, fmt)
            break
        except Exception:
            pass

    if parsed_date is None:
        return None

    try:
        parsed_time = datetime.strptime(time_str, "%H:%M")
    except Exception:
        return None

    return datetime(
        year=parsed_date.year,
        month=parsed_date.month,
        day=parsed_date.day,
        hour=parsed_time.hour,
        minute=parsed_time.minute,
        tzinfo=VN_TZ,
    )


def parse_dt_vn(raw_input: str):
    text = raw_input.strip().lower()
    now = datetime.now(VN_TZ)
    rel = re.findall(r"(\d+)\s*([dhm])", text)
    if rel:
        delta = timedelta()
        for number_text, unit in rel:
            number = int(number_text)
            if unit == "d":
                delta += timedelta(days=number)
            elif unit == "h":
                delta += timedelta(hours=number)
            elif unit == "m":
                delta += timedelta(minutes=number)
        return now + delta

    day_shift = None
    if "mốt" in text:
        day_shift = 2
    elif "mai" in text or "ngày mai" in text:
        day_shift = 1
    elif "hôm nay" in text or "nay" in text:
        day_shift = 0

    if day_shift is not None:
        base = (now + timedelta(days=day_shift)).replace(second=0, microsecond=0)
        match_clock = re.search(r"(\d{1,2})\s*:\s*(\d{1,2})", text)
        match_h = re.search(r"(\d{1,2})\s*h(?:\s*(\d{1,2}))?", text)
        if match_clock:
            hour, minute = int(match_clock.group(1)), int(match_clock.group(2))
            return base.replace(hour=hour, minute=minute)
        if match_h:
            hour = int(match_h.group(1))
            minute = int(match_h.group(2) or 0)
            return base.replace(hour=hour, minute=minute)
        return base.replace(hour=9, minute=0)

    formats = [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%d-%m-%Y %H:%M:%S",
        "%H:%M %d/%m/%Y",
        "%H:%M %d-%m-%Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=VN_TZ)
        except Exception:
            pass
    return None


def make_offsets(notify: str):
    if not notify:
        return [timedelta(days=1), timedelta(hours=1), timedelta(minutes=10)]

    out = []
    for part in notify.split(","):
        part = part.strip().lower()
        match = re.fullmatch(r"(\d+)\s*([dhm])", part)
        if not match:
            continue
        number = int(match.group(1))
        unit = match.group(2)
        if unit == "d":
            out.append(timedelta(days=number))
        elif unit == "h":
            out.append(timedelta(hours=number))
        elif unit == "m":
            out.append(timedelta(minutes=number))

    return out or [timedelta(days=1), timedelta(hours=1), timedelta(minutes=10)]


def masked_link(label: str, url: str | None) -> str | None:
    if not url:
        return None
    return f"[{label}]({url})"


async def autocomplete_due_date(interaction, current: str):
    now = datetime.now(VN_TZ)
    picks = [
        now.strftime("%d/%m/%Y"),
        (now + timedelta(days=1)).strftime("%d/%m/%Y"),
        (now + timedelta(days=2)).strftime("%d/%m/%Y"),
        (now + timedelta(days=7)).strftime("%d/%m/%Y"),
        now.strftime("%Y-%m-%d"),
        (now + timedelta(days=1)).strftime("%Y-%m-%d"),
        (now + timedelta(days=2)).strftime("%Y-%m-%d"),
    ]
    normalized = current.strip().lower()
    out = []
    seen = set()
    for item in picks:
        if item in seen:
            continue
        if not normalized or normalized in item.lower():
            out.append(app_commands.Choice(name=item, value=item))
            seen.add(item)
    return out[:25]


async def autocomplete_due_time(interaction, current: str):
    picks = [
        "08:00",
        "09:00",
        "10:00",
        "12:00",
        "14:00",
        "17:00",
        "20:00",
        "21:00",
        "22:00",
        "23:00",
    ]
    normalized = current.strip().lower()
    out = []
    for item in picks:
        if not normalized or normalized in item.lower():
            out.append(app_commands.Choice(name=item, value=item))
    return out[:25]


async def autocomplete_notify(interaction, current: str):
    picks = [
        "1d,1h,10m",
        "1d,12h,1h,10m",
        "12h,1h,10m",
        "6h,1h,10m",
        "1h,30m,10m",
        "30m,10m",
    ]
    normalized = current.strip().lower()
    out = []
    for item in picks:
        if not normalized or normalized in item.lower():
            out.append(app_commands.Choice(name=item, value=item))
    return out[:25]
