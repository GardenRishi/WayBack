"""
Optional demo helper — pre-seed a "returning driver" so you can show recall
instantly, and reset any person's memory.

The app needs no seeding to work: sign in with any name and your memory builds
live. But for a demo it's nice to sign in as an established driver and see the
agent already know your lane. This seeds "Maria" with a clear pattern: she grabs
light, near-home, daytime runs and skips heavy/late/far ones (real 94568 routes).

Usage:
  .venv/bin/python seed.py            # seed Maria (default)
  .venv/bin/python seed.py reset Sam  # wipe one person's memory
"""

import json
import sys
import time

import app  # reuse the backend's HydraDB client, tenant, trace logger, slugify

DEMO_NAME = "Maria"

# 5 past runs encoding the pattern, phrased first-person like live writes.
SEED = [
    "I (Maria) skipped a delivery run picking up from Ulferts Center (furniture), Dublin dropping in Schaefer Ranch: 58 lbs, hour 21, 32 min detour, 11.0 mi from home, $46 payout. Too heavy and too far this late.",
    "I (Maria) skipped a delivery run picking up from Dick's Sporting Goods, Fallon Gateway dropping in Livermore: 52 lbs, hour 20, 26 min detour, 9.0 mi from home, $42 payout. Too heavy and too late.",
    "I (Maria) skipped a delivery run picking up from Target, Fallon Gateway dropping in San Ramon: 35 lbs, hour 19, 18 min detour, 6.5 mi from home, $30 payout. Heavier and farther than I like.",
    "I (Maria) accepted a delivery run picking up from Whole Foods Market, Persimmon Place dropping in Dublin Ranch: 8 lbs, hour 13, 5 min detour, 1.4 mi from home, $13 payout. Light, near home, daytime — my lane.",
    "I (Maria) accepted a delivery run picking up from Crumbl Cookies, Fallon Gateway dropping in Jordan Ranch: 4 lbs, hour 12, 6 min detour, 1.1 mi from home, $11 payout. Quick and close, midday.",
]


def reset(name: str) -> int:
    slug = app.slugify(name)
    listed = app.hydra().context.list(
        tenant_id=app.TENANT, sub_tenant_id=slug, type="memory", page=1, page_size=100
    )
    ids = [m["memory_id"] for m in (listed.data.user_memories or [])]
    if ids:
        app.hydra().context.delete(tenant_id=app.TENANT, sub_tenant_id=slug, type="memory", ids=ids)
        app._trace("DELETE", slug, f"reset removed {len(ids)} memories")
    return len(ids)


def seed(name: str) -> list[str]:
    slug = app.slugify(name)
    items = [{"text": t, "infer": True} for t in SEED]
    resp = app.hydra().context.ingest(
        tenant_id=app.TENANT, sub_tenant_id=slug, type="memory", memories=json.dumps(items)
    )
    ids = [r.id for r in resp.data.results]
    app._trace("SEED", slug, f"wrote {resp.data.success_count} memories", resp.meta.request_id)
    return ids


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "reset":
        n = sys.argv[2]
        print(f"reset {n}: removed {reset(n)} memories")
        sys.exit(0)

    print(f"reset {DEMO_NAME}: removed {reset(DEMO_NAME)} existing memories")
    print(f"seeded {len(seed(DEMO_NAME))} runs for {DEMO_NAME}")
    time.sleep(10)
    hits = app.recall_history(app.slugify(DEMO_NAME))
    print(f"\nRecall for {DEMO_NAME}: {len(hits)} hit(s)")
    for h in hits:
        print(f"  [{h['score']:.3f}] {h['text'].splitlines()[0]}")
    print("\n=== DEMO DRIVER SEEDED — sign in as 'Maria' to see recall instantly ===")
