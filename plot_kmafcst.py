# -*- coding: utf-8 -*-
"""
기상청 단기예보(동네예보) vs 오늘 실측(ASOS) — 발표시각별 1시간 시계열.

실측 확정 (2026-08-21):
  · API허브 typ02 VilageFcstInfoService_2.0/getVilageFcst — apihub-pub만 일반키 허용
  · 단기예보는 1시간 간격(TMP), 발표 하루 8회(02/05/08/11/14/17/20/23시, +15분께 가용)

발표시각별 표출 (2026-08-21 사용자 요청):
  · 대상일 D에 대해 전일 17/20/23시 + 당일 발표 전부를 각각 PNG로 생성
    → 사이트 '예보-관측' 탭에서 발표시각 드롭다운으로 선택
  · 발표된 예보는 불변이므로 verification/kmafcst/D.json 에 캐시(커밋 대상)
    — 시간별 재실행 시 신규 발표분만 API 호출 (도시 6 × 신규 발표만)

산출: output/YYYYMMDD/kmafcst/kmafcst_{발표YYYYMMDDHH}.png
사용: python plot_kmafcst.py [--no-fetch]   (--no-fetch: ASOS 재수신 생략)
"""
import argparse
import datetime as dt
import json
import os
import re

import pandas as pd
import requests
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import sslfix  # noqa: F401
from config import BASE_DIR, OUT_DIR, VERIF_DIR, CITY_OBS_STN

API = "https://apihub-pub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getVilageFcst"
CITY_GRID = {"서울": (60, 127), "대전": (67, 100), "대구": (89, 90),
             "부산": (98, 76), "광주": (58, 74), "강릉": (92, 131)}
BASE_HOURS = [2, 5, 8, 11, 14, 17, 20, 23]
CACHE_DIR = os.path.join(VERIF_DIR, "kmafcst")

from matplotlib import font_manager as _fm
_inst = {f.name for f in _fm.fontManager.ttflist}
for _font in ["Malgun Gothic", "NanumGothic", "Noto Sans CJK KR"]:
    if _font in _inst:
        matplotlib.rc("font", family=_font)
        break
matplotlib.rcParams["axes.unicode_minus"] = False


def _auth_key() -> str:
    key = os.environ.get("KMA_AUTH_KEY")
    if key:
        return key.strip()
    m = re.search(r"KMA_AUTH_KEY\s*=\s*(\S+)",
                  open(os.path.join(BASE_DIR, ".env"), encoding="utf-8").read())
    return m.group(1)


def issuances_for(day: dt.date, now: dt.datetime) -> list[str]:
    """대상일 D의 선택지: 전일 17/20/23시 + 당일 발표분(가용 시각까지). 'YYYYMMDDHH'"""
    y = day - dt.timedelta(days=1)
    out = [f"{y:%Y%m%d}{h:02d}" for h in (17, 20, 23)]
    avail = now - dt.timedelta(minutes=15)
    for h in BASE_HOURS:
        t = dt.datetime.combine(day, dt.time(h))
        if t <= avail:
            out.append(f"{day:%Y%m%d}{h:02d}")
    return out


def fetch_tmp(nx: int, ny: int, bdt: str, key: str) -> dict:
    """발표 bdt('YYYYMMDDHH')의 TMP 시계열 {ISO시각: 값}."""
    r = requests.get(API, params={"pageNo": 1, "numOfRows": 1300, "dataType": "JSON",
                                  "base_date": bdt[:8], "base_time": bdt[8:] + "00",
                                  "nx": nx, "ny": ny, "authKey": key}, timeout=60)
    j = r.json()
    if j["response"]["header"]["resultCode"] != "00":
        raise RuntimeError(f"단기예보 오류({bdt}): {j['response']['header']}")
    out = {}
    for it in j["response"]["body"]["items"]["item"]:
        if it["category"] == "TMP":
            out[it["fcstDate"] + it["fcstTime"][:2]] = float(it["fcstValue"])
    return out


