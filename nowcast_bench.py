# -*- coding: utf-8 -*-
"""
구름(운량) 나우캐스트 벤치마크 하네스 — "감이 아니라 숫자로".

방법 4종을 동일 조건에서 채점:
  M0 persistence     마지막 관측장 유지 (기준선)
  M1 영상 CMV 이류    OpenCV DIS 광류(dense) + 후방 세미라그랑주 + 리드 비례 평활
                     (pysteps는 cp313 휠 부재로 동일 계열 자체 구현 — 문헌상 광류
                      선택은 부차적, Pulkkinen 2019: 기법 간 차이 <2%)
  M2 NWP 바람 이류    GFS 850·700hPa 평균풍을 픽셀 변위로 변환해 동일 외삽
  M3 블렌드           w(lead): 0분=M1 → 120분 이후=M2 선형 전이

채점: 위성 CLA 미래장 self-verification(격자 MAE, skill=1−MAE/MAE_M0)
      + ASOS 지점 운량 보조. 리드 +30/60/120/180분, 발령 매시 정시.

핵심 실측 반영:
  · CA는 raw×0.01=0~1 비율 → ×100 (%). _FillValue 65535
  · 격자: KO 900×900 2km LCC(30/60, 38N/126E), upper_left=(-899km,+899km)
  · 판독은 h5netcdf (netCDF4 C가 한글 경로 불가)
사용: python nowcast_bench.py [--issues-per-day 24]
산출: verification/nowcast_bench/{scores.csv, bench_report.md, skill_*.png, case_*.png}
"""
import argparse
import datetime as dt
import glob
import os

import numpy as np
import pandas as pd
import xarray as xr
import cv2
from scipy.ndimage import map_coordinates, gaussian_filter
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pyproj import CRS, Transformer

from config import DATA_DIR, VERIF_DIR, CITY_OBS_STN, CITIES

from matplotlib import font_manager as _fm
_inst = {f.name for f in _fm.fontManager.ttflist}
for _f in ["Malgun Gothic", "NanumGothic"]:
    if _f in _inst:
        matplotlib.rc("font", family=_f)
        break
matplotlib.rcParams["axes.unicode_minus"] = False

CLA_DIR = os.path.join(DATA_DIR, "gk2a", "cla_ko")
WIND_DIR = os.path.join(DATA_DIR, "gfs_wind")
OUT_DIR = os.path.join(VERIF_DIR, "nowcast_bench")

STEP_MIN = 10                    # 위성장 시간 간격
LEADS_MIN = [30, 60, 120, 180, 240, 300, 360]   # 채점 리드 (목표 +6h, 2026-08-23 확장)
DOWN = 2                         # 2배 축소(4km) — 속도·잡음 완화

# ── GK2A KO LCC 격자 (실측 상수) ──
N_PIX = 900 // DOWN
PIX_M = 2000.0 * DOWN
UL_E, UL_N = -899000.0, 899000.0
CRS_LCC = CRS.from_proj4(
    "+proj=lcc +lat_1=30 +lat_2=60 +lat_0=38 +lon_0=126 +x_0=0 +y_0=0 +ellps=WGS84")
_TR_TO_LL = Transformer.from_crs(CRS_LCC, CRS.from_epsg(4326), always_xy=True)
_TR_FROM_LL = Transformer.from_crs(CRS.from_epsg(4326), CRS_LCC, always_xy=True)


def grid_lonlat():
    x = UL_E + (np.arange(N_PIX) + 0.5) * PIX_M - PIX_M / 2
    y = UL_N - (np.arange(N_PIX) + 0.5) * PIX_M + PIX_M / 2
    xx, yy = np.meshgrid(x, y)
    lon, lat = _TR_TO_LL.transform(xx, yy)
    return lon, lat


# ── 위성장 로드 ──

def load_ca(stamp: str) -> np.ndarray | None:
    path = os.path.join(CLA_DIR, f"{stamp}.nc")
    if not os.path.exists(path):
        return None
    try:
        ds = xr.open_dataset(path, engine="h5netcdf", decode_cf=False)
        raw = ds["CA"].values.astype(np.float32)
        ds.close()
    except Exception:
        return None
    raw[raw == 65535] = np.nan
    ca = raw * 0.01 * 100.0          # 실측: raw×0.01=비율 → %
    ca = np.clip(ca, 0, 100)
    if DOWN > 1:                     # 평균 풀링 축소
        n = 900 // DOWN
        ca = np.nanmean(ca.reshape(n, DOWN, n, DOWN), axis=(1, 3))
    return ca


