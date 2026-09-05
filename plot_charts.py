# -*- coding: utf-8 -*-
"""
ECMWF/GFS GRIB 판독 및 표출
- 지도: 2m 기온, 전운량, (GFS) 저·중·상층 운량 HSL 합성
- 지점: 도시별 시계열 CSV + 대표지점 ECMWF vs GFS 미티오그램

HSL 합성은 ECMWF Newsletter No.101 방식의 근사 구현:
  저층=갈색, 중층=자홍, 상층=청록. 각 층 색을 운량 비율만큼 감법 혼합.
  무운=흰색, 전층 완전 운량=어두운 회청색.

사용:
    python plot_charts.py --ecmwf data/ecmwf_....grib2 --gfs data/gfs_....grib2
    (둘 중 하나만 줘도 동작)
"""
import argparse
import glob
import os
import warnings
import datetime as dt

import numpy as np
import pandas as pd
import xarray as xr
import matplotlib

import sslfix  # noqa: F401  (cartopy Natural Earth 다운로드도 AVG TLS 검사에 걸림)

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from config import (CITIES, LON_MIN, LON_MAX, LAT_MIN, LAT_MAX,
                    MAP_STEPS, KST_OFFSET_H, OUT_DIR, DATA_DIR, VERIF_DIR)

warnings.filterwarnings("ignore")

# 한글 폰트 — rc()는 미설치 폰트여도 예외를 안 던지므로 설치 목록에서 실제 존재를 확인
from matplotlib import font_manager as _fm
_installed_fonts = {f.name for f in _fm.fontManager.ttflist}
for font in ["Malgun Gothic", "NanumGothic", "Noto Sans CJK KR", "AppleGothic"]:
    if font in _installed_fonts:
        matplotlib.rc("font", family=font)
        break
else:
    print("[경고] 한글 폰트 미발견 — 그림의 한글 라벨이 깨질 수 있음")
matplotlib.rcParams["axes.unicode_minus"] = False

# ── cartopy는 있으면 쓰고, 없거나 해안선 다운로드가 막히면 평면 표출로 대체 ──
try:
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    HAS_CARTOPY = True
except Exception:
    HAS_CARTOPY = False


# ══════════════════════════════════════════════════════════
# GRIB 판독
# ══════════════════════════════════════════════════════════

def _open(path, filter_by_keys):
    return xr.open_dataset(
        path, engine="cfgrib",
        backend_kwargs={"filter_by_keys": filter_by_keys,
                        "indexpath": ""},
        decode_timedelta=True,
    )


def _subset(ds):
    """전구 자료를 한반도 영역으로 자름. 경도 0~360/-180~180 모두 대응."""
    lon = ds.longitude
    if float(lon.max()) > 180:
        ds = ds.assign_coords(longitude=(((lon + 180) % 360) - 180)).sortby("longitude")
    lat_slice = (slice(LAT_MAX, LAT_MIN)
                 if ds.latitude[0] > ds.latitude[-1]
                 else slice(LAT_MIN, LAT_MAX))
    return ds.sel(longitude=slice(LON_MIN, LON_MAX), latitude=lat_slice)


