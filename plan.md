# Deadhead — Build Plan (Proof of Concept)

**One-line pitch:** A delivery-matching agent for drivers heading home empty. The twist: it *remembers* each driver across sessions and adapts its recommendation to their history. Built on HydraDB.

**What this is:** A demo-only proof of concept for an 8-hour memory hackathon (Open Memory Track). It is built to be *recorded*, not deployed. We are optimizing for "the agent clearly remembers and acts on it," nothing else.

---

## The bet

We win on **memory legibility**, not features. The judges grade three things:
1. HydraDB is the memory layer.
2. The agent recalls past interactions on its own, across sessions.
3. The agent changes its output based on what it recalled.

Every hour we spend goes toward making those three things *obvious on camera*. Anything that doesn't serve them gets cut.

---

## Mandatory requirements → how we meet each

| Requirement | How we satisfy it |
|---|---|
| HydraDB as primary memory/context/storage | Every driver decision (accept/skip) is written to HydraDB. Recommendations are driven by what we read back from HydraDB. No other database. |
| Persistent memory logic (autonomous recall across sessions) | On every recommendation, the agent queries HydraDB for that driver's past behavior automatically — no human re-entering anything. Memory survives a tab close / server restart because it lives in HydraDB, not in app state. |
| Context-aware execution | The same pool of open jobs produces a *different* recommendation per driver, and shifts after a live skip — because the recall result is injected into the agent's reasoning. |

---

## Scope: corners we are deliberately cutting

**We ARE building:**
- One backend file that also serves a tiny web UI (no separate frontend project).
- One tenant in HydraDB, one sub-tenant per driver.
- Exactly two drivers: "Maria" (seeded with history) and "Alex" (empty).
- ~7 hardcoded delivery jobs with pre-baked numbers.
- One agent: read memory → ask Claude → recommend one job → write decision back.
- A trace log file that records every HydraDB read/write.

**We are NOT building (and feel zero guilt):**
- No real GPS, maps, or routing API — detour minutes and distances are hardcoded.
- No business onboarding agent, no dispatch coordinator, no notifications/SMS.
- No auth, no payments, no accounts, no database scaling. It does not need to handle more than a handful of drivers. Single user at a time is fine.
- No mobile app — a phone-sized web page is enough.
- No error-perfect production code — happy path only.

If a feature isn't one of the three demo proof points, it does not get built.

---

## Architecture (intentionally tiny)

```
[ built-in web page ]  ->  [ small backend ]  ->  [ Claude API ]  (reasoning)
                                   |
                                   v
                              [ HydraDB ]  (memory: read history + write decisions)
```

- **Backend:** one Python file (FastAPI). Two endpoints: get a recommendation for a driver, post a decision.
- **UI:** a single HTML page served by the backend. A driver toggle (Maria / Alex), a recommendation card with the "why," and Accept / Skip buttons. That's the entire interface.
- **Claude (Anthropic API):** the reasoning brain. Given the recalled history + today's jobs, it picks one job and writes a one-sentence justification.
- **HydraDB:** the memory. The only persistence in the system.

---

## HydraDB memory model (the important part)

- **Tenant** = the app. Create one, call it `deadhead`.
- **Sub-tenant** = a driver (`maria`, `alex`). This isolates each driver's memory.
- **Write a decision:** use `client.upload.add_memory(...)` with a plain-English sentence like *"Maria skipped a delivery job: 41 lbs, hour 23, 9 min detour."* Set `infer=True` so HydraDB extracts the preference pattern. One write per accept/skip.
- **Read history:** use `client.recall.recall_preferences(...)` with a query like *"jobs this driver accepts or rejects by detour, weight, payout, and time of day."* This returns the relevant past memories, which we paste into the agent prompt.

That's the whole integration: one write method, one read method. Two SDK calls.

**Setup steps (do this FIRST, before coding):**
1. Sign up at dashboard.hydradb.com.
2. Redeem promo code `HYDRA2026` in billing for credits.
3. Copy the API key into an environment variable.
4. Create the `deadhead` tenant and wait for its infrastructure status to be ready (can take a minute) before writing memories.

---

## Seed data

**Drivers:** Maria (home: Fremont, currently SoMa) and Alex (same route, no history).

**Jobs (~7):** each has pickup name, detour minutes, payout, weight, dropoff distance from home, and hour of day. Mix them so some are obviously bad for Maria (heavy, late) and some are her lane (short detour, near home, daytime).

