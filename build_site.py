# -*- coding: utf-8 -*-
"""
정적 웹 아카이브 빌더 (로드맵 ③).

output/YYYYMMDD/ 산출물을 사이트 폴더로 조립한다. 동적 서버 없음 — 전부 정적.

사이트 구조 (site_build/ = 배포 루트):
    index.html, app.js, style.css      ← site/ 정적 파일 복사
    manifest.json                      ← 날짜→모델→스텝→패널 트리 (뷰어의 유일한 진입점)
    archive/YYYYMMDD/*.png             ← 지도 패널·미티오그램 (보존 MAX_DAYS일)
    daily/YYYYMMDD.json                ← 도시별 예측 수치 (원수치)
    verif/summary.json, mae_curve_*.png, cases/*.md

사용:
    python build_site.py [--site-dir site_build]
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import shutil

import pandas as pd

from config import BASE_DIR, OUT_DIR, VERIF_DIR

MAX_DAYS = 90          # 지도 PNG 보존 일수 (셀룰러·저장소 용량 고려)
SITE_SRC = os.path.join(BASE_DIR, "site")

PNG_RE = re.compile(r"^(?P<model>[a-z]+)_(?P<run>\d{10})_f(?P<step>\d{3})_(?P<panel>\w+)\.png$")


def copy_outputs(site_dir: str):
    """output/YYYYMMDD → site/archive/YYYYMMDD (지도 패널 + 미티오그램), 기한 초과 삭제."""
    arch = os.path.join(site_dir, "archive")
    daily = os.path.join(site_dir, "daily")
    os.makedirs(arch, exist_ok=True)
    os.makedirs(daily, exist_ok=True)

    for day_dir in sorted(glob.glob(os.path.join(OUT_DIR, "????????"))):
        ymd = os.path.basename(day_dir)
        dst = os.path.join(arch, ymd)
        os.makedirs(dst, exist_ok=True)
        for sub in ("maps_ecmwf", "maps_gfs", "meteograms"):
            for png in glob.glob(os.path.join(day_dir, sub, "*.png")):
                target = os.path.join(dst, os.path.basename(png))
                if not os.path.exists(target) or os.path.getmtime(png) > os.path.getmtime(target):
                    shutil.copy2(png, target)
        csv = os.path.join(day_dir, "city_forecast.csv")
        if os.path.exists(csv):
            df = pd.read_csv(csv)
            with open(os.path.join(daily, f"{ymd}.json"), "w", encoding="utf-8") as f:
                json.dump({"columns": list(df.columns),
                           "rows": df.where(df.notna(), None).values.tolist()},
                          f, ensure_ascii=False)

    # 보존 기한 초과 정리 (지도만 — daily JSON·검증 자료는 전 기간 유지)
    cutoff = (dt.date.today() - dt.timedelta(days=MAX_DAYS)).strftime("%Y%m%d")
    removed = 0
    for d in glob.glob(os.path.join(arch, "????????")):
        if os.path.basename(d) < cutoff:
            shutil.rmtree(d)
            removed += 1
    if removed:
        print(f"[site] 보존기한({MAX_DAYS}일) 초과 {removed}일치 지도 삭제")


def copy_verif(site_dir: str):
    vd = os.path.join(site_dir, "verif")
    os.makedirs(os.path.join(vd, "cases"), exist_ok=True)
    for png in glob.glob(os.path.join(VERIF_DIR, "mae_curve_*.png")):
        shutil.copy2(png, vd)
    for md in glob.glob(os.path.join(VERIF_DIR, "cases", "*.md")):
        shutil.copy2(md, os.path.join(vd, "cases"))
    summ = os.path.join(VERIF_DIR, "scores_summary.csv")
    if os.path.exists(summ):
        df = pd.read_csv(summ)
        with open(os.path.join(vd, "summary.json"), "w", encoding="utf-8") as f:
            json.dump({"columns": list(df.columns),
                       "rows": df.where(df.notna(), None).values.tolist()},
                      f, ensure_ascii=False)


def export_verif_daily(site_dir: str) -> list[str]:
    """일별 검증표 JSON (관측 vs 모델별 예측·오차) — 메일에서 웹으로 이관(2026-08-20).
    구조: {var: {city: {obs: {h: v}, models: {m: {h: [fcst, err, step]}}}}}
    같은 유효시각에 여러 런이 있으면 최단 리드(최신 런)만."""
    out_dir = os.path.join(site_dir, "verif", "daily")
    os.makedirs(out_dir, exist_ok=True)
    dates = set()
    for f in glob.glob(os.path.join(VERIF_DIR, "scores", "*.csv")):
        sc = pd.read_csv(f, parse_dates=["valid_kst"])
        sc = sc[sc["var"].isin(["t2m", "tcc"])]
        for day, g in sc.groupby(sc["valid_kst"].dt.date):
            data = {}
            for r in g.itertuples():
                h = str(r.valid_kst.hour)
                city = data.setdefault(r.var, {}).setdefault(
                    r.city, {"obs": {}, "models": {}})
                if pd.notna(r.obs):
                    city["obs"][h] = float(r.obs)
                mdl = city["models"].setdefault(r.model, {})
                if h not in mdl or int(r.step_h) < mdl[h][2]:
                    mdl[h] = [None if pd.isna(r.fcst) else float(r.fcst),
                              None if pd.isna(r.err) else float(r.err),
                              int(r.step_h)]
            ymd = day.strftime("%Y%m%d")
            with open(os.path.join(out_dir, f"{ymd}.json"), "w", encoding="utf-8") as fp:
                json.dump(data, fp, ensure_ascii=False)
            dates.add(ymd)
    return sorted(dates)


def build_manifest(site_dir: str):
    """archive/ 를 스캔해 manifest.json 생성 — 파일명이 유일한 진실."""
    manifest = {"generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
                "max_days": MAX_DAYS, "dates": {}}
    for d in sorted(glob.glob(os.path.join(site_dir, "archive", "????????"))):
        ymd = os.path.basename(d)
        entry = {"models": {}, "meteograms": [], "daily_json": None}
        for fn in sorted(os.listdir(d)):
            m = PNG_RE.match(fn)
            if m:
                mdl = m["model"].upper()
                e = entry["models"].setdefault(
                    mdl, {"run": m["run"], "steps": [], "panels": []})
                # 최신 런만 남긴다 (하루 2회 배치로 런이 갱신될 수 있음)
                if m["run"] > e["run"]:
                    e.update({"run": m["run"], "steps": [], "panels": []})
                if m["run"] == e["run"]:
                    s = int(m["step"])
                    if s not in e["steps"]:
                        e["steps"].append(s)
                    if m["panel"] not in e["panels"]:
                        e["panels"].append(m["panel"])
            elif fn.startswith("meteogram_"):
                entry["meteograms"].append(fn)
        for e in entry["models"].values():
            e["steps"].sort()
        if os.path.exists(os.path.join(site_dir, "daily", f"{ymd}.json")):
            entry["daily_json"] = f"daily/{ymd}.json"
        if entry["models"] or entry["meteograms"]:
            manifest["dates"][ymd] = entry

    manifest["cases"] = sorted(
        os.path.basename(p) for p in
        glob.glob(os.path.join(site_dir, "verif", "cases", "*.md")))
    manifest["verif_dates"] = sorted(
        os.path.basename(p)[:-5] for p in
        glob.glob(os.path.join(site_dir, "verif", "daily", "*.json")))

    with open(os.path.join(site_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)
    print(f"[site] manifest: 날짜 {len(manifest['dates'])}건, 사례 {len(manifest['cases'])}건")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--site-dir", default=os.path.join(BASE_DIR, "site_build"))
    args = p.parse_args()

    os.makedirs(args.site_dir, exist_ok=True)
    # 정적 파일
    for fn in os.listdir(SITE_SRC):
        shutil.copy2(os.path.join(SITE_SRC, fn), args.site_dir)
    open(os.path.join(args.site_dir, ".nojekyll"), "w").close()

    copy_outputs(args.site_dir)
    copy_verif(args.site_dir)
    export_verif_daily(args.site_dir)
    build_manifest(args.site_dir)
    print(f"[site] 완료: {args.site_dir}")


if __name__ == "__main__":
    main()
