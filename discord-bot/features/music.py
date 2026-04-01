import os
import re
import json
import math
import time
import base64
import random
import asyncio
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass
from collections import deque
from typing import Optional, Any, cast

import discord
from discord import app_commands
from discord.ext import commands

try:
    import wavelink
except Exception:
    wavelink = None

try:
    import redis.asyncio as redis_async
except Exception:
    redis_async = None


CompatPlayer: Any = None

if wavelink is not None:
    class CompatPlayer(wavelink.Player):
        async def _dispatch_voice_update(self) -> None:
            guild = getattr(self, "guild", None)
            if guild is None:
                return

            data = self._voice_state.get("voice", {})
            session_id = data.get("session_id", None)
            token = data.get("token", None)
            endpoint = data.get("endpoint", None)

            if not session_id or not token or not endpoint:
                return

            request: Any = {
                "voice": {
                    "sessionId": session_id,
                    "token": token,
                    "endpoint": endpoint,
                    "channelId": str(getattr(getattr(self, "channel", None), "id", "")),
                }
            }

            try:
                await self.node._update_player(guild.id, data=cast(Any, request))
            except Exception:
                await self.disconnect()
            else:
                self._connection_event.set()
else:
    CompatPlayer = None


LAVALINK_URI = os.getenv("LAVALINK_URI", "http://127.0.0.1:2333")
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD", "youshallnotpass")
LAVALINK_NODES = os.getenv("LAVALINK_NODES", "")
LAVALINK_INACTIVE_TIMEOUT = int(os.getenv("LAVALINK_INACTIVE_TIMEOUT", "300"))
LAVALINK_HEALTHCHECK_INTERVAL = int(os.getenv("LAVALINK_HEALTHCHECK_INTERVAL", "30"))
MUSIC_RATE_LIMIT_USER_SEC = float(os.getenv("MUSIC_RATE_LIMIT_USER_SEC", "2.0"))
MUSIC_RATE_LIMIT_GUILD_SEC = float(os.getenv("MUSIC_RATE_LIMIT_GUILD_SEC", "1.0"))
MUSIC_RATE_LIMIT_BYPASS_DJ = os.getenv("MUSIC_RATE_LIMIT_BYPASS_DJ", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
MUSIC_REDIS_URL = os.getenv("MUSIC_REDIS_URL", "")
MUSIC_REDIS_PREFIX = os.getenv("MUSIC_REDIS_PREFIX", "music")
MUSIC_RESOLVE_CACHE_TTL_SEC = int(os.getenv("MUSIC_RESOLVE_CACHE_TTL_SEC", "1800"))
MUSIC_SPOTIFY_CACHE_TTL_SEC = int(os.getenv("MUSIC_SPOTIFY_CACHE_TTL_SEC", "21600"))
MUSIC_GUILD_STATE_TTL_SEC = int(os.getenv("MUSIC_GUILD_STATE_TTL_SEC", "604800"))
MUSIC_CACHE_WARMUP_TRACKS = int(os.getenv("MUSIC_CACHE_WARMUP_TRACKS", "5"))
MUSIC_CACHE_HOT_HITS = int(os.getenv("MUSIC_CACHE_HOT_HITS", "3"))
MUSIC_STATE_PERSIST_INTERVAL_SEC = int(os.getenv("MUSIC_STATE_PERSIST_INTERVAL_SEC", "15"))

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_TOTAL_MAX = int(os.getenv("MUSIC_SPOTIFY_TOTAL_MAX", "300"))
SPOTIFY_PRIME_TRIES = int(os.getenv("MUSIC_SPOTIFY_PRIME_TRIES", "3"))

MUSIC_QUEUE_PAGE_SIZE = int(os.getenv("MUSIC_QUEUE_PAGE_SIZE", "10"))
MUSIC_CONFIG_PATH = os.getenv("MUSIC_CONFIG_PATH", "data/music_config.json")


@dataclass
class QueueTrack:
    playable: Any
    title: str
    duration_sec: int
    source_url: str
    requester_name: str
    origin_url: str = ""
    queued_at: float = 0.0


@dataclass
class MusicMetrics:
    resolve_samples: int = 0
    resolve_total_ms: float = 0.0
    resolve_last_ms: float = 0.0
    queue_wait_samples: int = 0
    queue_wait_total_sec: float = 0.0
    queue_wait_last_sec: float = 0.0
    track_start_count: int = 0
    track_exception_count: int = 0
    node_checks: int = 0
    node_healthy_checks: int = 0
    node_last_connected: int = 0
    node_last_total: int = 0
    node_last_check_ts: float = 0.0
    resolve_cache_hits: int = 0
    resolve_cache_misses: int = 0
    spotify_cache_hits: int = 0
    spotify_cache_misses: int = 0
    queue_restore_guilds: int = 0


class GuildMusicState:
    def __init__(self):
        self.queue: deque[QueueTrack] = deque()
        self.current: Optional[QueueTrack] = None
        self.current_started_at: float = 0.0
        self.loop_one = False
        self.autoplay = False
        self.volume = 1.0
        self.lock = asyncio.Lock()
        self.background_loader_task: Optional[asyncio.Task] = None


GUILD_MUSIC: dict[int, GuildMusicState] = {}
_MUSIC_CONFIG: dict[str, dict] = {}
MUSIC_METRICS = MusicMetrics()
_MUSIC_RATELIMIT_LAST: dict[str, float] = {}
_MUSIC_RESOLVE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_MUSIC_SPOTIFY_CACHE_LOCAL: dict[str, tuple[float, list[str]]] = {}
_MUSIC_SPOTIFY_HOT_COUNTER: dict[str, int] = {}
_MUSIC_REDIS_CLIENT: Any = None
logger = logging.getLogger("bot.music")


def _embed(title: str, description: str, color: discord.Color = discord.Color.blurple()) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color)


def _fmt_duration(seconds: int) -> str:
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h > 0:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def _progress_bar(elapsed: int, total: int, width: int = 14) -> str:
    total = max(1, int(total))
    elapsed = max(0, min(int(elapsed), total))
    filled = int((elapsed / total) * width)
    return "[" + ("=" * filled) + "•" + ("-" * max(0, width - filled - 1)) + "]"


def _state(guild_id: int) -> GuildMusicState:
    if guild_id not in GUILD_MUSIC:
        st = GuildMusicState()
        cfg = _guild_cfg(guild_id)
        st.autoplay = bool(cfg.get("autoplay", False))
        vol = int(cfg.get("volume", 100) or 100)
        st.volume = max(0.0, min(2.0, vol / 100.0))
        GUILD_MUSIC[guild_id] = st
    return GUILD_MUSIC[guild_id]


