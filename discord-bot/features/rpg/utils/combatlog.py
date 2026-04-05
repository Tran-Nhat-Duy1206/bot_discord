import os
import urllib.request
import urllib.error


COMBAT_LOG_ENDPOINT = os.getenv("RPG_COMBAT_LOG_ENDPOINT", "https://paste.rs")
COMBAT_LOG_TIMEOUT = int(os.getenv("RPG_COMBAT_LOG_TIMEOUT", "8"))


def build_combat_log_text(user_tag: str, result: dict) -> str:
    lines = []
    lines.append(f"RPG Combat Log - {user_tag}")
    lines.append("=" * 48)
    lines.append(f"Encounters: {result.get('pack', 0)}")
    lines.append(f"Kills: {result.get('kills', 0)}")
    lines.append(f"Slime kills: {result.get('slime_kills', 0)}")
    lines.append(f"Reward: +{result.get('gold', 0)} gold, +{result.get('xp', 0)} xp")
    lines.append(f"HP left: {result.get('hp', 0)}")
    lines.append("")

    encounters = result.get("encounters") or {}
    if isinstance(encounters, dict) and encounters:
        lines.append("Encounter stats:")
        for k, v in sorted(encounters.items(), key=lambda x: x[0]):
            lines.append(f"- {k}: {v}")
        lines.append("")

    drops = result.get("drops") or {}
    if isinstance(drops, dict) and drops:
        lines.append("Drops:")
        for k, v in sorted(drops.items(), key=lambda x: x[0]):
            lines.append(f"- {k}: {v}")
        lines.append("")

    logs = result.get("logs") or []
    lines.append("Turn log:")
    if isinstance(logs, list) and logs:
        for line in logs:
            lines.append(f"- {line}")
    else:
        lines.append("- No details")

    return "\n".join(lines)


def _publish_sync(payload: str) -> str | None:
    endpoint = (COMBAT_LOG_ENDPOINT or "").strip()
    if not endpoint:
        return None

    data = payload.encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={"Content-Type": "text/plain; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=COMBAT_LOG_TIMEOUT) as resp:
            out = resp.read().decode("utf-8", errors="ignore").strip()
            if out.startswith("http://") or out.startswith("https://"):
                return out
            return None
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
        return None


async def publish_combat_log(payload: str) -> str | None:
    import asyncio

    return await asyncio.to_thread(_publish_sync, payload)