# ── 이류 코어 ──

def backward_sl(field: np.ndarray, vx: np.ndarray, vy: np.ndarray,
                n_steps: int, n_iter: int = 3) -> np.ndarray:
    """후방 세미라그랑주 (Germann-Zawadzki식 반복 변위 보정).
    vx,vy: 픽셀/스텝 변위장. 도착점에서 출발점을 거꾸로 찾아 구멍·겹침 없음."""
    ny, nx = field.shape
    jj, ii = np.meshgrid(np.arange(nx), np.arange(ny))
    dx = vx * n_steps
    dy = vy * n_steps
    for _ in range(n_iter):
        px = np.clip(jj - dx / 2, 0, nx - 1)
        py = np.clip(ii - dy / 2, 0, ny - 1)
        dx = map_coordinates(vx, [py, px], order=1, mode="nearest") * n_steps
        dy = map_coordinates(vy, [py, px], order=1, mode="nearest") * n_steps
    src_x = np.clip(jj - dx, 0, nx - 1)
    src_y = np.clip(ii - dy, 0, ny - 1)
    return map_coordinates(field, [src_y, src_x], order=1, mode="nearest")


def lead_smooth(field: np.ndarray, lead_min: int) -> np.ndarray:
    """리드타임 비례 가우시안 평활 — 문헌 핵심 교훈(Aicardi 2022: 평활이
    알고리즘 선택보다 스킬에 결정적). sigma는 30분당 1픽셀씩 증가."""
    return gaussian_filter(field, sigma=lead_min / 30.0)


