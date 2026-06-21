"""
Deadhead — a delivery-matching agent with personal, cross-session memory.

You tell it your name; it learns which runs you grab vs skip and adapts. Each
person's memory is isolated by name in HydraDB, so the next person to use the app
builds their own. Routes are real pickups around Dublin, CA (94568).

One FastAPI file that also serves the UI. Endpoints:
  GET  /recommend?user=<name>  -> recall YOUR history, ask Claude, return one run + why (in 2nd person)
  POST /decision               -> write your accept/skip back to HydraDB under your name

Run: .venv/bin/uvicorn app:app --reload --port 8000
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

# --- env loading (HYDRA_DB_API_KEY, OPENROUTER_API_KEY from .env) ---
def _load_env() -> None:
    env = Path(__file__).parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()

import math

# Default home label/center (Dublin, CA). Real home comes from the user at sign-in.
HOME_AREA = "Dublin, CA 94568"
DUBLIN_CENTER = (37.7022, -121.9358)


def slugify(name: str) -> str:
    """Turn a display name into a stable HydraDB sub-tenant id (one per person)."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "guest"


def haversine_mi(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in miles between two (lat, lng) points."""
    r = 3958.8
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(h)), 1)


# --- 43 delivery runs with REAL Tri-Valley pickups + drop-off areas ---
# Coordinates are real; detour and distance-from-home are computed per driver from
# their home address + current pin (no pre-baked distances, no live GPS).
JOBS = [
    # --- Persimmon Place (eastern Dublin, Gleason Dr / Fallon Rd) ---
    {"id": "wholefoods",      "pickup": "Whole Foods, Persimmon Place",          "pickup_ll": (37.7055, -121.8745), "dropoff": "Dublin Ranch",              "dropoff_ll": (37.7120, -121.8590), "payout": 13, "weight_lbs": 8,  "hour": 13},
    {"id": "nordstrom",       "pickup": "Nordstrom Rack, Persimmon Place",       "pickup_ll": (37.7055, -121.8748), "dropoff": "Downtown Dublin",           "dropoff_ll": (37.7045, -121.9360), "payout": 14, "weight_lbs": 9,  "hour": 14},
    {"id": "homegoods",       "pickup": "HomeGoods, Persimmon Place",            "pickup_ll": (37.7058, -121.8742), "dropoff": "Heritage Park, Dublin",     "dropoff_ll": (37.6985, -121.9310), "payout": 16, "weight_lbs": 14, "hour": 15},
    {"id": "petsmart",        "pickup": "PetSmart, Persimmon Place",             "pickup_ll": (37.7060, -121.8738), "dropoff": "Emerald Glen, Dublin",      "dropoff_ll": (37.7090, -121.8940), "payout": 12, "weight_lbs": 22, "hour": 11},
    {"id": "ulta",            "pickup": "Ulta Beauty, Persimmon Place",          "pickup_ll": (37.7053, -121.8750), "dropoff": "Dublin Ranch Village",      "dropoff_ll": (37.7105, -121.8670), "payout": 11, "weight_lbs": 5,  "hour": 12},

    # --- Fallon Gateway (eastern Dublin, Dublin Blvd / Fallon Rd) ---
    {"id": "crumbl",          "pickup": "Crumbl Cookies, Fallon Gateway",        "pickup_ll": (37.7065, -121.8640), "dropoff": "Jordan Ranch",              "dropoff_ll": (37.7185, -121.8520), "payout": 11, "weight_lbs": 4,  "hour": 12},
    {"id": "target_fallon",   "pickup": "Target, Fallon Gateway",                "pickup_ll": (37.7062, -121.8645), "dropoff": "San Ramon",                 "dropoff_ll": (37.7799, -121.9780), "payout": 30, "weight_lbs": 35, "hour": 19},
    {"id": "dicks",           "pickup": "Dick's Sporting Goods, Fallon Gateway", "pickup_ll": (37.7060, -121.8650), "dropoff": "Livermore",                 "dropoff_ll": (37.6819, -121.7680), "payout": 42, "weight_lbs": 52, "hour": 20},
    {"id": "fivebelow",       "pickup": "Five Below, Fallon Gateway",            "pickup_ll": (37.7068, -121.8635), "dropoff": "Positano Hills, Dublin",    "dropoff_ll": (37.7015, -121.9500), "payout": 10, "weight_lbs": 7,  "hour": 10},
    {"id": "cinemark",        "pickup": "Cinemark, Fallon Gateway",              "pickup_ll": (37.7070, -121.8628), "dropoff": "Jordan Ranch",              "dropoff_ll": (37.7185, -121.8520), "payout": 9,  "weight_lbs": 3,  "hour": 9},
    {"id": "petco_fallon",    "pickup": "Petco, Fallon Gateway",                 "pickup_ll": (37.7066, -121.8633), "dropoff": "Gale Ranch, San Ramon",     "dropoff_ll": (37.7662, -121.9480), "payout": 18, "weight_lbs": 20, "hour": 16},

    # --- Hacienda Crossings (central Dublin, Hacienda Dr) ---
    {"id": "bestbuy",         "pickup": "Best Buy, Hacienda Crossings",          "pickup_ll": (37.7048, -121.8865), "dropoff": "Pleasanton",                "dropoff_ll": (37.6624, -121.8747), "payout": 24, "weight_lbs": 22, "hour": 18},
    {"id": "ross",            "pickup": "Ross Dress for Less, Hacienda Crossings","pickup_ll": (37.7050, -121.8870), "dropoff": "Downtown Pleasanton",       "dropoff_ll": (37.6626, -121.8758), "payout": 15, "weight_lbs": 12, "hour": 14},
    {"id": "tjmaxx",          "pickup": "TJ Maxx, Hacienda Crossings",           "pickup_ll": (37.7045, -121.8875), "dropoff": "Downtown Dublin",           "dropoff_ll": (37.7045, -121.9360), "payout": 13, "weight_lbs": 10, "hour": 13},
    {"id": "michaels",        "pickup": "Michaels, Hacienda Crossings",          "pickup_ll": (37.7046, -121.8868), "dropoff": "Hansen Hills, San Ramon",   "dropoff_ll": (37.7540, -121.9580), "payout": 17, "weight_lbs": 15, "hour": 15},
    {"id": "panera",          "pickup": "Panera Bread, Hacienda Dr",             "pickup_ll": (37.7044, -121.8860), "dropoff": "Stoneridge, Pleasanton",    "dropoff_ll": (37.6947, -121.9050), "payout": 12, "weight_lbs": 6,  "hour": 11},

    # --- Dublin Blvd / West Dublin ---
    {"id": "ulferts",         "pickup": "Ulferts Center (furniture), Dublin",    "pickup_ll": (37.7045, -121.9080), "dropoff": "Schaefer Ranch",            "dropoff_ll": (37.7035, -121.9690), "payout": 46, "weight_lbs": 58, "hour": 21},
    {"id": "safeway_dub",     "pickup": "Safeway, Dublin Village Center",        "pickup_ll": (37.7010, -121.9290), "dropoff": "Heritage Park, Dublin",     "dropoff_ll": (37.6985, -121.9310), "payout": 14, "weight_lbs": 18, "hour": 16},
    {"id": "cvs_dublin",      "pickup": "CVS Pharmacy, Dublin Blvd",             "pickup_ll": (37.7035, -121.9395), "dropoff": "Donlon, Dublin",            "dropoff_ll": (37.7032, -121.9385), "payout": 9,  "weight_lbs": 4,  "hour": 9},
    {"id": "home_depot_dub",  "pickup": "Home Depot, Dublin",                    "pickup_ll": (37.7020, -121.8940), "dropoff": "Tassajara, Dublin",         "dropoff_ll": (37.7150, -121.8730), "payout": 28, "weight_lbs": 45, "hour": 17},
    {"id": "lowes_dub",       "pickup": "Lowe's, Dublin",                        "pickup_ll": (37.7018, -121.8950), "dropoff": "Fallon Sports Park area",   "dropoff_ll": (37.7080, -121.8710), "payout": 25, "weight_lbs": 38, "hour": 16},
    {"id": "sprouts",         "pickup": "Sprouts Farmers Market, Dublin",        "pickup_ll": (37.7025, -121.9360), "dropoff": "Sorrento, Dublin",          "dropoff_ll": (37.7028, -121.9370), "payout": 13, "weight_lbs": 9,  "hour": 13},
    {"id": "starbucks_dub",   "pickup": "Starbucks, Dublin Blvd",                "pickup_ll": (37.7038, -121.9200), "dropoff": "Downtown Dublin",           "dropoff_ll": (37.7045, -121.9360), "payout": 8,  "weight_lbs": 3,  "hour": 8},
    {"id": "trader_joes",     "pickup": "Trader Joe's, Dublin",                  "pickup_ll": (37.7042, -121.9245), "dropoff": "Shadow Hills, Dublin",      "dropoff_ll": (37.7005, -121.9420), "payout": 14, "weight_lbs": 11, "hour": 14},

    # --- Pleasanton, CA ---
    {"id": "target_pls",      "pickup": "Target, Pleasanton",                   "pickup_ll": (37.6952, -121.9020), "dropoff": "Bernal area, Pleasanton",   "dropoff_ll": (37.6605, -121.8800), "payout": 22, "weight_lbs": 28, "hour": 18},
    {"id": "safeway_pls",     "pickup": "Safeway, Pleasanton",                  "pickup_ll": (37.6620, -121.8720), "dropoff": "Downtown Pleasanton",       "dropoff_ll": (37.6626, -121.8758), "payout": 15, "weight_lbs": 16, "hour": 15},
    {"id": "walmart_pls",     "pickup": "Walmart, Pleasanton",                  "pickup_ll": (37.6587, -121.8980), "dropoff": "Hopyard area, Pleasanton",  "dropoff_ll": (37.6750, -121.8950), "payout": 20, "weight_lbs": 32, "hour": 17},
    {"id": "kohls_pls",       "pickup": "Kohl's, Pleasanton",                   "pickup_ll": (37.6596, -121.8730), "dropoff": "Amador Valley, Pleasanton", "dropoff_ll": (37.6720, -121.8820), "payout": 14, "weight_lbs": 11, "hour": 14},
    {"id": "stoneridge",      "pickup": "Stoneridge Shopping Center, Pleasanton","pickup_ll": (37.6947, -121.9050), "dropoff": "Castlewood, Pleasanton",    "dropoff_ll": (37.6670, -121.8640), "payout": 18, "weight_lbs": 14, "hour": 16},
    {"id": "costco_pls",      "pickup": "Costco, Pleasanton",                   "pickup_ll": (37.6540, -121.8950), "dropoff": "Hacienda Business Park",    "dropoff_ll": (37.6980, -121.9020), "payout": 35, "weight_lbs": 60, "hour": 19},

    # --- San Ramon, CA ---
    {"id": "costco_sr",       "pickup": "Costco, San Ramon",                    "pickup_ll": (37.7756, -121.9820), "dropoff": "Dougherty Valley",          "dropoff_ll": (37.7740, -121.9650), "payout": 38, "weight_lbs": 65, "hour": 20},
    {"id": "safeway_sr",      "pickup": "Safeway, San Ramon",                   "pickup_ll": (37.7720, -121.9720), "dropoff": "Crow Canyon area",          "dropoff_ll": (37.7645, -121.9720), "payout": 17, "weight_lbs": 19, "hour": 16},
    {"id": "target_sr",       "pickup": "Target, San Ramon",                    "pickup_ll": (37.7730, -121.9730), "dropoff": "Bishop Ranch, San Ramon",   "dropoff_ll": (37.7760, -121.9780), "payout": 26, "weight_lbs": 30, "hour": 18},
    {"id": "home_depot_sr",   "pickup": "Home Depot, San Ramon",                "pickup_ll": (37.7745, -121.9790), "dropoff": "Twin Creeks, San Ramon",    "dropoff_ll": (37.7820, -121.9840), "payout": 29, "weight_lbs": 42, "hour": 17},
    {"id": "city_center_sr",  "pickup": "City Center Bishop Ranch, San Ramon",  "pickup_ll": (37.7760, -121.9780), "dropoff": "Norris Canyon area",        "dropoff_ll": (37.7870, -121.9850), "payout": 15, "weight_lbs": 8,  "hour": 13},

    # --- Livermore, CA ---
    {"id": "outlets_liv",     "pickup": "Livermore Premium Outlets",            "pickup_ll": (37.6975, -121.7430), "dropoff": "Downtown Livermore",        "dropoff_ll": (37.6819, -121.7660), "payout": 20, "weight_lbs": 16, "hour": 15},
    {"id": "target_liv",      "pickup": "Target, Livermore",                    "pickup_ll": (37.6855, -121.7700), "dropoff": "South Livermore",           "dropoff_ll": (37.6700, -121.7580), "payout": 22, "weight_lbs": 25, "hour": 18},
    {"id": "safeway_liv",     "pickup": "Safeway, Livermore",                   "pickup_ll": (37.6800, -121.7680), "dropoff": "Tri-Valley, Livermore",     "dropoff_ll": (37.6785, -121.7540), "payout": 14, "weight_lbs": 14, "hour": 14},
    {"id": "costco_liv",      "pickup": "Costco, Livermore",                    "pickup_ll": (37.6924, -121.7492), "dropoff": "Livermore Ranch",           "dropoff_ll": (37.6860, -121.7330), "payout": 36, "weight_lbs": 62, "hour": 19},
    {"id": "home_depot_liv",  "pickup": "Home Depot, Livermore",                "pickup_ll": (37.6870, -121.7730), "dropoff": "Vineyard area, Livermore",  "dropoff_ll": (37.6760, -121.7400), "payout": 27, "weight_lbs": 40, "hour": 17},
    {"id": "kohls_liv",       "pickup": "Kohl's, Livermore",                    "pickup_ll": (37.6980, -121.7420), "dropoff": "El Charro area",            "dropoff_ll": (37.6910, -121.7320), "payout": 13, "weight_lbs": 10, "hour": 13},

    # --- Castro Valley / further out ---
    {"id": "safeway_cv",      "pickup": "Safeway, Castro Valley",               "pickup_ll": (37.6955, -122.0900), "dropoff": "Castro Valley center",      "dropoff_ll": (37.6941, -122.0867), "payout": 16, "weight_lbs": 13, "hour": 14},
    {"id": "target_cv",       "pickup": "Target, Castro Valley",                "pickup_ll": (37.6960, -122.0870), "dropoff": "Five Canyons, Castro Valley","dropoff_ll": (37.6870, -122.0680), "payout": 24, "weight_lbs": 27, "hour": 16},
]
JOBS_BY_ID = {j["id"]: j for j in JOBS}

AVG_MPH = 25  # local surface-street estimate for turning detour miles into minutes


def route_metrics(job: dict, home: tuple[float, float], cur: tuple[float, float]) -> dict:
    """Compute detour + distance-from-home for one run, given home and current pin.

    Detour = extra miles of (current -> pickup -> dropoff -> home) over driving
    straight home (current -> home). This is exactly the deadhead cost.
    """
    legs = (
        haversine_mi(cur, job["pickup_ll"])
        + haversine_mi(job["pickup_ll"], job["dropoff_ll"])
        + haversine_mi(job["dropoff_ll"], home)
    )
    detour_mi = round(max(0.0, legs - haversine_mi(cur, home)), 1)
    return {
        "detour_min": round(detour_mi / AVG_MPH * 60),
        "detour_mi": detour_mi,
        "dropoff_mi": haversine_mi(job["dropoff_ll"], home),
        "to_pickup_mi": haversine_mi(cur, job["pickup_ll"]),
    }

# --- HydraDB memory layer (the only persistence) ---
TENANT = "deadhead"
TRACE_FILE = Path(__file__).parent / "trace.log"

_hydra = None


def _trace(op: str, user: str, detail: str, request_id: str | None = None) -> None:
    """Append every HydraDB read/write to trace.log (Block 6 deliverable)."""
    ts = datetime.now(timezone.utc).isoformat()
    line = f"{ts}\t{op}\tuser={user}\t{detail}"
    if request_id:
        line += f"\trequest_id={request_id}"
    with TRACE_FILE.open("a") as f:
        f.write(line + "\n")
    print("TRACE", line)


def hydra():
    """Lazy singleton HydraDB client (applies the dev DNS shim first)."""
    global _hydra
    if _hydra is None:
        import net_fix
        net_fix.install()
        from hydra_db import HydraDB
        token = os.environ.get("HYDRA_DB_API_KEY")
        if not token:
            raise RuntimeError("HYDRA_DB_API_KEY not set (expected in .env)")
        _hydra = HydraDB(token=token)
    return _hydra


def recall_history(user_slug: str, query: str | None = None, max_results: int = 8) -> list[dict]:
    """Read this person's past runs back from HydraDB (autonomous recall)."""
    q = query or (
        "What kinds of delivery runs do I accept or reject, "
        "by detour, weight, payout, distance, and time of day?"
    )
    try:
        resp = hydra().query(
            tenant_id=TENANT,
            sub_tenant_id=user_slug,
            type="memory",
            query=q,
            max_results=max_results,
        )
        chunks = resp.data.chunks or []
        _trace("RECALL", user_slug, f"q={q!r} hits={len(chunks)}", resp.meta.request_id)
        return [{"text": c.chunk_content, "score": c.relevancy_score} for c in chunks]
    except Exception as e:
        _trace("RECALL_ERR", user_slug, f"error={e}")
        return []


def write_decision(user_slug: str, name: str, job: dict, action: str,
                   detour_min: float, dropoff_mi: float) -> dict:
    """Write one accept/skip run back to HydraDB as a first-person memory."""
    verb = "accepted" if action == "accept" else "skipped"
    text = (
        f"I ({name}) {verb} a delivery run picking up from {job['pickup']} "
        f"dropping in {job['dropoff']}: {job['weight_lbs']} lbs, hour {job['hour']}, "
        f"{round(detour_min)} min detour, {dropoff_mi} mi from home, ${job['payout']} payout."
    )
    resp = hydra().context.ingest(
        tenant_id=TENANT,
        sub_tenant_id=user_slug,
        type="memory",
        # infer=True -> HydraDB extracts the preference pattern from the sentence.
        memories=json.dumps([{"text": text, "infer": True}]),
    )
    mem_id = resp.data.results[0].id if resp.data.results else None
    _trace("WRITE", user_slug, f"action={action} job={job['id']} mem_id={mem_id} text={text!r}",
           resp.meta.request_id)
    return {"memory_id": mem_id, "text": text}


# --- Claude reasoning brain (via OpenRouter, OpenAI-compatible) ---
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
CLAUDE_MODEL = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4.6")

_SYSTEM = (
    "You are the driver's OWN personal dispatch assistant. You speak directly TO "
    "the driver as 'you' — never in the third person, never analyzing them from "
    "outside. From the open runs, pick the SINGLE best one for this driver and "
    "explain why in one warm, second-person sentence. Use their recalled history "
    "to infer what they like (detour, weight, payout, time of day, distance from "
    "home) and cite it ('you usually grab...'). If they have NO history yet, treat "
    "them as new: pick a sensible easy starter and say it's their first run so "
    "you'll learn from what they pick. Reply with STRICT JSON only, no prose, no "
    'markdown: {"job_id": "<one of the given ids>", "reason": "<one second-person '
    'sentence>"}'
)


def _fallback_job(enriched: list[dict]) -> dict:
    """Used only if Claude output can't be parsed: lowest-detour run."""
    return min(enriched, key=lambda j: (j["detour_min"], j["weight_lbs"]))


def _phase_line(name: str, after: str, last_pickup: str) -> str:
    """One lead line telling Claude what just happened so the next pick adapts."""
    if after == "accept" and last_pickup:
        return (f"{name} JUST ACCEPTED the '{last_pickup}' run and wants another one. "
                f"Briefly acknowledge that grab in the first clause, then suggest the next "
                f"best remaining run.\n\n")
    if after == "skip" and last_pickup:
        return (f"{name} JUST SKIPPED the '{last_pickup}' run. Do NOT re-pitch anything like "
                f"it — suggest a genuinely DIFFERENT remaining run that fits them better, and "
                f"acknowledge the skip in the first clause.\n\n")
    return ""


def _ask_claude(name: str, home_label: str, history: list[dict], enriched: list[dict],
                after: str = "", last_pickup: str = "") -> dict:
    """Send recalled history + open runs to Claude (via OpenRouter); return {job_id, reason}."""
    import httpx
    import net_fix
    net_fix.install()  # pin openrouter.ai for the dev-machine resolver

    hist_lines = [f"- {m['text']}" for m in history] or ["(no history yet — this is their first run)"]
    # Cap at 15 closest runs so the prompt stays compact for smaller models
    candidates = sorted(enriched, key=lambda j: (j["detour_min"], j["dropoff_mi"]))[:15]
    job_lines = [
        f"- id={j['id']}: pick up {j['pickup']}, drop in {j['dropoff']}, "
        f"{j['detour_min']} min detour ({j['detour_mi']} extra mi), {j['weight_lbs']} lbs, "
        f"${j['payout']}, drop-off is {j['dropoff_mi']} mi from home, hour {j['hour']}"
        for j in candidates
    ]
    user = (
        _phase_line(name, after, last_pickup) +
        f"The driver's name is {name}. They are heading home to {home_label}, and "
        f"detour/distance numbers below are computed from their real home and current "
        f"location.\n\n"
        f"What you remember about this driver:\n" + "\n".join(hist_lines) + "\n\n"
        f"Open runs right now (already-handled ones are not listed):\n" + "\n".join(job_lines) + "\n\n"
        f"Pick the best run for {name} and tell them why, speaking to them as 'you'. "
        "Strict JSON only."
    )
    try:
        resp = httpx.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                "X-OpenRouter-Title": "Deadhead",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 300,
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": user},
                ],
            },
            timeout=60,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        fb = _fallback_job(candidates)
        return {"job_id": fb["id"], "reason": f"Closest low-detour run near home based on your location.", "parsed": False}
    # tolerate accidental code fences
    if raw.startswith("```"):
        raw = raw.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        out = json.loads(raw)
        job_id = out["job_id"]
        if job_id not in JOBS_BY_ID:
            raise ValueError(f"unknown job_id {job_id!r}")
        return {"job_id": job_id, "reason": out.get("reason", ""), "parsed": True}
    except Exception as e:
        fb = _fallback_job(candidates)
        return {"job_id": fb["id"], "reason": "Closest low-detour run near home based on your location.", "parsed": False}