def _read_windows(path, short_name, kind, scale=1.0, per_hour=False):
    """누적(accum)·구간평균(avg) 변수를 **3시간 창**으로 정규화해 DataArray 로 (2026-09-06).

    모델마다 창 규약이 다르다 (실측):
      · ECMWF tp/ssrd : 런 시작부터 누적 (0-3, 0-6, …; 144h 이후 6h 간격)
      · GFS  APCP     : f009 에 (6-9)·(0-9) 공존, f006 은 (0-6)만 — 6시간마다 리셋
      · GFS  DSWRF avg: (0-3),(0-6),(6-9),(6-12) … 6시간 리셋 구간 평균
      · KIM  avg_sdswrf: (3-6),(6-9) … 처음부터 3h 창 / KIM tp: 누적
    규칙: 끝 시각 e 마다 가장 짧은 창 (s,e) 를 잡고, 3h 보다 길면 (s,e-3) 또는 (0,e-3)
    기록과의 차로 3h 를 만든다. avg 는 창 길이를 곱해 적분값으로 바꿔 같은 산술을 쓴다.
    반환 DataArray: dims (step, latitude, longitude) + 좌표 win_h (창 길이, 시간).
      kind="accum": 값 = 창 합계 × scale         (tp: m→mm 면 scale=1000)
      kind="avg"  : 값 = 창 평균 (W/m² 등)
      per_hour=True: 누적 적분값을 창 시간(초)으로 나눠 평균 W/m² 로 (ssrd J/m² 용)
    cfgrib 를 쓰지 않는 이유: 같은 step 에 창이 둘인 GFS 기록이 하이퍼큐브 충돌을 낸다.
    """
    import eccodes
    recs: dict[tuple[int, int], np.ndarray] = {}
    geo = None
    with open(path, "rb") as f:
        while True:
            gid = eccodes.codes_grib_new_from_file(f)
            if gid is None:
                break
            try:
                if eccodes.codes_get(gid, "shortName") != short_name:
                    continue
                s, e = int(eccodes.codes_get(gid, "startStep")), int(eccodes.codes_get(gid, "endStep"))
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
                    jj = np.where((lats >= LAT_MIN) & (lats <= LAT_MAX))[0]
                    ii = np.where((lons >= LON_MIN) & (lons <= LON_MAX))[0]
                    run = (dt.datetime.strptime(str(eccodes.codes_get(gid, "dataDate")), "%Y%m%d")
                           + dt.timedelta(hours=int(eccodes.codes_get(gid, "dataTime")) // 100))
                    geo = (ni, nj, lats[jj], lons[ii], jj, ii, run)
                ni, nj, _la, _lo, jj, ii, _run = geo
                v = eccodes.codes_get_values(gid).reshape(nj, ni)[np.ix_(jj, ii)]
                if kind == "avg":
                    v = v * (e - s)              # 평균 → 적분(값·시간)
                recs[(s, e)] = v
            finally:
                eccodes.codes_release(gid)
    if not recs:
        return None
    ni, nj, lats, lons, jj, ii, run = geo
    ends = sorted({e for _s, e in recs})
    steps, wins, arrs = [], [], []
    for e in ends:
        cands = sorted((s, ee) for (s, ee) in recs if ee == e)
        s, _ = max(cands)                       # 가장 짧은 창
        win, arr = e - s, recs[(s, e)]
        if win > 3:
            if (s, e - 3) in recs:
                win, arr = 3, arr - recs[(s, e - 3)]
            elif s == 0:
                prev = [pe for pe in ends if pe < e and (0, pe) in recs]
                if prev:
                    pe = max(prev); win, arr = e - pe, arr - recs[(0, pe)]
        if win <= 0:
            continue
        if kind == "avg":
            arr = arr / win                     # 적분 → 창 평균
        elif per_hour:
            arr = arr / (win * 3600.0)          # J/m² 누적 → W/m²
        arr = np.where(arr < 0, 0.0, arr) * scale   # 차분 잡음의 음수 제거
        steps.append(e); wins.append(win); arrs.append(arr)
    da = xr.DataArray(np.stack(arrs), dims=("step", "latitude", "longitude"),
                      coords={"step": np.array(steps, dtype="timedelta64[h]"),
                              "latitude": lats, "longitude": lons})
    da = da.assign_coords(win_h=("step", np.array(wins)))
    # 위도가 남→북이면 기존 판독기(북→남)와 맞춘다
    if float(da.latitude[0]) < float(da.latitude[-1]):
        da = da.isel(latitude=slice(None, None, -1))
    return da.sortby("longitude")


def load_ecmwf(path):
    """ECMWF IFS: {'t2m': DataArray(°C), 'tcc': DataArray(%) or None, 'run': datetime,
    'dswrf': 3h 평균 W/m²(ssrd 차분) or None, 'tp': 3h 강수 mm or None}"""
    out = {"dswrf": None, "tp": None}
    ds_t = _subset(_open(path, {"shortName": "2t"}))
    out["t2m"] = ds_t["t2m"] - 273.15
    out["run"] = pd.Timestamp(ds_t.time.values).to_pydatetime()
    try:
        ds_c = _subset(_open(path, {"shortName": "tcc"}))
        tcc = ds_c["tcc"]
        # IFS tcc는 0~1 비율 → %
        out["tcc"] = tcc * 100.0 if float(tcc.max()) <= 1.5 else tcc
    except Exception:
        print("[판독] ECMWF tcc 없음 — 기온만 표출 (해당 런 미제공 가능)")
        out["tcc"] = None
    # 2026-09-06 추가: 일사(ssrd, J/m² 누적)·강수(tp, m 누적) → 3h 창
    for sn, key, kw in (("ssrd", "dswrf", dict(kind="accum", per_hour=True)),
                        ("tp", "tp", dict(kind="accum", scale=1000.0))):
        try:
            out[key] = _read_windows(path, sn, **kw)
            if out[key] is None:
                print(f"[판독] ECMWF {sn} 없음 (구 런 파일이거나 미제공)")
        except Exception as e:
            print(f"[판독] ECMWF {sn} 판독 실패: {e}")
    return out


def load_gfs(path):
    """GFS: t2m(°C), tcc/lcc/mcc/hcc(%), dswrf(W/m²). 없는 변수는 None."""
    out = {"tcc": None, "lcc": None, "mcc": None, "hcc": None, "dswrf": None}

    ds_t = _subset(_open(path, {"typeOfLevel": "heightAboveGround", "level": 2}))
    out["t2m"] = ds_t["t2m"] - 273.15
    out["run"] = pd.Timestamp(ds_t.time.values).to_pydatetime()

    # 실측 확정(2026-08-14, gfs.t18z 실파일 dump 대조):
    #   층별 운량 shortName=lcc/mcc/hcc, typeOfLevel=lowCloudLayer 등.
    #   instant와 avg(shortName=avg_lcc 등) 두 계열이 공존하므로
    #   stepType=instant를 명시해야 cfgrib 하이퍼큐브 충돌이 없다.
    layer_map = {"lcc": "lowCloudLayer", "mcc": "middleCloudLayer",
                 "hcc": "highCloudLayer"}
    for key, tol in layer_map.items():
        try:
            ds = _subset(_open(path, {"typeOfLevel": tol, "shortName": key,
                                      "stepType": "instant"}))
            out[key] = ds[key]
        except Exception:
            print(f"[판독] GFS {key}({tol}) 없음")

    # 전운량: 실측 확정 typeOfLevel=atmosphere, instant/avg 공존 → instant 사용
    try:
        ds = _subset(_open(path, {"typeOfLevel": "atmosphere", "shortName": "tcc",
                                  "stepType": "instant"}))
        out["tcc"] = ds["tcc"]
    except Exception:
        print("[판독] GFS 전운량 판독 실패 — tools/dump_grib.py로 확인 필요")

    # 일사: 실측 확정 shortName=sdswrf (dswrf 아님), avg만 존재.
    # 평균 구간은 6시간마다 리셋(f003=0-3h, f006=0-6h, f009=6-9h ...) → _read_windows 가
    # 3h 창으로 정규화한다 (2026-09-06. 예전엔 6h 리셋 창 그대로 CSV 에 실렸다 — 검증은
    # win_h 열이 없는 옛 행에만 그 규약을 적용한다).
    out["tp"] = None
    for sn, key, kw in (("sdswrf", "dswrf", dict(kind="avg")),
                        ("tp", "tp", dict(kind="accum"))):           # GFS APCP 의 shortName 은 tp
        try:
            out[key] = _read_windows(path, sn, **kw)
            if out[key] is None:
                print(f"[판독] GFS {sn} 없음")
        except Exception as e:
            print(f"[판독] GFS {sn} 판독 실패: {e}")
    return out


def load_kim(path):
    """KIM(k512, fetch_kim.py로 변수 추출된 파일): t2m(°C), tcc/lcc/mcc/hcc(%), dswrf.
    실측(2026-08-21): 층별 운량 typeOfLevel은 'unknown'이라 shortName으로만 필터.
    일사는 avg_sdswrf(구간 평균) — GFS와 동일하게 dswrf 키에 담는다."""
    out = {"tcc": None, "lcc": None, "mcc": None, "hcc": None, "dswrf": None, "tp": None}
    ds_t = _subset(_open(path, {"shortName": "2t"}))
    out["t2m"] = ds_t["t2m"] - 273.15
    out["run"] = pd.Timestamp(ds_t.time.values).to_pydatetime()
    for sn, key in [("tcc", "tcc"), ("lcc", "lcc"), ("mcc", "mcc"), ("hcc", "hcc")]:
        try:
            ds = _subset(_open(path, {"shortName": sn}))
            da = ds[list(ds.data_vars)[0]]
            # 실측 함정(2026-08-21): KIM 운량은 units='%'로 찍혀 있지만 실값은 0~1 비율
            if key in ("tcc", "lcc", "mcc", "hcc") and float(da.max()) <= 1.5:
                da = da * 100.0
            out[key] = da
        except Exception:
            print(f"[판독] KIM {sn} 없음")
    # 일사 avg_sdswrf 는 처음부터 3h 창(실측: 3-6, 6-9 …) → 공통 정규화기
    try:
        out["dswrf"] = _read_windows(path, "avg_sdswrf", kind="avg")
        if out["dswrf"] is None:
            print("[판독] KIM avg_sdswrf 없음 (fetch_kim.py KEEP_SHORTNAMES 확인)")
    except Exception as e:
        print(f"[판독] KIM avg_sdswrf 판독 실패: {e}")
    # 강수: k512 'tp' 는 빈 필드(2026-09-06 실측, 전 스텝 최대 0.02mm). 대규모(lswp)+대류(cwp)
    # 수적 강수와 눈(snol·snoc, 수당량)을 더한다. 각각 3h 창 누적(kg/m² = mm).
    parts = []
    for sn in ("lswp", "cwp", "snol", "snoc"):
        try:
            da = _read_windows(path, sn, kind="accum")
            if da is not None:
                parts.append(da)
        except Exception as e:
            print(f"[판독] KIM {sn} 판독 실패: {e}")
    if parts:
        tot = parts[0]
        for da in parts[1:]:
            tot = tot + da.reindex(step=tot.step, fill_value=0.0)
        out["tp"] = tot.assign_coords(win_h=parts[0].win_h)
    else:
        print("[판독] KIM 강수(lswp/cwp) 없음 — KEEP_SHORTNAMES 확인")
    return out


def _steps_h(da):
    """step 좌표를 시간(정수 h) 배열로."""
    return (da.step.values / np.timedelta64(1, "h")).astype(int)


def _valid_kst(run, step_h):
    return run + dt.timedelta(hours=int(step_h) + KST_OFFSET_H)


# ══════════════════════════════════════════════════════════
# 지도 표출
# ══════════════════════════════════════════════════════════

def _make_ax(fig, pos, line_color="black"):
    """line_color: 해안선·경계선 색 — 전운량은 위성영상처럼 노란 지리선."""
    if HAS_CARTOPY:
        ax = fig.add_subplot(*pos, projection=ccrs.PlateCarree())
        try:
            ax.coastlines(resolution="50m", linewidth=0.7, color=line_color)
            ax.add_feature(cfeature.BORDERS, linewidth=0.4, edgecolor=line_color)
            ax.add_feature(cfeature.NaturalEarthFeature(
                "cultural", "admin_1_states_provinces_lines", "10m",
                facecolor="none"), edgecolor=line_color, linewidth=0.35, alpha=0.7)
        except Exception:
            pass  # 해안선 데이터 다운로드 불가 환경
        ax.set_extent([LON_MIN, LON_MAX, LAT_MIN, LAT_MAX])
        gl = ax.gridlines(draw_labels=True, linewidth=0.2, alpha=0.5)
        gl.top_labels = gl.right_labels = False
        return ax
    ax = fig.add_subplot(*pos)
    ax.set_xlim(LON_MIN, LON_MAX)
    ax.set_ylim(LAT_MIN, LAT_MAX)
    ax.set_aspect(1.0 / np.cos(np.deg2rad((LAT_MIN + LAT_MAX) / 2)))
    return ax


def _sel_step(da, step_h):
    hs = _steps_h(da)
    if step_h not in hs:
        return None
    return da.isel(step=int(np.where(hs == step_h)[0][0]))


def hsl_composite(lcc, mcc, hcc):
    """저·중·상층 운량(%) → RGB. ECMWF Newsletter 101 방식 근사(감법 혼합)."""
    c_low = np.clip(np.nan_to_num(lcc) / 100.0, 0, 1)
    c_mid = np.clip(np.nan_to_num(mcc) / 100.0, 0, 1)
    c_high = np.clip(np.nan_to_num(hcc) / 100.0, 0, 1)
    base = {  # 각 층의 기준색
        "low": np.array([0.55, 0.36, 0.18]),   # 갈색
        "mid": np.array([0.78, 0.16, 0.50]),   # 자홍
        "high": np.array([0.10, 0.62, 0.68]),  # 청록
    }
    rgb = np.ones(c_low.shape + (3,))
    for cov, col in [(c_low, base["low"]), (c_mid, base["mid"]), (c_high, base["high"])]:
        rgb -= cov[..., None] * (1.0 - col)[None, None, :] * 0.85
    return np.clip(rgb, 0.12, 1.0)


def plot_maps(model_name, data, out_dir):
    """패널별 개별 PNG 저장 (2026-08-20 개편).
    3패널 가로 합본(18인치 폭)은 셀룰러 태블릿에서 판독 불가(브리프 ③) →
    변수별 1장씩 저장하고 웹 뷰어가 탭·슬라이더로 조합한다.
    파일명: {model}_{runYYYYMMDDHH}_f{step:03d}_{panel}.png  (panel: t2m|tcc|cloud3)
    """
    run = data["run"]
    os.makedirs(out_dir, exist_ok=True)
    has_layers = all(data.get(k) is not None for k in ("lcc", "mcc", "hcc"))
    n_saved = 0

    def _save(step_h, panel, draw):
        nonlocal n_saved
        # 그림 크기를 지도 종횡비(경도15°×위도13°)+콜로바에 맞춰 여백 최소화.
        # 주의: bbox_inches="tight"는 gridliner(경위선 라벨)와 충돌해 지도가 잘려나감
        # (2026-08-20 실측: 105px 폭 PNG). tight_layout도 금지(GEOSException) — 수동 여백만.
        fig = plt.figure(figsize=(7.4, 5.9))
        # 전운량은 위성영상풍(어두운 배경) — 해안·행정경계는 청록(노랑=등치선과 구분)
        ax = _make_ax(fig, (1, 1, 1), line_color="yellow" if panel == "tcc" else "black")
        draw(fig, ax)
        vkst = _valid_kst(run, step_h)
        ax.set_title(f"{model_name}  런 {run:%m-%d %H}UTC  +{step_h:03d}h  "
                     f"유효 {vkst:%m-%d %H}KST", fontsize=11)
        fig.subplots_adjust(top=0.92, bottom=0.08, left=0.07, right=0.97)
        fname = os.path.join(
            out_dir, f"{model_name.lower()}_{run:%Y%m%d%H}_f{step_h:03d}_{panel}.png")
        fig.savefig(fname, dpi=100)
        plt.close(fig)
        n_saved += 1

    for step_h in MAP_STEPS:
        t2m = _sel_step(data["t2m"], step_h)
        if t2m is None:
            continue
        lon2d, lat2d = np.meshgrid(t2m.longitude, t2m.latitude)

        def draw_t2m(fig, ax, _t=t2m, _lo=lon2d, _la=lat2d):
            pm = ax.pcolormesh(_lo, _la, _t.values, cmap="RdYlBu_r",
                               vmin=-15, vmax=38, shading="auto")
            cs = ax.contour(_lo, _la, _t.values, levels=np.arange(-15, 40, 3),
                            colors="k", linewidths=0.3)
            ax.clabel(cs, fmt="%d", fontsize=10)
            fig.colorbar(pm, ax=ax, shrink=0.8, label="2m 기온 (°C)")
        _save(step_h, "t2m", draw_t2m)

        tcc = _sel_step(data["tcc"], step_h) if data.get("tcc") is not None else None
        if tcc is not None:
            def draw_tcc(fig, ax, _c=tcc, _lo=lon2d, _la=lat2d):
                # 위성영상풍: 0%=어두움, 100%=밝음(구름=흰색).
                # 원자료 0.25°의 픽셀 블록은 bilinear 표시 보간으로 매끈하게
                # (해상도 자체는 오픈데이터 한계 — 시각 보간일 뿐임을 명시)
                origin = "upper" if _c.latitude[0] > _c.latitude[-1] else "lower"
                kw = {"transform": ccrs.PlateCarree()} if HAS_CARTOPY else {}
                pm = ax.imshow(_c.values, origin=origin, cmap="gray",
                               vmin=0, vmax=100, interpolation="bilinear",
                               extent=[float(_c.longitude.min()), float(_c.longitude.max()),
                                       float(_c.latitude.min()), float(_c.latitude.max())],
                               **kw)
                # 등치선 없음 — 위성영상 문법에 맞춰 구름 테두리를 빼고 지리선만 노란색
                # (2026-08-26 사용자 확정: 이전의 50·75 등치선 표출을 대체)
                fig.colorbar(pm, ax=ax, shrink=0.8, label="전운량 (%)")
            _save(step_h, "tcc", draw_tcc)

        if has_layers:
            l = _sel_step(data["lcc"], step_h)
            m = _sel_step(data["mcc"], step_h)
            h = _sel_step(data["hcc"], step_h)
            if all(x is not None for x in (l, m, h)):
                rgb = hsl_composite(l.values, m.values, h.values)
                origin = "upper" if t2m.latitude[0] > t2m.latitude[-1] else "lower"

                def draw_c3(fig, ax, _rgb=rgb, _or=origin):
                    kw = {"transform": ccrs.PlateCarree()} if HAS_CARTOPY else {}
                    ax.imshow(_rgb, origin=_or,
                              extent=[LON_MIN, LON_MAX, LAT_MIN, LAT_MAX], **kw)
                    ax.text(0.01, 0.01, "저:갈색 중:자홍 상:청록", transform=ax.transAxes,
                            fontsize=8, va="bottom",
                            bbox=dict(fc="white", alpha=0.7, ec="none"))
                _save(step_h, "cloud3", draw_c3)

        # 2026-09-06 추가 — 일사(3h 평균 W/m²)·강수(3h mm). 창 길이가 3h 가 아니면 제목에 표시.
        for key, panel in (("dswrf", "dswrf"), ("tp", "tp")):
            da = data.get(key)
            if da is None:
                continue
            fld = _sel_step(da, step_h)
            if fld is None:
                continue
            win = int(fld.win_h) if "win_h" in fld.coords else 3
            lo2d, la2d = np.meshgrid(fld.longitude, fld.latitude)
            if panel == "dswrf":
                def draw_sw(fig, ax, _f=fld, _lo=lo2d, _la=la2d, _w=win):
                    pm = ax.pcolormesh(_lo, _la, _f.values, cmap="YlOrRd", vmin=0, vmax=900,
                                       shading="auto")
                    fig.colorbar(pm, ax=ax, shrink=0.8, label=f"하향 단파복사 {_w}h 평균 (W/m²)")
                _save(step_h, panel, draw_sw)
            else:
                def draw_tp(fig, ax, _f=fld, _lo=lo2d, _la=la2d, _w=win):
                    from matplotlib.colors import BoundaryNorm, ListedColormap
                    lev = [0.1, 0.5, 1, 2, 5, 10, 20, 30, 50, 80]
                    cols = ["#d4ecff", "#a6d4ff", "#6fb6ff", "#3d8ef0", "#1f5fd0", "#7a3fd0",
                            "#c02fb0", "#e0207a", "#ff4040"]
                    cmap = ListedColormap(cols); cmap.set_under("#ffffff", alpha=0); cmap.set_over("#7a0000")
                    pm = ax.pcolormesh(_lo, _la, np.ma.masked_less(_f.values, 0.1), cmap=cmap,
                                       norm=BoundaryNorm(lev, cmap.N), shading="auto")
                    fig.colorbar(pm, ax=ax, shrink=0.8, extend="max", ticks=lev,
                                 label=f"{_w}h 강수 (mm) — 0.1 미만 표시 안 함")
                _save(step_h, panel, draw_tp)

    print(f"[지도] {model_name} 패널 PNG {n_saved}장 저장: {out_dir}")


# ══════════════════════════════════════════════════════════
# 지점 시계열
# ══════════════════════════════════════════════════════════

def city_series(model_name, data):
    """도시별 시계열 DataFrame."""
    run = data["run"]
    rows = []
    # 변수마다 스텝 구성이 다르다 (실측: avg 계열 dswrf는 f000이 없음)
    # → t2m 인덱스를 공용하지 말고 변수별로 "스텝 시간 → 인덱스"를 만들어 조회한다.
    def _at(da_city, idx_map, sh, ndigits):
        if da_city is None or sh not in idx_map:
            return None
        return round(float(da_city.isel(step=idx_map[sh])), ndigits)

    for name, lat, lon, is_rep in CITIES:
        sel = dict(latitude=lat, longitude=lon, method="nearest")
        series = {}
        for key in ("t2m", "tcc", "lcc", "mcc", "hcc", "dswrf", "tp"):
            da = data.get(key)
            if da is None:
                series[key] = (None, {})
            else:
                da_city = da.sel(**sel)
                idx_map = {int(s): i for i, s in enumerate(_steps_h(da_city))}
                series[key] = (da_city, idx_map)
        # 창 길이(win_h): 일사·강수 공통 (2026-09-06). 없으면(구 자료) NaN → 검증이 옛 규약 적용
        win_da = None
        for key in ("dswrf", "tp"):
            if series[key][0] is not None and "win_h" in series[key][0].coords:
                win_da = series[key]
                break
        for sh in _steps_h(series["t2m"][0]):
            sh = int(sh)
            win = (int(win_da[0].win_h.values[win_da[1][sh]])
                   if win_da is not None and sh in win_da[1] else None)
            rows.append({
                "model": model_name,
                "run_utc": run.strftime("%Y-%m-%d %H:00"),
                "valid_kst": _valid_kst(run, sh).strftime("%Y-%m-%d %H:00"),
                "step_h": sh,
                "city": name,
                "rep": int(is_rep),
                "t2m_C": _at(*series["t2m"], sh, 1),
                "tcc_pct": _at(*series["tcc"], sh, 0),
                "lcc_pct": _at(*series["lcc"], sh, 0),
                "mcc_pct": _at(*series["mcc"], sh, 0),
                "hcc_pct": _at(*series["hcc"], sh, 0),
                "dswrf_avg_Wm2": _at(*series["dswrf"], sh, 0),
                "tp_mm": _at(*series["tp"], sh, 1),
                "win_h": win,
            })
    return pd.DataFrame(rows)


def plot_meteograms(df, out_dir, days=3):
    """대표지점: ECMWF vs GFS 기온·전운량 비교 미티오그램."""
    os.makedirs(out_dir, exist_ok=True)
    df = df.copy()
    df["valid_kst"] = pd.to_datetime(df["valid_kst"])
    t_end = df["valid_kst"].min() + pd.Timedelta(days=days)
    df = df[df["valid_kst"] <= t_end]

    for city in [c[0] for c in CITIES if c[3]]:
        sub = df[df["city"] == city]
        if sub.empty:
            continue
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True)
        # 모델 색은 오차 칩 지도와 통일: EC=빨강, GFS=초록, KIM=파랑
        colors = {"ECMWF": "tab:red", "GFS": "tab:green", "KIM": "tab:blue"}
        for model, g in sub.groupby("model"):
            g = g.sort_values("valid_kst")
            ax1.plot(g["valid_kst"], g["t2m_C"], "-o", ms=3,
                     color=colors.get(model, None), label=model)
            if g["tcc_pct"].notna().any():
                ax2.plot(g["valid_kst"], g["tcc_pct"], "-o", ms=3,
                         color=colors.get(model, None), label=model)
        ax1.set_ylabel("2m 기온 (°C)")
        ax2.set_ylabel("전운량 (%)")
        ax2.set_ylim(-5, 105)
        # 태양광 피크(11~14 KST) 음영
        for d in pd.date_range(df["valid_kst"].min().normalize(), t_end, freq="D"):
            ax2.axvspan(d + pd.Timedelta(hours=11), d + pd.Timedelta(hours=14),
                        color="gold", alpha=0.15)
        for ax in (ax1, ax2):
            ax.grid(alpha=0.3)
            ax.legend(loc="upper right", fontsize=8)
        fig.suptitle(f"{city} — ECMWF vs GFS (음영: 태양광 피크 11~14 KST)")
        fig.autofmt_xdate()
        fig.tight_layout(rect=[0, 0, 1, 0.95])
        fig.savefig(os.path.join(out_dir, f"meteogram_{city}.png"), dpi=110)
        plt.close(fig)
    print(f"[미티오그램] 저장: {out_dir}")


# ══════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ecmwf", default=None, help="ECMWF GRIB 경로 (생략 시 data/ 최신)")
    p.add_argument("--gfs", default=None, help="GFS GRIB 경로 (생략 시 data/ 최신)")
    p.add_argument("--kim", default=None, help="KIM GRIB 경로 (생략 시 data/ 최신)")
    args = p.parse_args()

    def latest(pattern):
        files = sorted(f for f in glob.glob(os.path.join(DATA_DIR, pattern))
                       if not f.endswith("_trial.grib2"))
        return files[-1] if files else None

    ec_path = args.ecmwf or latest("ecmwf_*.grib2")
    gfs_path = args.gfs or latest("gfs_*.grib2")
    kim_path = args.kim or latest("kim_*.grib2")
    if not ec_path and not gfs_path and not kim_path:
        raise SystemExit("판독할 GRIB이 없습니다. fetch_ecmwf.py / fetch_gfs.py 먼저 실행")

    today = dt.date.today().strftime("%Y%m%d")
    out_dir = os.path.join(OUT_DIR, today)
    os.makedirs(out_dir, exist_ok=True)

    frames = []
    if ec_path:
        print(f"[판독] ECMWF: {ec_path}")
        ec = load_ecmwf(ec_path)
        plot_maps("ECMWF", ec, os.path.join(out_dir, "maps_ecmwf"))
        frames.append(city_series("ECMWF", ec))
    if gfs_path:
        print(f"[판독] GFS: {gfs_path}")
        gf = load_gfs(gfs_path)
        plot_maps("GFS", gf, os.path.join(out_dir, "maps_gfs"))
        frames.append(city_series("GFS", gf))
    if kim_path:
        print(f"[판독] KIM: {kim_path}")
        km = load_kim(kim_path)
        plot_maps("KIM", km, os.path.join(out_dir, "maps_kim"))
        frames.append(city_series("KIM", km))

    df = pd.concat(frames, ignore_index=True)
    csv_path = os.path.join(out_dir, "city_forecast.csv")
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    # 검증 폴더에도 사본(커밋 대상) — 러너는 매번 새로 시작하므로 저장소에 남겨야
    # 미티오그램 과거 날짜가 사이트에서 사라지지 않는다. 원본 GRIB과 달리 이건 영구 보존 가능
    keep = os.path.join(VERIF_DIR, "city_forecast")
    os.makedirs(keep, exist_ok=True)
    df.to_csv(os.path.join(keep, os.path.basename(out_dir) + ".csv"),
              index=False, encoding="utf-8-sig")
    print(f"[CSV] 도시별 시계열 저장: {csv_path}")

    plot_meteograms(df, os.path.join(out_dir, "meteograms"))
    print(f"\n완료. 산출물 폴더: {out_dir}")


if __name__ == "__main__":
    main()
