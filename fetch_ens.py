# -*- coding: utf-8 -*-
"""
ECMWF 앙상블(ENS, 50멤버) 2m 기온 — 도시별 스프레드 요약 수신.

실측 확정 (2026-09-06, 0p25 enfo 인덱스 대조):
  · 오픈데이터 ENS 에는 평균(em)·표준편차(es) 산출물이 **없다** — pf 50멤버만 있다
    (Client.latest() 는 통과하지만 retrieve 가 'Cannot find index entries' 로 실패).
  · 2t 한 스텝 = 50멤버 × 0.66MB ≈ 33MB. 전 스텝을 받으면 런당 1.6GB → 러너에 과함.
    → 수요예측이 보는 시각만 받는다: D+1~D+6 의 06 KST(일최저 무렵)·15 KST(일최고 무렵)
      = 12스텝 ≈ 400MB. 격자는 버리고 11도시 최근접 격자점 통계(평균·표준편차·10/50/90%)
      만 JSON 으로 남긴다(5KB).
  · 바이트 범위 요청이라 필요한 메시지만 내려온다. 미러(azure/aws)로 본 서버 부담 회피.

산출: verification/ens/{runYYYYMMDDHH}.json
      {run, param, cities:{city:{valid_kst:[...], step:[...], mean:[], sd:[], p10:[], p50:[], p90:[], min:[], max:[]}}}
사용: python fetch_ens.py [--source azure|aws|ecmwf] [--time 0|12]
"""
import argparse
import datetime as dt
import json
import os
import sys

import numpy as np

import sslfix  # noqa: F401
from config import CITIES, DATA_DIR, VERIF_DIR, KST_OFFSET_H

OUT_DIR = os.path.join(VERIF_DIR, "ens")
TARGET_KST_HOURS = (6, 15)      # 일최저·일최고 부근
DAYS = range(1, 7)              # D+1 ~ D+6


def steps_for(run: dt.datetime) -> list[int]:
    """런 시각 기준, D+1~D+6 의 06·15 KST 에 해당하는 리드(h). ENS 는 0~144h 3h 간격."""
    base_kst = run + dt.timedelta(hours=KST_OFFSET_H)
    day0 = base_kst.replace(hour=0, minute=0)
    out = []
    for d in DAYS:
        for h in TARGET_KST_HOURS:
            t = day0 + dt.timedelta(days=d, hours=h)
            step = int((t - base_kst).total_seconds() // 3600)
            if 0 < step <= 144 and step % 3 == 0:
                out.append(step)
    return sorted(set(out))


def fetch(source: str, run_time: int | None) -> str:
    from ecmwf.opendata import Client
    c = Client(source=source, model="ifs", resol="0p25")
    req = {"type": "pf", "stream": "enfo", "param": ["2t"], "number": list(range(1, 51))}
    if run_time is not None:
        req["time"] = run_time
    latest = c.latest(**{**req, "step": [6]})
    steps = steps_for(latest)
    req["step"] = steps
    os.makedirs(DATA_DIR, exist_ok=True)
    target = os.path.join(DATA_DIR, f"ens_2t_{latest:%Y%m%d%H}.grib2")
    print(f"[ENS] 런 {latest:%Y-%m-%d %H}UTC, 스텝 {steps}")
    if not (os.path.exists(target) and os.path.getsize(target) > 0):
        tmp = target + ".part"
        c.retrieve(target=tmp, **req)
        os.replace(tmp, target)
    print(f"[ENS] 수신 완료: {target} ({os.path.getsize(target) / 1e6:.0f} MB)")
    return target


def summarize(path: str) -> dict:
    import eccodes
    # (step) -> list of member arrays at city points
    vals: dict[int, list[np.ndarray]] = {}
    run = None
    idx = None
    with open(path, "rb") as f:
        while True:
            gid = eccodes.codes_grib_new_from_file(f)
            if gid is None:
                break
            if run is None:
                d = str(eccodes.codes_get(gid, "dataDate")); t = int(eccodes.codes_get(gid, "dataTime")) // 100
                run = dt.datetime.strptime(d, "%Y%m%d") + dt.timedelta(hours=t)
                ni = eccodes.codes_get(gid, "Ni"); nj = eccodes.codes_get(gid, "Nj")
                lat0 = eccodes.codes_get(gid, "latitudeOfFirstGridPointInDegrees")
                lon0 = eccodes.codes_get(gid, "longitudeOfFirstGridPointInDegrees")
                dlat = eccodes.codes_get(gid, "jDirectionIncrementInDegrees")
                dlon = eccodes.codes_get(gid, "iDirectionIncrementInDegrees")
                scan_neg = eccodes.codes_get(gid, "jScansPositively") == 0
                idx = []
                for _n, lat, lon, _rep in CITIES:
                    j = int(round((lat0 - lat) / dlat)) if scan_neg else int(round((lat - lat0) / dlat))
                    i = int(round(((lon - lon0) % 360) / dlon)) % ni
                    idx.append(j * ni + i)
                idx = np.array(idx)
            step = int(eccodes.codes_get(gid, "endStep"))
            v = eccodes.codes_get_values(gid)[idx] - 273.15
            vals.setdefault(step, []).append(v)
            eccodes.codes_release(gid)
    out = {"run": run.strftime("%Y%m%d%H"), "param": "2t", "n_members": None, "cities": {}}
    steps = sorted(vals)
    for ci, (name, *_r) in enumerate(CITIES):
        c = {"step": steps, "valid_kst": [], "mean": [], "sd": [], "p10": [], "p50": [], "p90": [],
             "min": [], "max": []}
        for s in steps:
            m = np.array([a[ci] for a in vals[s]])
            out["n_members"] = len(m)
            c["valid_kst"].append((run + dt.timedelta(hours=s + KST_OFFSET_H)).strftime("%Y%m%d%H"))
            c["mean"].append(round(float(m.mean()), 1)); c["sd"].append(round(float(m.std()), 2))
            c["p10"].append(round(float(np.percentile(m, 10)), 1))
            c["p50"].append(round(float(np.percentile(m, 50)), 1))
            c["p90"].append(round(float(np.percentile(m, 90)), 1))
            c["min"].append(round(float(m.min()), 1)); c["max"].append(round(float(m.max()), 1))
        out["cities"][name] = c
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", default="azure", choices=["ecmwf", "azure", "aws"])
    p.add_argument("--time", type=int, default=None, choices=[0, 12])
    p.add_argument("--grib", default=None, help="이미 받은 GRIB 요약만")
    args = p.parse_args()
    try:
        path = args.grib or fetch(args.source, args.time)
        summ = summarize(path)
        os.makedirs(OUT_DIR, exist_ok=True)
        out = os.path.join(OUT_DIR, f"{summ['run']}.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(summ, f, ensure_ascii=False, separators=(",", ":"))
        print(f"[ENS] 요약 저장: {out} (멤버 {summ['n_members']}, 스텝 {len(next(iter(summ['cities'].values()))['step'])})")
    except Exception as e:
        print(f"[ENS] 실패: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