def _enrich(home: tuple[float, float], cur: tuple[float, float], jobs: list[dict]) -> list[dict]:
    """Build per-run dicts with computed metrics + JSON-friendly coords."""
    out = []
    for j in jobs:
        m = route_metrics(j, home, cur)
        out.append({
            "id": j["id"], "pickup": j["pickup"], "dropoff": j["dropoff"],
            "weight_lbs": j["weight_lbs"], "payout": j["payout"], "hour": j["hour"],
            "pickup_ll": list(j["pickup_ll"]), "dropoff_ll": list(j["dropoff_ll"]),
            **m,
        })
    return out


def recommend(name: str, home: tuple[float, float], cur: tuple[float, float],
              home_label: str = HOME_AREA, exclude: set[str] | None = None,
              after: str = "", last_id: str = "") -> dict:
    """Full agent loop step: recall -> reason over real geography -> one run + why.

    `exclude` are run ids already accepted/skipped this session — never re-suggested.
    """
    slug = slugify(name)
    exclude = exclude or set()
    history = recall_history(slug)
    remaining = [j for j in JOBS if j["id"] not in exclude]
    if not remaining:
        return {"user": slug, "name": name, "done": True, "history": history,
                "home_ll": list(home), "current_ll": list(cur),
                "message": "That's every nearby run for now — nice work. Switch driver or come back later."}

    enriched = _enrich(home, cur, remaining)
    by_id = {j["id"]: j for j in enriched}
    last_pickup = JOBS_BY_ID[last_id]["pickup"] if last_id in JOBS_BY_ID else ""
    pick = _ask_claude(name, home_label, history, enriched, after=after, last_pickup=last_pickup)
    return {
        "user": slug,
        "name": name,
        "done": False,
        "home_ll": list(home),
        "current_ll": list(cur),
        "job": by_id[pick["job_id"]],
        "reason": pick["reason"],
        "parsed": pick["parsed"],
        "history": history,
        "remaining": len(remaining),
    }


