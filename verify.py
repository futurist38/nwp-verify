# -*- coding: utf-8 -*-
"""
오답노트 — 예측 vs ASOS 실황 대조.

서브커맨드:
    archive   당일 city_forecast.csv 를 verification/forecast/YYYY-MM.csv 에 적재
    score     지정일(기본 어제, KST)의 실황을 받아 예측과 조인·채점, 임계 초과 시 사례 파일 생성
    report    누적 scores 를 도시×모델×리드타임 버킷으로 ME/MAE 집계 + MAE 곡선 PNG

원칙 (PROJECT_BRIEF):
  · 모델 간 발산을 평균·중재하지 않는다. 행 단위로 fcst·obs 원수치를 보존한다.
  · 수집·조인 실패는 추정으로 채우지 않고 누락으로 명시한다.
  · 사례 파일의 원인 분석은 사람이 쓴다. 파이프라인은 재료만 정리한다.

변수 정합:
  t2m : 예측 t2m_C(℃) ↔ 실황 TA(℃)
  tcc : 예측 tcc_pct(%) ↔ 실황 CA_TOT(0~10 십분위)×10
  dswrf(GFS만) : 예측 dswrf_avg_Wm2 는 6시간마다 리셋되는 구간 평균
        (f003=0-3h, f006=0-6h, f009=6-9h ... → 구간 시작 = 6*((step-1)//6)).
        실황은 SI(MJ/m², 직전 1시간 적산)를 W/m²(×10⁶/3600)로 바꿔
        같은 구간의 시간별 값을 평균해 비교한다. 구간 내 실황이 하나라도 결측이면 결측.
"""
import argparse
import datetime as dt
import glob
import os

import numpy as np
import pandas as pd

from config import (CITY_OBS_STN, CASE_THRESHOLDS, LEAD_BUCKETS,
                    OUT_DIR, VERIF_DIR)

FCST_DIR = os.path.join(VERIF_DIR, "forecast")
OBS_DIR = os.path.join(VERIF_DIR, "obs")
SCORE_DIR = os.path.join(VERIF_DIR, "scores")
CASE_DIR = os.path.join(VERIF_DIR, "cases")

SI_TO_W = 1e6 / 3600.0   # MJ/m²(1h 적산) → 평균 W/m²


# ══════════════════════════════════════════════════════════
# archive — 예측 적재
# ══════════════════════════════════════════════════════════

def cmd_archive(csv_path: str | None = None):
    """output/*/city_forecast.csv → verification/forecast/YYYY-MM.csv (run_utc 월 기준)."""
    if csv_path is None:
        cands = sorted(glob.glob(os.path.join(OUT_DIR, "*", "city_forecast.csv")))
        if not cands:
            raise SystemExit("적재할 city_forecast.csv 가 없습니다. plot_charts.py 먼저 실행.")
        csv_path = cands[-1]
    df = pd.read_csv(csv_path)
    df["run_utc"] = pd.to_datetime(df["run_utc"])
    os.makedirs(FCST_DIR, exist_ok=True)
    n_new = 0
    for ym, g in df.groupby(df["run_utc"].dt.strftime("%Y-%m")):
        path = os.path.join(FCST_DIR, f"{ym}.csv")
        key = ["model", "run_utc", "city", "step_h"]
        if os.path.exists(path):
            old = pd.read_csv(path, parse_dates=["run_utc"])
            before = len(old)
            merged = pd.concat([old, g], ignore_index=True)
            merged = merged.drop_duplicates(subset=key, keep="last")
            n_new += len(merged) - before
        else:
            merged = g.drop_duplicates(subset=key, keep="last")
            n_new += len(merged)
        merged = merged.sort_values(["run_utc", "model", "city", "step_h"])
        merged.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"[archive] {path}: {len(merged)}행 (신규 {n_new})")
    print(f"[archive] 적재 원본: {csv_path}")


# ══════════════════════════════════════════════════════════
# score — 실황 조인·채점
# ══════════════════════════════════════════════════════════

