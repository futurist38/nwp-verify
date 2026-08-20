# -*- coding: utf-8 -*-
"""
관측 실황 지도 (ASOS 전 지점 보간) — 기온·일사·체감온도.

ASOS ~97지점 시간값을 격자 보간(scipy griddata)해 부드러운 색 필드로 그린다.
바다는 cartopy OCEAN 피처를 위에 덮어 마스킹(간단·견고).
북한 지역은 지점이 없어 보간 헐 밖 → 공백이 정상(추정으로 채우지 않음).

체감온도(KMA 공식):
  여름(5~9월): 습구온도(Stull 2011) 기반 KMA 여름 체감온도
  겨울(Ta≤10℃ & WS≥1.3m/s): 풍속냉각(wind chill)
  그 외: 기온 그대로

산출: output/<관측일YYYYMMDD>/obsmaps/obs_{ta|si|feel}_{HH}.png  (3시간 간격)

사용:
    python plot_obsmap.py                 # 어제 전일 + 오늘 가용 시각
    python plot_obsmap.py --date 2026-08-19
"""
import argparse
import datetime as dt
import glob
import os

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.interpolate import griddata

from config import BASE_DIR, OUT_DIR, VERIF_DIR

# 한글 폰트 (plot_charts와 동일 규칙)
from matplotlib import font_manager as _fm
_inst = {f.name for f in _fm.fontManager.ttflist}
for _font in ["Malgun Gothic", "NanumGothic", "Noto Sans CJK KR"]:
    if _font in _inst:
        matplotlib.rc("font", family=_font)
        break
matplotlib.rcParams["axes.unicode_minus"] = False

try:
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    HAS_CARTOPY = True
except Exception:
    HAS_CARTOPY = False

# 남한 관측 영역 (모델 지도보다 좁게)
EXT = [125.0, 130.0, 33.0, 38.8]
GRID_RES = 0.05
HOURS = list(range(0, 24, 3))

# 표출 지점 (사용자 지정, 2026-08-20)
LABEL_CITIES = [("서울", 108), ("대전", 133), ("대구", 143),
                ("부산", 159), ("광주", 156), ("강릉", 105)]

VARS = {
    # key: (컬럼계산, cmap, vmin, vmax, 제목, 단위)
    "ta":   ("TA",   "RdYlBu_r", -15, 38, "기온", "℃"),
    "si":   ("SI",   "YlOrRd",     0,  4, "일사", "MJ/㎡·h"),
    "feel": ("FEEL", "RdYlBu_r", -15, 38, "체감온도", "℃"),
}


def feel_temp(ta, hm, ws):
    """KMA 체감온도. 여름(5~9월 외부에서 월 판단)·겨울 조건은 호출부가 아니라
    값 조건으로 처리: 더위 체감은 Ta≥20에서, 추위 체감은 Ta≤10 & WS≥1.3에서 의미."""
    out = np.array(ta, dtype=float)
    ta = np.asarray(ta, dtype=float)
    hm = np.asarray(hm, dtype=float)
    ws = np.asarray(ws, dtype=float)

    # 여름형 (습구온도 Stull 2011 → KMA 여름 체감온도)
    hot = (ta >= 20) & ~np.isnan(hm)
    if hot.any():
        t, rh = ta[hot], np.clip(hm[hot], 1, 100)
        tw = (t * np.arctan(0.151977 * np.sqrt(rh + 8.313659))
              + np.arctan(t + rh) - np.arctan(rh - 1.67633)
              + 0.00391838 * rh ** 1.5 * np.arctan(0.023101 * rh) - 4.686035)
        out[hot] = (-0.2442 + 0.55399 * tw + 0.45535 * t
                    - 0.0022 * tw ** 2 + 0.00278 * tw * t + 3.0)

    # 겨울형 (wind chill, Ta≤10℃ & WS≥1.3m/s)
    cold = (ta <= 10) & ~np.isnan(ws) & (ws >= 1.3)
    if cold.any():
        t, v = ta[cold], ws[cold] * 3.6  # m/s → km/h
        out[cold] = (13.12 + 0.6215 * t - 11.37 * v ** 0.16
                     + 0.3965 * t * v ** 0.16)
    return out


