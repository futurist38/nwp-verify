# -*- coding: utf-8 -*-
"""
고도별 기압장 지도 (2026-09-07 사용자 요청): 지상(해면기압 등압선 + 2m 기온) · 925/850/700/500/300/200 hPa
(지오퍼텐셜 고도 등고선 + 그 층의 기온 색). 영역은 동아시아(100~150E, 20~55N), 6시간 간격 0~120h.

입력: fetch_upper.py 산출(ECMWF pl·sfc, GFS) + kim_*.grib2(지상만 — prmsl·2t).
산출: output/YYYYMMDD/upper/{model}_{run}_f{step:03d}_{sfc|p925|...|p200}.png
--delete-raw: 그림을 만든 뒤 상층 GRIB 원본을 지운다(그림만 보존 — 사용자 결정). KIM 본 파일은 남긴다.

GRIB 실측(2026-09-07): ECMWF pl gh(gpm)·t(K) typeOfLevel=isobaricInhPa, msl(Pa) meanSea, 2t heightAboveGround/2.
GFS HGT→shortName gh, TMP→t, PRMSL→prmsl(meanSea). KIM prmsl(meanSea)·2t.
"""
import argparse
import datetime as dt
import glob
import os

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import sslfix  # noqa: F401
from config import OUT_DIR, DATA_DIR, KST_OFFSET_H, LON_MIN, LON_MAX, LAT_MIN, LAT_MAX
from fetch_upper import LEVELS, UP_LON_MIN, UP_LON_MAX, UP_LAT_MIN, UP_LAT_MAX

# 등치선 간격(지상 hPa, 상층 m)과 기온 색 범위(℃) — 층별 관례
CONTOUR = {"sfc": 4, 925: 30, 850: 30, 700: 30, 500: 60, 300: 120, 200: 120}
TRANGE = {"sfc": (-20, 36), 925: (-15, 32), 850: (-20, 28), 700: (-30, 15),
          500: (-45, 0), 300: (-65, -25), 200: (-75, -40)}

from matplotlib import font_manager as _fm
_inst = {f.name for f in _fm.fontManager.ttflist}
for _font in ["Malgun Gothic", "NanumGothic", "Noto Sans CJK KR"]:
    if _font in _inst:
        matplotlib.rc("font", family=_font)
        break
matplotlib.rcParams["axes.unicode_minus"] = False


