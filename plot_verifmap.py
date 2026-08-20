# -*- coding: utf-8 -*-
"""
모델 오차 칩 지도 — 지점별 ECMWF/GFS(추후 KIM) 관측오차를 한 지도에.

설계 (2026-08-20, 문헌 검토 후 확정):
  · 도시마다 모델별 색 칩(세로 적층, 순서 고정). 색 = ME 다이버징(파랑 저평가↔빨강 과대),
    칩 안에 원수치 병기 (막대 길이 대신 색 — 3D/막대의 가림·왜곡 회피)
  · 칩 크기 = 신뢰도: 같은 기간 MAE가 낮은 모델의 칩을 크게 (사용자 요청)
  · 보조로 small multiples(모델당 지도 1장, 한 그림 안 패널)도 생성
  · 지점: 서울·대전·대구·부산·광주·강릉 (사용자 지정)

산출 (verification/):
  verifmap_{t2m|tcc}_{d|7|30}.png   칩 지도 (어제 하루 / 7일 / 30일 ME)
  verifmap_sm_{t2m|tcc}.png         small multiples (30일 ME, 전 검증 도시)

사용: python plot_verifmap.py
"""
import datetime as dt
import glob
import os

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable

from config import CITIES, VERIF_DIR

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

EXT = [124.8, 130.2, 33.0, 38.9]
MODEL_ORDER = ["ECMWF", "GFS", "KIM"]
MODEL_SHORT = {"ECMWF": "EC", "GFS": "GFS", "KIM": "KIM"}

# 표출 지점 (사용자 지정) — config.CITIES에서 좌표 참조
CHIP_CITIES = ["서울", "대전", "대구", "부산", "광주", "강릉"]
CITY_POS = {c[0]: (c[2], c[1]) for c in CITIES}  # name → (lon, lat)

VAR_CFG = {  # var: (색축 절대범위, 단위, 제목)
    "t2m": (3.0, "℃", "기온"),
    "tcc": (40.0, "%p", "운량"),
}
WINDOWS = {"d": 1, "7": 7, "30": 30}
CHIP_W, CHIP_H = 0.95, 0.30   # 경도·위도 단위 기본 칩 크기

# 칩 스택이 겹치는 지점의 수동 오프셋 (경도, 위도) — 실좌표에는 점+지시선
CHIP_OFFSET = {"부산": (0.75, -0.55), "대구": (-0.15, 0.05)}


def load_scores(days: int = 40) -> pd.DataFrame:
    since = dt.date.today() - dt.timedelta(days=days)
    frames = []
    for f in sorted(glob.glob(os.path.join(VERIF_DIR, "scores", "*.csv"))):
        frames.append(pd.read_csv(f, parse_dates=["valid_kst"]))
    if not frames:
        return pd.DataFrame()
    sc = pd.concat(frames, ignore_index=True).dropna(subset=["err"])
    sc["day"] = sc["valid_kst"].dt.date
    return sc[sc["day"] >= since]


def _base_ax(fig, pos=(1, 1, 1)):
    if HAS_CARTOPY:
        ax = fig.add_subplot(*pos, projection=ccrs.PlateCarree())
        ax.set_extent(EXT)
        ax.add_feature(cfeature.LAND.with_scale("50m"), facecolor="#f7f5f0")
        ax.add_feature(cfeature.OCEAN.with_scale("50m"), facecolor="#eef1f5")
        ax.coastlines(resolution="50m", linewidth=0.5)
    else:
        ax = fig.add_subplot(*pos)
        ax.set_xlim(EXT[0], EXT[1]); ax.set_ylim(EXT[2], EXT[3])
        ax.set_aspect(1.0 / np.cos(np.deg2rad(36)))
    return ax


