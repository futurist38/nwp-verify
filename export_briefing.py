# -*- coding: utf-8 -*-
"""
브리핑 묶음 — 앞으로 7일치 모델·관측·기상청 예보 값을 한 파일로 (2026-09-08, 사용자 요청).

그림 대신 값을 LLM(Claude)에게 주고 분석시키기 위한 것. 과거는 남기지 않고 매번 덮어쓴다.
새로 받는 자료 없이 저장소에 이미 있는 CSV·JSON 에서 잘라낸다 (몇 초).

산출 (site 루트):
  briefing/latest.md    사람·LLM 이 읽는 표 (~15KB)
  briefing/latest.json  같은 내용 기계용
원칙: 원수치 그대로, 모델 평균·중재 없음, 결측은 비움. 전부 공개 자료.
주의 표기: 모델 일최고/최저는 3시간 값 기반(정시 사이 극값을 놓쳐 참값보다 안쪽).
"""
import datetime as dt
import glob
import json
import os

import numpy as np
import pandas as pd

from config import CITIES, CITY_OBS_STN, VERIF_DIR

REP6 = ["서울", "대전", "대구", "부산", "광주", "강릉"]   # 3시간 시계열까지 싣는 도시
DAYS = 7
MODELS = ["ECMWF", "GFS", "KIM"]
SHORT = {"ECMWF": "EC", "GFS": "GFS", "KIM": "KIM"}


