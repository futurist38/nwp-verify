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

import sslfix  # noqa: F401  (cartopy Natural Earth 다운로드 — AVG TLS 대응)
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

# 모델 고유색: EC=빨강, GFS=초록, KIM=파랑 (2026-08-20 2차 — 주황은 빨강과
# 혼동되어 교체). 색상=모델 식별, 진하기=|ME| 크기. 부호는 칩 안 수치(±).
# 좌→우 순서도 EC→GFS→KIM 고정이라 색약에도 위치로 구분 가능.
MODEL_CMAP = {"ECMWF": "Reds", "GFS": "Greens", "KIM": "Blues"}

# 한국 표준 람베르트 정각원추 — PlateCarree는 위도 36°에서 가로 1.24배 왜곡(실측 지적)
def _proj():
    return ccrs.LambertConformal(central_longitude=127.5,
                                 standard_parallels=(30, 60))

# 표출 지점 (사용자 지정) — config.CITIES에서 좌표 참조
CHIP_CITIES = ["서울", "대전", "대구", "부산", "광주", "강릉"]
CITY_POS = {c[0]: (c[2], c[1]) for c in CITIES}  # name → (lon, lat)

VAR_CFG = {  # var: (색축 절대범위, 단위, 제목)
    "t2m": (3.0, "℃", "기온"),
    "tcc": (40.0, "%p", "운량"),
}
WINDOWS = {"d": 1, "7": 7, "30": 30}
CHIP_W, CHIP_H = 0.95, 0.30   # 경도·위도 단위 기본 칩 크기

# 칩이 겹치는 지점의 수동 오프셋 (경도, 위도) — 지점명 라벨 제거로 대부분 불필요.
# 대구·부산 칩 행의 수평 겹침만 소폭 분리 (2026-08-20 2차: 부산은 제 위치 유지)
CHIP_OFFSET = {"대구": (-0.12, 0.12), "부산": (0.12, -0.12)}


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
        ax = fig.add_subplot(*pos, projection=_proj())
        ax.set_extent(EXT, crs=ccrs.PlateCarree())
        ax.add_feature(cfeature.LAND.with_scale("50m"), facecolor="#f7f5f0")
        ax.add_feature(cfeature.OCEAN.with_scale("50m"), facecolor="#eef1f5")
        ax.coastlines(resolution="50m", linewidth=0.5)
        ax.add_feature(cfeature.NaturalEarthFeature(
            "cultural", "admin_1_states_provinces_lines", "10m",
            facecolor="none"), edgecolor="#999", linewidth=0.5)
    else:
        ax = fig.add_subplot(*pos)
        ax.set_xlim(EXT[0], EXT[1]); ax.set_ylim(EXT[2], EXT[3])
        ax.set_aspect(1.0 / np.cos(np.deg2rad(36)))
    return ax


def _xy(ax, lon, lat):
    """경위도 → 그리기 좌표 (LCC 미터 / 폴백 시 도)."""
    if HAS_CARTOPY:
        return ax.projection.transform_point(lon, lat, ccrs.PlateCarree())
    return lon, lat


def chip_map(sc: pd.DataFrame, var: str, wkey: str, end_day: dt.date):
    lim, unit, title = VAR_CFG[var]
    start = end_day - dt.timedelta(days=WINDOWS[wkey] - 1)
    g = sc[(sc["var"] == var) & (sc["day"] >= start) & (sc["day"] <= end_day)]
    if g.empty:
        return False
    stat = g.groupby(["city", "model"])["err"].agg(
        ME="mean", MAE=lambda e: e.abs().mean(), n="count")

    models = [m for m in MODEL_ORDER if m in g["model"].unique()]

    fig = plt.figure(figsize=(6.8, 7.4))
    ax = _base_ax(fig)

    # 정사각형 칩 크기 (LCC 미터 / 폴백 도)
    base = 42_000 if HAS_CARTOPY else 0.42
    gap = base * 0.18

    for city in CHIP_CITIES:
        if city not in CITY_POS:
            continue
        lon0, lat0 = CITY_POS[city]
        dx, dy = CHIP_OFFSET.get(city, (0, 0))
        x0, y0 = _xy(ax, lon0, lat0)
        x, y = _xy(ax, lon0 + dx, lat0 + dy)
        rows = {m: stat.loc[(city, m)] for m in models if (city, m) in stat.index}
        if not rows:
            continue
        best = min(rows, key=lambda m: rows[m]["MAE"])  # 신뢰도(낮은 MAE) 모델
        ax.plot(x0, y0, "o", ms=4, color="#333", zorder=4)
        # 지점명 라벨 제거(2026-08-20 2차) — 행정구역 경계선으로 위치 식별

        # 정사각형 칩 가로 배치 — 색=모델, 진하기=|ME|, 큰 칩=기간 MAE 낮음(신뢰)
        present = [m for m in models if m in rows]
        sizes = {m: base * (1.25 if m == best else 0.85) for m in present}
        total_w = sum(sizes.values()) + gap * (len(present) - 1)
        cx = x - total_w / 2
        for m in present:
            me = rows[m]["ME"]
            s = sizes[m]
            frac = min(abs(me) / lim, 1.0)
            face = plt.get_cmap(MODEL_CMAP[m])(0.20 + 0.65 * frac)
            ax.add_patch(mpatches.Rectangle(
                (cx, y - s / 2), s, s, facecolor=face,
                edgecolor="#333", linewidth=1.5 if m == best else 0.6, zorder=4))
            lum = 0.299 * face[0] + 0.587 * face[1] + 0.114 * face[2]
            ax.text(cx + s / 2, y, f"{me:+.1f}",
                    ha="center", va="center",
                    fontsize=10 if m == best else 8.5,
                    color="white" if lum < 0.55 else "black", zorder=5)
            cx += s + gap

    # 레전드: 색=모델 (진하기=|ME| 크기 안내 포함)
    handles = [mpatches.Patch(facecolor=plt.get_cmap(MODEL_CMAP[m])(0.6),
                              edgecolor="#333", label=m) for m in models]
    ax.legend(handles=handles, loc="upper left", fontsize=9, framealpha=0.9,
              title=f"진할수록 |오차| 큼 (±{lim:g}{unit} 포화)", title_fontsize=8)

    period = (f"{end_day:%m/%d}" if wkey == "d"
              else f"{start:%m/%d}~{end_day:%m/%d} ({WINDOWS[wkey]}일)")
    ax.set_title(f"{title} 관측오차 ME (예측-실황, {unit})  {period}\n"
                 f"큰 칩·굵은 테두리 = 기간 MAE 낮음(신뢰)", fontsize=11)
    fig.subplots_adjust(top=0.91, bottom=0.03, left=0.03, right=0.97)
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
            x, y = _xy(ax, lon, lat)
            off = 22_000 if HAS_CARTOPY else 0.22
            ax.scatter(x, y, s=260, c=[cmap(norm(me))],
                       edgecolors="#333", linewidths=0.7, zorder=4)
            ax.text(x, y - off, f"{city}\n{me:+.1f}", ha="center", va="top",
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