**Maria's seeded history (~5 past decisions) — this is the most important prep:**
- Skipped: 38 lb job (too heavy)
- Skipped: hour-23 job (too late)
- Skipped: 25 lb late job
- Accepted: short-detour bakery run near home, daytime
- Accepted: small florist drop, near home, daytime

The pattern to bake in: **rejects heavy + late, accepts short-detour + near-home + daytime.** Recall quality depends entirely on this seed. If the agent's reasoning feels generic during testing, add *more* seed decisions before touching anything else.

---

## The agent loop

1. Driver opens the app → backend calls HydraDB recall for that driver.
2. Backend sends the recalled history + the open jobs to Claude.
3. Claude returns one job + a short reason that cites the history ("6-min detour, near your house, daytime — your usual lane").
4. Driver taps Accept or Skip → backend writes that decision to HydraDB.
5. Next recommendation reflects the new memory. Loop.

No human edits memory by hand at any point — recall and write are automatic. That autonomy is what the brief is asking for.

---

## Build order (compressible to ~5–6 hours)

Times are relative blocks. If you're short, do the **Minimum Viable Path** (starred items) and skip the rest.

- **Block 1 — Setup (★, ~30 min):** HydraDB account, credits, API key, create tenant, confirm infra ready. Get a single test write + read working in a scratch script. Do not proceed until one round-trip works.
- **Block 2 — Backend core (★, ~90 min):** the two endpoints, the Claude call, the recall + write wiring. Test it in the terminal first — print the recommendation before building any UI.
- **Block 3 — Seed Maria (★, ~30 min):** write the 5 history entries. Verify recall returns them.
- **Block 4 — UI (★, ~60 min):** the one HTML page wired to the endpoints. Driver toggle, card, Accept/Skip.
- **Block 5 — The adaptation moment (★, ~45 min):** make a live skip visibly change the next recommendation. This is the demo climax — make sure it's crisp.
- **Block 6 — Trace logging (~20 min):** log every HydraDB read/write to a file with timestamps. This is a required deliverable; don't skip it.
- **Block 7 — Polish + rehearse (~45 min):** clean up the "why" text, rehearse the demo twice, freeze the code.

**Minimum Viable Path if time collapses:** Blocks 1–5 only. A working memory loop with two drivers beats a half-built four-agent system every time.

---

## Demo script (record this — ~90 seconds)

Three proof points, in order. Each maps to a graded requirement.

1. **Cross-session recall.** Open the app on Maria. Show her recommendation cites her history. Then restart the server / refresh — her memory is still there. *Say: "This isn't session state. Her memory lives in HydraDB and persists across sessions."*
2. **Cross-driver contrast.** Switch to Alex. Same job pool, different recommendation, because Alex has no history. *Say: "Same jobs, different driver, different decision — the memory is driving it, not a filter."*
3. **Live adaptation.** Back on Maria, skip a late-night job. Refresh. The next recommendation has shifted. *Say: "It just learned, in real time, and wrote that back to memory."*

Close on the trace log scrolling — visible proof the agent wrote and read HydraDB autonomously.

---

## Deliverables checklist

- [ ] Working prototype — recorded demo video (or live) showing recall + adaptation.
- [ ] Source code — repo with the agent logic and HydraDB integration visible.
- [ ] Execution logs — the trace file showing autonomous writes and queries to HydraDB.
- [ ] (Optional) Pitch deck — skip if tight on time.
- [ ] Submit via the Hackathon Portal with code `MEMORY2026`.

---

## Risks & fallbacks

- **HydraDB infra not ready in time:** create the tenant early in Block 1 so it's warm before you need it.
- **Recall feels generic:** add more seed history for Maria. Don't tune anything else first.
- **A HydraDB call flakes mid-demo:** keep a small in-memory mirror of decisions so a single failed call never blanks the screen during recording — but make sure the *real* HydraDB writes/reads are happening for the logs deliverable.
- **Claude returns malformed output:** instruct it to reply with strict JSON only, and default to the closest job if parsing fails. Never let the demo crash on a bad parse.
- **Running out of time:** drop to the Minimum Viable Path. The three proof points are the only things that score.

---

## Stretch (only if everything above is done and rehearsed)

- A third driver to make the contrast even sharper.
- A one-line "business notified, customer ETA sent" fake toast on Accept, to gesture at the full workflow.

Do not start any stretch item until the demo is recorded once successfully.
