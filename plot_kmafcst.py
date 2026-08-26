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

import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import sslfix  # noqa: F401
from kma_vilage import auth_key, fetch, issuances_for
from config import OUT_DIR, VERIF_DIR, CITY_OBS_STN

CITY_GRID = {"서울": (60, 127), "대전": (67, 100), "대구": (89, 90),
             "부산": (98, 76), "광주": (58, 74), "강릉": (92, 131)}
CACHE_DIR = os.path.join(VERIF_DIR, "kmafcst")
# 표출할 발표시각 (2026-08-26 사용자 확정) — 전일 11·17시 + 당일 05·11·17시.
# 8회 전부는 화면·API·저장 모두 과했고, 실무에서 보는 판은 이 다섯이다.
PREV_HOURS, DAY_HOURS = (11, 17), (5, 11, 17)

from matplotlib import font_manager as _fm
_inst = {f.name for f in _fm.fontManager.ttflist}
for _font in ["Malgun Gothic", "NanumGothic", "Noto Sans CJK KR"]:
    if _font in _inst:
        matplotlib.rc("font", family=_font)
        break
matplotlib.rcParams["axes.unicode_minus"] = False


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
                got[city] = fetch(nx, ny, bdt, key)["TMP"]
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


def load_obs_range(t0: dt.datetime, t1: dt.datetime) -> pd.DataFrame:
    """창이 자정을 넘으므로 걸치는 월 CSV를 모두 읽어 기간 필터."""
    months, m = [], t0.date().replace(day=1)
    while m <= t1.date():
        months.append(f"{m:%Y-%m}")
        m = (m + dt.timedelta(days=32)).replace(day=1)
    frames = []
    for mm in months:
        path = os.path.join(VERIF_DIR, "obs", f"{mm}.csv")
        if os.path.exists(path):
            frames.append(pd.read_csv(path, parse_dates=["TM"]))
    df = pd.concat(frames, ignore_index=True)
    return df[(df["TM"] >= t0) & (df["TM"] <= t1)]


def render(bdt: str, fc: dict, obs: pd.DataFrame, now: dt.datetime, out_dir: str):
    """발표시각 기준 창(−6h 실황 맥락 ~ +24h 예보 전체) — 2026-08-23 사용자 요청.
    발표 이후 구간에 실측이 겹쳐 그려져 '이 발표가 맞았나'가 바로 보임."""
    bt = dt.datetime.strptime(bdt, "%Y%m%d%H")
    x0, x1 = bt - dt.timedelta(hours=6), bt + dt.timedelta(hours=24)

    series = {}   # city -> (obs Series, fcst Series) — y축 공동 스케일 계산용
    for city in CITY_GRID:
        o = obs[obs["STN"] == CITY_OBS_STN[city]].set_index("TM")["TA"].sort_index()
        o = o[(o.index >= x0) & (o.index <= x1)]
        ts = {dt.datetime.strptime(k, "%Y%m%d%H"): v
              for k, v in fc.get(city, {}).items()}
        s = pd.Series(ts).sort_index()
        series[city] = (o, s[(s.index >= bt) & (s.index <= x1)])

    allv = pd.concat([pd.concat(v) for v in series.values()])
    ymid = (allv.min() + allv.max()) / 2
    yspan = max(8.0, (allv.max() - allv.min()) + 3.0)   # 최소 8℃ 폭
    y0, y1 = ymid - yspan / 2, ymid + yspan / 2

    import matplotlib.dates as mdates
    fig, axes = plt.subplots(3, 2, figsize=(13, 11), sharex=True, sharey=True)
    for ax, city in zip(axes.flat, CITY_GRID):
        o, s = series[city]
        ax.plot(o.index, o.values, "-o", color="black", ms=3.5, lw=1.8,
                label="실측(ASOS)", zorder=5)
        ax.plot(s.index, s.values, "--s", color="tab:blue", ms=3, lw=1.3,
                label=f"예보({bdt[4:6]}-{bdt[6:8]} {bdt[8:]}시 발표)")
        ax.axvline(bt, color="tab:blue", lw=1.0, ls=":", alpha=0.9)
        if x0 <= now <= x1:
            ax.axvline(now, color="#999", lw=0.8)
        ax.set_title(city, fontsize=13, weight="bold")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, loc="best")
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
        loc = mdates.HourLocator(byhour=range(0, 24, 3))  # 자정 눈금 → 날짜 전환 표시
        ax.xaxis.set_major_locator(loc)
        ax.xaxis.set_major_formatter(
            mdates.ConciseDateFormatter(loc, formats=["%y", "%m월", "%d일", "%H시", "%H시", "%S"],
                                        offset_formats=["", "", "", "", "", ""]))
    fig.suptitle(f"기상청 단기예보(동네예보 TMP·1시간) vs ASOS 지상관측 — 기온(℃)\n"
                 f"파란 점선 = {bdt[4:6]}-{bdt[6:8]} {bdt[8:]}시 발표 시점 · 창 = 발표 -6h ~ +24h · "
                 f"y축 6도시 공통 (생성 {now:%H:%M})", fontsize=13)
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

    key = auth_key()
    now = dt.datetime.now()
    today = now.date()

    if not args.no_fetch:
        import kma_asos
        stns = [s for s in (CITY_OBS_STN[c] for c in CITY_GRID) if s]
        df = kma_asos.get_hourly(stns, dt.datetime.combine(today, dt.time(0)), now,
                                 no_cache=True)
        kma_asos.save_monthly(df)

    bdts = issuances_for(today, now, PREV_HOURS, DAY_HOURS)
    cache = load_fcst_cached(today, bdts, key)
    # 창 = 가장 이른 발표 −6h ~ 가장 늦은 발표 +24h
    obs = load_obs_range(dt.datetime.combine(today - dt.timedelta(days=1), dt.time(11)),
                         now)

    out_dir = os.path.join(OUT_DIR, f"{today:%Y%m%d}", "kmafcst")
    n = 0
    for bdt in bdts:
        if bdt in cache and cache[bdt]:
            render(bdt, cache[bdt], obs, now, out_dir)
            n += 1
    # 표출 대상 밖 발표분은 지운다 — 남겨두면 계속 사이트로 복사된다
    keep = {f"kmafcst_{b}.png" for b in bdts}
    gone = 0
    for f in os.listdir(out_dir) if os.path.isdir(out_dir) else []:
        if f.startswith("kmafcst_") and f not in keep:
            os.remove(os.path.join(out_dir, f))
            gone += 1
    print(f"[단기예보] 발표 {n}건 렌더 → {out_dir}" + (f" (구 발표분 {gone}장 삭제)" if gone else ""))


if __name__ == "__main__":
    main()
