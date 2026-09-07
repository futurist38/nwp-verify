# -*- coding: utf-8 -*-
"""
고도별 기압장 지도 (2026-09-07 사용자 요청): 지상(해면기압 등압선 + 2m 기온) · 925/850/700/500/300/200 hPa.
영역은 동아시아(100~150E, 20~55N), 6시간 간격 0~120h.

층별 채움 변수는 종관 일기도 관례를 따른다 (2026-09-07 조사 — KMA 예보 일기도·Tropical Tidbits·Windy 등):
  지상   해면기압 등압선 + 2m 기온 (+ H/L 중심)
  925    고도 등고선 + 기온 + 바람깃           — 하층 기온·이류
  850    고도 등고선 + 기온 + 바람깃           — 전선·지상 최고기온의 표준 참조층
  700    고도 등고선 + 상대습도 + 바람깃       — 구름·강수역(700 습도가 관례, 기온은 정보가 적다)
  500    고도 등고선 + 절대와도 + 바람깃       — 골·능·단파(관례: 500 vorticity & heights)
  300/200 고도 등고선 + 풍속(제트) + 바람깃    — 제트 축·발산역(관례: 300/250 wind speed & heights)
기온을 쓰는 세 층(지상·925·850)은 **같은 컬러맵·같은 범위(−25~35℃)** 로 두어 층이 달라도 같은 색이 같은
온도가 되게 했다. 다른 변수 층은 변수별 고유 컬러맵.

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
import matplotlib.patheffects

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import sslfix  # noqa: F401
from config import OUT_DIR, DATA_DIR, KST_OFFSET_H, LON_MIN, LON_MAX, LAT_MIN, LAT_MAX
from fetch_upper import LEVELS, UP_LON_MIN, UP_LON_MAX, UP_LAT_MIN, UP_LAT_MAX

# 등치선 간격(지상 hPa, 상층 m) — 층별 관례
# 표준 일기도(기상청·JMA) 관례: 지상 4hPa, 925·850 30m, 700·500 60m, 300·200 120m (2026-09-07 사용자 요청)
CONTOUR = {"sfc": 4, 925: 30, 850: 30, 700: 60, 500: 60, 300: 120, 200: 120}
LW_CONTOUR = 1.4          # 등고선을 해안선(0.6)보다 확실히 굵게
# 층별 채움 변수: (변수, 컬러맵, vmin, vmax, 라벨). 기온 층은 범위·컬러맵 공통.
FILL = {"sfc": ("t", "RdYlBu_r", -25, 35, "2m 기온 (℃)"),
        925: ("t", "RdYlBu_r", -25, 35, "기온 (℃)"),
        850: ("t", "RdYlBu_r", -25, 35, "기온 (℃)"),
        700: ("r", "BrBG", 0, 100, "상대습도 (%)"),
        500: ("vort", "YlOrRd", 0, 30, "절대와도 (x1e-5 /s, 2σ 평활)"),   # 위첨자 글리프는 나눔고딕에 없음
        300: ("wspd", "YlGnBu", 0, 90, "풍속 (m/s)"),
        200: ("wspd", "YlGnBu", 0, 100, "풍속 (m/s)")}
FS_LABEL, FS_TITLE, FS_TICK = 12, 13, 11        # 글자 크기 (2026-09-07 사용자: 고도 값이 잘 보이게)
matplotlib.rcParams.update({"xtick.labelsize": FS_TICK, "ytick.labelsize": FS_TICK})

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
        ax.coastlines(resolution="50m", linewidth=0.6, color="#555")
        ax.add_feature(cfeature.BORDERS, linewidth=0.3, edgecolor="#444")
    except Exception:
        pass
    gl = ax.gridlines(draw_labels=True, linewidth=0.2, alpha=0.5)
    gl.top_labels = gl.right_labels = False
    # 한반도 표출 영역 표시(다른 탭 지도의 범위)
    ax.plot([LON_MIN, LON_MAX, LON_MAX, LON_MIN, LON_MIN], [LAT_MIN, LAT_MIN, LAT_MAX, LAT_MAX, LAT_MIN],
            color="#1a5fb4", lw=0.8, ls="--", alpha=0.7, transform=ccrs.PlateCarree())
    return ax


def abs_vorticity(u, v, lats, lons):
    """절대와도 ζ+f (10⁻⁵ s⁻¹). 위경도 격자 중심차분."""
    from scipy.ndimage import gaussian_filter
    u, v = gaussian_filter(u, 2.0), gaussian_filter(v, 2.0)     # 0.25° 격자 잡음 제거 — 종관 관례
    R, OMEGA = 6.371e6, 7.292e-5
    phi = np.deg2rad(lats)[:, None]
    dlam = np.deg2rad(np.gradient(lons))[None, :]
    dphi = np.deg2rad(np.gradient(lats))[:, None]
    dvdx = np.gradient(v, axis=1) / (R * np.cos(phi) * dlam)
    dudy = np.gradient(u, axis=0) / (R * dphi)
    return (dvdx - dudy + 2 * OMEGA * np.sin(phi)) * 1e5


def draw_panel(model: str, run: dt.datetime, step: int, lev, fields: dict, lats, lons, out_dir: str):
    """fields: {'t','gh'|'msl','u','v','r'} 중 층에 필요한 것. lev='sfc' 면 msl(hPa)+t(2m ℃)."""
    import cartopy.crs as ccrs
    var, cmap, vmin, vmax, clabel = FILL[lev]
    if var == "t":
        fill = fields["t"]
    elif var == "r":
        fill = fields["r"]
    elif var == "vort":
        fill = abs_vorticity(fields["u"], fields["v"], lats, lons)
    else:
        fill = np.hypot(fields["u"], fields["v"])
    # 그림 비율을 영역(50°×35°)에 맞춘다 — 안 맞으면 위·아래에 흰 띠가 생기고 바람깃이 그 위로 삐져나온다(실측)
    fig = plt.figure(figsize=(10.6, 6.3))
    ax = _ax(fig)
    lo2d, la2d = np.meshgrid(lons, lats)
    pm = ax.pcolormesh(lo2d, la2d, fill, cmap=cmap, vmin=vmin, vmax=vmax, shading="auto")
    if lev == "sfc":
        cs = ax.contour(lo2d, la2d, fields["msl"], levels=np.arange(920, 1080, CONTOUR["sfc"]), colors="k", linewidths=LW_CONTOUR)
        ax.clabel(cs, fmt="%d", fontsize=FS_LABEL, inline_spacing=3)
        _mark_centers(ax, fields["msl"], lats, lons)
        title = f"지상 - 해면기압({CONTOUR['sfc']}hPa 간격) + 2m 기온(℃)"
    else:
        cs = ax.contour(lo2d, la2d, fields["gh"], levels=np.arange(0, 20000, CONTOUR[lev]), colors="k", linewidths=LW_CONTOUR)
        ax.clabel(cs, fmt="%d", fontsize=FS_LABEL, inline_spacing=3)   # m 단위 그대로(예: 5880) — dam 표기는 낯설다(사용자)
        what = {"t": "기온(℃)", "r": "상대습도(%)", "vort": "절대와도", "wspd": "풍속(m/s)"}[var]
        title = f"{lev}hPa - 지위고도({CONTOUR[lev]}m 간격) + {what} + 바람(kt)"
        if "u" in fields and "v" in fields:
            k = max(1, int(round(2.5 / abs(lats[1] - lats[0]))))          # 2.5° 마다 바람깃
            sl = (slice(k // 2, None, k), slice(k // 2, None, k))            # 경계 격자는 피한다(깃이 지도 밖으로 나감)
            ax.barbs(lo2d[sl], la2d[sl], fields["u"][sl] * 1.944, fields["v"][sl] * 1.944,
                     length=5.5, linewidth=0.6, color="#222", transform=ccrs.PlateCarree())
    cb = fig.colorbar(pm, ax=ax, shrink=0.8, pad=0.02)
    cb.set_label(clabel, fontsize=FS_TICK)
    cb.ax.tick_params(labelsize=FS_TICK)
    vkst = run + dt.timedelta(hours=step + KST_OFFSET_H)
    # 제목은 figure 에 — GeoAxes 의 set_title 은 set_extent 로 줄어든 지도 위 여백에 묻혀 안 보였다(실측)
    fig.suptitle(f"{model}  런 {run:%m-%d %H}UTC  +{step:03d}h  유효 {vkst:%m-%d %H}KST\n{title}",
                 fontsize=FS_TITLE, y=0.985)
    fig.subplots_adjust(top=0.90, bottom=0.05, left=0.05, right=0.99)
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
            # 흰 테두리로 어떤 배경색 위에서도 읽히게 (2026-09-07 사용자 요청)
            pe = [matplotlib.patheffects.withStroke(linewidth=3.5, foreground="white")]
            ax.text(lons[i], lats[j], sym, color=col, fontsize=18, weight="bold", ha="center", va="center",
                    transform=ccrs.PlateCarree(), path_effects=pe)
            ax.text(lons[i], lats[j] - 1.3, f"{v:.0f}", color=col, fontsize=11, weight="bold", ha="center", va="top",
                    transform=ccrs.PlateCarree(), path_effects=pe)


PL_VARS = {925: ("gh", "t", "u", "v"), 850: ("gh", "t", "u", "v"), 700: ("gh", "r", "u", "v"),
           500: ("gh", "u", "v"), 300: ("gh", "u", "v"), 200: ("gh", "u", "v")}


def _render_levels(model: str, fields: dict, lats, lons, run, out_dir: str) -> int:
    n = 0
    for L, vs in PL_VARS.items():
        gh = fields.get(("gh", "isobaricInhPa", L), {})
        for step in sorted(gh):
            fl = {}
            for v in vs:
                arr = fields.get((v, "isobaricInhPa", L), {}).get(step)
                if arr is None:
                    break
                fl[v] = arr - 273.15 if v == "t" else arr
            else:
                draw_panel(model, run, step, L, fl, lats, lons, out_dir); n += 1
    return n


def _render_sfc(model: str, fields: dict, msl_key, lats, lons, run, out_dir: str, every=1) -> int:
    n = 0
    for step in sorted(fields.get(msl_key, {})):
        if step % (6 * every):
            continue
        t = fields.get(("2t", "heightAboveGround", 2), {}).get(step)
        if t is not None:
            draw_panel(model, run, step, "sfc", {"msl": fields[msl_key][step] / 100.0, "t": t - 273.15}, lats, lons, out_dir)
            n += 1
    return n


def render_ecmwf(paths: list[str], sfc_path: str, out_dir: str) -> int:
    want = {(v, "isobaricInhPa", L) for L, vs in PL_VARS.items() for v in vs}
    merged, lats, lons, run = {}, None, None, None
    for p in paths:
        f, la, lo, r = read_fields(p, want)
        merged.update(f); lats, lons, run = (la, lo, r) if f else (lats, lons, run)
    n = _render_levels("ECMWF", merged, lats, lons, run, out_dir) if merged else 0
    if sfc_path and os.path.exists(sfc_path):
        g, lats, lons, run = read_fields(sfc_path, {("msl", "meanSea", 0), ("2t", "heightAboveGround", 2)})
        n += _render_sfc("ECMWF", g, ("msl", "meanSea", 0), lats, lons, run, out_dir)
    return n


def render_gfs(path: str, out_dir: str) -> int:
    want = ({(v, "isobaricInhPa", L) for L, vs in PL_VARS.items() for v in vs}
            | {("prmsl", "meanSea", 0), ("2t", "heightAboveGround", 2)})
    f, lats, lons, run = read_fields(path, want)
    if not f:
        return 0
    return _render_levels("GFS", f, lats, lons, run, out_dir) + _render_sfc("GFS", f, ("prmsl", "meanSea", 0), lats, lons, run, out_dir)


def render_kim(path: str, out_dir: str) -> int:
    f, lats, lons, run = read_fields(path, {("prmsl", "meanSea", 0), ("2t", "heightAboveGround", 2)})
    return _render_sfc("KIM", f, ("prmsl", "meanSea", 0), lats, lons, run, out_dir) if f else 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--delete-raw", action="store_true", help="렌더 후 상층 GRIB 원본 삭제(그림만 보존)")
    p.add_argument("--run", default=None, help="런 YYYYMMDDHH 지정(백필) — 그 런의 파일만 그린다")
    p.add_argument("--out-date", default=None, help="산출 날짜 폴더 YYYYMMDD (기본 오늘)")
    p.add_argument("--no-kim", action="store_true", help="KIM 지상장 생략")
    a = p.parse_args()
    out_dir = os.path.join(OUT_DIR, a.out_date or dt.date.today().strftime("%Y%m%d"), "upper")
    tag = a.run or "*"

    def latest(pat):
        fs = sorted(glob.glob(os.path.join(DATA_DIR, pat)))
        return fs[-1] if fs else None

    raw = []
    ec_pl, ec_pl2, ec_sfc = (latest(f"upper_ecmwf_pl_{tag}.grib2"), latest(f"upper_ecmwf_pl2_{tag}.grib2"),
                             latest(f"upper_ecmwf_sfc_{tag}.grib2"))
    gf = latest(f"upper_gfs_{tag}.grib2")
    total = 0
    if ec_pl:
        pls = [ec_pl] + ([ec_pl2] if ec_pl2 else [])
        n = render_ecmwf(pls, ec_sfc, out_dir); print(f"[UPPER] ECMWF {n}장"); total += n
        raw += pls + ([ec_sfc] if ec_sfc else [])
    if gf:
        n = render_gfs(gf, out_dir); print(f"[UPPER] GFS {n}장"); total += n
        raw.append(gf)
    km = None if a.no_kim else latest(f"kim_*_{tag}.grib2")
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
