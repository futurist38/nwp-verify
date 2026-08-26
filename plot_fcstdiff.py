# -*- coding: utf-8 -*-
"""
예보 변화 지도 — 어제 발표 대비 오늘 발표의 일 최고/최저기온 변화(℃).

"예보가 얼마나 바뀌었나"를 한눈에 보기 위한 표출 (2026-08-26 사용자 요청).
비교 짝은 **어제 17시 발표 → 오늘 05시 발표** (사용자 확정) — 실무에서 저녁에 본
예보와 아침에 새로 나온 예보를 견주는 방식이다. 밤사이 얼마나 바뀌었는지가 보인다.

대상일은 **내일**만. 오늘은 이미 지난 시각이 예보에서 빠져 일최저(주로 새벽)가
잘리고, 모레는 어제 발표가 8시간밖에 담지 못한다(단기예보 3일 한계, 2026-08-26 실측:
어제 11시 발표의 모레 커버리지 8h vs 오늘 11시 발표 24h) — 둘 다 공정한 비교가 안 된다.

지점: ASOS 97곳의 위경도를 동네예보 격자로 변환해 사용(관측 지도와 같은 지점망이라
     두 탭의 그림을 겹쳐 읽을 수 있다). 발표분은 불변이라 캐시하면 하루 97회만 호출.

산출: output/YYYYMMDD/fcstdiff/fcstdiff_{tmx|tmn}_d{1,2}.png
캐시: verification/fcstdiff/{발표YYYYMMDDHH}.json
사용: python plot_fcstdiff.py [--issue YYYYMMDDHH]
"""
import argparse
import datetime as dt
import json
import os

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import sslfix  # noqa: F401
import mapviz
from kma_vilage import auth_key, fetch, latlon_to_grid
from config import OUT_DIR, VERIF_DIR, CITY_OBS_STN

CACHE_DIR = os.path.join(VERIF_DIR, "fcstdiff")
STN_CSV = os.path.join(VERIF_DIR, "obs", "stations.csv")
CACHE_KEEP_DAYS = 4     # 어제·오늘만 쓰므로 그 이상은 버림(발표당 ~130KB)
PREV_HOUR, NOW_HOUR = 17, 5   # 어제 17시 발표 → 오늘 05시 발표 (사용자 확정 짝)
MIN_HOURS = 20          # 대상일 커버리지가 이보다 적으면 그 날은 비교하지 않음
TARGET_DAYS = [1]       # 내일만 — 아래 주석 참조
VARS = {"tmx": ("일 최고기온", np.max), "tmn": ("일 최저기온", np.min)}
LABEL_CITIES = ["서울", "대전", "대구", "광주", "부산", "강릉"]  # 겹침 방지

from matplotlib import font_manager as _fm
_inst = {f.name for f in _fm.fontManager.ttflist}
for _font in ["Malgun Gothic", "NanumGothic", "Noto Sans CJK KR"]:
    if _font in _inst:
        matplotlib.rc("font", family=_font)
        break
matplotlib.rcParams["axes.unicode_minus"] = False


def stations() -> pd.DataFrame:
    df = pd.read_csv(STN_CSV)
    df["nx"], df["ny"] = zip(*[latlon_to_grid(r.lat, r.lon) for r in df.itertuples()])
    return df