# --- Delivery status tracker (flat JSON file, keyed by user slug) ---
DELIVERIES_FILE = Path(__file__).parent / "deliveries.json"


def _load_deliveries() -> dict:
    if DELIVERIES_FILE.exists():
        return json.loads(DELIVERIES_FILE.read_text())
    return {}


def _save_deliveries(data: dict) -> None:
    DELIVERIES_FILE.write_text(json.dumps(data, indent=2))


def track_accepted(user_slug: str, name: str, job: dict) -> str:
    """Record a newly accepted delivery; return its unique delivery_id."""
    import uuid
    data = _load_deliveries()
    data.setdefault(user_slug, [])
    delivery_id = uuid.uuid4().hex[:8]
    data[user_slug].append({
        "id": delivery_id,
        "job_id": job["id"],
        "pickup": job["pickup"],
        "dropoff": job["dropoff"],
        "payout": job["payout"],
        "weight_lbs": job["weight_lbs"],
        "hour": job["hour"],
        "status": "accepted",
        "accepted_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
    })
    _save_deliveries(data)
    return delivery_id


def mark_completed(user_slug: str, delivery_id: str) -> bool:
    data = _load_deliveries()
    for d in data.get(user_slug, []):
        if d["id"] == delivery_id:
            d["status"] = "completed"
            d["completed_at"] = datetime.now(timezone.utc).isoformat()
            _save_deliveries(data)
            return True
    return False


