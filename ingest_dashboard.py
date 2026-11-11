# -*- coding: utf-8 -*-
"""Export a sanitized public ingest dashboard from detailed operational events."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

KST = dt.timezone(dt.timedelta(hours=9))
ROOT = Path(__file__).resolve().parent
EVENT_DIR = ROOT / "verification" / "ingest" / "events"

SOURCE_ORDER = [
    "ecmwf","gfs","kim","upper_global","kim_upper",
    "kma_short","kma_fcstdiff","kma_mid","kma_midland",
    "asos","gk2a_solar","nowcast",
]


def _parse(s):
    try:
        return dt.datetime.fromisoformat(s)
    except Exception:
        return None


def export(site_dir: str, days: int = 3) -> dict:
    now = dt.datetime.now(KST)
    cut = now - dt.timedelta(days=days)
    events = []
    if EVENT_DIR.exists():
        for p in sorted(EVENT_DIR.glob("*.json")):
            try:
                e = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            end = _parse(e.get("ended_kst"))
            if not end or end < cut:
                continue
            # Public summary: no raw error detail, workflow/run IDs, command, keys, or URLs.
            events.append({
                "source": e.get("source"),
                "label": e.get("label") or e.get("source"),
                "kind": e.get("kind"),
                "issue": e.get("issue"),
                "started_kst": e.get("started_kst"),
                "ended_kst": e.get("ended_kst"),
                "duration_s": e.get("duration_s"),
                "status": e.get("status"),
                "summary": e.get("summary"),
            })

    latest = {}
    fail_count = {}
    for e in events:
        src = e["source"]
        latest[src] = e
        if e["status"] == "failed":
            fail_count[src] = fail_count.get(src, 0) + 1

    def rank(e):
        try:
            return SOURCE_ORDER.index(e["source"])
        except ValueError:
            return 999

    latest_rows = []
    for e in sorted(latest.values(), key=rank):
        row = dict(e)
        row["failures_3d"] = fail_count.get(e["source"], 0)
        latest_rows.append(row)

    out = {
        "schema": 1,
        "generated_kst": now.isoformat(timespec="seconds"),
        "window_days": days,
        "latest": latest_rows,
        "events": sorted(events, key=lambda e: e.get("ended_kst") or "", reverse=True),
    }
    d = Path(site_dir) / "ops"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ingest-status.json").write_text(
        json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return out