def flow_dis(prev: np.ndarray, curr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """DIS 광류 (dense, 다중스케일). 입력은 0~100% 운량장 → 8bit."""
    a = np.nan_to_num(prev, nan=0.0)
    b = np.nan_to_num(curr, nan=0.0)
    a8 = (a * 2.55).astype(np.uint8)
    b8 = (b * 2.55).astype(np.uint8)
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    fl = dis.calc(a8, b8, None)          # (H,W,2) 픽셀/프레임
    return fl[..., 0], fl[..., 1]


# ── M2: GFS 바람장 → 픽셀 변위 ──

_LON, _LAT = grid_lonlat()


def wind_field(issue_utc: dt.datetime) -> tuple[np.ndarray, np.ndarray] | None:
    """발령 시각 이전 최신 GFS 런의 해당 시각 850·700 평균풍 → 픽셀/스텝 변위장."""
    for back in range(0, 13):
        t = issue_utc - dt.timedelta(hours=back)
        run_h = (t.hour // 6) * 6
        run = t.replace(hour=run_h, minute=0)
        ef = int((issue_utc - run).total_seconds() // 3600)
        if ef > 5:
            continue
        path = os.path.join(WIND_DIR, f"gfswind_{run:%Y%m%d%H}_f{ef:03d}.grib2")
        if os.path.exists(path):
            break
    else:
        return None
    try:
        u_list, v_list = [], []
        for lev in (850, 700):
            ds = xr.open_dataset(path, engine="cfgrib",
                                 backend_kwargs={"filter_by_keys":
                                                 {"typeOfLevel": "isobaricInhPa",
                                                  "level": lev},
                                                 "indexpath": ""},
                                 decode_timedelta=True)
            u_list.append(ds["u"])
            v_list.append(ds["v"])
        u = (u_list[0] + u_list[1]) / 2
        v = (v_list[0] + v_list[1]) / 2
        # GFS 0.25° → CLA LCC 격자 최근접 샘플
        lons = u.longitude.values
        lats = u.latitude.values
        ji = np.clip(((_LON - lons[0]) / (lons[1] - lons[0])).round().astype(int),
                     0, len(lons) - 1)
        jj = np.clip(((_LAT - lats[0]) / (lats[1] - lats[0])).round().astype(int),
                     0, len(lats) - 1)
        uu = u.values[jj, ji]
        vv = v.values[jj, ji]
        # m/s → 픽셀/스텝. LCC y축은 북(+)이 위(행 감소)이므로 vy는 부호 반전
        vx = uu * (STEP_MIN * 60) / PIX_M
        vy = -vv * (STEP_MIN * 60) / PIX_M
        return vx.astype(np.float32), vy.astype(np.float32)
    except Exception as e:
        print(f"[바람] {path} 판독 실패: {e}")
        return None


# ── ASOS 보조 채점 준비 ──

def city_pixels():
    out = {}
    for name, lat, lon, _rep in CITIES:
        stn = CITY_OBS_STN.get(name)
        if not stn:
            continue
        x, y = _TR_FROM_LL.transform(lon, lat)
        j = int(round((x - UL_E) / PIX_M))
        i = int(round((UL_N - y) / PIX_M))
        if 0 <= i < N_PIX and 0 <= j < N_PIX:
            out[name] = (stn, i, j)
    return out


def load_asos_ca(days: list[dt.date]) -> pd.DataFrame:
    frames = []
    for ym in sorted({f"{d:%Y-%m}" for d in days}):
        p = os.path.join(VERIF_DIR, "obs", f"{ym}.csv")
        if os.path.exists(p):
            frames.append(pd.read_csv(p, parse_dates=["TM"]))
    df = pd.concat(frames, ignore_index=True)
    return df.dropna(subset=["CA_TOT"])


# ── 벤치마크 본체 ──

def run_bench(issues_per_day: int, tag: str = "", t0f: str = "", t1f: str = ""):
    os.makedirs(OUT_DIR, exist_ok=True)
    stamps = sorted(os.path.basename(p)[:-3]
                    for p in glob.glob(os.path.join(CLA_DIR, "????????????.nc")))
    if t0f:
        stamps = [s for s in stamps if s >= t0f]
    if t1f:
        stamps = [s for s in stamps if s <= t1f]
    if not stamps:
        raise SystemExit("CLA 자료 없음 — fetch_gk2a.py 먼저")
    have = set(stamps)
    t0 = dt.datetime.strptime(stamps[0], "%Y%m%d%H%M")
    t1 = dt.datetime.strptime(stamps[-1], "%Y%m%d%H%M")
    print(f"[bench] CLA {len(stamps)}시각 ({t0}~{t1} UTC), 격자 {N_PIX}px({PIX_M/1000:.0f}km)")

    # 발령 시각: 매시 정시(UTC) 중 t-10, t, t+최장리드 모두 존재하는 것
    issues = []
    t = t0.replace(minute=0) + dt.timedelta(hours=1)
    while t + dt.timedelta(minutes=LEADS_MIN[-1]) <= t1:
        need = [t - dt.timedelta(minutes=STEP_MIN), t] + \
               [t + dt.timedelta(minutes=m) for m in LEADS_MIN]
        if all(x.strftime("%Y%m%d%H%M") in have for x in need):
            issues.append(t)
        t += dt.timedelta(hours=1)
    # 하루 발령 수 제한(옵션)
    if issues_per_day < 24:
        sel = []
        for d, grp in pd.Series(issues).groupby(pd.Series(issues).map(lambda x: x.date())):
            idx = np.linspace(0, len(grp) - 1, min(issues_per_day, len(grp))).astype(int)
            sel += list(grp.iloc[idx])
        issues = sel
    print(f"[bench] 발령 {len(issues)}건")

    cpx = city_pixels()
    asos = load_asos_ca([(t0 + dt.timedelta(days=k)).date()
                         for k in range((t1 - t0).days + 2)])
    asos_idx = asos.set_index(["TM", "STN"])["CA_TOT"]

    rows, arows = [], []
    for n, issue in enumerate(issues, 1):
        f_prev = load_ca((issue - dt.timedelta(minutes=STEP_MIN)).strftime("%Y%m%d%H%M"))
        f_now = load_ca(issue.strftime("%Y%m%d%H%M"))
        if f_prev is None or f_now is None:
            continue
        vx1, vy1 = flow_dis(f_prev, f_now)
        w = wind_field(issue.replace(tzinfo=None))
        for lead in LEADS_MIN:
            actual = load_ca((issue + dt.timedelta(minutes=lead)).strftime("%Y%m%d%H%M"))
            if actual is None:
                continue
            nst = lead // STEP_MIN
            preds = {"M0": f_now}
            m1 = lead_smooth(backward_sl(f_now, vx1, vy1, nst), lead)
            preds["M1"] = m1
            if w is not None:
                m2 = lead_smooth(backward_sl(f_now, w[0], w[1], nst), lead)
                preds["M2"] = m2
                wgt = max(0.0, 1.0 - lead / 120.0)
                preds["M3"] = wgt * m1 + (1 - wgt) * m2
            valid = np.isfinite(actual) & np.isfinite(f_now)
            for m, p in preds.items():
                err = p[valid] - actual[valid]
                rows.append({"issue_utc": issue, "lead_min": lead, "method": m,
                             "mae": float(np.mean(np.abs(err))),
                             "rmse": float(np.sqrt(np.mean(err ** 2))),
                             "n_px": int(valid.sum())})
                # ASOS 보조 (정시 리드만)
                if lead % 60 == 0:
                    vt = issue + dt.timedelta(minutes=lead, hours=9)  # KST
                    for city, (stn, i, j) in cpx.items():
                        try:
                            obs = asos_idx.at[(pd.Timestamp(vt), stn)]
                        except KeyError:
                            continue
                        arows.append({"issue_utc": issue, "lead_min": lead,
                                      "method": m, "city": city,
                                      "pred": float(p[i, j]),
                                      "obs": float(obs) * 10.0})
        if n % 20 == 0:
            print(f"[bench] {n}/{len(issues)}")

    sc = pd.DataFrame(rows)
    suf = f"_{tag}" if tag else ""
    sc.to_csv(os.path.join(OUT_DIR, f"scores{suf}.csv"), index=False, encoding="utf-8-sig")
    pd.DataFrame(arows).to_csv(os.path.join(OUT_DIR, f"scores_asos{suf}.csv"),
                               index=False, encoding="utf-8-sig")
    report(sc, pd.DataFrame(arows), tag)


def report(sc: pd.DataFrame, asos: pd.DataFrame, tag: str = ""):
    piv = sc.pivot_table(index="lead_min", columns="method", values="mae", aggfunc="mean")
    skill = 1 - piv.div(piv["M0"], axis=0)
    suf = f"_{tag}" if tag else ""
    lines = [f"# 구름 나우캐스트 벤치마크 리포트 {tag}", "",
             f"- 표본: 발령 {sc['issue_utc'].nunique()}건 × 리드 {sorted(sc['lead_min'].unique())}",
             f"- 격자 채점(위성 self-verification), MAE 단위 %운량", "",
             "## 리드별 MAE (%)", piv.round(2).to_markdown(), "",
             "## Persistence 대비 skill (1 − MAE/MAE_M0)",
             (skill.drop(columns=["M0"]) * 100).round(1).to_markdown(), ""]
    if len(asos):
        a = asos.assign(err=lambda d: d["pred"] - d["obs"])
        ap = a.pivot_table(index="lead_min", columns="method", values="err",
                           aggfunc=lambda e: e.abs().mean())
        lines += ["## ASOS 지점 보조 채점 MAE (%)", ap.round(1).to_markdown(), ""]
    with open(os.path.join(OUT_DIR, f"bench_report{suf}.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    fig, ax = plt.subplots(figsize=(8, 5))
    for m in [c for c in piv.columns if c != "M0"]:
        ax.plot(skill.index, skill[m] * 100, "-o", label=m)
    ax.axhline(0, color="k", lw=0.8)
    ax.axhline(10, color="gray", lw=0.8, ls="--")
    ax.set_xlabel("리드타임 (분)")
    ax.set_ylabel("skill vs persistence (%)")
    ax.set_title("운량 나우캐스트 skill (점선=문헌 하한 +10%)")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, f"skill_curve{suf}.png"), dpi=110)
    plt.close(fig)
    print(f"[bench] 리포트: {os.path.join(OUT_DIR, f'bench_report{suf}.md')}")
    print(piv.round(2).to_string())
    print("skill(%):")
    print((skill.drop(columns=['M0']) * 100).round(1).to_string())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--issues-per-day", type=int, default=24)
    p.add_argument("--tag", default="")
    p.add_argument("--t0", default="", help="YYYYMMDDHHMM 필터 시작")
    p.add_argument("--t1", default="", help="YYYYMMDDHHMM 필터 끝")
    args = p.parse_args()
    run_bench(args.issues_per_day, args.tag, args.t0, args.t1)


if __name__ == "__main__":
    main()
