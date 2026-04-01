import discord
from discord.ext import commands
import os, json, logging, aiohttp, re
import asyncio
import heapq
import time

COMPS_API = "https://api-hc.metatft.com/tft-comps-api/comps_data?queue=1100"
LOOKUP_API = "https://data.metatft.com/lookups/TFTSet16_pbe_vi_vn.json"
LOCALE_API = "https://data.metatft.com/locales/vi_vn.json"
UNIT_ITEMS_API = "https://api-hc.metatft.com/tft-comps-api/unit_items_processed"

UNIT_ITEMS = {}
CHAMP_LOOKUP = {}
ITEM_LOOKUP = {}
TRAIT_LOOKUP = {}
TRAIT_EFFECTS = {}
CHAMP_COST = {}
CHAMP_UNLOCK = {}
VALID_CHAMPIONS = set()
LOCALE_COMMON = {}
DATA_READY = False
COMPS_DATA = None
LAST_REFRESH_TS = 0.0
TFT_CACHE_TTL_SEC = int(os.getenv("TFT_CACHE_TTL_SEC", "3600"))

# Giảm overhead regex + request
_RE_I_TFT = re.compile(r"%i:TFT16[A-Za-z0-9_]+%")
_RE_I = re.compile(r"%i:[A-Za-z0-9_]+%")
_RE_RULES = re.compile(r"<rules>(.*?)</rules>")
_RE_TAGS = re.compile(r"<.*?>")
_RE_TFT_TOKEN = re.compile(r"TFT16_[A-Za-z0-9_]+")
_RE_SPACES = re.compile(r"\s+")

_SESSION: aiohttp.ClientSession | None = None
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=10)
_INIT_LOCK = asyncio.Lock()

# Index để không phải quét toàn bộ clusters mỗi lần /team hoặc /item
CHAMP_TO_COMPS: dict[str, list[dict]] = {}
CHAMP_SEARCH: list[tuple[str, str]] = []  # (api, lower_name)

def clean_text_basic(t):
    if not t:
        return t
    t = t.replace("&nbsp;", " ")
    t = _RE_I_TFT.sub("", t)
    t = _RE_I.sub("", t)
    t = _RE_RULES.sub(r"(\1)", t)
    t = _RE_TAGS.sub("", t)
    t = _RE_TFT_TOKEN.sub("", t)
    t = _RE_SPACES.sub(" ", t)
    return t.strip()

def parse_trait_with_stage(raw):
    p = raw.split("_")
    if p[-1].isdigit():
        return "_".join(p[:-1]), int(p[-1])
    return raw, None

def get_champion_vi(cid):
    return CHAMP_LOOKUP.get(cid, cid)

def get_item_vi(iid):
    return ITEM_LOOKUP.get(iid, iid)

def get_cost(cid):
    c = CHAMP_COST.get(cid)
    return c if c else None

def fetch_required_value(cond):
    for k, v in cond.items():
        if isinstance(v, int) and v not in (0, 1) and k.startswith("{"):
            return v
    for k, v in cond.items():
        if isinstance(v, int) and k.startswith("{"):
            return v
    return 1

def unlock_to_text(unlock_block):
    conds = unlock_block.get("conditions", [])
    if not conds:
        t = unlock_block.get("manual_conditions", "")
        return clean_text_basic(t)

    lines = []
    for c in conds:
        champ_record = c.get("CharacterRecord")
        champ_name = get_champion_vi(champ_record) if champ_record else None
        req_val = fetch_required_value(c)
        desc = clean_text_basic(c.get("description", ""))
        if champ_name:
            desc = desc.replace("@ChampName@", champ_name)
        desc = desc.replace("@RequiredValue@", str(req_val))
        lines.append(desc)

    if len(lines) == 1:
        return lines[0]
    return " & ".join(lines)

def get_unlock(cid):
    return CHAMP_UNLOCK.get(cid)

def get_trait_vi(raw):
    tid, stage = parse_trait_with_stage(raw)
    base = TRAIT_LOOKUP.get(tid, tid)
    eff = TRAIT_EFFECTS.get(tid, [])
    if not stage or not eff:
        return base
    idx = max(0, min(stage - 1, len(eff) - 1))
    mu = eff[idx].get("minUnits", "")
    return f"{base} {mu}"

