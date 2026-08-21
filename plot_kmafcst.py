# -*- coding: utf-8 -*-
"""
기상청 단기예보(동네예보) vs 오늘 실측(ASOS) — 1시간 시계열 (로컬 전용, 사이트 미게시).

실측 확정 (2026-08-21):
  · API허브 typ02 VilageFcstInfoService_2.0/getVilageFcst — apihub-pub만 일반키 허용
  · 단기예보는 1시간 간격(TMP 등), 발표 02/05/08/11/14/17/20/23시(+10분께 가용)
비교선:
  · 실측 TA (ASOS, 현재까지)
  · 전일 23시 발표 예보 — "어제 시점에 오늘을 어떻게 봤나" (하루 전체 기준선)
  · 최신 발표 예보 — 당일 갱신분

사용: python plot_kmafcst.py [--no-fetch]
산출: output/YYYYMMDD/kmafcst/kmafcst_vs_obs.png (사이트 '예보-관측' 탭 게시, 2026-08-21)
"""
import argparse
import datetime as dt
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

# 동네예보 격자 (표출 지점 6곳)
CITY_GRID = {"서울": (60, 127), "대전": (67, 100), "대구": (89, 90),
             "부산": (98, 76), "광주": (58, 74), "강릉": (92, 131)}
BASE_HOURS = [2, 5, 8, 11, 14, 17, 20, 23]

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


def latest_base(now: dt.datetime) -> tuple[str, str]:
    """가장 최근 발표 (발표 후 15분 여유)."""
    t = now - dt.timedelta(minutes=15)
    cands = [h for h in BASE_HOURS if h <= t.hour]
    if cands:
        return t.strftime("%Y%m%d"), f"{max(cands):02d}00"
    y = t - dt.timedelta(days=1)
    return y.strftime("%Y%m%d"), "2300"


def fetch_tmp(nx: int, ny: int, base_date: str, base_time: str, key: str) -> pd.Series:
    """TMP(1h 기온) 예보 시계열 — index=유효시각(KST datetime)."""
    r = requests.get(API, params={"pageNo": 1, "numOfRows": 1300, "dataType": "JSON",
                                  "base_date": base_date, "base_time": base_time,
                                  "nx": nx, "ny": ny, "authKey": key}, timeout=60)
    j = r.json()
    if j["response"]["header"]["resultCode"] != "00":
        raise RuntimeError(f"단기예보 오류: {j['response']['header']}")
    rows = {}
    for it in j["response"]["body"]["items"]["item"]:
        if it["category"] == "TMP":
            t = dt.datetime.strptime(it["fcstDate"] + it["fcstTime"], "%Y%m%d%H%M")
            rows[t] = float(it["fcstValue"])
    return pd.Series(rows).sort_index()


def load_obs_today(day: dt.date) -> pd.DataFrame:
    path = os.path.join(VERIF_DIR, "obs", f"{day:%Y-%m}.csv")
    df = pd.read_csv(path, parse_dates=["TM"])
    return df[df["TM"].dt.date == day]


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

    obs = load_obs_today(today)
    bd_new, bt_new = latest_base(now)
    yday = (now - dt.timedelta(days=1)).strftime("%Y%m%d")

    fig, axes = plt.subplots(3, 2, figsize=(13, 11), sharex=True)
    x0 = dt.datetime.combine(today, dt.time(0))
    x1 = x0 + dt.timedelta(hours=24)

    for ax, (city, (nx, ny)) in zip(axes.flat, CITY_GRID.items()):
        # 실측
        stn = CITY_OBS_STN[city]
        o = obs[obs["STN"] == stn].set_index("TM")["TA"].sort_index()
        ax.plot(o.index, o.values, "-o", color="black", ms=3.5, lw=1.8,
                label="실측(ASOS)", zorder=5)
        # 전일 23시 발표 (오늘 하루 기준선)
        try:
            f_base = fetch_tmp(nx, ny, yday, "2300", key)
            f = f_base[(f_base.index >= x0) & (f_base.index <= x1)]
            ax.plot(f.index, f.values, "--s", color="tab:blue", ms=3, lw=1.2,
                    label="예보(전일 23시 발표)")
        except Exception as e:
            print(f"[단기예보] {city} 전일 발표 실패: {e}")
        # 최신 발표
        if (bd_new, bt_new) != (yday, "2300"):
            try:
                f_new = fetch_tmp(nx, ny, bd_new, bt_new, key)
                f2 = f_new[(f_new.index >= x0) & (f_new.index <= x1)]
                ax.plot(f2.index, f2.values, ":^", color="tab:red", ms=3, lw=1.2,
                        label=f"예보(금일 {bt_new[:2]}시 발표)")
            except Exception as e:
                print(f"[단기예보] {city} 최신 발표 실패: {e}")
        ax.axvline(now, color="#999", lw=0.8, ls="-")
        ax.set_title(city, fontsize=13, weight="bold")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, loc="best")
        ax.set_xlim(x0, x1)

    for ax in axes.flat:
        ax.tick_params(labelsize=9)
    fig.suptitle(f"기상청 단기예보(동네예보 TMP·1시간) vs ASOS 지상관측 — 기온(℃)  {today}\n"
                 f"검정=실측 · 파랑=전일 23시 발표 · 빨강=최신 발표  (세로선: 생성 {now:%H:%M})",
                 fontsize=13)
    fig.autofmt_xdate()
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    out_dir = os.path.join(OUT_DIR, f"{today:%Y%m%d}", "kmafcst")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "kmafcst_vs_obs.png")
    fig.savefig(out, dpi=110)
    plt.close(fig)
    print(f"[단기예보] 저장: {out}")


if __name__ == "__main__":
    main()