def get_deliveries(user_slug: str) -> list[dict]:
    return _load_deliveries().get(user_slug, [])


# --- FastAPI app ---
try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse
    from pydantic import BaseModel
except ImportError:  # allow importing this module for non-web tests
    FastAPI = None

app = FastAPI(title="Deadhead") if FastAPI else None
INDEX_HTML = Path(__file__).parent / "index.html"


if app:
    class Decision(BaseModel):
        name: str
        job_id: str
        action: str  # "accept" | "skip"
        detour_min: float
        dropoff_mi: float

    @app.get("/", response_class=HTMLResponse)
    def index():
        return INDEX_HTML.read_text()

    @app.get("/health")
    def health():
        return {"ok": True, "home": HOME_AREA, "jobs": len(JOBS)}

    @app.get("/recommend")
    def get_recommend(user: str, hlat: float, hlng: float, clat: float, clng: float,
                      home: str = HOME_AREA, exclude: str = "", after: str = "", last: str = ""):
        if not user.strip():
            raise HTTPException(400, "name is required")
        excl = {x for x in exclude.split(",") if x}
        return recommend(user.strip(), (hlat, hlng), (clat, clng), home_label=home,
                         exclude=excl, after=after, last_id=last)

    @app.post("/decision")
    def post_decision(d: Decision):
        if not d.name.strip():
            raise HTTPException(400, "name is required")
        if d.job_id not in JOBS_BY_ID:
            raise HTTPException(404, f"unknown job {d.job_id!r}")
        if d.action not in ("accept", "skip"):
            raise HTTPException(400, "action must be 'accept' or 'skip'")
        slug = slugify(d.name)
        job = JOBS_BY_ID[d.job_id]
        written = write_decision(slug, d.name.strip(), job, d.action, d.detour_min, d.dropoff_mi)
        delivery_id = None
        if d.action == "accept":
            delivery_id = track_accepted(slug, d.name.strip(), job)
        return {"ok": True, "written": written, "delivery_id": delivery_id}

    @app.get("/deliveries")
    def get_deliveries_endpoint(user: str):
        if not user.strip():
            raise HTTPException(400, "user is required")
        slug = slugify(user.strip())
        deliveries = get_deliveries(slug)
        active = [d for d in deliveries if d["status"] == "accepted"]
        completed = [d for d in deliveries if d["status"] == "completed"]
        total_earned = sum(d["payout"] for d in completed)
        return {
            "user": slug,
            "active": active,
            "completed": completed,
            "total_earned": total_earned,
        }

    class CompleteBody(BaseModel):
        name: str
        delivery_id: str

    @app.post("/delivery/complete")
    def post_complete(b: CompleteBody):
        if not b.name.strip():
            raise HTTPException(400, "name is required")
        slug = slugify(b.name.strip())
        ok = mark_completed(slug, b.delivery_id)
        if not ok:
            raise HTTPException(404, f"delivery {b.delivery_id!r} not found for {slug!r}")
        return {"ok": True, "delivery_id": b.delivery_id}