async def fetch_json(url):
    """Fetch JSON nhẹ hơn: dùng session dùng chung + timeout + retry nhẹ."""
    global _SESSION

    if _SESSION is None or _SESSION.closed:
        _SESSION = aiohttp.ClientSession(timeout=_HTTP_TIMEOUT)

    last_err = None
    for attempt in (1, 2):
        try:
            async with _SESSION.get(url) as r:
                if r.status != 200:
                    last_err = RuntimeError(f"HTTP {r.status}")
                    await asyncio.sleep(0.2 * attempt)
                    continue

                # content-type đôi khi không chuẩn => vẫn parse được
                return await r.json(content_type=None)
        except Exception as e:
            last_err = e
            await asyncio.sleep(0.2 * attempt)

    logging.warning(f"fetch_json failed: {url} ({last_err})")
    return None

async def load_unit_items():
    global UNIT_ITEMS
    raw = await fetch_json(UNIT_ITEMS_API)
    if not raw or "units" not in raw:
        return
    UNIT_ITEMS = raw["units"]

async def load_locale():
    global CHAMP_LOOKUP, ITEM_LOOKUP, TRAIT_LOOKUP, TRAIT_EFFECTS, CHAMP_COST, CHAMP_UNLOCK
    raw = await fetch_json(LOOKUP_API)
    if not raw:
        return

    for u in raw.get("units", []):
        api = u.get("apiName")
        name = u.get("name")
        if api and name:
            CHAMP_LOOKUP[api] = name
        if api and "cost" in u:
            CHAMP_COST[api] = u["cost"]
        if api and "unlock" in u:
            CHAMP_UNLOCK[api] = unlock_to_text(u["unlock"])

    for it in raw.get("items", []):
        api = it.get("apiName")
        name = it.get("name")
        if api and name:
            ITEM_LOOKUP[api] = name

    for tr in raw.get("traits", []):
        api = tr.get("apiName")
        name = tr.get("name")
        eff = tr.get("effects", [])
        if api and name:
            TRAIT_LOOKUP[api] = name
            TRAIT_EFFECTS[api] = eff

async def load_locale_vi():
    global LOCALE_COMMON
    raw = await fetch_json(LOCALE_API)
    if raw and "common" in raw:
        LOCALE_COMMON = raw["common"]

async def load_comps():
    global COMPS_DATA, VALID_CHAMPIONS, CHAMP_TO_COMPS, CHAMP_SEARCH
    data = await fetch_json(COMPS_API)
    if not data:
        return

    clusters = (
        data.get("results", {})
            .get("data", {})
            .get("cluster_details")
    )
    if not isinstance(clusters, dict):
        return

    COMPS_DATA = data

    VALID_CHAMPIONS = set()
    CHAMP_TO_COMPS = {}

    for comp in clusters.values():
        units_str = comp.get("units_string", "")
        if not units_str:
            continue
        units = [u.strip() for u in units_str.split(",") if u.strip()]
        for cid in units:
            VALID_CHAMPIONS.add(cid)
            CHAMP_TO_COMPS.setdefault(cid, []).append(comp)

    # cache cho autocomplete (api, lower_name)
    CHAMP_SEARCH = [
        (api, name.lower())
        for api, name in CHAMP_LOOKUP.items()
        if api in VALID_CHAMPIONS
    ]

def get_carry_champion(comp):
    builds = comp.get("builds", [])
    if builds:
        best = max(builds, key=lambda b: (b.get("count", 0), -b.get("avg", 99)))
        return get_champion_vi(best.get("unit"))

    for n in comp.get("name", []):
        if n.get("type") == "unit":
            return get_champion_vi(n.get("name"))

    for u in comp.get("units_string", "").split(","):
        return get_champion_vi(u.strip())

    return "Không rõ"

def get_levelling_vi(key):
    if not key:
        return None
    return LOCALE_COMMON.get(key, key)

def get_levelling_tooltip(key):
    return LOCALE_COMMON.get(key + "_tooltip")

def get_core_trait(comp):
    best = None
    best_stage = 0

    for raw in comp.get("traits_string", "").split(","):
        tid, stage = parse_trait_with_stage(raw.strip())
        if stage and stage > best_stage:
            best_stage = stage
            best = tid

    return get_trait_vi(best) if best else None

def get_short_team_desc(comp):
    trait = get_core_trait(comp)
    carry = get_carry_champion(comp)
    if trait and carry:
        return f"{trait} • {carry}"
    return comp.get("name_string", "Không rõ")

