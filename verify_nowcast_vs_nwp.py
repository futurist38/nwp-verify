# -*- coding: utf-8 -*-
"""나우캐스트 vs 수치모델(NWP) — 같은 시각·같은 지점·같은 관측으로 운량 예측 대결.

왜 필요한가 (2026-08-26): 나우캐스트의 스킬은 지금까지 '지속성(현재 화면 유지)' 대비로만
쟀다. 지속성은 리드가 길어질수록 아주 약한 상대라, 그걸 이겼다고 +6h가 쓸 만하다는 증명이
못 된다. 긴 리드의 진짜 경쟁자는 NWP다 — 문헌도 위성 외삽이 NWP에 자리를 내주는 지점을
2.75~4.5h로 본다(Urbich 2018/2019). 그 교차점이 우리 자료에서 어디인지 직접 잰다.

방식:
  · 정답은 ASOS 목측 운량(%) — 두 예측이 같은 관측으로 채점된다
  · NWP는 verification/scores 에 이미 쌓인 값 중 **그 유효시각에 대해 우리가 실제로 보유한
    최단 리드**를 쓴다(실제 운영에서 손에 있던 최선). 사용된 리드는 결과에 함께 적는다
  · 나우캐스트는 유효시각 - 리드 시점에 발령해 같은 지점 격자값을 뽑는다

사용: python verify_nowcast_vs_nwp.py [--from 2026-08-13] [--to 2026-08-21]
산출: verification/nowcast_bench/vs_nwp.csv / vs_nwp.md
"""
import argparse
import datetime as dt
import glob
import os

import numpy as np
import pandas as pd

from config import VERIF_DIR
from nowcast_bench import city_pixels, OUT_DIR as BENCH_OUT

LEADS_H = [1, 2, 3, 4, 5, 6]
OUT_DIR = os.path.join(VERIF_DIR, "nowcast_bench")


def load_nwp(t0: dt.datetime, t1: dt.datetime) -> pd.DataFrame:
    df = pd.concat([pd.read_csv(f, parse_dates=["valid_kst"])
                    for f in glob.glob(os.path.join(VERIF_DIR, "scores", "*.csv"))])
    df = df[(df["var"] == "tcc") & df["obs"].notna() & df["fcst"].notna()]
    df = df[(df["valid_kst"] >= t0) & (df["valid_kst"] <= t1)]
    # 유효시각·도시·모델별로 우리가 보유한 최단 리드 (= 그 시점 손에 있던 최선)
    return df.loc[df.groupby(["valid_kst", "city", "model"])["step_h"].idxmin()]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="d0", default="2026-08-13")
    p.add_argument("--to", dest="d1", default="2026-08-21")
    p.add_argument("--tag", default="", help="산출 파일명 접미사(구간 분할 실행용)")
    args = p.parse_args()
    t0, t1 = pd.Timestamp(args.d0), pd.Timestamp(args.d1)

    nwp = load_nwp(t0, t1)
    if nwp.empty:
        raise SystemExit("NWP 검증 자료 없음")
    print(f"[vs] NWP {len(nwp)}행, 유효시각 {nwp.valid_kst.nunique()}개")

    from dl_infer import DLNowcaster
    d = DLNowcaster()
    cpx = city_pixels()

    # 필요한 발령시각 = 유효시각 - 리드 (KST → UTC)
    rows = []
    issues = sorted({v - pd.Timedelta(hours=h) for v in nwp.valid_kst.unique()
                     for h in LEADS_H})
    for n, iss_kst in enumerate(issues, 1):
        iss_utc = (iss_kst - pd.Timedelta(hours=9)).to_pydatetime()
        out = d.predict(iss_utc, [h * 60 for h in LEADS_H])
        if out is None:
            continue
        for h in LEADS_H:
            vt = iss_kst + pd.Timedelta(hours=h)
            sub = nwp[nwp.valid_kst == vt]
            if sub.empty:
                continue
            f = out[h * 60]
            for city, (stn, i, j) in cpx.items():
                s = sub[sub.city == city]
                if s.empty:
                    continue
                obs = float(s.iloc[0]["obs"])
                rows.append({"valid_kst": vt, "city": city, "lead_h": h,
                             "method": "나우캐스트", "fcst": float(f[i, j]),
                             "obs": obs, "step_h": h})
                for r in s.itertuples():
                    rows.append({"valid_kst": vt, "city": city, "lead_h": h,
                                 "method": r.model, "fcst": float(r.fcst),
                                 "obs": obs, "step_h": int(r.step_h)})
        if n % 20 == 0:
            print(f"[vs] {n}/{len(issues)} 발령")

    df = pd.DataFrame(rows)
    if df.empty:
        raise SystemExit("겹치는 표본 없음 — 기간/위성자료 확인")
    df["ae"] = (df["fcst"] - df["obs"]).abs()
    os.makedirs(OUT_DIR, exist_ok=True)
    df.to_csv(os.path.join(OUT_DIR, f"vs_nwp{args.tag}.csv"), index=False, encoding="utf-8-sig")

    mae = df.pivot_table(index="lead_h", columns="method", values="ae", aggfunc="mean")
    cnt = df.pivot_table(index="lead_h", columns="method", values="ae", aggfunc="size")
    step = df[df.method != "나우캐스트"].pivot_table(index="lead_h", columns="method",
                                                  values="step_h", aggfunc="median")
    lines = ["# 나우캐스트 vs 수치모델 — ASOS 운량(%) MAE", "",
             f"기간 {args.d0} ~ {args.d1} · 도시 {df.city.nunique()}곳 · 표본 {len(df):,}행", "",
             "낮을수록 좋음. NWP는 그 유효시각에 대해 우리가 보유한 최단 리드를 사용.", "",
             mae.round(1).to_markdown(), "",
             "## 표본 수", "", cnt.astype("Int64").to_markdown(), "",
             "## NWP가 실제로 쓴 리드(중앙값, 시간)", "", step.round(0).astype("Int64").to_markdown()]
    with open(os.path.join(OUT_DIR, f"vs_nwp{args.tag}.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(mae.round(1).to_string())
    print("\nNWP 실사용 리드(중앙값):")
    print(step.round(0).to_string())
    print(f"\n[vs] 리포트 → {os.path.join(OUT_DIR, 'vs_nwp.md')}")


if __name__ == "__main__":
    main()
