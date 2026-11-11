#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Operational ingest event logger.

Wraps a receiver command, mirrors its output, and writes one immutable JSON
event under verification/ingest/events/. The site exports only a sanitized
summary; detailed event files remain operational records in GitHub.

Usage:
  python tools/ingest_status.py run --source ecmwf --kind model -- python fetch_ecmwf.py
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENT_DIR = ROOT / "verification" / "ingest" / "events"
KST = dt.timezone(dt.timedelta(hours=9))


def now_kst() -> dt.datetime:
    return dt.datetime.now(KST)


def sanitize(text: str) -> str:
    text = re.sub(r"(?i)(authKey|authorization|token|secret|password)=?[^\s&]+", r"\1=***", text)
    text = re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1***", text)
    return text[-4000:]


def infer_issue(source: str, output: str, started: dt.datetime) -> str | None:
    pats = {
        "ecmwf": [r"ecmwf_ifs025_(\d{10})", r"최신 가용 런:\s*([0-9-]{10}\s+[0-9:]{5})"],
        "gfs": [r"수신 대상 런:\s*(\d{8})\s+(\d{2})Z", r"gfs_0p25_(\d{10})"],
        "kim": [r"kim_NE57_(\d{10})", r"kim_nc_run[^0-9]*(\d{10})"],
        "kim_upper": [r"upper_kim_(\d{10})", r"kim_NE57_(\d{10})"],
        "kma_short": [r"\b(20\d{8})(?:\b|[^0-9])"],
        "kma_mid": [r"\b(20\d{8})(?:00)?\b"],
        "kma_midland": [r"\b(20\d{8})\b"],
        "nowcast": [r"발령[^0-9]*(20\d{10})", r"issue[^0-9]*(20\d{10})"],
    }
    for pat in pats.get(source, []):
        m = re.search(pat, output)
        if not m:
            continue
        if source == "gfs" and len(m.groups()) == 2:
            return m.group(1) + m.group(2)
        val = m.group(1)
        if re.fullmatch(r"\d{10,12}", val):
            return val[:12]
    # File-based fallbacks for KMA/obs products.
    try:
        if source == "kma_short":
            files = sorted((ROOT / "verification" / "kmafcst").glob("*.json"), reverse=True)
            issues = []
            for p in files[:3]:
                j = json.loads(p.read_text(encoding="utf-8"))
                issues.extend(k for k in j if re.fullmatch(r"\d{10}", k))
            return max(issues) if issues else None
        if source == "kma_mid":
            files = [p.stem for p in (ROOT / "verification" / "midfcst").glob("*.json")
                     if re.fullmatch(r"\d{10}", p.stem)]
            return max(files) if files else None
        if source == "kma_midland":
            files = [p.stem for p in (ROOT / "verification" / "midland").glob("*.json")
                     if re.fullmatch(r"\d{10}", p.stem)]
            return max(files) if files else None
        if source == "asos":
            import pandas as pd
            p = ROOT / "verification" / "obs" / f"{started:%Y-%m}.csv"
            if p.exists():
                df = pd.read_csv(p, usecols=["TM"])
                if len(df):
                    t = pd.to_datetime(df["TM"], errors="coerce").max()
                    if not pd.isna(t):
                        return t.strftime("%Y%m%d%H")
        if source == "nowcast":
            p = ROOT / "output" / "nowcast" / "latest" / "issue.txt"
            if p.exists():
                s = p.read_text(encoding="utf-8").strip()
                return re.sub(r"\D", "", s)[:12] or None
    except Exception:
        pass
    return None


def classify(returncode: int, output: str) -> tuple[str, str | None]:
    low = output.lower()
    if returncode == 0:
        if "수신 실패" in output or "미완료" in output or "warning" in low:
            return "partial", "일부 수신 실패 또는 경고"
        return "success", None
    if returncode == 124 or "timeout" in low or "시간초과" in output:
        return "failed", "시간초과"
    if "403" in output:
        return "failed", "인증/권한 오류(HTTP 403)"
    if "429" in output:
        return "failed", "요청 제한(HTTP 429)"
    if "5" in str(returncode) and "http" in low:
        return "failed", "외부 서버 오류"
    return "failed", "수신 작업 실패"


def write_event(event: dict) -> Path:
    EVENT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = now_kst().strftime("%Y%m%dT%H%M%S")
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    path = EVENT_DIR / f"{stamp}_{event['source']}_{run_id}_{uuid.uuid4().hex[:6]}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def run(args: argparse.Namespace) -> int:
    if not args.command:
        raise SystemExit("실행할 명령이 없습니다. -- 뒤에 명령을 지정하세요.")
    started = now_kst()
    tic = time.monotonic()
    p = subprocess.run(args.command, text=True, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, errors="replace")
    output = p.stdout or ""
    sys.stdout.write(output)
    ended = now_kst()
    status, summary = classify(p.returncode, output)
    issue = infer_issue(args.source, output, started)
    lines = [x.strip() for x in sanitize(output).splitlines() if x.strip()]
    detail = "\n".join(lines[-8:]) if status != "success" else None
    event = {
        "schema": 1,
        "source": args.source,
        "label": args.label or args.source,
        "kind": args.kind,
        "issue": issue,
        "started_kst": started.isoformat(timespec="seconds"),
        "ended_kst": ended.isoformat(timespec="seconds"),
        "duration_s": round(time.monotonic() - tic, 1),
        "status": status,
        "summary": summary,
        "detail": detail,
        "returncode": p.returncode,
        "workflow": os.environ.get("GITHUB_WORKFLOW"),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
    }
    path = write_event(event)
    print(f"[ingest-status] {args.label or args.source}: {status}, issue={issue or '-'} -> {path}")
    return p.returncode


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="action", required=True)
    rp = sub.add_parser("run")
    rp.add_argument("--source", required=True)
    rp.add_argument("--label", default="")
    rp.add_argument("--kind", required=True,
                    choices=["model", "forecast", "observation", "satellite", "system"])
    rp.add_argument("command", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    if args.action == "run":
        if args.command and args.command[0] == "--":
            args.command = args.command[1:]
        raise SystemExit(run(args))


if __name__ == "__main__":
    main()
