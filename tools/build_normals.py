# -*- coding: utf-8 -*-
"""
ASOS 일 평년값(1991~2020) 자체 산출 — 기상청 API허브에 평년값 API가 없어(2026-09-06 실측:
nrm_*, sts_nrm 등 후보 전부 404) 지상관측 일자료(kma_sfcdd3)로 직접 만든다.

  · 입력: kma_sfcdd3.php?tm1=YYYY0101&tm2=YYYY1231&stn=0  — 1년·전지점이 한 호출(8.5MB, 2초)
          → 30년 = 30회 호출. 원문은 data/normals_raw/ 에 캐시(재실행 시 무료).
  · 산출: verification/normals_daily.csv  (stn, mmdd, tavg, tmax, tmin, n)
      - 30년 중 유효 연수 n ≥ 20 인 (지점, 날짜)만 남긴다 — 1991년엔 72지점만 있었다.
      - ±7일(15일 창) 이동평균으로 다듬는다(기상청 평년값도 평활을 거친다. 다만 방식은
        동일하지 않으니 '자체 산출 평년'임을 표출에 명시).
      - 2월 29일은 윤년 자료만으로 계산(n 이 적어 대개 탈락) → 2/28 값으로 대체하지 않고 결측.
  · 공개 자료(공공누리)만 사용. 회사 자료 무관.

사용: .venv\\Scripts\\python tools/build_normals.py            # 캐시 있으면 API 호출 없음
      .venv\\Scripts\\python tools/build_normals.py --refresh  # 원문 재수신
"""
import argparse
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sslfix  # noqa: F401,E402
import requests  # noqa: E402
from kma_vilage import auth_key  # noqa: E402
from config import DATA_DIR, VERIF_DIR  # noqa: E402

URL = "https://apihub-pub.kma.go.kr/api/typ01/url/kma_sfcdd3.php"
Y0, Y1 = 1991, 2020
RAW_DIR = os.path.join(DATA_DIR, "normals_raw")
OUT_CSV = os.path.join(VERIF_DIR, "normals_daily.csv")
MIN_YEARS = 20
HALF_WIN = 7
MISSING = {"-9", "-9.0", "-99", "-99.0", "-999", "-999.0"}
# 일자료 열(0-base): TM STN WS_AVG WR_DAY WD_MAX WS_MAX WS_MAX_TM WD_INS WS_INS WS_INS_TM
#                    TA_AVG(10) TA_MAX(11) TA_MAX_TM(12) TA_MIN(13) ...
COL = {"tavg": 10, "tmax": 11, "tmin": 13}


def fetch_year(year: int, key: str, refresh: bool) -> str:
    os.makedirs(RAW_DIR, exist_ok=True)
    path = os.path.join(RAW_DIR, f"{year}.txt")
    if os.path.exists(path) and not refresh:
        return open(path, encoding="utf-8").read()
    for attempt in range(3):
        try:
            r = requests.get(URL, params={"tm1": f"{year}0101", "tm2": f"{year}1231",
                                          "stn": 0, "help": 0, "authKey": key}, timeout=180)
            r.raise_for_status()
            if "#START7777" not in r.text:
                raise RuntimeError("응답 형식 이상")
            open(path, "w", encoding="utf-8").write(r.text)
            return r.text
        except Exception as e:
            print(f"[normals] {year} 수신 실패({attempt + 1}/3): {e}")
            time.sleep(5)
    raise RuntimeError(f"{year} 수신 실패")


def parse(text: str) -> pd.DataFrame:
    rows = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        f = line.split()
        if len(f) < 15:
            continue
        rec = {"tm": f[0], "stn": int(f[1])}
        for k, i in COL.items():
            rec[k] = None if f[i] in MISSING else float(f[i])
        rows.append(rec)
    return pd.DataFrame(rows)


def smooth_circular(vals: np.ndarray, cnt: np.ndarray) -> np.ndarray:
    """366칸(윤년 기준) 배열을 ±HALF_WIN 창으로 가중(유효 연수) 이동평균. 결측 칸은 건너뜀."""
    n = len(vals)
    out = np.full(n, np.nan)
    for i in range(n):
        idx = [(i + k) % n for k in range(-HALF_WIN, HALF_WIN + 1)]
        v = vals[idx]; w = cnt[idx].astype(float)
        m = ~np.isnan(v) & (w > 0)
        if m.sum() >= HALF_WIN:          # 창의 절반 이상 있어야 다듬은 값 인정
            out[i] = np.average(v[m], weights=w[m])
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args()
    key = auth_key()

    frames = []
    for y in range(Y0, Y1 + 1):
        df = parse(fetch_year(y, key, args.refresh))
        print(f"[normals] {y}: {len(df)}행, 지점 {df['stn'].nunique()}")
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df["mmdd"] = df["tm"].str[4:8]

    # 윤년 기준 366칸 인덱스
    days = pd.date_range("2000-01-01", "2000-12-31").strftime("%m%d").tolist()
    slot = {d: i for i, d in enumerate(days)}

    out = []
    for stn, g in df.groupby("stn"):
        rec = {}
        for var in COL:
            agg = g.groupby("mmdd")[var].agg(["mean", "count"])
            vals = np.full(366, np.nan); cnt = np.zeros(366, dtype=int)
            for d, r in agg.iterrows():
                if d in slot and r["count"] >= MIN_YEARS:
                    vals[slot[d]] = r["mean"]; cnt[slot[d]] = int(r["count"])
            rec[var] = smooth_circular(vals, cnt)
            rec[var + "_n"] = cnt
        for i, d in enumerate(days):
            if all(np.isnan(rec[v][i]) for v in COL):
                continue
            out.append({"stn": stn, "mmdd": d,
                        **{v: (None if np.isnan(rec[v][i]) else round(float(rec[v][i]), 1)) for v in COL},
                        "n": int(max(rec[v + "_n"][i] for v in COL))})
    res = pd.DataFrame(out)
    os.makedirs(VERIF_DIR, exist_ok=True)
    res.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"[normals] 저장: {OUT_CSV} ({len(res)}행, 지점 {res['stn'].nunique()}, "
          f"{Y0}~{Y1} 유효연수≥{MIN_YEARS}, ±{HALF_WIN}일 평활)")


if __name__ == "__main__":
    main()
