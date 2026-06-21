# Deadhead

A personal delivery-matching agent for drivers heading home empty around
**Dublin, CA (94568)**. You enter your **name** and **home address** and drop a
**pin for your current location** on an interactive map (no live GPS). From your
home + current pin it computes each real local run's detour and distance-from-home,
recommends the best one, learns from each Accept/Skip, and adapts — talking to
*you* in the second person. Each person's memory is isolated by name in **HydraDB**,
so the next driver who opens the app builds their own; sign in with the same name
later and your memory comes back.

> Demo-only proof of concept for an 8-hour memory hackathon (Open Memory Track).
> See [plan.md](plan.md) for the full build plan and demo script.

## Status

- [x] **Block 1 — Setup**: HydraDB SDK + key wired, `deadhead` tenant live,
      infra confirmed ready, one write→read round-trip proven
      ([`scratch_roundtrip.py`](scratch_roundtrip.py)).
- [x] **Block 2 — Backend core**: [`app.py`](app.py) FastAPI backend with
      `GET /recommend` and `POST /decision`, HydraDB recall+write wiring, Claude
      reasoning (via OpenRouter) with strict-JSON output + fallback, and trace
      logging. Terminal-tested: Maria's pick cites her recalled history, Alex's
      says "no history yet."
- [x] **Block 3 — Seed Maria's history**: [`seed.py`](seed.py) resets and writes
      her 5 canonical decisions (`infer=True` for pattern extraction) and verifies
      recall returns both the reject (heavy/late) and accept (near/daytime)
      patterns. Maria's recommendation now cites her pattern directly.
- [x] **Block 4 — UI**: [`index.html`](index.html) served at `GET /` — phone-sized
      page with a Maria/Alex toggle, a recommendation card (pickup, "recalled N past
      decisions" badge, the "why," a stats grid) and Accept/Skip buttons that POST a
      decision and auto-refresh. `seed.py restore_demo_state()` resets the baseline
      (Maria = 5 seed, Alex = empty) before a rehearsal.
- [ ] Block 5 — Live adaptation moment
- [ ] Block 6 — Trace logging
- [ ] Block 7 — Polish + rehearse

## Setup

Requires **Python ≥ 3.10** (the `hydradb-sdk` package needs it; system Python 3.9
will not work).

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # then paste your real HYDRA_DB_API_KEY
.venv/bin/python scratch_roundtrip.py
```

A successful run ends with: `=== ROUND-TRIP COMPLETE: wrote 1 memory, recalled it back ✓ ===`

### Run the backend

`.env` needs both `HYDRA_DB_API_KEY` and `OPENROUTER_API_KEY` (see `.env.example`).

```bash
.venv/bin/uvicorn app:app --reload --port 8000
# then open http://localhost:8000, enter name + home address, drop a current-location pin
# hlat/hlng = home coords (geocoded in the browser), clat/clng = your map pin
curl 'http://localhost:8000/recommend?user=Anirudha&home=Dublin&hlat=37.7026&hlng=-121.9348&clat=37.7048&clng=-121.8865'
curl -X POST localhost:8000/decision \
  -H 'content-type: application/json' \
  -d '{"name":"Anirudha","job_id":"target","action":"skip","detour_min":18,"dropoff_mi":6.5}'
```

`GET /recommend` recalls *that person's* history from HydraDB (isolated by a name
slug), computes each run's detour + distance-from-home from the home/current coords
(haversine over real Dublin coordinates), sends history + runs to Claude
(`anthropic/claude-sonnet-4.6` via OpenRouter), and returns one run + a one-sentence
"why" addressed to *you*. `POST /decision` writes the Accept/Skip back under your
name. Every read/write is appended to `trace.log`.

**Location:** the UI uses Leaflet + OpenStreetMap tiles for the map and
Nominatim (browser-side, no API key) to geocode your home address. The map pin is
your current location. Name + home + pin persist in `localStorage`, so the same
name auto-resumes with its memory.

Optional: `.venv/bin/python seed.py` pre-seeds a returning driver "Maria" with an
established pattern, so you can sign in as `Maria` and see recall instantly.
`seed.py reset <name>` wipes one person's memory.

## HydraDB integration (the real API)

`plan.md` describes the memory layer with placeholder method names. The actual
`hydra_db` SDK maps as follows:

| Concept | Real SDK call |
|---|---|
| Memory layer | `from hydra_db import HydraDB` (base URL `https://api.hydradb.com`) |
| Create tenant | `client.tenants.create(tenant_id="deadhead")` |
| Confirm infra ready | `client.tenants.status(...).data.infra.ready_for_ingestion` |
| Per-person isolation | `sub_tenant_id=slug(name)` on ingest + query (one per driver) |
| Write a decision | `client.context.ingest(tenant_id=..., sub_tenant_id=..., type="memory", memories='[{"text": "...", "infer": true}]')` |
| Recall history | `client.query(tenant_id=..., sub_tenant_id=..., type="memory", query="...")` |

- A memory item is `{"text": "..."}` (a JSON list of these in `memories`).
- Writes return immediately as `status="queued"`; recall picks them up within
  seconds.

## Local environment note: DNS workaround

On the dev machine, CPython's `getaddrinfo` fails to resolve any host (the
`resolv.conf` advertises an IPv6 link-local nameserver from a phone hotspot that
CPython can't use), even though `curl`/`pip` work. Every SDK call would otherwise
die with `httpx.ConnectError: [Errno 8] nodename nor servname provided`.

[`net_fix.py`](net_fix.py) resolves `api.hydradb.com` via the system resolver
(`curl`) once and pins that hostname→IP at the socket layer. TLS SNI and the HTTP
Host header keep the real hostname, so certificate validation is unaffected. The
API sits behind a rotating load balancer, so the IP is resolved dynamically at
startup rather than hardcoded. Import it before constructing the client:

```python
import net_fix; net_fix.install()
```

This is a dev-machine quirk, not part of the product — on a normal network it is
a harmless no-op-ish shim.