def build_overview_embed(top_comps, champion):
    """Compact overview embed used by the dropdown navigator."""
    embed = discord.Embed(
        title=f"Top đội hình cho {get_champion_vi(champion)}",
        description="Dùng menu bên dưới để xem chi tiết từng team.",
        color=discord.Color.green()
    )

    for i, t in enumerate(top_comps, 1):
        short_desc = get_short_team_desc(t)
        overall = t.get("overall", {}) or {}
        cnt = overall.get("count", 0)
        avg = overall.get("avg", None)
        avg_txt = "?" if avg is None else str(round(avg, 4))
        embed.add_field(
            name=f"Team {i} — {short_desc}",
            value=f"🔥 Game: {cnt}\n📉 TB: {avg_txt}",
            inline=True
        )
    return embed

def build_team_embed(team, champion):
    grouped = {1: [], 2: [], 3: [], 4: [], 5: []}
    unlocked = []

    for cid in team["units_string"].split(","):
        cid = cid.strip()
        name = f"**{get_champion_vi(cid)}**"
        cost = get_cost(cid)
        unlock = get_unlock(cid)

        if unlock:
            unlocked.append(f"{name} — {unlock}")
        elif cost:
            grouped[cost].append(name)

    parts = []
    for c in range(1, 6):
        if grouped[c]:
            parts.append(f"• {c} vàng: " + ", ".join(grouped[c]))

    if unlocked:
        parts.append("• Tướng mở khóa\n" + "\n".join(unlocked))

    units_vi = "\n\n".join(parts)

    builds = heapq.nlargest(3, team.get("builds", []), key=lambda x: x.get("count", 0))
    bt = ""
    for b in builds:
        n = get_champion_vi(b["unit"])
        items = ", ".join(get_item_vi(i) for i in b.get("buildName", []))
        bt += f"**{n}**: {items}\n"

    e = discord.Embed(
        title=f"Đội hình cho: {get_champion_vi(champion)}",
        description=f"**Tên đội hình:** {get_short_team_desc(team)}",
        color=discord.Color.blue()
    )

    lev = team.get("levelling")
    if lev:
        lv_vi = get_levelling_vi(lev)
        lv_tip = get_levelling_tooltip(lev)
        e.add_field(
            name="📈 Lối chơi",
            value=lv_vi if not lv_tip else f"{lv_vi}\n{lv_tip}",
            inline=False
        )

    e.add_field(name="✨ Tướng", value=units_vi, inline=False)

    if bt:
        e.add_field(name="🛠️ Đồ chuẩn", value=bt, inline=False)

    return e

def get_core_items_by_team(unit_api, comps_list, min_count=5000):
    """Tính core items chỉ trên các comp có chứa unit -> nhẹ hơn nhiều."""
    result = []

    for cluster in comps_list:
        builds = cluster.get("builds", [])
        for b in builds:
            if (
                b.get("unit") == unit_api
                and b.get("num_items") == 3
                and b.get("count", 0) >= min_count
            ):
                items = [get_item_vi(i) for i in b["buildName"]]
                team_name = get_short_team_desc(cluster)
                result.append({
                    "team": team_name,
                    "items": items,
                    "avg": b.get("avg"),
                    "count": b.get("count")
                })

    result.sort(key=lambda x: (x["avg"], -x["count"]))
    return result

def get_flex_items(unit_api, limit=8):
    data = UNIT_ITEMS.get(unit_api)
    if not data:
        return []
    items = data.get("items", [])[:limit]
    return [get_item_vi(i["itemName"]) for i in items]

async def autocomplete_champion(interaction: discord.Interaction, current: str):
    current = current.lower()
    if not current:
        # trả nhanh 20 tướng đầu (ổn cho mobile)
        out = []
        for api, lname in CHAMP_SEARCH[:20]:
            out.append(discord.app_commands.Choice(name=CHAMP_LOOKUP.get(api, api), value=api))
        return out

    starts = []
    contains = []
    for api, lname in CHAMP_SEARCH:
        if lname.startswith(current) or api.lower().startswith(current):
            starts.append(api)
        elif current in lname or current in api.lower():
            contains.append(api)

        if len(starts) + len(contains) >= 40:  # cắt sớm
            break

    picks = (starts + contains)[:20]
    return [discord.app_commands.Choice(name=CHAMP_LOOKUP.get(a, a), value=a) for a in picks]