def load_issue(bdt: str, stns: pd.DataFrame, key: str) -> dict:
    """{STN: {'YYYYMMDDHH': 기온}} — 캐시에 없는 지점만 호출."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{bdt}.json")
    cache = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    n_new = 0
    for r in stns.itertuples():
        if str(r.STN) in cache:
            continue
        try:
            cache[str(r.STN)] = fetch(r.nx, r.ny, bdt, key)["TMP"]
            n_new += 1
        except Exception as e:
            print(f"[예보변화] {bdt} STN{r.STN} 수신 실패: {e}")
    if n_new:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
        print(f"[예보변화] {bdt}: 신규 {n_new}지점 수신 → {path}")
    return cache


def prune_cache(today: dt.date):
    """오래된 발표 캐시 삭제 — 비교에 어제·오늘만 쓰므로 쌓아둘 이유가 없다."""
    cut = f"{today - dt.timedelta(days=CACHE_KEEP_DAYS):%Y%m%d}"
    n = 0
    for f in os.listdir(CACHE_DIR) if os.path.isdir(CACHE_DIR) else []:
        if f.endswith(".json") and f[:8] < cut:
            os.remove(os.path.join(CACHE_DIR, f))
            n += 1
    if n:
        print(f"[예보변화] 캐시 정리: {n}건 삭제")


def daily_stat(series: dict, day: dt.date, fn) -> float | None:
    """해당 일자의 시간별 값에서 최고/최저. 커버리지 부족이면 None(추정 금지)."""
    vals = [v for k, v in series.items() if k[:8] == f"{day:%Y%m%d}"]
    return float(fn(vals)) if len(vals) >= MIN_HOURS else None


def draw(diff: pd.DataFrame, var: str, day: dt.date, lead: int,
         bdt_now: str, bdt_prev: str, out_dir: str):
    title, _ = VARS[var]
    pts = diff.dropna(subset=["d"])
    if len(pts) < 10:
        print(f"[예보변화] {var} +{lead}일: 지점 {len(pts)}개 — 생략")
        return False

    gx, gy, gz = mapviz.interp(pts["lon"], pts["lat"], pts["d"])
    lim = max(2.0, float(np.ceil(np.nanmax(np.abs(pts["d"])))))

    fig = plt.figure(figsize=(6.4, 7.2))
    ax, tf = mapviz.make_axes(fig)
    pm = ax.pcolormesh(gx, gy, gz, cmap="RdBu_r", vmin=-lim, vmax=lim,
                       shading="auto", **tf)
    mapviz.basemap(ax)
    fig.colorbar(pm, ax=ax, shrink=0.8, label="예보 변화 (℃)  빨강=상향 · 파랑=하향")

    val = pts.set_index("STN")["d"]
    for name in LABEL_CITIES:
        stn = CITY_OBS_STN.get(name)
        if stn in val.index:
            row = pts[pts["STN"] == stn].iloc[0]
            mapviz.label_point(ax, row["lon"], row["lat"],
                               f"{name} {val[stn]:+.1f}", tf)

    ax.set_title(f"{title} 예보 변화  {day:%m-%d}(+{lead}일)\n"
                 f"{bdt_prev[4:6]}-{bdt_prev[6:8]} {bdt_prev[8:]}시 발표 대비 "
                 f"{bdt_now[4:6]}-{bdt_now[6:8]} {bdt_now[8:]}시 발표  "
                 f"(지점 {len(pts)}개)", fontsize=11)
    fig.subplots_adjust(top=0.94, bottom=0.04, left=0.06, right=0.98)
    os.makedirs(out_dir, exist_ok=True)
    fig.savefig(os.path.join(out_dir, f"fcstdiff_{var}_d{lead}.png"), dpi=100,
                bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--issue", default="", help="기준 발표시각 YYYYMMDDHH (생략=최신)")
    args = p.parse_args()

    now = dt.datetime.now()
    if args.issue:
        bdt_now = args.issue
        t = dt.datetime.strptime(bdt_now, "%Y%m%d%H")
    else:
        t = dt.datetime.combine(now.date(), dt.time(NOW_HOUR))
        if now < t + dt.timedelta(minutes=15):     # 아직 안 나온 발표면 전날 짝으로
            t -= dt.timedelta(days=1)
        bdt_now = f"{t:%Y%m%d%H}"
    prev_t = dt.datetime.combine(t.date() - dt.timedelta(days=1), dt.time(PREV_HOUR))
    bdt_prev = f"{prev_t:%Y%m%d%H}"
    print(f"[예보변화] {bdt_prev}(어제 {PREV_HOUR}시) → {bdt_now}(오늘 {NOW_HOUR}시)")

    key, stns = auth_key(), stations()
    cur, prev = load_issue(bdt_now, stns, key), load_issue(bdt_prev, stns, key)
    if not cur or not prev:
        raise SystemExit("[예보변화] 발표 자료 부족 — 중단")

    out_dir = os.path.join(OUT_DIR, f"{t.date():%Y%m%d}", "fcstdiff")
    n = 0
    for lead in TARGET_DAYS:
        day = t.date() + dt.timedelta(days=lead)
        for var, (_, fn) in VARS.items():
            rows = []
            for r in stns.itertuples():
                a = daily_stat(cur.get(str(r.STN), {}), day, fn)
                b = daily_stat(prev.get(str(r.STN), {}), day, fn)
                rows.append({"STN": r.STN, "lon": r.lon, "lat": r.lat,
                             "d": None if (a is None or b is None) else a - b})
            n += draw(pd.DataFrame(rows), var, day, lead, bdt_now, bdt_prev, out_dir)
    prune_cache(t.date())
    print(f"[예보변화] {n}장 생성 → {out_dir}")


if __name__ == "__main__":
    main()
