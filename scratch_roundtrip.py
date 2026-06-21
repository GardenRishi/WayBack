"""
Block 1 / Section 1 scratch script — prove ONE HydraDB write -> read round-trip.

Per plan.md: "Get a single test write + read working in a scratch script.
Do not proceed until one round-trip works."

Run: .venv/bin/python scratch_roundtrip.py
Requires HYDRA_DB_API_KEY (loaded from .env).
"""

import json
import os
import sys
import time
from pathlib import Path

import net_fix  # dev-machine DNS workaround; must run before any SDK call

from hydra_db import HydraDB
from hydra_db.errors import ConflictError

TENANT = "deadhead"
SUB_TENANT = "maria"


def load_env() -> str:
    env = Path(__file__).parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    token = os.environ.get("HYDRA_DB_API_KEY")
    if not token:
        sys.exit("HYDRA_DB_API_KEY not set (expected in .env)")
    return token


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> None:
    token = load_env()
    pins = net_fix.install()
    log(f"DNS pins applied: {pins}")
    client = HydraDB(token=token)
    log(f"client ready -> base_url default (api.hydradb.com), api_version=2")

    # 1) Create the tenant (idempotent: tolerate 'already exists').
    try:
        resp = client.tenants.create(tenant_id=TENANT)
        log(f"tenants.create accepted: {resp}")
    except ConflictError:
        log(f"tenant '{TENANT}' already exists — reusing")

    # 2) Wait for infra to be ready before writing.
    for attempt in range(30):
        status = client.tenants.status(tenant_id=TENANT)
        infra = status.data.infra
        log(f"tenants.status[{attempt}]: ready_for_ingestion={infra.ready_for_ingestion} "
            f"memories={infra.vectorstore_status.memories} graph={infra.graph_status}")
        if infra.ready_for_ingestion:
            log("infra ready ✓")
            break
        time.sleep(5)
    else:
        log("WARNING: infra never reported ready; attempting write anyway")

    # 3) WRITE one memory for sub-tenant 'maria'.
    memory_text = (
        "Maria skipped a delivery job: 38 lbs, hour 22, 9 min detour. "
        "Reason inferred: too heavy and too late."
    )
    write = client.context.ingest(
        tenant_id=TENANT,
        sub_tenant_id=SUB_TENANT,
        type="memory",
        memories=json.dumps([{"text": memory_text}]),  # MemoryItem: {"text": ...}
    )
    log(f"context.ingest -> success={write.data.success_count} "
        f"id={write.data.results[0].id} status={write.data.results[0].status}")

    # 4) Let ingestion settle, then READ it back via recall.
    time.sleep(8)
    recall = client.query(
        tenant_id=TENANT,
        sub_tenant_id=SUB_TENANT,
        type="memory",
        query="What kinds of jobs does this driver skip by weight and time of day?",
        max_results=5,
    )
    chunks = recall.data.chunks or []
    log(f"client.query (recall) -> {len(chunks)} chunk(s)")
    for ch in chunks:
        log(f"  [{ch.relevancy_score:.3f}] {ch.chunk_content}")

    # Verify the round-trip: the text we wrote must come back via recall.
    recalled_text = " ".join(c.chunk_content or "" for c in chunks)
    assert "38 lbs" in recalled_text or memory_text in recalled_text, (
        "round-trip FAILED: written memory not found in recall"
    )
    print("\n=== ROUND-TRIP COMPLETE: wrote 1 memory, recalled it back ✓ ===")


if __name__ == "__main__":
    main()