class TeamView(discord.ui.View):
    """Dropdown navigator: chọn team sẽ edit message (không spam kênh)."""
    def __init__(self, comps, champion):
        super().__init__(timeout=180)
        self.comps = comps
        self.champion = champion

        options = [
            discord.SelectOption(
                label="📋 Tổng quan",
                value="overview",
                description="Xem danh sách top đội hình"
            )
        ]
        for i, comp in enumerate(comps, 1):
            desc = get_short_team_desc(comp) or ""
            if len(desc) > 100:
                desc = desc[:97] + "…"
            options.append(
                discord.SelectOption(
                    label=f"Team {i}",
                    value=str(i - 1),
                    description=desc if desc else None
                )
            )

        self.add_item(TeamSelect(options))


class TeamSelect(discord.ui.Select):
    def __init__(self, options):
        super().__init__(
            placeholder="Chọn đội hình để xem chi tiết…",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        if val == "overview":
            embed = build_overview_embed(self.view.comps, self.view.champion)
        else:
            idx = int(val)
            team = self.view.comps[idx]
            embed = build_team_embed(team, self.view.champion)

        await interaction.response.edit_message(embed=embed, view=self.view)

async def init_data():
    global DATA_READY, LAST_REFRESH_TS
    now = time.time()
    # refresh if not ready or TTL expired
    if DATA_READY and COMPS_DATA is not None and (now - LAST_REFRESH_TS) < TFT_CACHE_TTL_SEC:
        return

    async with _INIT_LOCK:
        now = time.time()
        if DATA_READY and COMPS_DATA is not None and (now - LAST_REFRESH_TS) < TFT_CACHE_TTL_SEC:
            return

        # locale changes rarely; but safe to reload
        await load_locale()
        await load_locale_vi()
        await load_comps()
        await load_unit_items()
        DATA_READY = True
        LAST_REFRESH_TS = now


async def close_http_session():
    global _SESSION
    if _SESSION is not None and not _SESSION.closed:
        await _SESSION.close()
    _SESSION = None

def setup(bot: commands.Bot):
    @bot.tree.command(name="team", description="Tìm đội hình theo tướng")
    @discord.app_commands.autocomplete(champion=autocomplete_champion)
    async def team(interaction: discord.Interaction, champion: str):
        await interaction.response.defer()
        if not DATA_READY or COMPS_DATA is None:
            await init_data()

        api = champion
        if api not in CHAMP_LOOKUP:
            for cid, name in CHAMP_LOOKUP.items():
                if api.lower() in name.lower():
                    api = cid
                    break

        res = CHAMP_TO_COMPS.get(api, [])
        if not res:
            return await interaction.followup.send(f"❌ Không thấy đội hình cho **{champion}**")

        top3 = heapq.nlargest(3, res, key=lambda x: x.get("overall", {}).get("count", 0))

        embed = build_overview_embed(top3, champion)

        await interaction.followup.send(embed=embed, view=TeamView(top3, champion))

    @bot.tree.command(name="item", description="Xem đồ khuyên dùng cho tướng")
    @discord.app_commands.autocomplete(unit=autocomplete_champion)
    async def item(interaction: discord.Interaction, unit: str):
        await interaction.response.defer()
        if not DATA_READY or COMPS_DATA is None:
            await init_data()

        api = unit
        if api not in CHAMP_LOOKUP:
            for cid, name in CHAMP_LOOKUP.items():
                if api.lower() in name.lower():
                    api = cid
                    break

        comps_list = CHAMP_TO_COMPS.get(api, [])
        core_items = get_core_items_by_team(api, comps_list, min_count=3000)
        flex_items = get_flex_items(api, limit=8)

        if not core_items and not flex_items:
            return await interaction.followup.send(f"❌ Không tìm thấy đồ khuyên dùng cho **{unit}**")

        embed = discord.Embed(
            title=f"Đồ khuyên dùng cho {get_champion_vi(unit)}",
            color=discord.Color.purple()
        )

        if core_items:
            ci_text = ""
            for ci in core_items[:3]:
                items_str = ", ".join(f"{item}" for item in ci["items"])
                ci_text += f"• **{ci['team']}** (TB: {round(ci['avg'], 4)}, Game: {ci['count']})\n  {items_str}\n\n"
            embed.add_field(name="• Đồ theo đội hình", value=ci_text, inline=False)

        if flex_items:
            fi_text = ", ".join(flex_items)
            embed.add_field(name="• Đồ flex", value=fi_text, inline=False)

        await interaction.followup.send(embed=embed)

