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

from config import BASE_DIR, OUT_DIR, VERIF_DIR, CITY_OBS_STN

KMAFCST_DATES: list[str] = []
METEO_DATES: list[str] = []
OBS_DATES: list[str] = []
FD_DATES: list[str] = []
HAS_MIDFCST = False    # export_midfcst 결과 (manifest 용)
MAX_DAYS = 14          # 모델 지도 보존 일수 (2026-09-08 사용자: 2주면 충분. 하루 ~40MB)
UPPER_MAX_DAYS = 7     # 고도별 기압장(925~200) 보존 일수 (하루 ~90MB — 2026-09-08 사용자: 7일, 그림 크기 유지)
UPPER_PANELS = {"p925", "p850", "p700", "p500", "p300", "p200"}   # sfc(지상장)는 일반 지도와 같이 MAX_DAYS
# 그림이 R2 에 있어도 최근 창은 site-data(github.io)에 같이 둔다 — 회사망이 r2.dev 를 막는다(2026-09-09 실측).
# 하루 최대 170MB(지상·상층 127 + 지도 42) → 지도 7일 + 지상·상층 3일 ≈ 700MB 로 Pages 1GB 안. 뷰어는 manifest.local_cut 으로 판단.
LOCAL_DAYS_MAPS = 7    # 일반 지도·위성 일사: 이 날수 안이면 site-data 에도 있다
LOCAL_DAYS_UPPER = 3   # 지상(sfc)·925~200: 이 날수 안이면 site-data 에도 있다


def local_cuts() -> tuple[str, str]:
    """(지도 창 시작일, 지상·상층 창 시작일) YYYYMMDD — publish_site.sh 의 복원·정리와 manifest 가 같은 값을 쓴다."""
    today = dt.date.today()
    return ((today - dt.timedelta(days=LOCAL_DAYS_MAPS - 1)).strftime("%Y%m%d"),
            (today - dt.timedelta(days=LOCAL_DAYS_UPPER - 1)).strftime("%Y%m%d"))
OBS_MAX_DAYS = 21      # 관측 지도 보존 일수 (1h×3변수 = 일 63장이라 별도 제한)
SITE_SRC = os.path.join(BASE_DIR, "site")

PNG_RE = re.compile(r"^(?P<model>[a-z]+)_(?P<run>\d{10})_f(?P<step>\d{3})_(?P<panel>\w+)\.webp$")
OBS_RE = re.compile(r"^obs_(?P<var>\w+)_(?P<hour>\d{2})\.webp$")


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
        for sub in ("maps_ecmwf", "maps_gfs", "maps_kim", "kmafcst", "fcstdiff", "satsw", "upper"):
            for png in glob.glob(os.path.join(day_dir, sub, "*.png")) + glob.glob(os.path.join(day_dir, sub, "city_upper_*.json")):
                # 무조건 복사 — site-data 복원본은 checkout 시각이 mtime으로 찍혀
                # "더 새것만 복사" 비교가 항상 지는 함정이 있다 (2026-08-20 실측:
                # 같은 파일명의 개선판 이미지가 배포에서 누락됨)
                shutil.copy2(png, os.path.join(dst, os.path.basename(png)))
        csv = os.path.join(day_dir, "city_forecast.csv")
        if os.path.exists(csv):
            df = pd.read_csv(csv)
            with open(os.path.join(daily, f"{ymd}.json"), "w", encoding="utf-8") as f:
                json.dump({"columns": list(df.columns),
                           "rows": df.where(df.notna(), None).values.tolist()},
                          f, ensure_ascii=False)

    # 보존 기한 초과 정리 (지도만 — daily JSON·검증 자료는 전 기간 유지)
    cutoff = (dt.date.today() - dt.timedelta(days=MAX_DAYS)).strftime("%Y%m%d")
    cutoff_obs = (dt.date.today() - dt.timedelta(days=OBS_MAX_DAYS)).strftime("%Y%m%d")
    cutoff_up = (dt.date.today() - dt.timedelta(days=UPPER_MAX_DAYS)).strftime("%Y%m%d")
    removed = n_obs = n_up = 0
    for d in glob.glob(os.path.join(arch, "????????")):
        ymd = os.path.basename(d)
        if ymd < cutoff:
            shutil.rmtree(d)
            removed += 1
            continue
        if ymd < cutoff_obs:
            for f in glob.glob(os.path.join(d, "obs_*.png")) + glob.glob(os.path.join(d, "obs_*.webp")):
                os.remove(f)
                n_obs += 1
        if ymd < cutoff_up:      # 고도별 기압장은 14일만 (용량)
            for f in glob.glob(os.path.join(d, "*_f???_*.*")):
                m = PNG_RE.match(os.path.basename(f)) or PNG_RE.match(os.path.basename(f)[:-4] + ".webp")
                if m and m["panel"] in UPPER_PANELS:
                    os.remove(f)
                    n_up += 1
    if removed or n_obs or n_up:
        print(f"[site] 보존기한 정리: 지도 {removed}일치, 관측 PNG {n_obs}장, 고도별 {n_up}장 삭제")