def chip_map(sc: pd.DataFrame, var: str, wkey: str, end_day: dt.date):
    lim, unit, title = VAR_CFG[var]
    start = end_day - dt.timedelta(days=WINDOWS[wkey] - 1)
    g = sc[(sc["var"] == var) & (sc["day"] >= start) & (sc["day"] <= end_day)]
    if g.empty:
        return False
    stat = g.groupby(["city", "model"])["err"].agg(
        ME="mean", MAE=lambda e: e.abs().mean(), n="count")

    models = [m for m in MODEL_ORDER if m in g["model"].unique()]
    cmap = plt.get_cmap("RdBu_r")
    norm = Normalize(-lim, lim)

    fig = plt.figure(figsize=(6.8, 7.4))
    ax = _base_ax(fig)

    for city in CHIP_CITIES:
        if city not in CITY_POS:
            continue
        lon0, lat0 = CITY_POS[city]
        dx, dy = CHIP_OFFSET.get(city, (0, 0))
        lon, lat = lon0 + dx, lat0 + dy
        rows = {m: stat.loc[(city, m)] for m in models if (city, m) in stat.index}
        if not rows:
            continue
        best = min(rows, key=lambda m: rows[m]["MAE"])  # 신뢰도(낮은 MAE) 모델
        ax.plot(lon0, lat0, "o", ms=3, color="#333", zorder=4)
        if (dx, dy) != (0, 0):
            ax.plot([lon0, lon], [lat0, lat], "-", color="#888",
                    linewidth=0.7, zorder=3)
        ax.text(lon, lat + 0.10, city, ha="center", fontsize=10,
                weight="bold", zorder=5,
                path_effects=[pe.withStroke(linewidth=2.5, foreground="white")])
        y = lat - 0.10
        for m in models:
            if m not in rows:
                continue
            me, mae = rows[m]["ME"], rows[m]["MAE"]
            scale = 1.25 if m == best else 0.8   # 신뢰 모델 칩을 크게
            w, hgt = CHIP_W * scale, CHIP_H * scale
            y -= hgt + 0.04
            face = cmap(norm(me))
            ax.add_patch(mpatches.Rectangle(
                (lon - w / 2, y), w, hgt, facecolor=face,
                edgecolor="#333", linewidth=1.4 if m == best else 0.6, zorder=4))
            lum = 0.299 * face[0] + 0.587 * face[1] + 0.114 * face[2]
            ax.text(lon, y + hgt / 2,
                    f"{MODEL_SHORT[m]} {me:+.1f}",
                    ha="center", va="center", fontsize=8.5 * (1.1 if m == best else 0.9),
                    color="white" if lum < 0.55 else "black", zorder=5)

    sm = ScalarMappable(norm=norm, cmap=cmap)
    fig.colorbar(sm, ax=ax, shrink=0.7,
                 label=f"ME 평균오차 ({unit}) — 파랑: 저평가 / 빨강: 과대")
    period = (f"{end_day:%m/%d}" if wkey == "d"
              else f"{start:%m/%d}~{end_day:%m/%d} ({WINDOWS[wkey]}일)")
    ax.set_title(f"{title} 관측오차 (예측-실황)  {period}\n"
                 f"큰 칩·굵은 테두리 = 기간 MAE 낮음(신뢰)", fontsize=11)
    fig.subplots_adjust(top=0.91, bottom=0.03, left=0.05, right=0.98)
    out = os.path.join(VERIF_DIR, f"verifmap_{var}_{wkey}.png")
    fig.savefig(out, dpi=100)
    plt.close(fig)
    print(f"[오차지도] {out}")
    return True


def small_multiples(sc: pd.DataFrame, var: str, end_day: dt.date, days: int = 30):
    """모델당 지도 1장(전 검증 도시 색점) — 문헌상 비교 성능이 좋은 보조 뷰."""
    lim, unit, title = VAR_CFG[var]
    start = end_day - dt.timedelta(days=days - 1)
    g = sc[(sc["var"] == var) & (sc["day"] >= start) & (sc["day"] <= end_day)]
    if g.empty:
        return False
    stat = g.groupby(["city", "model"])["err"].mean()
    models = [m for m in MODEL_ORDER if m in g["model"].unique()]
    cmap = plt.get_cmap("RdBu_r")
    norm = Normalize(-lim, lim)

    fig = plt.figure(figsize=(5.6 * len(models), 6.4))
    for i, m in enumerate(models, 1):
        ax = _base_ax(fig, (1, len(models), i))
        for city, (lon, lat) in CITY_POS.items():
            if (city, m) not in stat.index:
                continue
            me = stat.loc[(city, m)]
            ax.scatter(lon, lat, s=260, c=[cmap(norm(me))],
                       edgecolors="#333", linewidths=0.7, zorder=4)
            ax.text(lon, lat - 0.22, f"{city}\n{me:+.1f}", ha="center", va="top",
                    fontsize=8, zorder=5,
                    path_effects=[pe.withStroke(linewidth=2, foreground="white")])
        ax.set_title(m, fontsize=12)
    sm = ScalarMappable(norm=norm, cmap=cmap)
    fig.colorbar(sm, ax=fig.axes, shrink=0.65, label=f"ME ({unit})")
    fig.suptitle(f"{title} 관측오차 모델별 비교  {start:%m/%d}~{end_day:%m/%d}", fontsize=13)
    out = os.path.join(VERIF_DIR, f"verifmap_sm_{var}.png")
    fig.savefig(out, dpi=100)
    plt.close(fig)
    print(f"[오차지도] {out}")
    return True


def main():
    sc = load_scores()
    if sc.empty:
        raise SystemExit("[오차지도] scores 없음 — verify.py score 먼저 실행")
    end_day = sc["day"].max()
    for var in VAR_CFG:
        for wkey in WINDOWS:
            chip_map(sc, var, wkey, end_day)
        small_multiples(sc, var, end_day)


if __name__ == "__main__":
    main()