def _load_music_config():
    global _MUSIC_CONFIG
    try:
        if not os.path.exists(MUSIC_CONFIG_PATH):
            _MUSIC_CONFIG = {}
            return
        with open(MUSIC_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        _MUSIC_CONFIG = data if isinstance(data, dict) else {}
    except Exception:
        _MUSIC_CONFIG = {}


def _save_music_config():
    try:
        parent = os.path.dirname(MUSIC_CONFIG_PATH)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(MUSIC_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(_MUSIC_CONFIG, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _guild_cfg(guild_id: int) -> dict:
    key = str(guild_id)
    cfg = _MUSIC_CONFIG.get(key)
    if not isinstance(cfg, dict):
        cfg = {"dj_role_id": 0, "autoplay": False, "volume": 100}
        _MUSIC_CONFIG[key] = cfg
    return cfg


def _parse_lavalink_nodes() -> list[tuple[str, str]]:
    raw = (LAVALINK_NODES or "").strip()
    if not raw:
        return [(LAVALINK_URI, LAVALINK_PASSWORD)]

    pairs: list[tuple[str, str]] = []
    chunks = re.split(r"[\n;,]+", raw)
    for entry in chunks:
        item = entry.strip()
        if not item:
            continue

        uri = item
        pwd = LAVALINK_PASSWORD
        if "|" in item:
            left, right = item.split("|", 1)
            uri = left.strip()
            pwd = (right or "").strip() or LAVALINK_PASSWORD
        if uri:
            pairs.append((uri, pwd))

    return pairs or [(LAVALINK_URI, LAVALINK_PASSWORD)]


def _metrics_add_resolve(ms: float):
    MUSIC_METRICS.resolve_samples += 1
    MUSIC_METRICS.resolve_total_ms += max(0.0, ms)
    MUSIC_METRICS.resolve_last_ms = max(0.0, ms)


def _metrics_add_queue_wait(sec: float):
    MUSIC_METRICS.queue_wait_samples += 1
    MUSIC_METRICS.queue_wait_total_sec += max(0.0, sec)
    MUSIC_METRICS.queue_wait_last_sec = max(0.0, sec)


def _metrics_update_node_health(total: int, connected: int):
    MUSIC_METRICS.node_checks += 1
    if connected > 0:
        MUSIC_METRICS.node_healthy_checks += 1
    MUSIC_METRICS.node_last_total = max(0, total)
    MUSIC_METRICS.node_last_connected = max(0, connected)
    MUSIC_METRICS.node_last_check_ts = time.time()


def _redis_on() -> bool:
    return bool(MUSIC_REDIS_URL and redis_async is not None)


def _redis_key(kind: str, key: str) -> str:
    return f"{MUSIC_REDIS_PREFIX}:{kind}:{key}"


async def _redis_client():
    global _MUSIC_REDIS_CLIENT
    if not _redis_on():
        return None
    if _MUSIC_REDIS_CLIENT is not None:
        return _MUSIC_REDIS_CLIENT
    try:
        _MUSIC_REDIS_CLIENT = redis_async.from_url(MUSIC_REDIS_URL, decode_responses=True)
        return _MUSIC_REDIS_CLIENT
    except Exception as e:
        logger.warning("Redis init failed: %s", e)
        _MUSIC_REDIS_CLIENT = None
        return None


async def _redis_get_json(kind: str, key: str) -> Any:
    c = await _redis_client()
    if c is None:
        return None
    try:
        data = await c.get(_redis_key(kind, key))
        if not data:
            return None
        return json.loads(data)
    except Exception:
        return None


async def _redis_set_json(kind: str, key: str, value: Any, ttl_sec: int = 0):
    c = await _redis_client()
    if c is None:
        return
    try:
        payload = json.dumps(value, ensure_ascii=False)
        if ttl_sec > 0:
            await c.set(_redis_key(kind, key), payload, ex=int(ttl_sec))
        else:
            await c.set(_redis_key(kind, key), payload)
    except Exception:
        return


async def _redis_del(kind: str, key: str):
    c = await _redis_client()
    if c is None:
        return
    try:
        await c.delete(_redis_key(kind, key))
    except Exception:
        return


async def _redis_scan_delete(pattern: str):
    c = await _redis_client()
    if c is None:
        return 0
    deleted = 0
    try:
        async for k in c.scan_iter(match=pattern):
            await c.delete(k)
            deleted += 1
    except Exception:
        return deleted
    return deleted


def _cache_compact_local():
    now = time.time()
    for key, item in list(_MUSIC_RESOLVE_CACHE.items()):
        if now >= item[0]:
            _MUSIC_RESOLVE_CACHE.pop(key, None)
    for key, item in list(_MUSIC_SPOTIFY_CACHE_LOCAL.items()):
        if now >= item[0]:
            _MUSIC_SPOTIFY_CACHE_LOCAL.pop(key, None)


def _track_payload_from_playable(playable: Any) -> dict[str, Any] | None:
    try:
        raw = getattr(playable, "raw_data", None)
        if isinstance(raw, dict) and raw:
            return raw
    except Exception:
        return None
    return None


def _playable_from_payload(payload: Any):
    if wavelink is None or not isinstance(payload, dict):
        return None
    try:
        return wavelink.Playable(payload)
    except Exception:
        return None


def _queue_track_to_payload(track: QueueTrack) -> dict[str, Any] | None:
    raw = _track_payload_from_playable(track.playable)
    if raw is None:
        return None
    return {
        "raw": raw,
        "title": track.title,
        "duration_sec": int(track.duration_sec),
        "source_url": track.source_url,
        "requester_name": track.requester_name,
        "origin_url": track.origin_url,
        "queued_at": float(track.queued_at or time.time()),
    }


def _queue_track_from_payload(data: Any) -> QueueTrack | None:
    if not isinstance(data, dict):
        return None
    playable = _playable_from_payload(data.get("raw"))
    if playable is None:
        return None
    return QueueTrack(
        playable=playable,
        title=str(data.get("title") or getattr(playable, "title", "Unknown title")),
        duration_sec=int(data.get("duration_sec") or (int(getattr(playable, "length", 0) or 0) // 1000)),
        source_url=str(data.get("source_url") or getattr(playable, "uri", "")),
        requester_name=str(data.get("requester_name") or "Unknown"),
        origin_url=str(data.get("origin_url") or ""),
        queued_at=float(data.get("queued_at") or time.time()),
    )


async def _persist_guild_state(guild_id: int):
    if not _redis_on():
        return
    st = _state(guild_id)
    async with st.lock:
        queue_data = []
        for tr in st.queue:
            p = _queue_track_to_payload(tr)
            if p is not None:
                queue_data.append(p)

        current_data = _queue_track_to_payload(st.current) if st.current is not None else None
        payload = {
            "queue": queue_data,
            "current": current_data,
            "loop_one": bool(st.loop_one),
            "autoplay": bool(st.autoplay),
            "volume": float(st.volume),
            "saved_at": time.time(),
        }

    await _redis_set_json("guild_state", str(guild_id), payload, MUSIC_GUILD_STATE_TTL_SEC)


async def _restore_guild_state(guild_id: int) -> bool:
    data = await _redis_get_json("guild_state", str(guild_id))
    if not isinstance(data, dict):
        return False

    st = _state(guild_id)
    restored_queue: deque[QueueTrack] = deque()

    queue_items = data.get("queue")
    if isinstance(queue_items, list):
        for item in queue_items:
            tr = _queue_track_from_payload(item)
            if tr is not None:
                restored_queue.append(tr)

    current = _queue_track_from_payload(data.get("current"))

    async with st.lock:
        st.queue = restored_queue
        if current is not None:
            st.queue.appendleft(current)
            st.current = None
        else:
            st.current = None
        st.current_started_at = 0.0
        st.loop_one = bool(data.get("loop_one", st.loop_one))
        st.autoplay = bool(data.get("autoplay", st.autoplay))
        st.volume = max(0.0, min(2.0, float(data.get("volume", st.volume))))

    return True


def _is_dj_or_admin(interaction: discord.Interaction) -> bool:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        return False
    if interaction.user.guild_permissions.administrator:
        return True
    role_id = int(_guild_cfg(interaction.guild.id).get("dj_role_id", 0) or 0)
    if role_id <= 0:
        return True
    return any(r.id == role_id for r in interaction.user.roles)


def _is_spotify_url(value: str) -> bool:
    s = (value or "").lower()
    return "open.spotify.com/" in s or s.startswith("spotify:")


def _normalize_spotify_url(value: str) -> str:
    raw = (value or "").strip()
    if raw.startswith("spotify:"):
        parts = raw.split(":")
        if len(parts) >= 3:
            return f"https://open.spotify.com/{parts[1]}/{parts[2]}"
        return raw

    try:
        p = urllib.parse.urlparse(raw)
        if "open.spotify.com" not in (p.netloc or ""):
            return raw
        return urllib.parse.urlunparse((p.scheme or "https", p.netloc, p.path, "", "", ""))
    except Exception:
        return raw


def _spotify_kind(value: str) -> str:
    s = _normalize_spotify_url(value).lower()
    if "/playlist/" in s:
        return "playlist"
    if "/album/" in s:
        return "album"
    if "/track/" in s:
        return "track"
    return "other"


def _spotify_oembed_title(url: str) -> str | None:
    endpoint = "https://open.spotify.com/oembed?url=" + urllib.parse.quote(_normalize_spotify_url(url), safe="")
    try:
        with urllib.request.urlopen(endpoint, timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
        title = payload.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
    except Exception:
        return None
    return None


def _spotify_api_token() -> str | None:
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        return None
    creds = f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode("utf-8")
    b64 = base64.b64encode(creds).decode("ascii")
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("utf-8")
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=body,
        headers={
            "Authorization": f"Basic {b64}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
        token = payload.get("access_token")
        if isinstance(token, str) and token:
            return token
    except Exception:
        return None
    return None


def _spotify_id_from_url(url: str) -> tuple[str, str] | tuple[None, None]:
    try:
        p = urllib.parse.urlparse(_normalize_spotify_url(url))
        parts = [x for x in (p.path or "").split("/") if x]
        if len(parts) >= 2 and parts[0] in {"playlist", "album", "track"}:
            return parts[0], parts[1]
    except Exception:
        pass
    return None, None


def _spotify_tracks_via_api(url: str) -> list[str]:
    token = _spotify_api_token()
    if not token:
        return []

    kind, sid = _spotify_id_from_url(url)
    if kind not in {"playlist", "album"} or not sid:
        return []

    names: list[str] = []
    offset = 0
    cap = max(1, SPOTIFY_TOTAL_MAX)

    while len(names) < cap:
        if kind == "playlist":
            endpoint = f"https://api.spotify.com/v1/playlists/{sid}/tracks?limit=100&offset={offset}"
        else:
            endpoint = f"https://api.spotify.com/v1/albums/{sid}/tracks?limit=50&offset={offset}"

        req = urllib.request.Request(endpoint, headers={"Authorization": f"Bearer {token}"}, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
        except Exception:
            break

        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list) or not items:
            break

        for item in items:
            if not isinstance(item, dict):
                continue
            node = item.get("track") if kind == "playlist" else item
            if not isinstance(node, dict):
                continue
            tname = node.get("name")
            artists = node.get("artists")
            if not isinstance(tname, str) or not tname.strip():
                continue
            artist = ""
            if isinstance(artists, list) and artists:
                f = artists[0]
                if isinstance(f, dict) and isinstance(f.get("name"), str):
                    artist = f["name"]
            names.append(f"{tname} {artist}".strip())
            if len(names) >= cap:
                break

        offset += len(items)

    return names


async def _spotify_tracks_cached(url: str) -> list[str]:
    norm = _normalize_spotify_url(url)
    key = norm.lower()
    _cache_compact_local()

    local = _MUSIC_SPOTIFY_CACHE_LOCAL.get(key)
    if local and time.time() < local[0]:
        MUSIC_METRICS.spotify_cache_hits += 1
        return list(local[1])

    redis_hit = await _redis_get_json("spotify_playlist", key)
    if isinstance(redis_hit, list):
        items = [str(x).strip() for x in redis_hit if isinstance(x, str) and str(x).strip()]
        if items:
            MUSIC_METRICS.spotify_cache_hits += 1
            _MUSIC_SPOTIFY_CACHE_LOCAL[key] = (time.time() + max(1, MUSIC_SPOTIFY_CACHE_TTL_SEC), items)
            return list(items)

    MUSIC_METRICS.spotify_cache_misses += 1
    names = await asyncio.to_thread(_spotify_tracks_via_api, norm)
    if names:
        ttl = max(1, MUSIC_SPOTIFY_CACHE_TTL_SEC)
        _MUSIC_SPOTIFY_CACHE_LOCAL[key] = (time.time() + ttl, list(names))
        await _redis_set_json("spotify_playlist", key, names, ttl)
    return names


def _playlist_invalidation_policy() -> str:
    return (
        f"resolve_ttl={max(1, MUSIC_RESOLVE_CACHE_TTL_SEC)}s, "
        f"spotify_ttl={max(1, MUSIC_SPOTIFY_CACHE_TTL_SEC)}s, "
        f"hot_threshold={max(1, MUSIC_CACHE_HOT_HITS)}, "
        f"warmup_tracks={max(0, MUSIC_CACHE_WARMUP_TRACKS)}"
    )


async def _maybe_warmup_playlist(url: str, titles: list[str]):
    if not titles or MUSIC_CACHE_WARMUP_TRACKS <= 0:
        return
    norm = _normalize_spotify_url(url).lower()
    hits = _MUSIC_SPOTIFY_HOT_COUNTER.get(norm, 0) + 1
    _MUSIC_SPOTIFY_HOT_COUNTER[norm] = hits
    if hits < max(1, MUSIC_CACHE_HOT_HITS):
        return

    _MUSIC_SPOTIFY_HOT_COUNTER[norm] = 0
    sample = titles[: max(1, MUSIC_CACHE_WARMUP_TRACKS)]
    for name in sample:
        try:
            await _wavelink_search_first(f"ytsearch:{name}")
        except Exception:
            continue


async def _wavelink_search_first(query: str):
    if wavelink is None:
        raise RuntimeError("Thiếu wavelink. Cài bằng: pip install wavelink")

    q = (query or "").strip()
    cache_key = q.lower()
    _cache_compact_local()

    local = _MUSIC_RESOLVE_CACHE.get(cache_key)
    if local and time.time() < local[0]:
        MUSIC_METRICS.resolve_cache_hits += 1
        p = _playable_from_payload(local[1])
        if p is not None:
            return p

    redis_hit = await _redis_get_json("resolve", cache_key)
    if isinstance(redis_hit, dict):
        p = _playable_from_payload(redis_hit)
        if p is not None:
            MUSIC_METRICS.resolve_cache_hits += 1
            _MUSIC_RESOLVE_CACHE[cache_key] = (time.time() + max(1, MUSIC_RESOLVE_CACHE_TTL_SEC), redis_hit)
            return p

    MUSIC_METRICS.resolve_cache_misses += 1

    src = None
    low = q.lower()
    if low.startswith("ytsearch:"):
        q = q[len("ytsearch:") :].strip()
        src = getattr(wavelink.TrackSource, "YouTube", None)
    elif low.startswith("ytmsearch:"):
        q = q[len("ytmsearch:") :].strip()
        src = getattr(wavelink.TrackSource, "YouTubeMusic", None)
    elif low.startswith("scsearch:"):
        q = q[len("scsearch:") :].strip()
        src = getattr(wavelink.TrackSource, "SoundCloud", None)

    if src is not None:
        result = await wavelink.Playable.search(q, source=src)
    else:
        result = await wavelink.Playable.search(q)

    if not result:
        return None

    first = None
    if isinstance(result, list):
        first = result[0]
    else:
        try:
            first = result[0]
        except Exception:
            for x in result:
                first = x
                break

    if first is None:
        return None

    payload = _track_payload_from_playable(first)
    if payload is not None:
        ttl = max(1, MUSIC_RESOLVE_CACHE_TTL_SEC)
        _MUSIC_RESOLVE_CACHE[cache_key] = (time.time() + ttl, payload)
        await _redis_set_json("resolve", cache_key, payload, ttl)
    return first


def _track_from_playable(playable: Any, requester_name: str, origin_url: str = "") -> QueueTrack:
    title = str(getattr(playable, "title", "Unknown title"))
    uri = str(getattr(playable, "uri", ""))
    length_ms = int(getattr(playable, "length", 0) or 0)
    duration_sec = max(0, length_ms // 1000)
    return QueueTrack(
        playable=playable,
        title=title,
        duration_sec=duration_sec,
        source_url=uri,
        requester_name=requester_name,
        origin_url=origin_url,
        queued_at=time.time(),
    )


async def _resolve_non_spotify(query: str, requester_name: str) -> list[QueueTrack]:
    q = query
    if _is_spotify_url(q) and _spotify_kind(q) == "track":
        title = _spotify_oembed_title(q) or q
        q = f"ytsearch:{title}"

    playable = await _wavelink_search_first(q)
    if playable is None:
        return []
    return [_track_from_playable(playable, requester_name, _normalize_spotify_url(query))]


async def _resolve_spotify_titles_fast(titles: list[str], requester_name: str, origin_url: str) -> tuple[list[QueueTrack], list[str]]:
    if not titles:
        return [], []

    first: list[QueueTrack] = []
    used_idx = -1
    tries = max(1, min(SPOTIFY_PRIME_TRIES, len(titles)))
    for i in range(tries):
        p = await _wavelink_search_first(f"ytsearch:{titles[i]}")
        if p is None:
            continue
        first = [_track_from_playable(p, requester_name, origin_url)]
        used_idx = i
        break

    if not first:
        return [], titles

    pending = [t for i, t in enumerate(titles) if i != used_idx]
    return first, pending


async def _background_enqueue_titles(guild_id: int, titles: list[str], requester_name: str, origin_url: str):
    if not titles:
        return
    st = _state(guild_id)
    chunk = 6
    for i in range(0, len(titles), chunk):
        c = titles[i : i + chunk]
        resolved: list[QueueTrack] = []
        for name in c:
            p = await _wavelink_search_first(f"ytsearch:{name}")
            if p is None:
                continue
            resolved.append(_track_from_playable(p, requester_name, origin_url))
        if not resolved:
            continue
        async with st.lock:
            for tr in resolved:
                st.queue.append(tr)
        await _persist_guild_state(guild_id)


def _format_now_line(player: Any, st: GuildMusicState) -> str:
    if st.current is None:
        return "▶️ **Now:** (none)"

    elapsed = 0
    if st.current_started_at > 0:
        elapsed = int(time.time() - st.current_started_at)
    duration = max(1, int(st.current.duration_sec or 0))
    elapsed = min(elapsed, duration)
    bar = _progress_bar(elapsed, duration)
    paused = False
    try:
        paused = bool(player.paused)
    except Exception:
        pass
    ico = "⏸️" if paused else "▶️"
    return f"{ico} **Now:** {st.current.title}\n`{_fmt_duration(elapsed)} {bar} {_fmt_duration(duration)}`"


async def _ensure_node(bot: commands.Bot):
    if wavelink is None:
        raise RuntimeError("Thiếu wavelink. Cài bằng: pip install wavelink")
    try:
        if getattr(wavelink.Pool, "nodes", None):
            if len(wavelink.Pool.nodes) > 0:
                return
    except Exception:
        pass

    specs = _parse_lavalink_nodes()
    nodes: list[Any] = []
    for i, (uri, password) in enumerate(specs, start=1):
        nodes.append(
            wavelink.Node(
                identifier=f"node-{i}",
                uri=uri,
                password=password,
                inactive_player_timeout=LAVALINK_INACTIVE_TIMEOUT,
            )
        )

    await wavelink.Pool.connect(nodes=nodes, client=bot)


def _is_node_connected(node: Any) -> bool:
    status = getattr(node, "status", None)
    name = str(getattr(status, "name", "")).upper()
    if name:
        return name == "CONNECTED"
    return str(status).upper().endswith("CONNECTED")


def _node_status_lines() -> tuple[int, int, list[str]]:
    if wavelink is None:
        return 0, 0, ["wavelink chưa được cài."]

    nodes = getattr(wavelink.Pool, "nodes", {}) or {}
    if not nodes:
        return 0, 0, ["Chưa có node Lavalink trong pool."]

    lines: list[str] = []
    connected = 0
    for identifier, node in nodes.items():
        ok = _is_node_connected(node)
        if ok:
            connected += 1
        status = getattr(getattr(node, "status", None), "name", str(getattr(node, "status", "UNKNOWN")))
        players = len(getattr(node, "players", {}) or {})
        marker = "🟢" if ok else "🔴"
        lines.append(f"{marker} `{identifier}` • {status} • players={players}")
    return len(nodes), connected, lines


def _voice_perm_issue(member: discord.Member, channel: discord.VoiceChannel | discord.StageChannel) -> str | None:
    perms = channel.permissions_for(member)
    missing: list[str] = []
    if not perms.connect:
        missing.append("Connect")
    if not perms.speak and isinstance(channel, discord.VoiceChannel):
        missing.append("Speak")
    if missing:
        return ", ".join(missing)
    return None


async def _play_next(bot: commands.Bot, guild: discord.Guild, player: Any):
    st = _state(guild.id)

    async with st.lock:
        if st.current and st.loop_one:
            nxt = st.current
        else:
            nxt = st.queue.popleft() if st.queue else None
            st.current = nxt

    if nxt is None:
        if st.autoplay and st.current is not None:
            q = f"ytsearch:{st.current.title} audio"
            p = await _wavelink_search_first(q)
            if p is not None:
                nxt = _track_from_playable(p, st.current.requester_name, st.current.origin_url)
                async with st.lock:
                    st.current = nxt

    if nxt is None:
        async with st.lock:
            st.current = None
            st.current_started_at = 0.0
        await _persist_guild_state(guild.id)
        return

    st.current_started_at = time.time()
    wait_sec = max(0.0, st.current_started_at - float(getattr(nxt, "queued_at", st.current_started_at) or st.current_started_at))
    _metrics_add_queue_wait(wait_sec)
    try:
        await player.play(nxt.playable)
    except Exception as e:
        logger.warning("Play failed in guild %s for track '%s': %s", guild.id, nxt.title, e)
        return

    try:
        await player.set_volume(int(max(0.0, min(2.0, st.volume)) * 100))
    except Exception:
        pass

    await _persist_guild_state(guild.id)


def setup(bot: commands.Bot):
    _load_music_config()
    monitor_task: Optional[asyncio.Task] = None
    persist_task: Optional[asyncio.Task] = None
    restored_once = False

    def _build_queue_embed(guild: discord.Guild, page: int) -> tuple[discord.Embed, int]:
        st = _state(guild.id)
        vc = guild.voice_client

        if vc is None:
            return _embed("ℹ️ Không có voice client", "Bot chưa ở voice."), 1

        lines = [_format_now_line(vc, st)]
        q = list(st.queue)
        per_page = max(5, MUSIC_QUEUE_PAGE_SIZE)
        total_pages = max(1, math.ceil(len(q) / per_page))
        page = max(1, min(page, total_pages))

        if q:
            start = (page - 1) * per_page
            end = start + per_page
            for idx, t in enumerate(q[start:end], start=start + 1):
                lines.append(f"`{idx}.` {t.title} `[{_fmt_duration(t.duration_sec)}]` • {t.requester_name}")
        else:
            lines.append("Queue trống.")

        e = _embed("📜 Music Queue", "\n".join(lines))
        e.set_footer(text=f"Loop: {'ON' if st.loop_one else 'OFF'} • Autoplay: {'ON' if st.autoplay else 'OFF'} • Page {page}/{total_pages}")
        return e, total_pages

    class QueuePagerView(discord.ui.View):
        def __init__(self, guild_id: int, page: int = 1):
            super().__init__(timeout=180)
            self.guild_id = guild_id
            self.page = max(1, page)
            self.message: Optional[discord.Message] = None

        def _sync_buttons(self, total_pages: int):
            self.prev_btn.disabled = self.page <= 1
            self.next_btn.disabled = self.page >= total_pages

        async def _refresh_page(self, interaction: discord.Interaction):
            if interaction.guild is None or interaction.guild.id != self.guild_id:
                return await interaction.response.send_message("❌ View không hợp lệ cho server này.", ephemeral=True)

            embed, total_pages = _build_queue_embed(interaction.guild, self.page)
            self.page = max(1, min(self.page, total_pages))
            self._sync_buttons(total_pages)
            await interaction.response.edit_message(embed=embed, view=self)

        async def on_timeout(self):
            for child in self.children:
                if hasattr(child, "disabled"):
                    setattr(child, "disabled", True)
            if self.message is not None:
                try:
                    await self.message.edit(view=self)
                except Exception:
                    pass

        @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
        async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.page -= 1
            await self._refresh_page(interaction)

        @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
        async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.page += 1
            await self._refresh_page(interaction)

    async def _require_dj(interaction: discord.Interaction) -> bool:
        if _is_dj_or_admin(interaction):
            return True
        await interaction.response.send_message(
            embed=_embed("❌ Không có quyền", "Bạn cần DJ role hoặc quyền Admin để dùng lệnh này."),
            ephemeral=True,
        )
        return False

    async def _rate_limit_guard(interaction: discord.Interaction, action: str) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return True
        if MUSIC_RATE_LIMIT_BYPASS_DJ and _is_dj_or_admin(interaction):
            return True

        now = time.monotonic()
        guild_id = interaction.guild.id
        user_id = interaction.user.id

        user_wait = max(0.0, MUSIC_RATE_LIMIT_USER_SEC)
        guild_wait = max(0.0, MUSIC_RATE_LIMIT_GUILD_SEC)

        ukey = f"u:{guild_id}:{user_id}:{action}"
        gkey = f"g:{guild_id}:{action}"

        remain_user = max(0.0, user_wait - (now - _MUSIC_RATELIMIT_LAST.get(ukey, 0.0)))
        remain_guild = max(0.0, guild_wait - (now - _MUSIC_RATELIMIT_LAST.get(gkey, 0.0)))
        remain = max(remain_user, remain_guild)

        if remain > 0:
            txt = f"Lệnh đang cooldown, thử lại sau **{remain:.1f}s**."
            await interaction.response.send_message(embed=_embed("⏱️ Rate limit", txt), ephemeral=True)
            return False

        _MUSIC_RATELIMIT_LAST[ukey] = now
        _MUSIC_RATELIMIT_LAST[gkey] = now
        return True

    async def _monitor_lavalink():
        last_connected: Optional[bool] = None
        while not bot.is_closed():
            try:
                await _ensure_node(bot)
                total, connected, _ = _node_status_lines()
                _metrics_update_node_health(total, connected)
                healthy = connected > 0

                if not healthy and total > 0 and wavelink is not None:
                    pool = getattr(wavelink, "Pool", None)
                    if pool is not None:
                        await pool.reconnect()
                    _, connected_after, _ = _node_status_lines()
                    healthy = connected_after > 0

                if last_connected is None or healthy != last_connected:
                    if healthy:
                        logger.info("Lavalink healthy: %s/%s nodes connected", connected, total)
                    else:
                        logger.warning("Lavalink unhealthy: 0/%s nodes connected", total)
                    last_connected = healthy
            except Exception as e:
                logger.warning("Lavalink monitor error: %s", e)

            await asyncio.sleep(max(10, LAVALINK_HEALTHCHECK_INTERVAL))

    async def _persist_state_loop():
        while not bot.is_closed():
            try:
                if _redis_on():
                    for gid in list(GUILD_MUSIC.keys()):
                        await _persist_guild_state(gid)
            except Exception as e:
                logger.warning("Music persist loop error: %s", e)
            await asyncio.sleep(max(10, MUSIC_STATE_PERSIST_INTERVAL_SEC))

    async def _restore_all_states_once():
        nonlocal restored_once
        if restored_once or not _redis_on():
            return
        restored = 0
        for g in bot.guilds:
            try:
                ok = await _restore_guild_state(g.id)
                if ok:
                    restored += 1
            except Exception:
                continue
        if restored > 0:
            MUSIC_METRICS.queue_restore_guilds += restored
            logger.info("Restored music queue states for %s guild(s)", restored)
        restored_once = True

    @bot.listen("on_ready")
    async def _music_on_ready():
        nonlocal monitor_task, persist_task
        try:
            await _ensure_node(bot)
        except Exception as e:
            logger.warning("music node connect failed: %s", e)

        await _restore_all_states_once()

        if monitor_task is None or monitor_task.done():
            monitor_task = asyncio.create_task(_monitor_lavalink())
        if persist_task is None or persist_task.done():
            persist_task = asyncio.create_task(_persist_state_loop())

    @bot.listen("on_wavelink_track_end")
    async def _on_track_end(payload):
        player = getattr(payload, "player", None)
        if player is None:
            return
        guild = getattr(player, "guild", None)
        if guild is None:
            return
        await _play_next(bot, guild, player)

    @bot.listen("on_wavelink_track_exception")
    async def _on_track_exception(payload):
        exc = getattr(payload, "exception", None)
        MUSIC_METRICS.track_exception_count += 1
        player = getattr(payload, "player", None)
        guild = getattr(player, "guild", None)
        gid = getattr(guild, "id", "unknown")
        logger.warning("Track exception in guild %s: %s", gid, exc)

    @bot.listen("on_wavelink_track_start")
    async def _on_track_start(payload):
        MUSIC_METRICS.track_start_count += 1
        player = getattr(payload, "player", None)
        guild = getattr(player, "guild", None)
        track = getattr(payload, "track", None)
        title = str(getattr(track, "title", "Unknown"))
        gid = getattr(guild, "id", "unknown")
        logger.info("Track started in guild %s: %s", gid, title)

    @bot.tree.command(name="join", description="Vào voice channel của bạn")
    async def join(interaction: discord.Interaction):
        if wavelink is None:
            return await interaction.response.send_message(embed=_embed("❌ Thiếu wavelink", "Cài: `pip install wavelink`"), ephemeral=True)
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(embed=_embed("❌ Không hợp lệ", "Chỉ dùng trong server."), ephemeral=True)
        if interaction.user.voice is None or interaction.user.voice.channel is None:
            return await interaction.response.send_message(embed=_embed("❌ Chưa vào voice", "Bạn cần vào voice channel trước."), ephemeral=True)
        if not await _rate_limit_guard(interaction, "join"):
            return

        ch = interaction.user.voice.channel
        me = interaction.guild.me
        if me is None:
            return await interaction.response.send_message(embed=_embed("❌ Không tìm thấy bot member", "Thử lại sau vài giây."), ephemeral=True)
        miss = _voice_perm_issue(me, ch)
        if miss:
            return await interaction.response.send_message(
                embed=_embed("❌ Thiếu quyền voice", f"Bot thiếu quyền: **{miss}** ở {ch.mention}."),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        await _ensure_node(bot)
        vc = interaction.guild.voice_client
        try:
            if vc is None:
                await ch.connect(cls=CompatPlayer)
            elif getattr(vc, "channel", None) != ch:
                await vc.move_to(ch)
        except Exception as e:
            msg = str(e)
            if "ChannelTimeoutException" in type(e).__name__ or "exceeded the timeout" in msg.lower():
                msg = (
                    "Kết nối voice bị timeout. Kiểm tra bot có quyền Connect/Speak,"
                    " thử đổi voice channel hoặc restart Lavalink/bot."
                )
            return await interaction.followup.send(embed=_embed("❌ Không thể join", msg, discord.Color.red()), ephemeral=True)

        await interaction.followup.send(embed=_embed("🎧 Connected", f"Đã vào {ch.mention}"), ephemeral=True)

    async def _add_tracks(interaction: discord.Interaction, query: str, insert_front: bool):
        if wavelink is None:
            return await interaction.response.send_message(embed=_embed("❌ Thiếu wavelink", "Cài: `pip install wavelink`"), ephemeral=True)
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(embed=_embed("❌ Không hợp lệ", "Chỉ dùng trong server."), ephemeral=True)
        if interaction.user.voice is None or interaction.user.voice.channel is None:
            return await interaction.response.send_message(embed=_embed("❌ Chưa vào voice", "Bạn cần vào voice channel trước."), ephemeral=True)
        if not await _rate_limit_guard(interaction, "playnext" if insert_front else "play"):
            return

        me = interaction.guild.me
        if me is not None:
            miss = _voice_perm_issue(me, interaction.user.voice.channel)
            if miss:
                return await interaction.response.send_message(
                    embed=_embed("❌ Thiếu quyền voice", f"Bot thiếu quyền: **{miss}** ở {interaction.user.voice.channel.mention}."),
                    ephemeral=True,
                )

        await interaction.response.defer()
        await _ensure_node(bot)

        vc = interaction.guild.voice_client
        if vc is None:
            try:
                vc = await interaction.user.voice.channel.connect(cls=CompatPlayer)
            except Exception as e:
                return await interaction.followup.send(embed=_embed("❌ Join voice thất bại", f"Lỗi: `{e}`", discord.Color.red()), ephemeral=True)

        st = _state(interaction.guild.id)
        norm = _normalize_spotify_url(query)
        is_collection = _is_spotify_url(norm) and _spotify_kind(norm) in {"playlist", "album"}
        resolve_started = time.perf_counter()

        try:
            if is_collection:
                titles = await _spotify_tracks_cached(norm)
                if not titles:
                    return await interaction.followup.send(
                        embed=_embed("❌ Không đọc được playlist/album", "Cần SPOTIFY_CLIENT_ID/SPOTIFY_CLIENT_SECRET hợp lệ trong .env.", discord.Color.red()),
                        ephemeral=True,
                    )
                asyncio.create_task(_maybe_warmup_playlist(norm, titles))
                first_tracks, pending = await _resolve_spotify_titles_fast(titles, interaction.user.display_name, norm)
                tracks = first_tracks
            else:
                tracks = await _resolve_non_spotify(query, interaction.user.display_name)
                pending = []
        except Exception as e:
            return await interaction.followup.send(embed=_embed("❌ Không lấy được bài", str(e), discord.Color.red()), ephemeral=True)
        finally:
            _metrics_add_resolve((time.perf_counter() - resolve_started) * 1000.0)

        if not tracks:
            return await interaction.followup.send(embed=_embed("❌ Không có bài hợp lệ", "Không tìm thấy track để phát."), ephemeral=True)

        async with st.lock:
            before = len(st.queue)
            if insert_front:
                for t in reversed(tracks):
                    st.queue.appendleft(t)
            else:
                for t in tracks:
                    st.queue.append(t)
            after = len(st.queue)

        await _persist_guild_state(interaction.guild.id)

        try:
            is_playing = bool(vc.playing)
            is_paused = bool(vc.paused)
        except Exception:
            is_playing = False
            is_paused = False
        if not is_playing and not is_paused:
            await _play_next(bot, interaction.guild, vc)

        if len(tracks) == 1:
            t = tracks[0]
            title = "✅ Đã thêm vào queue" if not insert_front else "⏫ Đã thêm lên đầu queue"
            e = _embed(title, f"**{t.title}**")
            e.add_field(name="Thời lượng", value=_fmt_duration(t.duration_sec), inline=True)
            e.add_field(name="Yêu cầu bởi", value=t.requester_name, inline=True)
            e.add_field(name="Queue", value=f"{before + 1} -> {after}", inline=True)
            e.add_field(name="Nguồn", value=t.source_url, inline=False)
            if _is_spotify_url(t.origin_url):
                e.add_field(name="Spotify", value=t.origin_url, inline=False)
        else:
            preview = "\n".join(f"`{i+1}.` {x.title}" for i, x in enumerate(tracks[:8]))
            if len(tracks) > 8:
                preview += f"\n... và {len(tracks) - 8} bài nữa"
            title = "✅ Đã thêm playlist/album" if not insert_front else "⏫ Đã chèn playlist/album lên đầu"
            e = _embed(title, preview)
            e.add_field(name="Số bài thêm", value=str(len(tracks)), inline=True)
            e.add_field(name="Queue", value=f"{before + 1} -> {after}", inline=True)
            e.add_field(name="Yêu cầu bởi", value=interaction.user.display_name, inline=True)
            if _is_spotify_url(norm):
                e.add_field(name="Spotify", value=norm, inline=False)

        if pending:
            if st.background_loader_task and not st.background_loader_task.done():
                pass
            st.background_loader_task = asyncio.create_task(
                _background_enqueue_titles(interaction.guild.id, pending, interaction.user.display_name, norm)
            )
            e.add_field(name="Background Load", value=f"Đang nạp thêm **{len(pending)}** bài ở nền...", inline=False)

        await interaction.followup.send(embed=e)

    @bot.tree.command(name="play", description="Phát nhạc từ URL hoặc từ khóa")
    @app_commands.describe(query="YouTube/Spotify URL hoặc từ khóa")
    async def play(interaction: discord.Interaction, query: str):
        await _add_tracks(interaction, query, insert_front=False)

    @bot.tree.command(name="playnext", description="Thêm nhạc vào đầu hàng đợi")
    @app_commands.describe(query="YouTube/Spotify URL hoặc từ khóa")
    async def playnext(interaction: discord.Interaction, query: str):
        await _add_tracks(interaction, query, insert_front=True)

    @bot.tree.command(name="queue", description="Xem hàng đợi nhạc")
    async def queue_cmd(interaction: discord.Interaction, page: int = 1):
        if interaction.guild is None:
            return await interaction.response.send_message(embed=_embed("❌ Không hợp lệ", "Chỉ dùng trong server."), ephemeral=True)
        if not await _rate_limit_guard(interaction, "queue"):
            return

        embed, total_pages = _build_queue_embed(interaction.guild, page)
        view = QueuePagerView(interaction.guild.id, page)
        view._sync_buttons(total_pages)
        await interaction.response.send_message(embed=embed, view=view)
        try:
            view.message = await interaction.original_response()
        except Exception:
            pass

    @bot.tree.command(name="shuffle", description="Trộn ngẫu nhiên queue")
    async def shuffle(interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message(embed=_embed("❌ Không hợp lệ", "Chỉ dùng trong server."), ephemeral=True)
        if not await _rate_limit_guard(interaction, "shuffle"):
            return
        if not await _require_dj(interaction):
            return
        st = _state(interaction.guild.id)
        async with st.lock:
            if len(st.queue) < 2:
                return await interaction.response.send_message(embed=_embed("ℹ️ Queue quá ngắn", "Cần ít nhất 2 bài để shuffle."), ephemeral=True)
            temp = list(st.queue)
            random.shuffle(temp)
            st.queue = deque(temp)
        await interaction.response.send_message(embed=_embed("🔀 Shuffled", "Đã trộn ngẫu nhiên hàng đợi."))
        await _persist_guild_state(interaction.guild.id)

    @bot.tree.command(name="skip", description="Bỏ qua bài hiện tại")
    async def skip(interaction: discord.Interaction):
        if interaction.guild is None or interaction.guild.voice_client is None:
            return await interaction.response.send_message(embed=_embed("❌ Không có voice client", "Bot chưa ở voice."), ephemeral=True)
        if not await _rate_limit_guard(interaction, "skip"):
            return
        if not await _require_dj(interaction):
            return
        vc = interaction.guild.voice_client
        try:
            await vc.skip()
        except Exception:
            try:
                await vc.stop()
            except Exception:
                pass
        await interaction.response.send_message(embed=_embed("⏭️ Skipped", "Đã bỏ qua bài hiện tại."))

    @bot.tree.command(name="pause", description="Tạm dừng nhạc")
    async def pause(interaction: discord.Interaction):
        if interaction.guild is None or interaction.guild.voice_client is None:
            return await interaction.response.send_message(embed=_embed("❌ Không có voice client", "Bot chưa ở voice."), ephemeral=True)
        if not await _rate_limit_guard(interaction, "pause"):
            return
        if not await _require_dj(interaction):
            return
        vc = interaction.guild.voice_client
        try:
            await vc.pause(True)
            await interaction.response.send_message(embed=_embed("⏸️ Paused", "Đã tạm dừng."))
        except Exception:
            await interaction.response.send_message(embed=_embed("ℹ️ Không phát", "Không có bài đang phát để pause."), ephemeral=True)

    @bot.tree.command(name="resume", description="Tiếp tục nhạc")
    async def resume(interaction: discord.Interaction):
        if interaction.guild is None or interaction.guild.voice_client is None:
            return await interaction.response.send_message(embed=_embed("❌ Không có voice client", "Bot chưa ở voice."), ephemeral=True)
        if not await _rate_limit_guard(interaction, "resume"):
            return
        if not await _require_dj(interaction):
            return
        vc = interaction.guild.voice_client
        try:
            await vc.pause(False)
            await interaction.response.send_message(embed=_embed("▶️ Resumed", "Tiếp tục phát nhạc."))
        except Exception:
            await interaction.response.send_message(embed=_embed("ℹ️ Không pause", "Nhạc không ở trạng thái pause."), ephemeral=True)

    @bot.tree.command(name="stop", description="Dừng nhạc và xóa queue")
    async def stop(interaction: discord.Interaction):
        if interaction.guild is None or interaction.guild.voice_client is None:
            return await interaction.response.send_message(embed=_embed("❌ Không có voice client", "Bot chưa ở voice."), ephemeral=True)
        if not await _rate_limit_guard(interaction, "stop"):
            return
        if not await _require_dj(interaction):
            return
        st = _state(interaction.guild.id)
        async with st.lock:
            st.queue.clear()
            st.current = None
            st.current_started_at = 0.0
        vc = interaction.guild.voice_client
        try:
            await vc.stop()
        except Exception:
            pass
        await interaction.response.send_message(embed=_embed("⏹️ Stopped", "Đã dừng phát và xóa queue."))
        await _persist_guild_state(interaction.guild.id)

    @bot.tree.command(name="leave", description="Rời voice channel")
    async def leave(interaction: discord.Interaction):
        if interaction.guild is None or interaction.guild.voice_client is None:
            return await interaction.response.send_message(embed=_embed("❌ Không có voice client", "Bot chưa ở voice."), ephemeral=True)
        if not await _rate_limit_guard(interaction, "leave"):
            return
        if not await _require_dj(interaction):
            return
        st = _state(interaction.guild.id)
        async with st.lock:
            st.queue.clear()
            st.current = None
            st.current_started_at = 0.0
        vc = interaction.guild.voice_client
        try:
            await vc.disconnect()
        except Exception as e:
            return await interaction.response.send_message(embed=_embed("❌ Leave thất bại", f"Lỗi: `{e}`", discord.Color.red()), ephemeral=True)
        await interaction.response.send_message(embed=_embed("👋 Disconnected", "Đã rời voice channel."))
        await _persist_guild_state(interaction.guild.id)

    @bot.tree.command(name="loop", description="Bật/tắt lặp 1 bài")
    @app_commands.describe(enabled="true để bật, false để tắt")
    async def loop(interaction: discord.Interaction, enabled: bool):
        if interaction.guild is None:
            return await interaction.response.send_message(embed=_embed("❌ Không hợp lệ", "Chỉ dùng trong server."), ephemeral=True)
        if not await _rate_limit_guard(interaction, "loop"):
            return
        if not await _require_dj(interaction):
            return
        st = _state(interaction.guild.id)
        st.loop_one = enabled
        await _persist_guild_state(interaction.guild.id)
        await interaction.response.send_message(embed=_embed("🔁 Loop one", f"Trạng thái: **{'ON' if enabled else 'OFF'}**"))

    @bot.tree.command(name="autoplay", description="Bật/tắt autoplay khi queue rỗng")
    @app_commands.describe(enabled="true để bật, false để tắt")
    async def autoplay(interaction: discord.Interaction, enabled: bool):
        if interaction.guild is None:
            return await interaction.response.send_message(embed=_embed("❌ Không hợp lệ", "Chỉ dùng trong server."), ephemeral=True)
        if not await _rate_limit_guard(interaction, "autoplay"):
            return
        if not await _require_dj(interaction):
            return
        st = _state(interaction.guild.id)
        st.autoplay = enabled
        cfg = _guild_cfg(interaction.guild.id)
        cfg["autoplay"] = bool(enabled)
        _save_music_config()
        await _persist_guild_state(interaction.guild.id)
        await interaction.response.send_message(embed=_embed("♾️ Autoplay", f"Trạng thái: **{'ON' if enabled else 'OFF'}**"))

    @bot.tree.command(name="volume", description="Xem/chỉnh volume nhạc")
    @app_commands.describe(level="0-200, để trống để xem")
    async def volume(interaction: discord.Interaction, level: int = -1):
        if interaction.guild is None:
            return await interaction.response.send_message(embed=_embed("❌ Không hợp lệ", "Chỉ dùng trong server."), ephemeral=True)
        if not await _rate_limit_guard(interaction, "volume"):
            return
        st = _state(interaction.guild.id)
        if level < 0:
            return await interaction.response.send_message(embed=_embed("🔊 Volume", f"Hiện tại: **{int(st.volume*100)}%**"), ephemeral=True)
        if not await _require_dj(interaction):
            return
        if level > 200:
            return await interaction.response.send_message(embed=_embed("❌ Volume không hợp lệ", "Chỉ nhận 0-200."), ephemeral=True)
        st.volume = max(0.0, min(2.0, level / 100.0))
        cfg = _guild_cfg(interaction.guild.id)
        cfg["volume"] = int(level)
        _save_music_config()
        await _persist_guild_state(interaction.guild.id)
        vc = interaction.guild.voice_client
        if vc is not None:
            try:
                await vc.set_volume(int(st.volume * 100))
            except Exception:
                pass
        await interaction.response.send_message(embed=_embed("🔊 Volume", f"Đã đặt: **{level}%**"))

    @bot.tree.command(name="lyrics", description="Lấy lyrics bài đang phát")
    async def lyrics(interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message(embed=_embed("❌ Không hợp lệ", "Chỉ dùng trong server."), ephemeral=True)
        if not await _rate_limit_guard(interaction, "lyrics"):
            return
        st = _state(interaction.guild.id)
        if st.current is None:
            return await interaction.response.send_message(embed=_embed("ℹ️ Không có bài", "Hiện không có bài nào đang phát."), ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        title = st.current.title
        artist = ""
        m = re.match(r"\s*(.+?)\s*[-–]\s*(.+?)\s*$", title)
        if m:
            artist = m.group(1).strip()
            title = m.group(2).strip()

        params = {"track_name": title}
        if artist:
            params["artist_name"] = artist
        url = "https://lrclib.net/api/search?" + urllib.parse.urlencode(params)

        text = ""
        try:
            raw = await asyncio.to_thread(lambda: urllib.request.urlopen(url, timeout=10).read().decode("utf-8", errors="ignore"))
            arr = json.loads(raw)
            if isinstance(arr, list) and arr:
                first = arr[0] if isinstance(arr[0], dict) else {}
                text = str(first.get("plainLyrics") or first.get("syncedLyrics") or "")
        except Exception:
            text = ""

        if not text:
            return await interaction.followup.send(embed=_embed("📝 Lyrics", "Không tìm thấy lyrics cho bài hiện tại."), ephemeral=True)

        e = _embed("📝 Lyrics", text[:3800])
        e.add_field(name="Track", value=st.current.title, inline=False)
        await interaction.followup.send(embed=e, ephemeral=True)

    @bot.tree.command(name="set_dj_role", description="Đặt DJ role cho music")
    @app_commands.describe(role="Role được quyền điều khiển nhạc")
    async def set_dj_role(interaction: discord.Interaction, role: discord.Role):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(embed=_embed("❌ Không hợp lệ", "Chỉ dùng trong server."), ephemeral=True)
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message(embed=_embed("❌ Không có quyền", "Cần Manage Server."), ephemeral=True)
        cfg = _guild_cfg(interaction.guild.id)
        cfg["dj_role_id"] = role.id
        _save_music_config()
        await interaction.response.send_message(embed=_embed("🎛️ DJ Role", f"Đã đặt DJ role: {role.mention}"))

    @bot.tree.command(name="clear_dj_role", description="Xóa DJ role restriction")
    async def clear_dj_role(interaction: discord.Interaction):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(embed=_embed("❌ Không hợp lệ", "Chỉ dùng trong server."), ephemeral=True)
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message(embed=_embed("❌ Không có quyền", "Cần Manage Server."), ephemeral=True)
        cfg = _guild_cfg(interaction.guild.id)
        cfg["dj_role_id"] = 0
        _save_music_config()
        await interaction.response.send_message(embed=_embed("🎛️ DJ Role", "Đã tắt DJ role restriction."))

    @bot.tree.command(name="music_health", description="Kiểm tra trạng thái Lavalink node")
    async def music_health(interaction: discord.Interaction):
        if wavelink is None:
            return await interaction.response.send_message(
                embed=_embed("❌ Thiếu wavelink", "Cài: `pip install wavelink`"),
                ephemeral=True,
            )

        total, connected, lines = _node_status_lines()
        desc = "\n".join(lines)
        e = _embed("🩺 Music Health", desc if desc else "Không có dữ liệu node.")
        e.add_field(name="Configured Nodes", value=str(len(_parse_lavalink_nodes())), inline=True)
        e.add_field(name="Redis", value="ON" if _redis_on() else "OFF", inline=True)
        e.add_field(name="Primary URI", value=LAVALINK_URI, inline=False)
        e.add_field(name="Connected", value=f"{connected}/{total}", inline=True)
        e.add_field(name="Healthcheck", value=f"{max(10, LAVALINK_HEALTHCHECK_INTERVAL)}s", inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @bot.tree.command(name="music_metrics", description="Xem metrics music runtime")
    async def music_metrics(interaction: discord.Interaction):
        resolve_avg = (MUSIC_METRICS.resolve_total_ms / MUSIC_METRICS.resolve_samples) if MUSIC_METRICS.resolve_samples else 0.0
        wait_avg = (MUSIC_METRICS.queue_wait_total_sec / MUSIC_METRICS.queue_wait_samples) if MUSIC_METRICS.queue_wait_samples else 0.0
        healthy_ratio = (MUSIC_METRICS.node_healthy_checks / MUSIC_METRICS.node_checks * 100.0) if MUSIC_METRICS.node_checks else 0.0
        checked_ago = int(max(0.0, time.time() - MUSIC_METRICS.node_last_check_ts)) if MUSIC_METRICS.node_last_check_ts > 0 else -1

        lines = [
            f"Node health: **{MUSIC_METRICS.node_last_connected}/{MUSIC_METRICS.node_last_total}**",
            f"Node uptime ratio: **{healthy_ratio:.1f}%** ({MUSIC_METRICS.node_healthy_checks}/{MUSIC_METRICS.node_checks} checks)",
            f"Resolve latency: avg **{resolve_avg:.0f}ms**, last **{MUSIC_METRICS.resolve_last_ms:.0f}ms** ({MUSIC_METRICS.resolve_samples} samples)",
            f"Queue wait: avg **{wait_avg:.1f}s**, last **{MUSIC_METRICS.queue_wait_last_sec:.1f}s** ({MUSIC_METRICS.queue_wait_samples} samples)",
            f"Track start/exceptions: **{MUSIC_METRICS.track_start_count}/{MUSIC_METRICS.track_exception_count}**",
            f"Resolve cache hit/miss: **{MUSIC_METRICS.resolve_cache_hits}/{MUSIC_METRICS.resolve_cache_misses}**",
            f"Spotify cache hit/miss: **{MUSIC_METRICS.spotify_cache_hits}/{MUSIC_METRICS.spotify_cache_misses}**",
            f"Queue restored guilds: **{MUSIC_METRICS.queue_restore_guilds}**",
        ]
        if checked_ago >= 0:
            lines.append(f"Last node check: **{checked_ago}s ago**")

        e = _embed("📈 Music Metrics", "\n".join(lines))
        e.add_field(name="Rate limit", value=f"user={MUSIC_RATE_LIMIT_USER_SEC:.1f}s • guild={MUSIC_RATE_LIMIT_GUILD_SEC:.1f}s", inline=False)
        e.add_field(name="Cache policy", value=_playlist_invalidation_policy(), inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @bot.tree.command(name="music_cache", description="Xem/clear cache music")
    @app_commands.describe(action="info hoặc clear")
    async def music_cache(interaction: discord.Interaction, action: str = "info"):
        act = (action or "info").strip().lower()
        if act not in {"info", "clear"}:
            return await interaction.response.send_message(
                embed=_embed("❌ Action không hợp lệ", "Dùng `info` hoặc `clear`."),
                ephemeral=True,
            )

        if act == "info":
            _cache_compact_local()
            lines = [
                f"Redis: **{'ON' if _redis_on() else 'OFF'}**",
                f"Local resolve cache: **{len(_MUSIC_RESOLVE_CACHE)}**",
                f"Local spotify cache: **{len(_MUSIC_SPOTIFY_CACHE_LOCAL)}**",
                f"Policy: `{_playlist_invalidation_policy()}`",
            ]
            return await interaction.response.send_message(embed=_embed("🗃️ Music Cache", "\n".join(lines)), ephemeral=True)

        if not _is_dj_or_admin(interaction):
            return await interaction.response.send_message(
                embed=_embed("❌ Không có quyền", "Bạn cần DJ role hoặc quyền Admin để clear cache."),
                ephemeral=True,
            )

        _MUSIC_RESOLVE_CACHE.clear()
        _MUSIC_SPOTIFY_CACHE_LOCAL.clear()
        _MUSIC_SPOTIFY_HOT_COUNTER.clear()

        deleted = 0
        if _redis_on():
            deleted += await _redis_scan_delete(f"{MUSIC_REDIS_PREFIX}:resolve:*")
            deleted += await _redis_scan_delete(f"{MUSIC_REDIS_PREFIX}:spotify_playlist:*")

        await interaction.response.send_message(
            embed=_embed("🧹 Music Cache", f"Đã clear cache local. Redis keys deleted: **{deleted}**"),
            ephemeral=True,
        )