def read_fields(path: str, want: set[tuple[str, str, int]]) -> tuple[dict, np.ndarray, np.ndarray, dt.datetime]:
    """want = {(shortName, typeOfLevel, level)} → {(sn, tol, lev): {step: 2D}} (동아시아 절단)."""
    import eccodes
    out: dict = {}
    geo = None
    with open(path, "rb") as f:
        while True:
            gid = eccodes.codes_grib_new_from_file(f)
            if gid is None:
                break
            try:
                key = (eccodes.codes_get(gid, "shortName"), eccodes.codes_get(gid, "typeOfLevel"),
                       int(eccodes.codes_get(gid, "level")))
                if key not in want:
                    continue
                if geo is None:
                    ni, nj = eccodes.codes_get(gid, "Ni"), eccodes.codes_get(gid, "Nj")
                    lat0 = eccodes.codes_get(gid, "latitudeOfFirstGridPointInDegrees")
                    lon0 = eccodes.codes_get(gid, "longitudeOfFirstGridPointInDegrees")
                    dlat = eccodes.codes_get(gid, "jDirectionIncrementInDegrees")
                    dlon = eccodes.codes_get(gid, "iDirectionIncrementInDegrees")
                    if eccodes.codes_get(gid, "jScansPositively") == 0:
                        dlat = -dlat
                    lats = lat0 + dlat * np.arange(nj)
                    lons = ((lon0 + dlon * np.arange(ni)) + 180) % 360 - 180
                    jj = np.where((lats >= UP_LAT_MIN) & (lats <= UP_LAT_MAX))[0]
                    ii = np.where((lons >= UP_LON_MIN) & (lons <= UP_LON_MAX))[0]
                    run = (dt.datetime.strptime(str(eccodes.codes_get(gid, "dataDate")), "%Y%m%d")
                           + dt.timedelta(hours=int(eccodes.codes_get(gid, "dataTime")) // 100))
                    geo = (ni, nj, lats[jj], lons[ii], jj, ii, run)
                ni, nj, _la, _lo, jj, ii, _run = geo
                step = int(eccodes.codes_get(gid, "endStep"))
                v = eccodes.codes_get_values(gid).reshape(nj, ni)[np.ix_(jj, ii)]
                out.setdefault(key, {})[step] = v
            finally:
                eccodes.codes_release(gid)
    if geo is None:
        return {}, None, None, None
    ni, nj, lats, lons, jj, ii, run = geo
    order = np.argsort(lons)
    for k in out:
        for s in out[k]:
            out[k][s] = out[k][s][:, order]
    return out, lats, lons[order], run


def _ax(fig):
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
    ax.set_extent([UP_LON_MIN, UP_LON_MAX, UP_LAT_MIN, UP_LAT_MAX])
    try:
        ax.coastlines(resolution="50m", linewidth=0.6, color="#222")
        ax.add_feature(cfeature.BORDERS, linewidth=0.3, edgecolor="#444")
    except Exception:
        pass
    gl = ax.gridlines(draw_labels=True, linewidth=0.2, alpha=0.5)
    gl.top_labels = gl.right_labels = False
    # 한반도 표출 영역 표시(다른 탭 지도의 범위)
    ax.plot([LON_MIN, LON_MAX, LON_MAX, LON_MIN, LON_MIN], [LAT_MIN, LAT_MIN, LAT_MAX, LAT_MAX, LAT_MIN],
            color="#1a5fb4", lw=0.8, ls="--", alpha=0.7, transform=ccrs.PlateCarree())
    return ax


def draw_panel(model: str, run: dt.datetime, step: int, lev, temp: np.ndarray, field: np.ndarray,
               lats, lons, out_dir: str):
    """lev='sfc' → field=해면기압(hPa), 그 외 → 지오퍼텐셜 고도(m)."""
    fig = plt.figure(figsize=(8.6, 6.6))
    ax = _ax(fig)
    lo2d, la2d = np.meshgrid(lons, lats)
    tmin, tmax = TRANGE[lev]
    pm = ax.pcolormesh(lo2d, la2d, temp, cmap="RdYlBu_r", vmin=tmin, vmax=tmax, shading="auto")
    if lev == "sfc":
        levels = np.arange(920, 1080, CONTOUR["sfc"])
        cs = ax.contour(lo2d, la2d, field, levels=levels, colors="k", linewidths=0.6)
        ax.clabel(cs, fmt="%d", fontsize=8, inline_spacing=2)
        # 고·저기압 중심 표시(국지 극값 — 5° 창)
        _mark_centers(ax, field, lats, lons)
        title = "지상 — 해면기압(hPa) · 색 2m 기온(℃)"
    else:
        levels = np.arange(0, 20000, CONTOUR[lev])
        cs = ax.contour(lo2d, la2d, field, levels=levels, colors="k", linewidths=0.6)
        ax.clabel(cs, fmt=lambda v: f"{v / 10:.0f}", fontsize=8, inline_spacing=2)   # dam
        title = f"{lev} hPa — 지오퍼텐셜 고도(dam, {CONTOUR[lev]}m 간격) · 색 기온(℃)"
    fig.colorbar(pm, ax=ax, shrink=0.8, pad=0.02, label="기온 (℃)")
    vkst = run + dt.timedelta(hours=step + KST_OFFSET_H)
    # 제목은 figure 에 — GeoAxes 의 set_title 은 set_extent 로 줄어든 지도 위 여백에 묻혀 안 보였다(실측)
    fig.suptitle(f"{model}  런 {run:%m-%d %H}UTC  +{step:03d}h  유효 {vkst:%m-%d %H}KST\n{title}",
                 fontsize=10.5, y=0.985)
    fig.subplots_adjust(top=0.93, bottom=0.04, left=0.05, right=0.99)
    os.makedirs(out_dir, exist_ok=True)
    name = "sfc" if lev == "sfc" else f"p{lev}"
    fig.savefig(os.path.join(out_dir, f"{model.lower()}_{run:%Y%m%d%H}_f{step:03d}_{name}.png"), dpi=100)
    plt.close(fig)


def _mark_centers(ax, p, lats, lons):
    from scipy.ndimage import minimum_filter, maximum_filter
    import cartopy.crs as ccrs
    w = int(round(8.0 / abs(lats[1] - lats[0])))   # 8° 창
    for filt, sym, col in ((minimum_filter, "L", "#c01c28"), (maximum_filter, "H", "#1a5fb4")):
        ext = filt(p, size=w, mode="nearest")
        js, is_ = np.where(p == ext)
        picked = []
        for j, i in sorted(zip(js, is_), key=lambda t: p[t[0], t[1]] * (1 if sym == "L" else -1)):
            v = p[j, i]
            if (sym == "L" and v > 1006) or (sym == "H" and v < 1018):
                continue
            if (lats[j] < UP_LAT_MIN + 2 or lats[j] > UP_LAT_MAX - 2
                    or lons[i] < UP_LON_MIN + 2 or lons[i] > UP_LON_MAX - 2):
                continue                                   # 경계에 걸린 것은 진짜 중심이 아니다
            if any(abs(lats[j] - a) < 8 and abs(lons[i] - b) < 8 for a, b in picked):
                continue                                   # 평탄한 마루/골에서 겹치는 표시 제거
            picked.append((lats[j], lons[i]))
            ax.text(lons[i], lats[j], sym, color=col, fontsize=14, weight="bold", ha="center", va="center",
                    transform=ccrs.PlateCarree())
            ax.text(lons[i], lats[j] - 1.2, f"{v:.0f}", color=col, fontsize=8, ha="center", va="top",
                    transform=ccrs.PlateCarree())


def render_ecmwf(pl_path: str, sfc_path: str, out_dir: str) -> int:
    want = {("gh", "isobaricInhPa", L) for L in LEVELS} | {("t", "isobaricInhPa", L) for L in LEVELS}
    f, lats, lons, run = read_fields(pl_path, want)
    n = 0
    if f:
        for L in LEVELS:
            for step in sorted(f.get(("gh", "isobaricInhPa", L), {})):
                t = f.get(("t", "isobaricInhPa", L), {}).get(step)
                if t is None:
                    continue
                draw_panel("ECMWF", run, step, L, t - 273.15, f[("gh", "isobaricInhPa", L)][step], lats, lons, out_dir)
                n += 1
    if sfc_path and os.path.exists(sfc_path):
        g, lats, lons, run = read_fields(sfc_path, {("msl", "meanSea", 0), ("2t", "heightAboveGround", 2)})
        for step in sorted(g.get(("msl", "meanSea", 0), {})):
            t = g.get(("2t", "heightAboveGround", 2), {}).get(step)
            if t is None:
                continue
            draw_panel("ECMWF", run, step, "sfc", t - 273.15, g[("msl", "meanSea", 0)][step] / 100.0, lats, lons, out_dir)
            n += 1
    return n


def render_gfs(path: str, out_dir: str) -> int:
    want = ({("gh", "isobaricInhPa", L) for L in LEVELS} | {("t", "isobaricInhPa", L) for L in LEVELS}
            | {("prmsl", "meanSea", 0), ("2t", "heightAboveGround", 2)})
    f, lats, lons, run = read_fields(path, want)
    n = 0
    if not f:
        return 0
    for L in LEVELS:
        for step in sorted(f.get(("gh", "isobaricInhPa", L), {})):
            t = f.get(("t", "isobaricInhPa", L), {}).get(step)
            if t is not None:
                draw_panel("GFS", run, step, L, t - 273.15, f[("gh", "isobaricInhPa", L)][step], lats, lons, out_dir); n += 1
    for step in sorted(f.get(("prmsl", "meanSea", 0), {})):
        t = f.get(("2t", "heightAboveGround", 2), {}).get(step)
        if t is not None:
            draw_panel("GFS", run, step, "sfc", t - 273.15, f[("prmsl", "meanSea", 0)][step] / 100.0, lats, lons, out_dir); n += 1
    return n


def render_kim(path: str, out_dir: str) -> int:
    f, lats, lons, run = read_fields(path, {("prmsl", "meanSea", 0), ("2t", "heightAboveGround", 2)})
    n = 0
    for step in sorted(f.get(("prmsl", "meanSea", 0), {})):
        if step % 6:
            continue
        t = f.get(("2t", "heightAboveGround", 2), {}).get(step)
        if t is not None:
            draw_panel("KIM", run, step, "sfc", t - 273.15, f[("prmsl", "meanSea", 0)][step] / 100.0, lats, lons, out_dir); n += 1
    return n


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--delete-raw", action="store_true", help="렌더 후 상층 GRIB 원본 삭제(그림만 보존)")
    a = p.parse_args()
    out_dir = os.path.join(OUT_DIR, dt.date.today().strftime("%Y%m%d"), "upper")

    def latest(pat):
        fs = sorted(glob.glob(os.path.join(DATA_DIR, pat)))
        return fs[-1] if fs else None

    raw = []
    ec_pl, ec_sfc, gf = latest("upper_ecmwf_pl_*.grib2"), latest("upper_ecmwf_sfc_*.grib2"), latest("upper_gfs_*.grib2")
    total = 0
    if ec_pl:
        n = render_ecmwf(ec_pl, ec_sfc, out_dir); print(f"[UPPER] ECMWF {n}장"); total += n
        raw += [ec_pl] + ([ec_sfc] if ec_sfc else [])
    if gf:
        n = render_gfs(gf, out_dir); print(f"[UPPER] GFS {n}장"); total += n
        raw.append(gf)
    km = latest("kim_*.grib2")
    if km:
        n = render_kim(km, out_dir); print(f"[UPPER] KIM 지상 {n}장" + (" (prmsl 없음 — fetch_kim KEEP 확인)" if n == 0 else "")); total += n
    print(f"[UPPER] 총 {total}장 → {out_dir}")
    if a.delete_raw:
        for f in raw:
            try:
                os.remove(f); print(f"[UPPER] 원본 삭제: {os.path.basename(f)}")
            except OSError as e:
                print(f"[UPPER] 삭제 실패 {f}: {e}")


if __name__ == "__main__":
    main()