def copy_verif(site_dir: str):
    vd = os.path.join(site_dir, "verif")
    os.makedirs(os.path.join(vd, "cases"), exist_ok=True)
    for pat in ("mae_curve_*.png", "verifmap_*.png"):
        for png in glob.glob(os.path.join(VERIF_DIR, pat)):
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
        sc = sc[sc["var"].isin(["t2m", "tcc", "dswrf"])]   # dswrf(일사) 2026-09-06 추가
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


def copy_nowcast(site_dir: str) -> dict | None:
    """운영 나우캐스트(최신 발령 표출 + 최근 7일 skill 요약) → site/nowcast/.
    산출이 없으면 None — app.js 는 manifest.nowcast 부재 시 탭을 숨긴다."""
    src = os.path.join(OUT_DIR, "nowcast", "latest")
    issue_txt = os.path.join(src, "issue.txt")
    if not os.path.exists(issue_txt):
        # 이번 런에서 산출이 없으면(API 혼잡 등) 직전 발행분을 그대로 유지 —
        # 일시적 실패로 탭이 사라지지 않게. 화면의 상대시간이 노후를 드러낸다.
        prev = os.path.join(site_dir, "manifest.json")
        if os.path.exists(prev):
            try:
                old = json.load(open(prev, encoding="utf-8")).get("nowcast")
                if old and os.path.exists(os.path.join(site_dir, "nowcast")):
                    print("[site] 나우캐스트: 신규 산출 없음 — 직전 발행분 유지")
                    return old
            except Exception:
                pass
        return None
    nd = os.path.join(site_dir, "nowcast")
    os.makedirs(nd, exist_ok=True)
    for pat in ("*.png", "*.webp"):   # 미러 — 리드 축소 시 옛 지도 잔존 방지
        for old in glob.glob(os.path.join(nd, pat)):
            os.remove(old)
    for png in glob.glob(os.path.join(src, "*.png")):
        shutil.copy2(png, nd)   # 무조건 복사(mtime 함정 — copy_outputs 참조)

    # 과거 검증 패널은 **쌓아 간다** — 통째로 미러하면 러너(그날 산출만 있음)에서
    # 배포본이 매번 지워진다. 새 것만 더하고 기한(7일)만 정리한다.
    # 7일 뒤에는 그림을 지우고 검증 채점표(텍스트)만 남긴다 (2026-08-28 사용자 지시).
    adst = os.path.join(nd, "archive")
    os.makedirs(adst, exist_ok=True)
    for png in glob.glob(os.path.join(OUT_DIR, "nowcast", "archive", "*.png")):
        shutil.copy2(png, adst)
    acut = (dt.date.today() - dt.timedelta(days=7)).strftime("%Y%m%d%H")
    gone = 0
    for f in glob.glob(os.path.join(adst, "*.*")):
        stem = os.path.splitext(os.path.basename(f))[0]
        if stem.isdigit() and stem < acut:
            os.remove(f)
            gone += 1
    if gone:
        print(f"[site] 검증패널 보관 정리: {gone}장 삭제(7일 경과)")

    all_leads = sorted(int(re.match(r"map_(\d+)h", os.path.basename(p)).group(1))
                       for p in glob.glob(os.path.join(nd, "map_*h.png")))
    info = {"issue": open(issue_txt).read().strip(), "skill": {}, "n_issues": 0,
            "leads": [h for h in all_leads if h > 0],   # 0=현재 관측(별도 표출)
            "has_now": 0 in all_leads,
            "has_verify": os.path.exists(os.path.join(nd, "verify.png")),
            # 확장자는 to_webp 이후 .webp 가 된다 — .png 만 찾으면 목록이 비어 과거가
            # 통째로 사라진다 (2026-08-27 실측: past 0건)
            "past": sorted({os.path.splitext(os.path.basename(p))[0]
                            for p in glob.glob(os.path.join(nd, "archive", "*.png"))
                            + glob.glob(os.path.join(nd, "archive", "*.webp"))})}

    frames = [pd.read_csv(f, parse_dates=["issue_utc"])
              for f in glob.glob(os.path.join(VERIF_DIR, "nowcast", "*.csv"))]
    if frames:
        df = pd.concat(frames, ignore_index=True)
        cut = dt.datetime.utcnow() - dt.timedelta(days=7)
        df = df[df["issue_utc"] >= cut]
        if len(df):
            piv = df.pivot_table(index="lead_min", columns="method",
                                 values="mae", aggfunc="mean")
            if "M0" in piv.columns and "M4" in piv.columns:
                sk = (1 - piv["M4"] / piv["M0"]) * 100
                max_lead = max(info["leads"], default=3) * 60
                info["skill"] = {str(int(k)): round(float(v), 1)
                                 for k, v in sk.items()
                                 if pd.notna(v) and int(k) <= max_lead}
                info["n_issues"] = int(df[df["method"] == "M4"]["issue_utc"].nunique())
    return info


KMAF_CITIES = ["서울", "대전", "대구", "부산", "광주", "강릉"]
KMAF_PREV_H, KMAF_DAY_H = (11, 17), (5, 11, 17)