def load_fcst_cached(day: dt.date, bdts: list[str], key: str) -> dict:
    """{bdt: {city: {timekey: val}}} — 캐시에 없는 발표만 API 호출."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{day:%Y%m%d}.json")
    cache = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    changed = False
    for bdt in bdts:
        got = cache.setdefault(bdt, {})
        for city, (nx, ny) in CITY_GRID.items():
            if city in got:
                continue
            try:
                got[city] = fetch_tmp(nx, ny, bdt, key)
                changed = True
            except Exception as e:
                print(f"[단기예보] {bdt} {city} 수신 실패: {e}")
        if not got:
            cache.pop(bdt, None)
    if changed:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
        print(f"[단기예보] 캐시 갱신: {path}")
    return cache


def load_obs_day(day: dt.date) -> pd.DataFrame:
    path = os.path.join(VERIF_DIR, "obs", f"{day:%Y-%m}.csv")
    df = pd.read_csv(path, parse_dates=["TM"])
    return df[df["TM"].dt.date == day]


def render(day: dt.date, bdt: str, fc: dict, obs: pd.DataFrame,
           now: dt.datetime, out_dir: str):
    x0 = dt.datetime.combine(day, dt.time(0))
    x1 = x0 + dt.timedelta(hours=24)
    fig, axes = plt.subplots(3, 2, figsize=(13, 11), sharex=True)
    for ax, city in zip(axes.flat, CITY_GRID):
        stn = CITY_OBS_STN[city]
        o = obs[obs["STN"] == stn].set_index("TM")["TA"].sort_index()
        ax.plot(o.index, o.values, "-o", color="black", ms=3.5, lw=1.8,
                label="실측(ASOS)", zorder=5)
        ser = fc.get(city, {})
        ts = {dt.datetime.strptime(k, "%Y%m%d%H"): v for k, v in ser.items()}
        s = pd.Series(ts).sort_index()
        s = s[(s.index >= x0) & (s.index <= x1)]
        ax.plot(s.index, s.values, "--s", color="tab:blue", ms=3, lw=1.3,
                label=f"예보({bdt[4:6]}-{bdt[6:8]} {bdt[8:]}시 발표)")
        if x0 <= now <= x1:
            ax.axvline(now, color="#999", lw=0.8)
        ax.set_title(city, fontsize=13, weight="bold")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, loc="best")
        ax.set_xlim(x0, x1)
    fig.suptitle(f"기상청 단기예보(동네예보 TMP·1시간) vs ASOS 지상관측 — 기온(℃)  {day}\n"
                 f"파랑 = {bdt[4:6]}-{bdt[6:8]} {bdt[8:]}시 발표 예보 · 검정 = 실측 "
                 f"(생성 {now:%H:%M})", fontsize=13)
    fig.autofmt_xdate()
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"kmafcst_{bdt}.png")
    fig.savefig(out, dpi=110)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--no-fetch", action="store_true", help="ASOS 재수신 생략")
    args = p.parse_args()

    key = _auth_key()
    now = dt.datetime.now()
    today = now.date()

    if not args.no_fetch:
        import kma_asos
        stns = [s for s in (CITY_OBS_STN[c] for c in CITY_GRID) if s]
        df = kma_asos.get_hourly(stns, dt.datetime.combine(today, dt.time(0)), now,
                                 no_cache=True)
        kma_asos.save_monthly(df)

    obs = load_obs_day(today)
    bdts = issuances_for(today, now)
    cache = load_fcst_cached(today, bdts, key)

    out_dir = os.path.join(OUT_DIR, f"{today:%Y%m%d}", "kmafcst")
    n = 0
    for bdt in bdts:
        if bdt in cache and cache[bdt]:
            render(today, bdt, cache[bdt], obs, now, out_dir)
            n += 1
    print(f"[단기예보] 발표 {n}건 렌더 → {out_dir}")


if __name__ == "__main__":
    main()
