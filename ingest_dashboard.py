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

# Expected platform receipt windows (KST). These are deliberately the times
# our platform is expected to have refreshed, not every upstream production cycle.
# The grid therefore answers: "should this have been here by now?"
EXPECTED = {
    "ecmwf":       {"hours": [6, 11], "grace_h": 2, "label": "일일 NWP 1차"},
    "gfs":         {"hours": [6, 11], "grace_h": 2, "label": "일일 NWP 1차"},
    "kim":         {"hours": [6, 11], "grace_h": 2, "label": "일일 NWP 1차"},
    "upper_global":{"hours": [7, 12], "grace_h": 2, "label": "일일 NWP 2차"},
    "kim_upper":   {"hours": [7, 12], "grace_h": 2, "label": "일일 NWP 2차"},
    "kma_short":   {"hours": [5, 11, 17], "grace_h": 2, "label": "단기예보 주요 발표"},
    "kma_fcstdiff":{"hours": [7], "grace_h": 2, "label": "예보변화 산출"},
    "kma_mid":     {"hours": [12], "grace_h": 2, "label": "중기예보 수집"},
    "kma_midland": {"hours": [7, 19], "grace_h": 2, "label": "중기 개황 확인"},
    "asos":        {"every_hour": True, "grace_h": 1, "label": "매시 관측"},
    "gk2a_solar":  {"hours": [7, 12], "grace_h": 2, "label": "일일 위성일사"},
    "nowcast":     {"every_hour": True, "grace_h": 1, "label": "매시 초단기"},
}


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

    # Statuspage-style hourly history. Each source gets 72 hourly buckets;
    # a bucket is colored only when an ingest/check event actually ran.
    # Multiple events in one hour collapse to the worst status so a failure
    # followed by a success remains visible in the history.
    severity = {"success": 0, "partial": 1, "failed": 2}
    hours = []
    end_hour = now.replace(minute=0, second=0, microsecond=0)
    for i in range(days * 24 - 1, -1, -1):
        h = end_hour - dt.timedelta(hours=i)
        hours.append(h.isoformat(timespec="minutes"))
    matrix = {}
    detail = {}
    expected = {}
    schedule_meta = {}
    hour_objs = [dt.datetime.fromisoformat(h) for h in hours]
    for src, cfg in EXPECTED.items():
        schedule_meta[src] = {"label": cfg.get("label"), "grace_h": cfg.get("grace_h", 1)}
        slots = {}
        for h in hour_objs:
            due = bool(cfg.get("every_hour")) or h.hour in cfg.get("hours", [])
            if due:
                slots[h.isoformat(timespec="minutes")] = True
        expected[src] = slots

    # Associate each event with the nearest expected slot at or before completion,
    # within the source's grace window. This prevents a 06:40 completion from
    # making the 06:00 due slot look missing.
    unmatched = []
    for e in events:
        end = _parse(e.get("ended_kst"))
        if not end:
            continue
        src = e["source"]
        cfg = EXPECTED.get(src, {})
        candidates = []
        for h in hour_objs:
            if h > end:
                continue
            due = bool(cfg.get("every_hour")) or h.hour in cfg.get("hours", [])
            if due and (end - h) <= dt.timedelta(hours=cfg.get("grace_h", 1)):
                candidates.append(h)
        if candidates:
            slot = max(candidates)
            key = slot.isoformat(timespec="minutes")
        else:
            key = end.replace(minute=0, second=0, microsecond=0).isoformat(timespec="minutes")
            unmatched.append((src, key))
        prev = matrix.setdefault(src, {}).get(key)
        if prev is None or severity.get(e["status"], 2) >= severity.get(prev, 2):
            matrix[src][key] = e["status"]
            detail.setdefault(src, {})[key] = e

    # Any past due slot with no event becomes an explicit missed slot.
    # Future/current slots inside grace stay "expected" instead of falsely red.
    for src, slots in expected.items():
        grace = dt.timedelta(hours=EXPECTED[src].get("grace_h", 1))
        for key in slots:
            h = dt.datetime.fromisoformat(key)
            if key not in matrix.get(src, {}) and now > h + grace:
                matrix.setdefault(src, {})[key] = "missed"

    out = {
        "schema": 2,
        "generated_kst": now.isoformat(timespec="seconds"),
        "window_days": days,
        "hours": hours,
        "matrix": matrix,
        "matrix_detail": detail,
        "expected": expected,
        "schedule_meta": schedule_meta,
        "latest": latest_rows,
        "events": sorted(events, key=lambda e: e.get("ended_kst") or "", reverse=True),
    }
    d = Path(site_dir) / "ops"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ingest-status.json").write_text(
        json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return out
