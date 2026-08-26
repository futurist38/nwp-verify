# -*- coding: utf-8 -*-
"""
운영 나우캐스트 — 매시 M4(DL) 운량 예측 표출 + 지속 채점.

흐름 (Actions obs-hourly 매시 20분, 2026-08-24 운영 편입):
  1. GK2A CLA 최신 4프레임(t-30~t, 10분 간격) 수신 — 지연 ~8분 고려해 발령시각 자동 선정
  2. M4 추론 → 지도 PNG(+1~+6h, 위성영상 문법: 0어두움·100밝음 + 노란 지리선)
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
from nowcast_bench import CLA_DIR, load_ca, city_pixels


def _gk2a_proj():
    import cartopy.crs as ccrs
    return ccrs.LambertConformal(central_longitude=126, central_latitude=38,
                                 standard_parallels=(30, 60))

NOWCAST_OUT = os.path.join(OUT_DIR, "nowcast")
FIELDS_DIR = os.path.join(NOWCAST_OUT, "fields")
SCORE_DIR = os.path.join(VERIF_DIR, "nowcast")
ARCHIVE_DIR = os.path.join(NOWCAST_OUT, "archive")   # 과거 조회용 검증 패널
ARCHIVE_EVERY_H = 3    # 3시간마다 한 장만 보관 — 매시 보관하면 site-data가 감당 못 함
ARCHIVE_KEEP_DAYS = 30
# 운영 리드 +6h (2026-08-26 확장). 근거 둘:
#  · 계절별 5기간에서 v5가 +6h까지 지속성 대비 +15~23% 유지 (V5_판정.md)
#  · ASOS 실측 대비 NWP와 직접 대결에서 +6h까지 교차점 없음 — 나우캐스트 14.9 vs
#    ECMWF 19.4 (VS_NWP_판정.md). 문헌의 2.75~4.5h 교차점이 우리 조건엔 오지 않았다
MAP_LEADS_H = [1, 2, 3, 4, 5, 6]
SERIES_STEP_MIN = 30          # 도시 시계열 해상도
LEADS_ALL = list(range(30, 361, 30))

from matplotlib import font_manager as _fm
_inst = {f.name for f in _fm.fontManager.ttflist}
for _font in ["Malgun Gothic", "NanumGothic", "Noto Sans CJK KR"]:
    if _font in _inst:
        matplotlib.rc("font", family=_font)
        break
matplotlib.rcParams["axes.unicode_minus"] = False


SERIES_CITIES = ["서울", "대전", "대구", "광주", "부산", "강릉"]   # 사용자 확정 지점·순서


REF_Q = 4096      # 확률매칭 참조 분위 개수 (npz에 함께 보관 — 값이 작아 부담 없음)


def ref_quantiles(field: np.ndarray | None) -> np.ndarray | None:
    """참조장(발령시각 실황)의 값 분포를 분위로 압축."""
    if field is None:
        return None
    v = field[np.isfinite(field)]
    if v.size < 1000:
        return None
    return np.quantile(v, np.linspace(0, 1, REF_Q)).astype(np.float32)


def pmm(pred: np.ndarray, ref_q: np.ndarray | None) -> np.ndarray:
    """확률매칭(probability matching) — 예측의 순위는 그대로 두고 값 분포만 참조장에 맞춘다.
    긴 리드에서 모델이 불확실성 때문에 평평해진 대비를 되살리는 나우캐스팅 표준 기법.
    실측(2026-08-26, +6h 25발령): 대비 유지율 0.74→0.99, MAE 22.8→23.4(+3%).
    **정보를 더하지는 않는다 — 표출 전용이며 채점은 원본으로 한다.**
    참조는 '발령시각 실황'이라 미래 정보를 쓰지 않는다."""
    if ref_q is None:
        return pred
    order = np.argsort(pred.ravel())
    vals = np.interp(np.linspace(0, 1, pred.size),
                     np.linspace(0, 1, len(ref_q)), ref_q)
    out = np.empty(pred.size, np.float32)
    out[order] = vals
    return out.reshape(pred.shape)


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


def render_maps(issue: dt.datetime, fields: dict[int, np.ndarray], out_dir: str,
                obs_native: np.ndarray | None = None,
                ref_q: np.ndarray | None = None):
    """위성영상 문법(plot_charts 전운량과 동일): gray 0어두움/100밝음 + 노란 지리선."""
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    proj = _gk2a_proj()
    kst = issue + dt.timedelta(hours=9)
    # lead 0 = 현재 위성 관측(비교 기준) — 사용자 요청 2026-08-25
    panels = [(0, obs_native if obs_native is not None else load_ca(issue.strftime("%Y%m%d%H%M")))]
    panels += [(h, pmm(fields[h * 60], ref_q)) for h in MAP_LEADS_H]
    for h, f in panels:
        if f is None:
            continue
        fig = plt.figure(figsize=(7.4, 5.9))
        ax = fig.add_axes([0.06, 0.05, 0.9, 0.86], projection=proj)
        ax.imshow(f, transform=proj, origin="upper",   # row0=북 실측 확정
                  extent=[-899000, 899000, -899000, 899000],
                  cmap="gray", vmin=0, vmax=100, interpolation="bilinear")
        # 위성영상 문법: 구름 등치선 없이 지리선만 노란색 (2026-08-26 사용자 확정)
        ax.coastlines(resolution="10m", color="yellow", linewidth=0.9)
        ax.add_feature(cfeature.STATES.with_scale("10m"),
                       edgecolor="yellow", linewidth=0.35, facecolor="none")
        vt = kst + dt.timedelta(hours=h)
        ax.set_title(f"현재 위성 관측  {kst:%m-%d %H:%M} KST" if h == 0 else
                     f"운량 나우캐스트 +{h}h  유효 {vt:%m-%d %H시} KST (발령 {kst:%H:%M})",
                     fontsize=11)
        fig.savefig(os.path.join(out_dir, f"map_{h}h.png"), dpi=110)
        plt.close(fig)


def draw_verify(panels: list, valid_kst: dt.datetime, out_path: str,
                note: str = "") -> bool:
    """패널 목록[(라벨, 장 or None)] → 한 장으로. 첫 칸이 실제, 나머지가 과거 예측."""
    import cartopy.feature as cfeature
    proj = _gk2a_proj()
    if sum(f is not None for _, f in panels) < 2:
        print("[nowcast] 비교할 예측이 부족 — 검증 화면 생략")
        return False
    fig = plt.figure(figsize=(16.5, 8.6))
    for n, (label, f) in enumerate(panels):
        if f is None:   # 지도 축으로 만들면 투영 경계가 부채꼴로 그려져 흉하다 → 평면 축
            ax = fig.add_subplot(2, 4, n + 1)
            ax.set_xticks([]); ax.set_yticks([])
            ax.set_facecolor("#f2f2f2")
            ax.text(0.5, 0.5, "없음", ha="center", va="center",
                    transform=ax.transAxes, fontsize=10, color="#888")
            ax.set_title(label, fontsize=11)
            continue
        ax = fig.add_subplot(2, 4, n + 1, projection=proj)
        ax.set_title(label, fontsize=11, weight="bold" if n == 0 else "normal")
        ax.imshow(f, transform=proj, origin="upper",
                  extent=[-899000, 899000, -899000, 899000],
                  cmap="gray", vmin=0, vmax=100, interpolation="bilinear")
        ax.coastlines(resolution="10m", color="yellow", linewidth=0.7)
        ax.add_feature(cfeature.STATES.with_scale("10m"),
                       edgecolor="yellow", linewidth=0.3, facecolor="none")
    head = f"같은 시각을 언제 예측했나 - 유효 {valid_kst:%Y-%m-%d %H:%M} KST"
    if note:
        head += f"   [{note}]"
    fig.suptitle(head + "\n왼쪽 위가 실제, 나머지는 그 시각을 1~6시간 전에 내다본 결과",
                 fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig.savefig(out_path, dpi=100)
    plt.close(fig)
    return True


def render_verify(issue: dt.datetime, obs: np.ndarray | None, out_dir: str):
    """'지금 위성' vs '과거에 예측한 지금' — 리드 1~6h를 한 장에 (2026-08-26 사용자 요청).
    보관해 둔 과거 발령 예측장(FIELDS_DIR)에서 유효시각이 이번 발령과 맞는 것을 꺼내 쓴다
    — 추가 추론도 추가 수신도 없다."""
    kst = issue + dt.timedelta(hours=9)

    stored = {}
    for path in glob.glob(os.path.join(FIELDS_DIR, "*.npz")):
        try:
            stored[dt.datetime.strptime(os.path.basename(path)[:-4], "%Y%m%d%H%M")] = path
        except ValueError:
            continue

    panels = [("현재 위성 관측", obs)]
    for h in MAP_LEADS_H:
        want = issue - dt.timedelta(hours=h)
        cand = [t for t in stored if abs((t - want).total_seconds()) <= 1200]
        f = None
        if cand:
            t = min(cand, key=lambda t: abs((t - want).total_seconds()))
            with np.load(stored[t]) as z:
                key = f"m{h * 60}"
                if key in z.files:
                    f = z[key].astype(np.float32)
                    rq = z["ref"] if "ref" in z.files else None
                    f = pmm(f, rq if rq is not None and rq.size else None)
        panels.append((f"{h}시간 전 예측", f))

    return draw_verify(panels, kst, os.path.join(out_dir, "verify.png"))


def verify_case(valid_utc: dt.datetime, out_dir: str,
                out_name: str = "", note: str = "") -> bool:
    """과거 임의 시각을 되짚어 본다 — 그 시각을 1~6시간 전에 각각 어떻게 예측했는지 재현.
    보관분에 의존하지 않고 그 자리에서 추론하므로 위성 원자료가 있는 기간이면 언제든 가능.
    사이트에는 올라가지 않는다(발행 대상은 output/nowcast/latest 뿐)."""
    from dl_infer import DLNowcaster, load_ca_native
    d = DLNowcaster()
    obs_path = os.path.join(CLA_DIR, valid_utc.strftime("%Y%m%d%H%M") + ".nc")
    obs = load_ca_native(obs_path) if os.path.exists(obs_path) else None
    if obs is None:
        print(f"[사례] 실황 위성 없음: {valid_utc} — 그 시각 자료를 먼저 받아야 함")

    panels = [("실제 위성 관측", obs)]
    for h in MAP_LEADS_H:
        issue = valid_utc - dt.timedelta(hours=h)
        f = None
        if frames_ready(issue):
            out = d.predict(issue, [h * 60], native=True)
            if out:
                ip = os.path.join(CLA_DIR, issue.strftime("%Y%m%d%H%M") + ".nc")
                rq = ref_quantiles(load_ca_native(ip)) if os.path.exists(ip) else None
                f = pmm(out[h * 60], rq)
        else:
            print(f"[사례] {h}시간 전({issue:%m-%d %H:%M}) 입력 프레임 부족")
        panels.append((f"{h}시간 전 예측", f))

    kst = valid_utc + dt.timedelta(hours=9)
    out_path = os.path.join(out_dir, out_name or f"case_{valid_utc:%Y%m%d%H%M}.png")
    ok = draw_verify(panels, kst, out_path, note)
    if ok:
        print(f"[사례] 저장 → {out_path}")
    return ok


def archive_verify(issue: dt.datetime, latest_dir: str):
    """검증 패널을 유효시각 이름으로 보관 — 과거 날짜 조회용.
    장당 ~400KB라 매시 보관하면 하루 10MB, site-data(이미 500MB)가 감당 못 한다.
    3시간 간격 · 30일 보존이면 ~95MB 선에서 유지된다."""
    kst = issue + dt.timedelta(hours=9)
    if kst.hour % ARCHIVE_EVERY_H != 0:
        return
    src = os.path.join(latest_dir, "verify.png")
    if not os.path.exists(src):
        return
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    import shutil
    shutil.copy2(src, os.path.join(ARCHIVE_DIR, f"{kst:%Y%m%d%H}.png"))
    cut = f"{(kst - dt.timedelta(days=ARCHIVE_KEEP_DAYS)):%Y%m%d%H}"
    n = 0
    for f in os.listdir(ARCHIVE_DIR):
        if f.endswith(".png") and f[:-4] < cut:
            os.remove(os.path.join(ARCHIVE_DIR, f))
            n += 1
    if n:
        print(f"[nowcast] 보관 정리: {n}장 삭제")


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
            if pred.shape != actual.shape:      # 원해상도 보관본 → 채점 격자로
                import cv2
                pred = cv2.resize(pred, actual.shape[::-1], interpolation=cv2.INTER_AREA)
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
    p.add_argument("--backfill", nargs=2, metavar=("YYYYMMDD", "YYYYMMDD"), default=None,
                   help="과거 보관분 소급 생성(KST 3시간 간격) — 현재 모델로 재현")
    p.add_argument("--case", default="",
                   help="과거 유효시각 YYYYMMDDHHMM(UTC) 되짚어보기 — 사이트 미발행")
    args = p.parse_args()

    if args.backfill:   # 과거 보관분 채우기 — 당시 예측이 아니라 현 모델 소급 재현
        d0 = dt.datetime.strptime(args.backfill[0], "%Y%m%d")
        d1 = dt.datetime.strptime(args.backfill[1], "%Y%m%d")
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
        made = skip = 0
        day = d0
        while day <= d1:
            for hh in range(0, 24, ARCHIVE_EVERY_H):
                kst = day + dt.timedelta(hours=hh)
                name = f"{kst:%Y%m%d%H}.png"
                if os.path.exists(os.path.join(ARCHIVE_DIR, name)):
                    skip += 1
                    continue
                if verify_case(kst - dt.timedelta(hours=9), ARCHIVE_DIR, name,
                               "현 모델 소급 재현"):
                    made += 1
            print(f"[백필] {day:%m-%d} 누적 생성 {made} / 기존 {skip}")
            day += dt.timedelta(days=1)
        return

    if args.case:   # 과거 사례 조회 모드 — 운영 산출물을 건드리지 않는다
        verify_case(dt.datetime.strptime(args.case, "%Y%m%d%H%M"),
                    os.path.join(NOWCAST_OUT, "cases"))
        return

    now_utc = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    issue = (dt.datetime.strptime(args.issue, "%Y%m%d%H%M") if args.issue
             else pick_issue(now_utc))
    if args.issue and not frames_ready(issue):
        raise SystemExit(f"[nowcast] 프레임 확보 실패: {issue}")
    print(f"[nowcast] 발령 {issue} UTC")
    fetch_series_past(issue)

    from dl_infer import DLNowcaster, MODEL_H5, load_ca_native
    print(f"[nowcast] 모델: {MODEL_H5}")
    d = DLNowcaster()
    # 표출은 원해상도(512), 채점·시계열은 벤치격자(450) — 축소가 만드는 맥놀이 격자 회피
    native = d.predict(issue, LEADS_ALL, native=True)
    if native is None:
        raise SystemExit("[nowcast] hist 결측 — 추론 불가")
    import cv2
    from nowcast_bench import N_PIX
    fields = {m: cv2.resize(f, (N_PIX, N_PIX), interpolation=cv2.INTER_AREA)
              for m, f in native.items()}
    obs_path = os.path.join(CLA_DIR, issue.strftime("%Y%m%d%H%M") + ".nc")
    obs_native = load_ca_native(obs_path) if os.path.exists(obs_path) else None
    ref_q = ref_quantiles(obs_native)      # 표출 대비 보정용(발령시각 실황 분포)

    os.makedirs(FIELDS_DIR, exist_ok=True)
    # uint8 저장 — Actions에선 site-data에 실려 런 간 왕복하므로 크기 최소화.
    # 원해상도(512)로 보관: 채점은 축소해 쓰고, "과거 예측 vs 지금" 표출에 재사용한다
    # (450으로 저장하면 표출 때 맥놀이 격자가 되살아남 — 2026-08-26)
    np.savez_compressed(os.path.join(FIELDS_DIR, f"{issue:%Y%m%d%H%M}.npz"),
                        ref=(ref_q if ref_q is not None else np.zeros(0, np.float32)),
                        **{f"m{m}": np.round(v).astype(np.uint8)
                           for m, v in native.items()})

    if not args.no_plot:
        latest = os.path.join(NOWCAST_OUT, "latest")
        os.makedirs(latest, exist_ok=True)
        render_maps(issue, native, latest, obs_native, ref_q)
        if render_verify(issue, obs_native, latest):
            archive_verify(issue, latest)
        render_cities(issue, fields, latest)
        with open(os.path.join(latest, "issue.txt"), "w") as f:
            f.write(f"{issue:%Y%m%d%H%M}")
        print(f"[nowcast] 표출 → {latest}")

    if not args.no_score:
        score_due(now_utc)


if __name__ == "__main__":
    main()