def load_obs_day(day: dt.date) -> pd.DataFrame:
    path = os.path.join(VERIF_DIR, "obs", f"{day:%Y-%m}.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, parse_dates=["TM"])
    df = df[df["TM"].dt.date == day]
    stn = pd.read_csv(os.path.join(VERIF_DIR, "obs", "stations.csv"))
    return df.merge(stn[["STN", "lon", "lat"]], on="STN", how="inner")


def draw_map(df_h: pd.DataFrame, var_key: str, day: dt.date, hour: int, out_dir: str,
             vrange=None):
    col, cmap, vmin, vmax, title, unit = VARS[var_key]
    if vrange is not None:
        vmin, vmax = vrange
    if col == "FEEL":
        df_h = df_h.copy()
        df_h["FEEL"] = feel_temp(df_h["TA"], df_h["HM"], df_h["WS"])
    pts = df_h.dropna(subset=[col, "lon", "lat"])
    if len(pts) < 10:
        return False  # 지점 부족 — 누락으로 처리(그리지 않음)

    gx, gy = np.meshgrid(np.arange(EXT[0], EXT[1], GRID_RES),
                         np.arange(EXT[2], EXT[3], GRID_RES))
    gz = griddata((pts["lon"], pts["lat"]), pts[col], (gx, gy), method="linear")

    fig = plt.figure(figsize=(6.4, 7.2))
    if HAS_CARTOPY:
        ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
        ax.set_extent(EXT)
    else:
        ax = fig.add_subplot(1, 1, 1)
        ax.set_xlim(EXT[0], EXT[1]); ax.set_ylim(EXT[2], EXT[3])
        ax.set_aspect(1.0 / np.cos(np.deg2rad(36)))

    pm = ax.pcolormesh(gx, gy, gz, cmap=cmap, vmin=vmin, vmax=vmax, shading="auto")
    if HAS_CARTOPY:
        ax.add_feature(cfeature.OCEAN.with_scale("50m"), facecolor="#eef1f5", zorder=2)
        ax.coastlines(resolution="50m", linewidth=0.6, zorder=3)
    fig.colorbar(pm, ax=ax, shrink=0.8, label=f"{title} ({unit})")

    # 주요 도시 라벨 (실측 원값)
    stn_val = pts.set_index("STN")[col]
    for name, stn in LABEL_CITIES:
        if stn in stn_val.index:
            row = pts[pts["STN"] == stn].iloc[0]
            ax.plot(row["lon"], row["lat"], "o", ms=4, mfc="white", mec="black", zorder=4)
            ax.annotate(f"{name}\n{stn_val[stn]:.1f}", (row["lon"], row["lat"]),
                        textcoords="offset points", xytext=(5, -12),
                        fontsize=8, zorder=4,
                        path_effects=None)

    ax.set_title(f"ASOS {title} 실황  {day:%m-%d} {hour:02d}시 KST  (지점 {len(pts)}개 보간)",
                 fontsize=11)
    fig.subplots_adjust(top=0.94, bottom=0.04, left=0.06, right=0.98)
    os.makedirs(out_dir, exist_ok=True)
    fig.savefig(os.path.join(out_dir, f"obs_{var_key}_{hour:02d}.png"), dpi=100)
    plt.close(fig)
    return True


def make_day(day: dt.date) -> int:
    df = load_obs_day(day)
    if df.empty:
        print(f"[관측지도] {day}: 실황 없음 — 생략")
        return 0
    out_dir = os.path.join(OUT_DIR, f"{day:%Y%m%d}", "obsmaps")

    # 기온·체감은 당일 실측 범위로 색축 고정 (하루 안에서는 동일 → 시간 간 비교 가능,
    # 8월에 -15~38 고정축을 쓰면 대비가 사라지는 문제 회피)
    df_feel = df.assign(FEEL=feel_temp(df["TA"], df["HM"], df["WS"]))
    vranges = {}
    for key, col in [("ta", "TA"), ("feel", "FEEL")]:
        s = df_feel[col].dropna()
        if len(s):
            vranges[key] = (float(np.floor(s.min() - 1)), float(np.ceil(s.max() + 1)))

    n = 0
    for hour in HOURS:
        df_h = df[df["TM"].dt.hour == hour]
        if df_h.empty:
            continue
        for var_key in VARS:
            if draw_map(df_h, var_key, day, hour, out_dir, vranges.get(var_key)):
                n += 1
    print(f"[관측지도] {day}: {n}장 저장 → {out_dir}")
    return n


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=None, help="관측일 YYYY-MM-DD (생략 시 어제+오늘)")
    p.add_argument("--no-fetch", action="store_true", help="API 수신 생략(기존 CSV만)")
    args = p.parse_args()
    if args.date:
        make_day(dt.date.fromisoformat(args.date))
        return
    yday = dt.date.today() - dt.timedelta(days=1)
    if not args.no_fetch:
        # 당일 아침분까지 자체 수신 (score는 어제까지만 받으므로) — 캐시로 중복요청 회피
        import kma_asos
        try:
            df = kma_asos.get_hourly(kma_asos.all_stations(),
                                     dt.datetime.combine(yday, dt.time(0)),
                                     dt.datetime.now(), no_cache=True)
            kma_asos.save_monthly(df)
        except Exception as e:
            print(f"[관측지도] 실황 수신 실패({e}) — 기존 CSV로 진행")
    make_day(yday)
    make_day(dt.date.today())


if __name__ == "__main__":
    main()