def _months(d0: dt.date, d1: dt.date):
    out, cur = [], d0.replace(day=1)
    while cur <= d1:
        out.append(cur.strftime("%Y-%m"))
        cur = (cur.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return out


def _load_csvs(sub: str, months, parse_col: str) -> pd.DataFrame:
    frames = []
    for ym in months:
        fp = os.path.join(VERIF_DIR, sub, f"{ym}.csv")
        if os.path.exists(fp):
            df = pd.read_csv(fp)
            df[parse_col] = pd.to_datetime(df[parse_col], format="mixed")
            frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _r(v, nd=1):
    if v is None or (isinstance(v, float) and np.isnan(v)) or (hasattr(v, "__float__") and np.isnan(float(v))):
        return None
    return int(round(float(v))) if nd == 0 else round(float(v), nd)


def _sky(tcc, tp, win):
    if tp is not None and tp >= (1.0 if (win or 3) > 3 else 0.5):
        return "강수"
    if tcc is None:
        return None
    return "흐림" if tcc >= 85 else "구름많음" if tcc >= 55 else "맑음"


def build(now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now()
    today = now.date()
    days = [today + dt.timedelta(days=k) for k in range(DAYS + 1)]     # 오늘 포함 8일(오늘=0)
    out = {"generated_kst": now.strftime("%Y-%m-%d %H:%M"), "runs": {}, "notes": [
        "모델 일최고/최저는 3시간 값 기반 — 정시 사이 극값을 놓쳐 참값보다 안쪽(대개 0.5~1℃)",
        "모델은 평균·중재하지 않고 나란히 둔다. 폭 = 최고기온 예보의 모델 간 최대−최소",
        "관측 = ASOS 정시값(KST). 평년 = 1991~2020 자체 산출(±7일 평활)",
        "하늘: 3h 강수≥0.5mm 강수 / 운량≥85% 흐림 / 55~85 구름많음 / 그 외 맑음"], "cities": {}}

    # ── 모델(최신 런) ─────────────────────────────────────
    fc = _load_csvs("forecast", _months(today - dt.timedelta(days=3), days[-1]), "run_utc")
    if not fc.empty:
        fc["valid"] = pd.to_datetime(fc["valid_kst"], format="mixed")
        latest = fc.groupby("model")["run_utc"].max()
        fc = fc[[r.run_utc == latest[r.model] for r in fc.itertuples()]]
        out["runs"] = {m: pd.Timestamp(latest[m]).strftime("%m-%d %Hz") for m in latest.index}
    # ── 관측 ──────────────────────────────────────────────
    ob = _load_csvs("obs", _months(today - dt.timedelta(days=2), today), "TM")
    # ── 평년 ──────────────────────────────────────────────
    nrm = {}
    p = os.path.join(VERIF_DIR, "normals_daily.csv")
    if os.path.exists(p):
        nd_ = pd.read_csv(p, dtype={"mmdd": str})
        nrm = {(int(r.stn), r.mmdd): (r.tmax, r.tmin) for r in nd_.itertuples()}
    # ── 기상청 단기예보(최신 발표) ────────────────────────
    kma, kma_issue = {}, None
    for fp in sorted(glob.glob(os.path.join(VERIF_DIR, "kmafcst", "????????.json")))[-2:]:
        cache = json.load(open(fp, encoding="utf-8"))
        for b in sorted(cache):
            if cache[b] and (kma_issue is None or b > kma_issue):
                kma_issue, kma = b, cache[b]
    if kma_issue:
        out["runs"]["기상청 단기예보"] = f"{kma_issue[4:6]}-{kma_issue[6:8]} {kma_issue[8:]}시 발표"
    # ── 중기예보(최신 발표) ───────────────────────────────
    mid, mid_issue = {}, None
    mf = sorted(glob.glob(os.path.join(VERIF_DIR, "midfcst", "??????????.json")))
    if mf:
        mid_issue = os.path.basename(mf[-1])[:-5]
        mid = json.load(open(mf[-1], encoding="utf-8"))
        out["runs"]["기상청 중기예보"] = f"{mid_issue[4:6]}-{mid_issue[6:8]} {mid_issue[8:]}시 발표"
    # ── 최근 7일 모델 성적 ────────────────────────────────
    sc = _load_csvs("scores", _months(today - dt.timedelta(days=8), today), "valid_kst")
    if not sc.empty:
        sc = sc[(sc["valid_kst"] >= pd.Timestamp(today - dt.timedelta(days=7))) & sc["err"].notna()]
        out["skill_7d"] = {}
        for (var, m), g in sc.groupby(["var", "model"]):
            if var in ("t2m", "tcc"):
                out["skill_7d"].setdefault(m, {})[var] = {"MAE": _r(g["err"].abs().mean()), "ME": _r(g["err"].mean()),
                                                          "n": int(len(g))}

    # ── 도시별 ────────────────────────────────────────────
    for name, lat, lon, rep in CITIES:
        c: dict = {"stn": CITY_OBS_STN.get(name), "daily": [], "series3h": []}
        stn = CITY_OBS_STN.get(name)
        # 관측
        if stn and not ob.empty:
            o = ob[ob["STN"] == stn].sort_values("TM")
            last = o.dropna(subset=["TA"]).tail(1)
            if len(last):
                c["obs_now"] = {"time": last["TM"].iloc[0].strftime("%m-%d %H시"), "TA": _r(last["TA"].iloc[0]),
                                "CA": _r(last["CA_TOT"].iloc[0], 0), "SI": _r(last["SI"].iloc[0], 2)}
            for lab, d in (("today", today), ("yesterday", today - dt.timedelta(days=1))):
                g = o[o["TM"].dt.date == d]
                if len(g):
                    c["obs_" + lab] = {"tmax": _r(g["TA"].max()), "tmin": _r(g["TA"].min()), "n_h": int(g["TA"].notna().sum()),
                                       "ca_mean": _r(g["CA_TOT"].mean()), "si_sum": _r(g["SI"].sum())}
            h24 = o[o["TM"] >= pd.Timestamp(now) - pd.Timedelta(hours=24)]
            c["obs_24h"] = [[r.TM.strftime("%d%H"), _r(r.TA), _r(r.CA_TOT, 0)] for r in h24.itertuples()]
        # 일별 (오늘 + 7일)
        sub = fc[fc["city"] == name] if not fc.empty else pd.DataFrame()
        for d in days:
            row = {"date": d.strftime("%m-%d(%a)"), "models": {}}
            if stn and (stn, d.strftime("%m%d")) in nrm:
                tx, tn = nrm[(stn, d.strftime("%m%d"))]
                row["normal"] = {"tmax": _r(tx), "tmin": _r(tn)}
            for m in MODELS:
                g = sub[(sub["model"] == m) & (sub["valid"].dt.date == d)]
                if len(g) < 4:
                    continue
                day = g[(g["valid"].dt.hour >= 9) & (g["valid"].dt.hour <= 18)]
                row["models"][m] = {"tmax": _r(g["t2m_C"].max()), "tmin": _r(g["t2m_C"].min()),
                                    "tcc_day": _r(day["tcc_pct"].mean(), 0) if len(day) else None,
                                    "tp_sum": _r(g["tp_mm"].sum()) if "tp_mm" in g else None,
                                    "sw_day": _r(day["dswrf_avg_Wm2"].mean(), 0) if len(day) and "dswrf_avg_Wm2" in day else None,
                                    "n": int(len(g))}
            tmaxs = [v["tmax"] for v in row["models"].values() if v["tmax"] is not None]
            if len(tmaxs) >= 2:
                row["spread_tmax"] = _r(max(tmaxs) - min(tmaxs))
            # 기상청 단기(1h TMP 최고/최저) · 중기
            if kma.get(name):
                ks = {k: v for k, v in kma[name].items() if k[:8] == d.strftime("%Y%m%d")}
                if len(ks) >= 12:
                    row["kma"] = {"tmax": _r(max(ks.values())), "tmin": _r(min(ks.values())), "n_h": len(ks)}
                    pop = {k: v for k, v in kma.get(f"{name}#POP", {}).items() if k[:8] == d.strftime("%Y%m%d")}
                    pty = {k: v for k, v in kma.get(f"{name}#PTY", {}).items() if k[:8] == d.strftime("%Y%m%d")}
                    if pop:
                        row["kma"]["pop_max"] = int(max(pop.values()))
                    if pty and any(v for v in pty.values()):
                        row["kma"]["pty"] = "강수"
            if mid.get(name, {}).get(d.strftime("%Y%m%d")):
                v = mid[name][d.strftime("%Y%m%d")]
                row["mid"] = {"tmax": v.get("max"), "tmin": v.get("min")}
            c["daily"].append(row)
        # 3시간 시계열 (대표 6도시, 앞 3일)
        if name in REP6 and not sub.empty:
            t1 = pd.Timestamp(today + dt.timedelta(days=3))
            g3 = sub[(sub["valid"] >= pd.Timestamp(now) - pd.Timedelta(hours=3)) & (sub["valid"] < t1)]
            for t, gg in g3.groupby("valid"):
                rec = {"time": t.strftime("%d일%H시")}
                for r in gg.itertuples():
                    tp = _r(getattr(r, "tp_mm", None)); w = getattr(r, "win_h", None)
                    rec[SHORT[r.model]] = [_r(r.t2m_C), _r(r.tcc_pct, 0), tp,
                                           _sky(_r(r.tcc_pct, 0), tp, None if w is None or pd.isna(w) else int(w))]
                k = t.strftime("%Y%m%d%H")
                if kma.get(name, {}).get(k) is not None:
                    rec["KMA"] = [_r(kma[name][k]), kma.get(f"{name}#SKY", {}).get(k), kma.get(f"{name}#POP", {}).get(k)]
                c["series3h"].append(rec)
        out["cities"][name] = c
    return out


def to_markdown(b: dict) -> str:
    L = [f"# 브리핑 묶음 — 생성 {b['generated_kst']} KST",
         "런/발표: " + " · ".join(f"{k} {v}" for k, v in b.get("runs", {}).items()), ""]
    L += ["주의: " + " / ".join(b["notes"]), ""]
    if b.get("skill_7d"):
        L += ["## 최근 7일 모델 성적 (전 도시, 예측−실측)", "| 모델 | 기온 MAE | 기온 ME | 운량 MAE | 운량 ME | n(기온) |", "|---|---|---|---|---|---|"]
        for m in MODELS:
            s = b["skill_7d"].get(m, {})
            t, c = s.get("t2m", {}), s.get("tcc", {})
            L.append(f"| {m} | {t.get('MAE', '')} | {t.get('ME', '')} | {c.get('MAE', '')} | {c.get('ME', '')} | {t.get('n', '')} |")
        L.append("")
    f = lambda v: "" if v is None else v
    for name, c in b["cities"].items():
        L.append(f"## {name}")
        on = c.get("obs_now")
        if on:
            ot, oy = c.get("obs_today", {}), c.get("obs_yesterday", {})
            L.append(f"관측: 지금 {on['TA']}℃ ({on['time']}, 운량 {f(on['CA'])}/10) · 오늘 지금까지 최고 {f(ot.get('tmax'))} / 최저 {f(ot.get('tmin'))} "
                     f"({ot.get('n_h', 0)}시간) · 어제 최고 {f(oy.get('tmax'))} / 최저 {f(oy.get('tmin'))} · 어제 일사합 {f(oy.get('si_sum'))} MJ/㎡")
            if c.get("obs_24h"):
                L.append("최근 24h 기온(일시:값): " + " ".join(f"{t}:{ta}" for t, ta, _ in c["obs_24h"] if ta is not None))
        else:
            L.append("관측: 해당 ASOS 지점 없음")
        L += ["", "| 날짜 | 평년 최고/최저 | EC 최고/최저 | GFS | KIM | 폭 | 기상청 단기 | 중기 | 낮운량% EC/GFS/KIM | 강수mm EC/GFS/KIM |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for d in c["daily"]:
            mm = d["models"]
            mx = lambda m: f"{f(mm[m]['tmax'])}/{f(mm[m]['tmin'])}" if m in mm else ""
            nr = d.get("normal", {})
            kma = d.get("kma", {}); mid = d.get("mid", {})
            kma_s = (f"{f(kma.get('tmax'))}/{f(kma.get('tmin'))}" + (f" 강수확률{kma['pop_max']}%" if kma.get("pop_max") else "")) if kma else ""
            mid_s = f"{f(mid.get('tmax'))}/{f(mid.get('tmin'))}" if mid else ""
            tcc = "/".join(f(mm[m]["tcc_day"]) and str(mm[m]["tcc_day"]) or "" for m in MODELS if m in mm)
            tp = "/".join(str(mm[m]["tp_sum"]) if m in mm and mm[m]["tp_sum"] is not None else "" for m in MODELS if m in mm)
            L.append(f"| {d['date']} | {f(nr.get('tmax'))}/{f(nr.get('tmin'))} | {mx('ECMWF')} | {mx('GFS')} | {mx('KIM')} | {f(d.get('spread_tmax'))} | {kma_s} | {mid_s} | {tcc} | {tp} |")
        if c.get("series3h"):
            L += ["", "3시간 시계열 (기온℃ / 운량% / 강수mm / 하늘; 기상청 = 기온/SKY/강수확률)",
                  "| 시각 | EC | GFS | KIM | 기상청 |", "|---|---|---|---|---|"]
            for r in c["series3h"]:
                cell = lambda k: " ".join(str(f(x)) for x in r[k]) if k in r else ""
                L.append(f"| {r['time']} | {cell('EC')} | {cell('GFS')} | {cell('KIM')} | {cell('KMA')} |")
        L.append("")
    return "\n".join(L)


def export(site_dir: str) -> None:
    b = build()
    od = os.path.join(site_dir, "briefing")
    os.makedirs(od, exist_ok=True)
    with open(os.path.join(od, "latest.json"), "w", encoding="utf-8") as fp:
        json.dump(b, fp, ensure_ascii=False, separators=(",", ":"))
    md = to_markdown(b)
    with open(os.path.join(od, "latest.md"), "w", encoding="utf-8") as fp:
        fp.write(md)
    print(f"[site] 브리핑 묶음: md {len(md.encode('utf-8')) / 1024:.0f}KB, 도시 {len(b['cities'])}, 런 {b.get('runs')}")


if __name__ == "__main__":
    import sys
    export(sys.argv[1] if len(sys.argv) > 1 else "site_build")