def export_kmafcst(site_dir: str) -> list[str]:
    """예보-관측 비교를 **이미지 대신 데이터**로 내보낸다 (2026-08-26 사용자 제안).

    같은 내용이 WebP 5장 347KB → JSON 약 11KB (30배). 게다가 마우스로 값을 읽을 수 있고
    폰트·글리프 문제에서도 자유롭다. 예보 캐시(verification/kmafcst)는 이미 커밋돼 있어
    새로 받을 것도 없다.

    구조: {cities, t0(YYYYMMDDHH), hours, obs:{city:[...]}, fcst:{발표:{city:[...]}}}
          모든 계열을 t0 기준 1시간 격자에 정렬 — 없는 값은 null.
    """
    out_dir = os.path.join(site_dir, "kmafcst")
    os.makedirs(out_dir, exist_ok=True)
    dates = []
    obs_cache: dict[str, pd.DataFrame] = {}

    for src in sorted(glob.glob(os.path.join(VERIF_DIR, "kmafcst", "????????.json"))):
        ymd = os.path.basename(src)[:-5]
        day = dt.datetime.strptime(ymd, "%Y%m%d")
        prev = day - dt.timedelta(days=1)
        want = [f"{prev:%Y%m%d}{h:02d}" for h in KMAF_PREV_H] +                [f"{ymd}{h:02d}" for h in KMAF_DAY_H]
        cache = json.load(open(src, encoding="utf-8"))
        issues = [b for b in want if b in cache and cache[b]]
        if not issues:
            continue

        t0 = dt.datetime.strptime(issues[0], "%Y%m%d%H") - dt.timedelta(hours=6)
        # 당일 발표(05·11·17시)는 뷰어가 **내일 23시**까지 보여준다(2026-09-01 사용자 요청).
        # 격자를 그 시각까지 깔아두지 않으면 자료 끝에서 잘린다.
        t1 = max(dt.datetime.strptime(issues[-1], "%Y%m%d%H") + dt.timedelta(hours=24),
                 day + dt.timedelta(days=1, hours=23))
        hours = int((t1 - t0).total_seconds() // 3600) + 1
        grid = [t0 + dt.timedelta(hours=i) for i in range(hours)]
        keys = [f"{g:%Y%m%d%H}" for g in grid]

        data = {"cities": KMAF_CITIES, "t0": f"{t0:%Y%m%d%H}", "hours": hours,
                "fcst": {}, "obs": {}, "sky": {}, "pty": {}, "pop": {}, "obs_ca": {}}
        for b in issues:
            data["fcst"][b] = {c: [cache[b].get(c, {}).get(k) for k in keys]
                               for c in KMAF_CITIES}
            # 하늘상태(SKY 1맑음·3구름많음·4흐림)·강수형태(PTY 0없음 1비 2비/눈 3눈 4소나기)·
            # 강수확률(POP %) — 2026-09-06 부터 캐시에 "도시#카테고리" 키로 함께 저장
            for cat, slot in (("SKY", "sky"), ("PTY", "pty"), ("POP", "pop")):
                per_city = {c: cache[b].get(f"{c}#{cat}") for c in KMAF_CITIES}
                if any(per_city.values()):
                    data[slot][b] = {c: [None if not v else v.get(k) for k in keys]
                                     for c, v in per_city.items()}

        for mm in {f"{g:%Y-%m}" for g in grid}:
            if mm not in obs_cache:
                fp = os.path.join(VERIF_DIR, "obs", f"{mm}.csv")
                obs_cache[mm] = (pd.read_csv(fp, parse_dates=["TM"])
                                 if os.path.exists(fp) else pd.DataFrame())
        frames = [obs_cache[mm] for mm in {f"{g:%Y-%m}" for g in grid}
                  if len(obs_cache[mm])]
        if frames:
            ob = pd.concat(frames, ignore_index=True)
            ob["key"] = ob["TM"].dt.strftime("%Y%m%d%H")
            for c in KMAF_CITIES:
                stn = CITY_OBS_STN.get(c)
                ser = ob[ob["STN"] == stn].set_index("key")["TA"] if stn else pd.Series(dtype=float)
                data["obs"][c] = [None if k not in ser.index or pd.isna(ser[k])
                                  else round(float(ser[k]), 1) for k in keys]
                # 실측 하늘(전운량 십분위) — 예보 SKY 띠와 나란히 (2026-09-06)
                if stn and "CA_TOT" in ob.columns:
                    ca = ob[ob["STN"] == stn].set_index("key")["CA_TOT"]
                    data["obs_ca"][c] = [None if k not in ca.index or pd.isna(ca[k])
                                         else int(ca[k]) for k in keys]

        # 발표 수가 같으면 관측이 더 찬 쪽이 새것
        _write_unless_older(os.path.join(out_dir, f"{ymd}.json"), data,
                            lambda d: (len(d["fcst"]), _n_values(d["obs"])), "예보-관측")
    return _json_dates(out_dir, MAX_DAYS)


def export_meteo(site_dir: str) -> list[str]:
    """미티오그램을 이미지 대신 데이터로 (2026-08-26). city_forecast.csv 가 이미 도시·모델·
    시각별 기온/운량을 담고 있어 새로 계산할 것이 없다. 모델별 최신 런만 3시간 격자에 정렬.

    구조: {cities, models, runs:{model:run}, t0(YYYYMMDDHH), steps, 
           series:{model:{city:{t2m:[...], tcc:[...]}}}}
    """
    out_dir = os.path.join(site_dir, "meteo")
    os.makedirs(out_dir, exist_ok=True)
    dates = []
    # 검증 폴더(커밋 대상) 우선 — 러너의 output/ 은 그날 것만 있어 과거가 사라진다
    srcs = {os.path.basename(f)[:-4]: f
            for f in glob.glob(os.path.join(VERIF_DIR, "city_forecast", "????????.csv"))}
    for day_dir in sorted(glob.glob(os.path.join(OUT_DIR, "????????"))):
        c = os.path.join(day_dir, "city_forecast.csv")
        if os.path.exists(c):
            srcs.setdefault(os.path.basename(day_dir), c)

    # 이전 런(런 간 흔들림 띠) 은 전 런이 쌓이는 예측 아카이브에서 (verify.py archive)
    arch_cache: dict[str, pd.DataFrame] = {}

    def archive_month(ym: str) -> pd.DataFrame:
        if ym not in arch_cache:
            fp = os.path.join(VERIF_DIR, "forecast", f"{ym}.csv")
            arch_cache[ym] = pd.read_csv(fp) if os.path.exists(fp) else pd.DataFrame()
        return arch_cache[ym]

    def _grid_series(sub: pd.DataFrame, idx: dict, n: int, col: str, nd: int):
        arr = [None] * n
        if col not in sub.columns:
            return arr
        for r in sub.itertuples():
            i = idx.get(r.valid)
            v = getattr(r, col)
            if i is not None and pd.notna(v):
                arr[i] = round(float(v), nd)
        return arr

    for ymd, csv in sorted(srcs.items()):
        df = pd.read_csv(csv)
        df = df[df["city"].isin(KMAF_CITIES)]
        if df.empty:
            continue
        df["valid"] = pd.to_datetime(df["valid_kst"])
        # 모델별 최신 런만
        latest = df.groupby("model")["run_utc"].max()
        df = df[[r.run_utc == latest[r.model] for r in df.itertuples()]]

        grid = pd.date_range(df["valid"].min(), df["valid"].max(), freq="3h")
        idx = {t: i for i, t in enumerate(grid)}
        n = len(grid)
        data = {"cities": KMAF_CITIES, "models": sorted(latest.index),
                "runs": {m: pd.Timestamp(latest[m]).strftime("%Y%m%d%H") for m in latest.index},
                "t0": grid[0].strftime("%Y%m%d%H"), "steps": n, "series": {},
                "wins": {}, "prev": {}}
        for m in data["models"]:
            data["series"][m] = {}
            sub_m = df[df["model"] == m]
            # 창 길이(일사·강수) — 도시 공통. 없으면(구 자료) null
            data["wins"][m] = _grid_series(sub_m[sub_m["city"] == KMAF_CITIES[0]], idx, n, "win_h", 0)
            for c in KMAF_CITIES:
                sub = sub_m[sub_m["city"] == c]
                data["series"][m][c] = {"t2m": _grid_series(sub, idx, n, "t2m_C", 1),
                                        "tcc": _grid_series(sub, idx, n, "tcc_pct", 0),
                                        "dswrf": _grid_series(sub, idx, n, "dswrf_avg_Wm2", 0),
                                        "tp": _grid_series(sub, idx, n, "tp_mm", 1)}

            # 이전 런 최대 4개 (2026-09-06, 런 겹치기) — 같은 유효시각 격자에 정렬, 기온·운량만
            run_ts = pd.Timestamp(latest[m])
            months = {(run_ts - pd.Timedelta(days=d)).strftime("%Y-%m") for d in range(0, 4)}
            arch = pd.concat([archive_month(ym) for ym in sorted(months)], ignore_index=True) \
                if months else pd.DataFrame()
            if not arch.empty:
                arch = arch[(arch["model"] == m) & (arch["city"].isin(KMAF_CITIES))].copy()
                # 아카이브 run_utc 는 "2026-09-04"(자정)·"… 12:00:00" 형식 혼합 (실측) → mixed 파싱 후 통일
                arch["run_utc"] = pd.to_datetime(arch["run_utc"], format="mixed").dt.strftime("%Y-%m-%d %H:%M")
                arch = arch[pd.to_datetime(arch["run_utc"]) < run_ts]
                prev_runs = sorted(arch["run_utc"].unique())[-4:]
                if prev_runs:
                    arch = arch[arch["run_utc"].isin(prev_runs)].copy()
                    arch["valid"] = pd.to_datetime(arch["valid_kst"])
                    data["prev"][m] = {}
                    for ru in prev_runs:
                        key = pd.Timestamp(ru).strftime("%Y%m%d%H")
                        g = arch[arch["run_utc"] == ru]
                        data["prev"][m][key] = {
                            c: {"t2m": _grid_series(g[g["city"] == c], idx, n, "t2m_C", 1),
                                "tcc": _grid_series(g[g["city"] == c], idx, n, "tcc_pct", 0)}
                            for c in KMAF_CITIES}

        # (앙상블 요약 부착은 2026-09-06 사용자 결정으로 보류 — fetch_ens.py 산출이 있으면 여기서 붙일 수 있다)
        with open(os.path.join(out_dir, f"{ymd}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    return _json_dates(out_dir, MAX_DAYS)


def export_midfcst(site_dir: str) -> bool:
    """중기예보 기온(D+3~D+10 최저·최고, kma_midfcst.py 캐시) → site/midfcst/index.json (2026-09-06).

    최근 21일 발표분과, 검증용 실측 일 최고·최저(ASOS 시간값 기반)를 한 파일에.
    구조: {issues:[tmfc...], cities:[...], fcst:{tmfc:{city:{ymd:[min,max,min_l,min_h,max_l,max_h]}}},
           obs:{city:{ymd:[tmax,tmin]}}}"""
    src = sorted(glob.glob(os.path.join(VERIF_DIR, "midfcst", "??????????.json")))
    if not src:
        return False
    cut = (dt.date.today() - dt.timedelta(days=21)).strftime("%Y%m%d")
    src = [f for f in src if os.path.basename(f)[:8] >= cut]
    out = {"issues": [], "cities": [], "fcst": {}, "obs": {}}
    cities: set[str] = set()
    for f in src:
        tmfc = os.path.basename(f)[:-5]
        d = json.load(open(f, encoding="utf-8"))
        out["issues"].append(tmfc)
        out["fcst"][tmfc] = {}
        for c, days in d.items():
            cities.add(c)
            out["fcst"][tmfc][c] = {ymd: [v.get("min"), v.get("max"), v.get("min_l"), v.get("min_h"),
                                          v.get("max_l"), v.get("max_h")] for ymd, v in days.items()}
    out["cities"] = [c for c in ("서울", "인천", "수원", "대전", "대구", "광주", "전주", "부산", "강릉", "제주")
                     if c in cities]
    # 실측 일 극값 (시간값 기반 — 정시 사이 극값은 놓친다; 표출에 명시)
    months = sorted({f"{(dt.date.today() - dt.timedelta(days=k)):%Y-%m}" for k in (0, 21, 35)})
    frames = [pd.read_csv(os.path.join(VERIF_DIR, "obs", f"{mm}.csv"), parse_dates=["TM"])
              for mm in months if os.path.exists(os.path.join(VERIF_DIR, "obs", f"{mm}.csv"))]
    if frames:
        ob = pd.concat(frames, ignore_index=True)
        ob = ob[ob["TM"].dt.strftime("%Y%m%d") >= (dt.date.today() - dt.timedelta(days=35)).strftime("%Y%m%d")]
        ob["ymd"] = ob["TM"].dt.strftime("%Y%m%d")
        for c in out["cities"]:
            stn = CITY_OBS_STN.get(c)
            if not stn:
                continue
            g = ob[ob["STN"] == stn].groupby("ymd")["TA"].agg(["max", "min", "count"])
            out["obs"][c] = {ymd: [round(float(r["max"]), 1), round(float(r["min"]), 1)]
                             for ymd, r in g.iterrows() if r["count"] >= 20}
    od = os.path.join(site_dir, "midfcst")
    os.makedirs(od, exist_ok=True)
    with open(os.path.join(od, "index.json"), "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, separators=(",", ":"))
    return True


def _n_values(obj) -> int:
    """JSON 트리의 숫자 잎 개수 — '자료가 얼마나 찼나' 의 단조 척도."""
    if isinstance(obj, dict):
        return sum(_n_values(v) for v in obj.values())
    if isinstance(obj, list):
        return sum(_n_values(v) for v in obj)
    return 1 if isinstance(obj, (int, float)) and not isinstance(obj, bool) else 0


def _write_unless_older(path: str, data: dict, key, label: str) -> bool:
    """무회귀 가드 (2026-09-06): 배포본보다 **덜 찬** 파일은 쓰지 않는다.

    러너마다 관측 CSV 의 시점이 다르다 — daily 는 시작 시각(예: 06:12)의 관측을 종료
    시각(07:40)에 발행하는데, 그 사이 obs-hourly 가 07:25 관측을 이미 올렸다면 daily 의
    발행이 사이트를 한 시간 뒤로 되돌린다. 두 워크플로가 서로 기다리지 않게 된 뒤로는
    (tools/publish_site.sh) 이 가드가 순서를 보장하는 유일한 장치다.
    key(data) 는 클수록 새것인 비교 가능한 값(정수 또는 튜플)."""
    new = key(data)
    if os.path.exists(path):
        try:
            old = key(json.load(open(path, encoding="utf-8")))
        except Exception:
            old = None
        if old is not None and new < old:
            print(f"[site] {label} {os.path.basename(path)}: 배포본이 더 참({old} > {new}) — 유지")
            return False
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    return True


def _json_dates(out_dir: str, keep_days: int) -> list[str]:
    """내보낸 JSON 폴더에서 날짜 목록을 만든다 + 보존기한 정리.

    러너는 매번 새로 시작하므로 output/ 에는 그날 산출만 있다. 목록을 '이번에 만든 것'으로
    잡으면 과거 날짜가 통째로 사라진다 (2026-08-27 실측: 미티오그램이 0건이 됨).
    site-data 에서 복원된 파일까지 함께 세어야 한다."""
    cut = (dt.date.today() - dt.timedelta(days=keep_days)).strftime("%Y%m%d")
    out = []
    for f in sorted(glob.glob(os.path.join(out_dir, "????????.json"))):
        ymd = os.path.basename(f)[:-5]
        if not ymd.isdigit():      # stations.json 등 8글자 비날짜 파일 제외
            continue
        if ymd < cut:
            os.remove(f)
        else:
            out.append(ymd)
    return out


def export_obs(site_dir: str) -> list[str]:
    """관측 실황을 이미지 대신 데이터로 (2026-08-27 사용자 확정 A안).

    96지점을 보간해 면으로 칠하던 그림(WebP 63장 2.3MB/일)을, 지점 값 자체(36KB/일)로
    바꾼다. 64배 작고 **모든 지점의 값을 마우스로 읽을 수 있다** — 지금은 6개 도시만
    숫자가 보였다. 지점 사이는 원래 관측이 없는 구간이라 점 표출이 더 정직하기도 하다.

    산출: site/obs/stations.json (지점·색눈금, 1회) · site/obs/{YYYYMMDD}.json (일별 값)
    """
    import matplotlib as mpl
    from plot_obsmap import VARS, feel_temp

    out_dir = os.path.join(site_dir, "obs")
    os.makedirs(out_dir, exist_ok=True)
    bm = json.load(open(os.path.join(SITE_SRC, "basemap.json"), encoding="utf-8"))
    pj, view = bm["proj"], bm["view"]

    from pyproj import CRS, Transformer
    lcc = CRS.from_proj4("+proj=lcc +lat_1=30 +lat_2=60 +lat_0=36 +lon_0=127.5 "
                         "+x_0=0 +y_0=0 +ellps=WGS84")
    tr = Transformer.from_crs(CRS.from_epsg(4326), lcc, always_xy=True)

    st = pd.read_csv(os.path.join(VERIF_DIR, "obs", "stations.csv"))
    sx, sy = tr.transform(st["lon"].values, st["lat"].values)
    st["vx"] = (sx - pj["x0"]) / pj["span"] * view
    st["vy"] = (pj["y1"] - sy) / pj["span"] * view

    scales = {}
    for k, (_col, cmap, vmin, vmax, label, unit) in VARS.items():
        m = mpl.colormaps[cmap]   # matplotlib 3.9+: cm.get_cmap 제거됨
        scales[k] = {"vmin": vmin, "vmax": vmax, "label": label, "unit": unit,
                     "colors": ["#%02x%02x%02x" % tuple(int(c * 255) for c in m(i / 31)[:3])
                                for i in range(32)]}
    with open(os.path.join(out_dir, "stations.json"), "w", encoding="utf-8") as f:
        # 대표 6도시는 지도에 값을 함께 적는다(L=1) — 나머지는 마우스로 확인
        label_stn = {CITY_OBS_STN[c] for c in
                     ("서울", "대전", "대구", "부산", "광주", "강릉")
                     if CITY_OBS_STN.get(c)}
        json.dump({"stations": [{"s": int(r.STN), "n": r.name_,
                                 "x": round(r.vx, 1), "y": round(r.vy, 1),
                                 "L": 1 if int(r.STN) in label_stn else 0}
                                for r in st.rename(columns={"name": "name_"}).itertuples()],
                   "scales": scales}, f, ensure_ascii=False, separators=(",", ":"))

    # 자체 산출 평년(1991~2020, tools/build_normals.py) — 있으면 날짜별 JSON 에 그날 값만 싣는다
    normals: dict[tuple[int, str], list] = {}
    nrm_path = os.path.join(VERIF_DIR, "normals_daily.csv")
    if os.path.exists(nrm_path):
        nd = pd.read_csv(nrm_path, dtype={"mmdd": str})
        for r in nd.itertuples():
            normals[(int(r.stn), r.mmdd)] = [None if pd.isna(v) else round(float(v), 1)
                                             for v in (r.tavg, r.tmax, r.tmin)]

    dates = []
    cutoff = (dt.date.today() - dt.timedelta(days=OBS_MAX_DAYS)).strftime("%Y%m%d")
    for src in sorted(glob.glob(os.path.join(VERIF_DIR, "obs", "????-??.csv"))):
        df = pd.read_csv(src, parse_dates=["TM"])
        if df.empty:
            continue
        df["FEEL"] = feel_temp(df["TA"], df["HM"], df["WS"])
        for day, g in df.groupby(df["TM"].dt.date):
            ymd = day.strftime("%Y%m%d")
            if ymd < cutoff:
                continue
            data = {"vars": {}}
            for k, (col, *_rest) in VARS.items():
                if col not in g.columns:
                    continue
                piv = g.pivot_table(index="STN", columns=g["TM"].dt.hour,
                                    values=col, aggfunc="first").reindex(columns=range(24))
                data["vars"][k] = {str(int(s)): [None if pd.isna(v) else round(float(v), 1)
                                                 for v in row]
                                   for s, row in piv.iterrows()}
            # 일 최고·최저(시간값 기반 — 정시 사이의 극값은 놓치므로 참값보다 약간 안쪽) + 평년
            # (2026-09-06, 평년편차 지도용). 관측이 다 쌓이기 전(당일)에는 '지금까지의' 극값.
            agg = g.groupby("STN")["TA"].agg(["max", "min", "count"])
            data["daily"] = {str(int(s)): [None if pd.isna(r["max"]) else round(float(r["max"]), 1),
                                           None if pd.isna(r["min"]) else round(float(r["min"]), 1),
                                           int(r["count"])]
                             for s, r in agg.iterrows()}
            if normals:
                mmdd = ymd[4:]
                data["normals"] = {str(s): normals[(int(s), mmdd)] for s in agg.index
                                   if (int(s), mmdd) in normals}
            _write_unless_older(os.path.join(out_dir, f"{ymd}.json"), data,
                                lambda d: _n_values(d["vars"]), "관측")
    return _json_dates(out_dir, OBS_MAX_DAYS)


def export_fcstdiff(site_dir: str) -> list[str]:
    """예보 변화도 지점값으로 (2026-08-27). 이미지 2장 대신 JSON 한 개(~2KB)."""
    out_dir = os.path.join(site_dir, "fcstdiff")
    os.makedirs(out_dir, exist_ok=True)
    for src in glob.glob(os.path.join(VERIF_DIR, "fcstdiff_data", "????????.json")):
        shutil.copy2(src, os.path.join(out_dir, os.path.basename(src)))
    return _json_dates(out_dir, MAX_DAYS)


def prune_kmafcst(site_dir: str):
    """예보-관측 그림 전량 제거 — 이제 사이트가 JSON으로 직접 그린다(2026-08-26).
    이미 배포된 과거분을 걷어내기 위한 정리 단계."""
    n = 0
    for pat in ("kmafcst_*.*", "obs_*.*", "meteogram_*.*", "fcstdiff_*.*", "*_dswrf.*"):
        for f in glob.glob(os.path.join(site_dir, "archive", "????????", pat)):
            os.remove(f)
            n += 1
    if n:
        print(f"[site] 이미지 정리: {n}장 삭제(예보-관측·관측·미티오그램은 데이터 표출로 대체)")


def to_webp(site_dir: str):
    """아카이브 이미지를 WebP로 변환 — PNG 대비 약 1/5 (실측: 모델지도 290KB→54KB).

    GitHub Pages 게시 상한이 1GB인데 PNG로는 하루 40~57MB가 쌓여 3주면 초과한다
    (2026-08-26 실측: 13일치 493MB). 이미 배포된 PNG도 여기서 함께 변환된다.
    verif/ 는 1MB 남짓이라 손대지 않는다."""
    from PIL import Image
    n = saved = 0
    for root in (os.path.join(site_dir, "archive"), os.path.join(site_dir, "nowcast")):
        for png in glob.glob(os.path.join(root, "**", "*.png"), recursive=True):
            webp = png[:-4] + ".webp"
            try:
                before = os.path.getsize(png)
                Image.open(png).convert("RGB").save(webp, format="WEBP",
                                                    quality=82, method=4)
                saved += before - os.path.getsize(webp)
                os.remove(png)
                n += 1
            except Exception as e:
                print(f"[site] WebP 변환 실패 {os.path.basename(png)}: {e}")
    if n:
        print(f"[site] WebP 변환 {n}장 — {saved / 2**20:.0f}MB 절감")


def build_manifest(site_dir: str, nowcast: dict | None = None):
    """archive/ 를 스캔해 manifest.json 생성 — 파일명이 유일한 진실."""
    manifest = {"generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
                "max_days": MAX_DAYS, "dates": {}}
    if nowcast:
        manifest["nowcast"] = nowcast
    # 그림이 R2 에 있으면(2026-09-08 이관) 러너의 archive/ 에는 이번 산출만 있다 → R2 목록(R2_LISTING,
    # `rclone lsf -R --files-only` 결과: "YYYYMMDD/파일명")과 합쳐 스캔한다. 파일명이 유일한 진실인 건 같다.
    files: dict[str, set] = {}
    for d in glob.glob(os.path.join(site_dir, "archive", "????????")):
        files.setdefault(os.path.basename(d), set()).update(os.listdir(d))
    listing = os.environ.get("R2_LISTING")
    if listing and os.path.exists(listing):
        cut = (dt.date.today() - dt.timedelta(days=MAX_DAYS)).strftime("%Y%m%d")
        n_remote = 0
        for line in open(listing, encoding="utf-8"):
            line = line.strip()
            if "/" not in line:
                continue
            ymd, fn = line.split("/", 1)
            if len(ymd) == 8 and ymd.isdigit() and ymd >= cut:
                files.setdefault(ymd, set()).add(fn); n_remote += 1
        print(f"[site] R2 목록 병합: {n_remote}개")
    if os.environ.get("IMG_BASE"):
        manifest["img_base"] = os.environ["IMG_BASE"].rstrip("/")
        cm, cu = local_cuts()          # 이 날짜부터는 site-data 에도 있다(뷰어가 R2 대신 사이트 자체 경로를 쓴다)
        manifest["local_cut"] = {"maps": cm, "upper": cu}
    for ymd in sorted(files):
        entry = {"models": {}, "meteograms": [], "daily_json": None, "obs": {}}
        for fn in sorted(files[ymd]):
            mo = OBS_RE.match(fn)
            if mo:
                entry["obs"].setdefault(mo["var"], []).append(int(mo["hour"]))
                continue
            m = PNG_RE.match(fn)
            if m and m["panel"] == "dswrf":
                continue            # 일사 지도는 표출 제외 (2026-09-06 사용자 결정) — 남은 파일은 prune 에서 삭제
            if m:
                mdl = m["model"].upper()
                e = entry["models"].setdefault(mdl, {"runs": {}, "latest": None})
                # 런별로 전부 보존 (2026-08-21 런 선택 기능 — 하루 2회 배치가 축적)
                r = e["runs"].setdefault(m["run"], {"steps": [], "panels": [], "psteps": {}})
                s = int(m["step"])
                if s not in r["steps"]:
                    r["steps"].append(s)
                if m["panel"] not in r["panels"]:
                    r["panels"].append(m["panel"])
                r["psteps"].setdefault(m["panel"], []).append(s)
            elif fn.startswith("meteogram_"):
                entry["meteograms"].append(fn)
            elif fn.startswith("fcstdiff_"):
                entry.setdefault("fcstdiff", []).append(fn)
            elif fn.startswith("satsw_"):          # 위성 일사 일적산 (2026-09-06)
                entry.setdefault("satsw", []).append(fn)
            elif fn.startswith("kmafcst_"):
                mk = re.match(r"^kmafcst_(\d{10})\.webp$", fn)
                if mk:
                    entry.setdefault("kmafcst", []).append(mk.group(1))
        for e in entry["models"].values():
            for r in e["runs"].values():
                r["steps"].sort()
                for k in r["psteps"]:
                    r["psteps"][k].sort()
            e["latest"] = max(e["runs"])
        if os.path.exists(os.path.join(site_dir, "daily", f"{ymd}.json")):
            entry["daily_json"] = f"daily/{ymd}.json"
        if entry["models"] or entry["meteograms"] or entry["obs"] or entry.get("satsw"):
            manifest["dates"][ymd] = entry

    manifest["cases"] = sorted(
        os.path.basename(p) for p in
        glob.glob(os.path.join(site_dir, "verif", "cases", "*.md")))
    manifest["kmafcst_dates"] = KMAFCST_DATES
    manifest["meteo_dates"] = METEO_DATES
    manifest["obs_dates"] = OBS_DATES
    manifest["fd_dates"] = FD_DATES
    manifest["midfcst"] = bool(HAS_MIDFCST)          # 2026-09-06 중기예보 섹션
    manifest["normals"] = os.path.exists(os.path.join(VERIF_DIR, "normals_daily.csv"))
    manifest["verif_dates"] = sorted(
        os.path.basename(p)[:-5] for p in
        glob.glob(os.path.join(site_dir, "verif", "daily", "*.json")))

    with open(os.path.join(site_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)
    print(f"[site] manifest: 날짜 {len(manifest['dates'])}건, 사례 {len(manifest['cases'])}건")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--site-dir", default=os.path.join(BASE_DIR, "site_build"))
    p.add_argument("--hourly", action="store_true",
                   help="시간별 잡 모드: 관측·예보-관측·나우캐스트만 갱신하고 daily 소유물"
                        "(모델 지도·미티오그램·검증·예보변화)은 배포본을 그대로 둔다")
    args = p.parse_args()

    os.makedirs(args.site_dir, exist_ok=True)
    # 정적 파일
    for fn in os.listdir(SITE_SRC):
        shutil.copy2(os.path.join(SITE_SRC, fn), args.site_dir)
    open(os.path.join(args.site_dir, ".nojekyll"), "w").close()

    global KMAFCST_DATES, METEO_DATES, OBS_DATES, FD_DATES, HAS_MIDFCST
    if args.hourly:
        # obs-hourly 러너의 checkout 은 daily 가 마지막으로 커밋한 검증 자료라 배포본보다
        # 오래됐을 수 있다(daily 커밋→발행 사이에 끼어든 경우). 그걸로 verif/·meteo/ 를
        # 다시 쓰면 검증 탭이 하루 뒤로 간다 → daily 소유물은 목록만 세고 손대지 않는다.
        METEO_DATES = _json_dates(os.path.join(args.site_dir, "meteo"), MAX_DAYS)
        FD_DATES = _json_dates(os.path.join(args.site_dir, "fcstdiff"), MAX_DAYS)
        HAS_MIDFCST = os.path.exists(os.path.join(args.site_dir, "midfcst", "index.json"))
    else:
        copy_outputs(args.site_dir)
        copy_verif(args.site_dir)
        export_verif_daily(args.site_dir)
        METEO_DATES = export_meteo(args.site_dir)
        FD_DATES = export_fcstdiff(args.site_dir)
        HAS_MIDFCST = export_midfcst(args.site_dir)
    KMAFCST_DATES = export_kmafcst(args.site_dir)
    OBS_DATES = export_obs(args.site_dir)
    nc = copy_nowcast(args.site_dir)
    # 브리핑 묶음(앞 7일 값, 2026-09-08) — daily·hourly 양쪽에서 갱신(관측은 매시, 모델은 daily 커밋 기준)
    try:
        import export_briefing
        export_briefing.export(args.site_dir)
    except Exception as e:
        print(f"[site] 브리핑 묶음 실패(계속): {e}")
    prune_kmafcst(args.site_dir)
    to_webp(args.site_dir)          # 반드시 manifest 생성 전에
    build_manifest(args.site_dir, nc)
    print(f"[site] 완료: {args.site_dir}")


if __name__ == "__main__":
    main()
