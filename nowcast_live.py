# -*- coding: utf-8 -*-
"""
운영 나우캐스트 — 매시 M4(DL) 운량 예측 표출 + 지속 채점.

흐름 (Actions obs-hourly 매시 20분, 2026-08-24 운영 편입):
  1. GK2A CLA 최신 4프레임(t-30~t, 10분 간격) 수신 — 지연 ~8분 고려해 발령시각 자동 선정
  2. M4 추론 → 지도 PNG(+1~+6h, 전운량 표출 문법: 0어두움·100밝음 + 노란 등치선 50/75)
     + 도시 6곳 시계열(과거 3h 위성 실측 + 예측 6h)
  3. 예측장 npz 보관(채점용, +6h 지나면 삭제)
  4. 지속 채점: 만기 도래 과거 발령을 실제 CLA와 대조 → verification/nowcast/YYYY-MM.csv
     (M0 persistence 병행 채점 — skill 산출용)

산출:
  output/nowcast/latest/map_{lead}h.png (1..6) · cities.png · issue.txt
  output/nowcast/fields/{issueYYYYMMDDHHMM}.npz  (rolling, 채점 후 삭제)
  verification/nowcast/YYYY-MM.csv  (issue_utc, lead_min, method, mae — 커밋 대상)

사용: python nowcast_live.py [--issue YYYYMMDDHHMM(UTC)] [--no-score] [--no-plot]
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

import sslfix  # noqa: F401
from config import OUT_DIR, VERIF_DIR
from fetch_gk2a import fetch_one, data_list
from nowcast_bench import CLA_DIR, load_ca, city_pixels, grid_lonlat


def _gk2a_proj():
    import cartopy.crs as ccrs
    return ccrs.LambertConformal(central_longitude=126, central_latitude=38,
                                 standard_parallels=(30, 60))

NOWCAST_OUT = os.path.join(OUT_DIR, "nowcast")
FIELDS_DIR = os.path.join(NOWCAST_OUT, "fields")
SCORE_DIR = os.path.join(VERIF_DIR, "nowcast")
# 운영 리드 +3h 제한 (2026-08-25 판정: from-scratch는 +2h까지 전승, 여름 장리드 붕괴
#  — 문헌 표준도 "0~3h 위성, 그 너머 NWP". +6h 확장은 롤아웃 안정화 라운드 후)
MAP_LEADS_H = [1, 2, 3]
SERIES_STEP_MIN = 30          # 도시 시계열 해상도
LEADS_ALL = list(range(30, 181, 30))

from matplotlib import font_manager as _fm
_inst = {f.name for f in _fm.fontManager.ttflist}
for _font in ["Malgun Gothic", "NanumGothic", "Noto Sans CJK KR"]:
    if _font in _inst:
        matplotlib.rc("font", family=_font)
        break
matplotlib.rcParams["axes.unicode_minus"] = False


SERIES_CITIES = ["서울", "대전", "대구", "광주", "부산", "강릉"]   # 사용자 확정 지점·순서


def frames_ready(issue: dt.datetime) -> bool:
    """추론용 4프레임(t-30~t) 확보 — 이미 있으면 그대로, 없으면 수신 시도."""
    for i in range(3, -1, -1):
        stamp = (issue - dt.timedelta(minutes=10 * i)).strftime("%Y%m%d%H%M")
        if not fetch_one("CLA", "KO", stamp, CLA_DIR):
            return False
    return True


def pick_issue(now_utc: dt.datetime) -> dt.datetime:
    """제공 지연(~8분)을 감안한 최신 발령시각. 목록 조회가 실패해도(API 혼잡)
    직접 수신으로 대체한다 — 운영이 목록 API 가용성에 종속되지 않도록."""
    cand = (now_utc.replace(minute=now_utc.minute // 10 * 10, second=0, microsecond=0)
            - dt.timedelta(minutes=10))
    try:
        avail = set(data_list("CLA", "KO", now_utc - dt.timedelta(hours=2), now_utc))
    except Exception as ex:
        print(f"[nowcast] 목록 조회 실패({str(ex)[:80]}) — 직접 수신으로 대체")
        avail = None
    for _ in range(9):
        need = [(cand - dt.timedelta(minutes=10 * i)).strftime("%Y%m%d%H%M")
                for i in range(4)]
        if (avail is None or all(n in avail for n in need)) and frames_ready(cand):
            return cand
        cand -= dt.timedelta(minutes=10)
    raise SystemExit("[nowcast] 최근 4프레임 확보 불가 — GK2A 제공 지연")


def fetch_series_past(issue: dt.datetime):
    """도시 시계열용 과거 3h(30분 간격) — 있으면 좋고 없어도 진행(그림만 짧아짐)."""
    for m in range(-180, -30, 30):
        fetch_one("CLA", "KO",
                  (issue + dt.timedelta(minutes=m)).strftime("%Y%m%d%H%M"), CLA_DIR)


def render_maps(issue: dt.datetime, fields: dict[int, np.ndarray], out_dir: str):
    """전운량 표출 문법(plot_charts와 동일): gray 0어두움/100밝음 + 노란 등치선 50/75."""
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    lons, lats = grid_lonlat()
    proj = _gk2a_proj()
    kst = issue + dt.timedelta(hours=9)
    # lead 0 = 현재 위성 관측(비교 기준) — 사용자 요청 2026-08-25
    panels = [(0, load_ca(issue.strftime("%Y%m%d%H%M")))]
    panels += [(h, fields[h * 60]) for h in MAP_LEADS_H]
    for h, f in panels:
        if f is None:
            continue
        fig = plt.figure(figsize=(7.4, 5.9))
        ax = fig.add_axes([0.06, 0.05, 0.9, 0.86], projection=proj)
        ax.imshow(f, transform=proj, origin="upper",   # row0=북 실측 확정
                  extent=[-899000, 899000, -899000, 899000],
                  cmap="gray", vmin=0, vmax=100, interpolation="bilinear")
        # 등치선은 평활장에서 — 관측 원장은 화소 잡음이 심해 얼룩이 됨(그림은 원본 유지)
        from scipy.ndimage import gaussian_filter
        ax.contour(lons, lats, gaussian_filter(np.nan_to_num(f, nan=0.0), 3.0),
                   levels=[50, 75], colors="yellow",
                   linewidths=[0.9, 1.4], transform=ccrs.PlateCarree())
        ax.coastlines(resolution="10m", color="#00cfff", linewidth=0.9)
        ax.add_feature(cfeature.STATES.with_scale("10m"),
                       edgecolor="#00cfff", linewidth=0.35, facecolor="none")
        vt = kst + dt.timedelta(hours=h)
        ax.set_title(f"현재 위성 관측  {kst:%m-%d %H:%M} KST" if h == 0 else
                     f"운량 나우캐스트 +{h}h  유효 {vt:%m-%d %H시} KST (발령 {kst:%H:%M})",
                     fontsize=11)
        fig.savefig(os.path.join(out_dir, f"map_{h}h.png"), dpi=110)
        plt.close(fig)


def render_cities(issue: dt.datetime, fields: dict[int, np.ndarray], out_dir: str):
    """과거 3h 위성 실측 + 예측 6h — 6도시, y축 0~100 공통."""
    cpx_all = city_pixels()
    cpx = {c: cpx_all[c] for c in SERIES_CITIES if c in cpx_all}
    kst = issue + dt.timedelta(hours=9)
    past = []
    for m in range(-180, 1, 30):
        f = load_ca((issue + dt.timedelta(minutes=m)).strftime("%Y%m%d%H%M"))
        past.append((m, f))
    fig, axes = plt.subplots(3, 2, figsize=(13, 9), sharex=True, sharey=True)
    for ax, (city, (stn, i, j)) in zip(axes.flat, cpx.items()):
        xs = [kst + dt.timedelta(minutes=m) for m, f in past if f is not None]
        ys = [float(f[i, j]) for m, f in past if f is not None]
        ax.plot(xs, ys, "-o", color="black", ms=3, lw=1.6, label="위성 실측")
        fx = [kst + dt.timedelta(minutes=m) for m in LEADS_ALL]
        fy = [float(fields[m][i, j]) for m in LEADS_ALL]
        ax.plot([xs[-1]] + fx if xs else fx, ([ys[-1]] + fy) if ys else fy,
                "--s", color="tab:red", ms=3, lw=1.4, label="M4 예측")
        ax.axvline(kst, color="tab:red", lw=0.9, ls=":")
        ax.set_ylim(0, 100)
        ax.set_title(city, fontsize=12, weight="bold")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, loc="best")
    fig.suptitle(f"도시별 운량(%) — 위성 실측 3h + 나우캐스트 6h  (발령 {kst:%m-%d %H:%M} KST)",
                 fontsize=13)
    fig.autofmt_xdate()
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(os.path.join(out_dir, "cities.png"), dpi=110)
    plt.close(fig)


def score_due(now_utc: dt.datetime):
    """만기(+6h 경과) 발령 npz를 실제 CLA와 대조 채점 후 삭제. M0 병행."""
    os.makedirs(SCORE_DIR, exist_ok=True)
    rows = []
    for path in sorted(glob.glob(os.path.join(FIELDS_DIR, "*.npz"))):
        stamp = os.path.basename(path)[:-4]
        issue = dt.datetime.strptime(stamp, "%Y%m%d%H%M")
        if now_utc < issue + dt.timedelta(minutes=LEADS_ALL[-1] + 20):
            continue
        with np.load(path) as z:   # 핸들 열린 채 remove 불가(WinError 32) — 즉시 닫기
            preds = {k: z[k].astype(np.float32) for k in z.files}
        base = load_ca(stamp)
        for m in LEADS_ALL:
            vt = issue + dt.timedelta(minutes=m)
            # 검증 프레임이 없으면 수신 시도(과거분 보충)
            fetch_one("CLA", "KO", vt.strftime("%Y%m%d%H%M"), CLA_DIR)
            actual = load_ca(vt.strftime("%Y%m%d%H%M"))
            if actual is None or f"m{m}" not in preds:
                continue
            pred = preds[f"m{m}"]
            valid = np.isfinite(actual)
            rows.append({"issue_utc": issue, "lead_min": m, "method": "M4",
                         "mae": float(np.mean(np.abs(pred[valid] - actual[valid])))})
            if base is not None:
                rows.append({"issue_utc": issue, "lead_min": m, "method": "M0",
                             "mae": float(np.mean(np.abs(base[valid] - actual[valid])))})
        os.remove(path)
        print(f"[nowcast] 채점 완료: {stamp}")
    if not rows:
        return
    df = pd.DataFrame(rows)
    for mm, grp in df.groupby(df["issue_utc"].map(lambda x: f"{x:%Y-%m}")):
        path = os.path.join(SCORE_DIR, f"{mm}.csv")
        if os.path.exists(path):
            old = pd.read_csv(path, parse_dates=["issue_utc"])
            grp = pd.concat([old, grp]).drop_duplicates(
                subset=["issue_utc", "lead_min", "method"], keep="last")
        grp.sort_values(["issue_utc", "lead_min", "method"]).to_csv(
            path, index=False, encoding="utf-8-sig")
        print(f"[nowcast] 채점 기록: {path}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--issue", default="", help="발령시각 YYYYMMDDHHMM(UTC), 생략=자동")
    p.add_argument("--no-score", action="store_true")
    p.add_argument("--no-plot", action="store_true")
    args = p.parse_args()

    now_utc = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    issue = (dt.datetime.strptime(args.issue, "%Y%m%d%H%M") if args.issue
             else pick_issue(now_utc))
    if args.issue and not frames_ready(issue):
        raise SystemExit(f"[nowcast] 프레임 확보 실패: {issue}")
    print(f"[nowcast] 발령 {issue} UTC")
    fetch_series_past(issue)

    from dl_infer import DLNowcaster, MODEL_H5
    print(f"[nowcast] 모델: {MODEL_H5}")
    d = DLNowcaster()
    fields = d.predict(issue, LEADS_ALL)
    if fields is None:
        raise SystemExit("[nowcast] hist 결측 — 추론 불가")

    os.makedirs(FIELDS_DIR, exist_ok=True)
    # uint8 저장 — Actions에선 site-data에 실려 런 간 왕복하므로 크기 최소화
    np.savez_compressed(os.path.join(FIELDS_DIR, f"{issue:%Y%m%d%H%M}.npz"),
                        **{f"m{m}": np.round(v).astype(np.uint8)
                           for m, v in fields.items()})

    if not args.no_plot:
        latest = os.path.join(NOWCAST_OUT, "latest")
        os.makedirs(latest, exist_ok=True)
        render_maps(issue, fields, latest)
        render_cities(issue, fields, latest)
        with open(os.path.join(latest, "issue.txt"), "w") as f:
            f.write(f"{issue:%Y%m%d%H%M}")
        print(f"[nowcast] 표출 → {latest}")

    if not args.no_score:
        score_due(now_utc)


if __name__ == "__main__":
    main()