def _load_months(dir_, months, parse_col):
    frames = []
    for ym in months:
        path = os.path.join(dir_, f"{ym}.csv")
        if os.path.exists(path):
            frames.append(pd.read_csv(path, parse_dates=[parse_col]))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _months_between(d1: dt.date, d2: dt.date):
    out, cur = [], dt.date(d1.year, d1.month, 1)
    while cur <= d2:
        out.append(cur.strftime("%Y-%m"))
        cur = (cur.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return out


def cmd_score(date_str: str | None = None, fetch_obs: bool = True):
    target = (dt.date.fromisoformat(date_str) if date_str
              else dt.date.today() - dt.timedelta(days=1))
    day0 = dt.datetime.combine(target, dt.time(0))
    day1 = day0 + dt.timedelta(hours=23)
    print(f"[score] 대상일(KST): {target}")

    # 1) 실황 확보 (dswrf 구간 평균용으로 전일 18시부터)
    if fetch_obs:
        import kma_asos
        # 전 지점 수신 — 검증(10지점)과 관측 실황 지도(전 지점 보간)를 한 번에 충당
        stations = kma_asos.all_stations()
        obs_new = kma_asos.get_hourly(stations, day0 - dt.timedelta(hours=6), day1)
        kma_asos.save_monthly(obs_new)

    months = _months_between(target - dt.timedelta(days=1), target)
    obs = _load_months(OBS_DIR, months, "TM")
    if obs.empty:
        raise SystemExit("[score] 실황이 없습니다. kma_asos.py 먼저 실행하거나 --no-fetch 제거.")

    # 2) 대상일에 유효한 예측 로드 (최장 리드 240h → 10일 전 런까지)
    f_months = _months_between(target - dt.timedelta(days=11), target)
    fc = _load_months(FCST_DIR, f_months, "run_utc")
    if fc.empty:
        raise SystemExit("[score] 적재된 예측이 없습니다. verify.py archive 먼저 실행.")
    fc["valid_kst"] = pd.to_datetime(fc["valid_kst"])
    fc = fc[(fc["valid_kst"] >= day0) & (fc["valid_kst"] <= day1)].copy()
    if fc.empty:
        print("[score] 대상일에 유효한 예측 행이 없습니다 — 종료")
        return

    # 3) 도시 → 지점 매핑 후 조인
    fc["stn"] = fc["city"].map(CITY_OBS_STN)
    n_no_stn = int(fc["stn"].isna().sum())
    if n_no_stn:
        skipped = sorted(fc.loc[fc["stn"].isna(), "city"].unique())
        print(f"[score] 실황 지점 없는 도시 제외: {skipped} ({n_no_stn}행) — 검증 불가로 명시")
    fc = fc.dropna(subset=["stn"])
    fc["stn"] = fc["stn"].astype(int)

    obs_idx = obs.set_index(["TM", "STN"])

    def obs_at(tm, stn, col):
        try:
            v = obs_idx.at[(tm, stn), col]
            return None if pd.isna(v) else float(v)
        except KeyError:
            return None

    rows = []
    n_miss = 0
    for r in fc.itertuples():
        pairs = []  # (var, fcst, obs)
        ta = obs_at(r.valid_kst, r.stn, "TA")
        if pd.notna(r.t2m_C):
            pairs.append(("t2m", float(r.t2m_C), ta))
        if pd.notna(r.tcc_pct):
            ca = obs_at(r.valid_kst, r.stn, "CA_TOT")
            pairs.append(("tcc", float(r.tcc_pct), None if ca is None else ca * 10.0))
        if getattr(r, "dswrf_avg_Wm2", None) is not None and pd.notna(r.dswrf_avg_Wm2):
            # 구간 평균 대 구간 평균 (모듈 주석의 규칙)
            win_start = 6 * ((int(r.step_h) - 1) // 6)
            hours = range(win_start + 1, int(r.step_h) + 1)
            si_vals = [obs_at(r.valid_kst - pd.Timedelta(hours=int(r.step_h) - h), r.stn, "SI")
                       for h in hours]
            if si_vals and all(v is not None for v in si_vals):
                obs_w = float(np.mean([v * SI_TO_W for v in si_vals]))
            else:
                obs_w = None
            pairs.append(("dswrf", float(r.dswrf_avg_Wm2), obs_w))

        for var, f_val, o_val in pairs:
            if o_val is None:
                n_miss += 1
            rows.append({
                "valid_kst": r.valid_kst, "city": r.city, "model": r.model,
                "run_utc": r.run_utc, "step_h": int(r.step_h),
                "lead_day": int(r.step_h) // 24, "var": var,
                "fcst": round(f_val, 2),
                "obs": None if o_val is None else round(o_val, 2),
                "err": None if o_val is None else round(f_val - o_val, 2),
            })

    sc = pd.DataFrame(rows)
    print(f"[score] 채점 {len(sc)}행 (실황 결측 {n_miss}건 — 누락으로 기록)")

    # 4) 저장 (valid 월 기준, 키 중복은 갱신)
    os.makedirs(SCORE_DIR, exist_ok=True)
    key = ["valid_kst", "city", "model", "run_utc", "var"]
    for ym, g in sc.groupby(sc["valid_kst"].dt.strftime("%Y-%m")):
        path = os.path.join(SCORE_DIR, f"{ym}.csv")
        if os.path.exists(path):
            old = pd.read_csv(path, parse_dates=["valid_kst", "run_utc"])
            g = pd.concat([old, g], ignore_index=True).drop_duplicates(subset=key, keep="last")
        g = g.sort_values(["valid_kst", "city", "model", "step_h", "var"])
        g.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"[score] 저장: {path} ({len(g)}행)")

    # 5) 사례 태깅 + 일일 요약
    tag_cases(sc, target)
    print()
    print(daily_summary_text(sc, target))


# ══════════════════════════════════════════════════════════
# 사례 태깅 — 오답노트의 핵심 ("틀린 문제 중심")
# ══════════════════════════════════════════════════════════

def tag_cases(sc: pd.DataFrame, target: dt.date):
    os.makedirs(CASE_DIR, exist_ok=True)
    scored = sc.dropna(subset=["err"])
    if scored.empty:
        return
    made = 0
    for (city, var), g in scored.groupby(["city", "var"]):
        trigger = None
        for model, gm in g.groupby("model"):
            me = gm["err"].mean()
            if var == "t2m" and abs(me) > CASE_THRESHOLDS["t2m_abs_me"]:
                trigger = f"{model} 기온 일평균 ME {me:+.1f}℃ (임계 ±{CASE_THRESHOLDS['t2m_abs_me']}℃)"
            if var == "tcc" and abs(me) > CASE_THRESHOLDS["tcc_abs_err"]:
                trigger = f"{model} 운량 일평균 오차 {me:+.0f}%p (임계 ±{CASE_THRESHOLDS['tcc_abs_err']:.0f}%p)"
        if trigger is None:
            continue

        path = os.path.join(CASE_DIR, f"{target:%Y%m%d}_{city}_{var}.md")
        lines = [
            f"# 오답노트 사례 — {target} {city} {var}",
            "",
            f"- 트리거: {trigger}",
            f"- 생성: 자동 (verify.py score). 수치는 원값 그대로이며 요약·보정 없음.",
            "",
            "## 예측 vs 실황 (전 리드타임 원수치)",
            "",
            "| 유효시각(KST) | 모델 | 런(UTC) | 리드(h) | 예측 | 실황 | 오차 |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in g.sort_values(["valid_kst", "model", "step_h"]).itertuples():
            lines.append(
                f"| {r.valid_kst:%m-%d %H시} | {r.model} | {r.run_utc:%m-%d %H} | "
                f"{r.step_h} | {r.fcst} | {r.obs} | {r.err:+.1f} |")
        lines += [
            "",
            f"## 그림",
            f"- 지도: `output/{target:%Y%m%d}/maps_*/`",
            f"- 미티오그램: `output/{target:%Y%m%d}/meteograms/meteogram_{city}.png`",
            "",
            "## 원인 분석 (사용자 기입)",
            "",
            "- (종관 상황, 모델이 놓친 것, 브리핑에 반영할 교훈)",
            "",
        ]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        made += 1
        print(f"[사례] 생성: {path} — {trigger}")
    if made == 0:
        print("[사례] 임계 초과 없음")


def daily_summary_text(sc: pd.DataFrame, target: dt.date) -> str:
    """도시×모델 일평균 ME 요약 (추후 ② 메일 본문에 그대로 재사용)."""
    scored = sc.dropna(subset=["err"])
    lines = [f"===== {target} 오답노트 요약 (일평균 ME, 예측-실황) ====="]
    for var, unit in [("t2m", "℃"), ("tcc", "%p")]:
        g = scored[scored["var"] == var]
        if g.empty:
            lines.append(f"[{var}] 자료 없음")
            continue
        pv = g.pivot_table(index="city", columns="model", values="err", aggfunc="mean")
        lines.append(f"[{var}] ({unit})")
        lines.append(pv.round(1).to_string())
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════
# report — 누적 집계
# ══════════════════════════════════════════════════════════

def cmd_report():
    files = sorted(glob.glob(os.path.join(SCORE_DIR, "*.csv")))
    if not files:
        raise SystemExit("[report] scores 가 없습니다. verify.py score 먼저 실행.")
    sc = pd.concat([pd.read_csv(f, parse_dates=["valid_kst", "run_utc"]) for f in files],
                   ignore_index=True).dropna(subset=["err"])

    def bucket(h):
        for lo, hi in LEAD_BUCKETS:
            if lo <= h < hi:
                return f"{lo:03d}-{hi:03d}h"
        return f"{LEAD_BUCKETS[-1][1]:03d}h+"

    sc["lead"] = sc["step_h"].map(bucket)
    agg = (sc.groupby(["var", "city", "model", "lead"])["err"]
             .agg(n="count", ME="mean", MAE=lambda e: e.abs().mean())
             .round(2).reset_index())
    out_csv = os.path.join(VERIF_DIR, "scores_summary.csv")
    agg.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"[report] 집계 저장: {out_csv} ({len(agg)}행, 원천 {len(sc)}행)")

    # MAE 곡선 (스텝별, 대표성 위해 전 도시 평균 — 원수치는 scores CSV에 보존)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager as fm
    inst = {f.name for f in fm.fontManager.ttflist}
    for font in ["Malgun Gothic", "NanumGothic", "Noto Sans CJK KR"]:
        if font in inst:
            matplotlib.rc("font", family=font)
            break
    matplotlib.rcParams["axes.unicode_minus"] = False

    for var, unit in [("t2m", "℃"), ("tcc", "%p")]:
        g = sc[sc["var"] == var]
        if g.empty:
            continue
        fig, ax = plt.subplots(figsize=(9, 5))
        for model, gm in g.groupby("model"):
            curve = gm.groupby("step_h")["err"].apply(lambda e: e.abs().mean())
            ax.plot(curve.index, curve.values, "-o", ms=3, label=model)
        ax.set_xlabel("리드타임 (h)")
        ax.set_ylabel(f"MAE ({unit})")
        ax.set_title(f"{var} 리드타임별 MAE (전 도시 평균, n={len(g)})")
        ax.grid(alpha=0.3)
        ax.legend()
        fig.tight_layout()
        out_png = os.path.join(VERIF_DIR, f"mae_curve_{var}.png")
        fig.savefig(out_png, dpi=110)
        plt.close(fig)
        print(f"[report] 저장: {out_png}")


# ══════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("archive")
    a.add_argument("--csv", default=None, help="적재할 city_forecast.csv (생략 시 최신)")
    s = sub.add_parser("score")
    s.add_argument("--date", default=None, help="대상일 YYYY-MM-DD (KST, 기본 어제)")
    s.add_argument("--no-fetch", action="store_true", help="실황 API 수신 생략(캐시/기존 CSV만)")
    sub.add_parser("report")
    args = p.parse_args()

    if args.cmd == "archive":
        cmd_archive(args.csv)
    elif args.cmd == "score":
        cmd_score(args.date, fetch_obs=not args.no_fetch)
    elif args.cmd == "report":
        cmd_report()


if __name__ == "__main__":
    main()
