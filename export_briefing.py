# -*- coding: utf-8 -*-
"""
브리핑 묶음 — 앞으로 7일치 모델·관측·기상청 예보 값을 한 파일로 (2026-09-08, 사용자 요청).

그림 대신 값을 LLM(Claude)에게 주고 분석시키기 위한 것. 과거는 남기지 않고 매번 덮어쓴다.
새로 받는 자료 없이 저장소에 이미 있는 CSV·JSON 에서 잘라낸다. 예외 둘(각 수 KB, 실패해도 나머지는 만든다):
  · 특보 현황  : API허브 wrn_now_data.php (종류·수준·구역·발효시각)
  · 예보 개황  : API허브 fct_afs_ds.php stn=108 (전국 종합 개황 문단 — 기압계·강수 시간대 서술)

산출 (site 루트): briefing/latest.md (사람·LLM 용 표) · briefing/latest.json
원칙: 원수치 그대로, 모델 평균·중재·보정 없음(사용자 결정), 결측은 비움. 전부 공개 자료.
상세(24h 관측·3h 시계열·발표분 비교·상층 지점값)는 대표 6지점만, 나머지 도시는 일별 표만 — 파일 크기 조절.
"""
import datetime as dt
import glob
import json
import os
import re

import numpy as np
import pandas as pd

from config import CITIES, CITY_OBS_STN, VERIF_DIR

REP6 = ["서울", "대전", "대구", "부산", "광주", "강릉"]     # 상세를 싣는 도시
COAST = ["인천", "강릉", "부산", "제주"]                       # 바람 요약(서해안·동해안·남해안·제주)
DAYS = 10          # 2026-09-08: 10일(ECMWF 240h·중기예보 D+10 과 맞춤)
MODELS = ["ECMWF", "GFS", "KIM"]
SHORT = {"ECMWF": "EC", "GFS": "GFS", "KIM": "KIM"}
SPREAD_WARN = 5.0
SITE_URL = "https://futurist38.github.io/nwp-verify"
SKY_KMA = {1: "맑음", 3: "구름많음", 4: "흐림"}
DIR16 = ["북", "북북동", "북동", "동북동", "동", "동남동", "남동", "남남동", "남", "남남서", "남서", "서남서", "서", "서북서", "북서", "북북서"]


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
    try:
        if v is None or np.isnan(float(v)):
            return None
    except (TypeError, ValueError):
        return None
    return int(round(float(v))) if nd == 0 else round(float(v), nd)


def _sky(tcc, tp, win):
    if tp is not None and tp >= (1.0 if (win or 3) > 3 else 0.5):
        return "강수"
    if tcc is None:
        return None
    return "흐림" if tcc >= 85 else "구름많음" if tcc >= 55 else "맑음"


def _dir(deg):
    return None if deg is None else DIR16[int((float(deg) + 11.25) // 22.5) % 16]


# ── 기상청 텍스트 API (선택, 실패해도 계속) ─────────────────────
def _kma_get(ep: str, params: dict, timeout=25) -> str | None:
    try:
        import sslfix  # noqa: F401
        import requests
        from kma_vilage import auth_key
        r = requests.get(f"https://apihub-pub.kma.go.kr/api/typ01/url/{ep}", params={**params, "authKey": auth_key()},
                         timeout=timeout)
        return r.text if r.status_code == 200 else None
    except Exception as e:
        print(f"[briefing] {ep} 실패(계속): {e}")
        return None


def warnings_now() -> list[dict]:
    """육상 특보 현황 — [{구역, 종류, 수준, 명령, 발효}]. 해상(REG_ID S…)은 제외."""
    t = _kma_get("wrn_now_data.php", {"fe": "f", "disp": 1})
    if not t or "[" not in t:
        return []
    try:
        items = json.loads(t[t.index("["):])
    except Exception:
        return []
    out = []
    for x in items:
        if str(x.get("REG_ID", "")).startswith("S"):
            continue
        out.append({"구역": x.get("REG_KO", "").strip(), "종류": x.get("WRN", "").strip(), "수준": x.get("LVL", "").strip(),
                    "명령": x.get("CMD", "").strip(), "발효": x.get("TM_EF", "")[:12], "발표": x.get("TM_FC", "")[:12]})
    return out


def overview_text(now: dt.datetime) -> dict | None:
    """전국 종합 개황(기상청 본청 stn=108) 최신 발표 — {tm_fc, text}. 응답이 유사 JSON(키에 따옴표 없음)이라 정규식으로."""
    t0 = (now - dt.timedelta(hours=36)).strftime("%Y%m%d%H")
    t = _kma_get("fct_afs_ds.php", {"stn": "108", "tmfc1": t0, "tmfc2": now.strftime("%Y%m%d%H"), "disp": 1})
    if not t:
        return None
    best = None
    for m in re.finditer(r'tm_fc:\s*"([^"]+)".*?wf_sv1:\s*"((?:[^"\\]|\\.)*)"', t, re.S):
        tm, raw = m.group(1), m.group(2)
        txt = raw.replace("\\n", "\n").replace('\\"', '"')
        if best is None or tm > best["tm_fc"]:
            best = {"tm_fc": tm, "text": txt.strip()}
    return best


def build(now: dt.datetime | None = None, site_dir: str | None = None) -> dict:
    now = now or dt.datetime.now()
    today = now.date()
    days = [today + dt.timedelta(days=k) for k in range(DAYS + 1)]
    out = {"generated_kst": now.strftime("%Y-%m-%d %H:%M"), "runs": {}, "notes": [
        "모델 일최고/최저는 3시간 값 기반 — 정시 사이 극값을 놓쳐 참값보다 안쪽(대개 0.5~1℃)",
        "모델은 평균·중재·보정하지 않고 나란히 둔다. 폭 = 최고기온 예보의 모델 간 최대−최소, 5℃ 초과는 ⚠",
        "관측 = ASOS 정시값(KST). 평년 = 1991~2020 자체 산출(±7일 평활)",
        "하늘: 3h 강수≥0.5mm 강수 / 운량≥85% 흐림 / 55~85 구름많음 / 그 외 맑음",
        "지점값: 기온·일사·강수·지위고도 최근접 격자, 운량·습도·풍속은 3×3 격자 평균 (2026-09-08부터; 그 전 채점과 운량 기준이 다름)",
        "상층 지점값: 850hPa 기온℃ / 700hPa 상대습도% / 500hPa 지위고도 m / 300hPa 풍속 m/s, 6시간 간격"], "cities": {}}

    out["warnings"] = warnings_now()
    out["overview"] = overview_text(now)

    fc = _load_csvs("forecast", _months(today - dt.timedelta(days=3), days[-1]), "run_utc")
    if not fc.empty:
        fc["valid"] = pd.to_datetime(fc["valid_kst"], format="mixed")
        latest = fc.groupby("model")["run_utc"].max()
        fc = fc[[r.run_utc == latest[r.model] for r in fc.itertuples()]]
        out["runs"] = {m: pd.Timestamp(latest[m]).strftime("%m-%d %Hz") for m in latest.index}
    ob = _load_csvs("obs", _months(today - dt.timedelta(days=2), today), "TM")
    nrm = {}
    p = os.path.join(VERIF_DIR, "normals_daily.csv")
    if os.path.exists(p):
        nd_ = pd.read_csv(p, dtype={"mmdd": str})
        nrm = {(int(r.stn), r.mmdd): (r.tmax, r.tmin) for r in nd_.itertuples()}

    # 기상청 단기예보: 최신 발표 + 직전 발표
    issues: dict[str, dict] = {}
    for fp in sorted(glob.glob(os.path.join(VERIF_DIR, "kmafcst", "????????.json")))[-2:]:
        for b, v in json.load(open(fp, encoding="utf-8")).items():
            if v:
                issues[b] = v
    iss_sorted = sorted(issues)
    kma_issue = iss_sorted[-1] if iss_sorted else None
    kma_prev = iss_sorted[-2] if len(iss_sorted) >= 2 else None
    kma = issues.get(kma_issue, {}) if kma_issue else {}
    if kma_issue:
        out["runs"]["기상청 단기예보"] = f"{kma_issue[4:6]}-{kma_issue[6:8]} {kma_issue[8:]}시 발표"
        if kma_prev:
            out["runs"]["직전 발표"] = f"{kma_prev[4:6]}-{kma_prev[6:8]} {kma_prev[8:]}시"
    mid, mf = {}, sorted(glob.glob(os.path.join(VERIF_DIR, "midfcst", "??????????.json")))
    if mf:
        mid_issue = os.path.basename(mf[-1])[:-5]
        mid = json.load(open(mf[-1], encoding="utf-8"))
        out["runs"]["기상청 중기예보"] = f"{mid_issue[4:6]}-{mid_issue[6:8]} {mid_issue[8:]}시 발표"

    sc = _load_csvs("scores", _months(today - dt.timedelta(days=8), today), "valid_kst")
    if not sc.empty:
        sc = sc[(sc["valid_kst"] >= pd.Timestamp(today - dt.timedelta(days=7))) & sc["err"].notna()]
        out["skill_7d"] = {}
        for (var, m), g in sc.groupby(["var", "model"]):
            if var in ("t2m", "tcc"):
                out["skill_7d"].setdefault(m, {})[var] = {"MAE": _r(g["err"].abs().mean()), "ME": _r(g["err"].mean()), "n": int(len(g))}

    # 상층 도시값·층별 일기도 링크 (오늘 archive 폴더)
    upper: dict[str, dict] = {}
    out["charts"] = {}
    if site_dir:
        arch = os.path.join(site_dir, "archive", today.strftime("%Y%m%d"))
        for fp in sorted(glob.glob(os.path.join(arch, "city_upper_*.json"))):
            d = json.load(open(fp, encoding="utf-8"))
            if d["model"] not in upper or d["run"] > upper[d["model"]]["run"]:
                upper[d["model"]] = d
        for m in MODELS:
            fs = sorted(glob.glob(os.path.join(arch, f"{m.lower()}_??????????_f???_p500.webp")))
            if not fs:
                continue
            run = os.path.basename(fs[-1]).split("_")[1]
            links = {}
            for panel in ("sfc", "p850", "p700", "p500", "p300"):
                for st in (0, 24, 48, 72):
                    fn = f"{m.lower()}_{run}_f{st:03d}_{panel}.webp"
                    if os.path.exists(os.path.join(arch, fn)):
                        links.setdefault(panel, {})[f"+{st}h"] = f"{SITE_URL}/archive/{today:%Y%m%d}/{fn}"
            if links:
                out["charts"][m] = {"run": run, "links": links}

    def kma_daily(b, c, d):
        if not b or not issues.get(b, {}).get(c):
            return None
        pre = d.strftime("%Y%m%d")
        ks = {k: v for k, v in issues[b][c].items() if k[:8] == pre}
        if len(ks) < 12:
            return None
        sky = [v for k, v in issues[b].get(f"{c}#SKY", {}).items() if k[:8] == pre and 9 <= int(k[8:]) <= 18]
        pty = [v for k, v in issues[b].get(f"{c}#PTY", {}).items() if k[:8] == pre]
        pop = [v for k, v in issues[b].get(f"{c}#POP", {}).items() if k[:8] == pre]
        r = {"tmax": _r(max(ks.values())), "tmin": _r(min(ks.values())), "n_h": len(ks)}
        if sky:
            r["sky"] = SKY_KMA.get(int(max(set(sky), key=sky.count)), "?")
        if pop:
            r["pop_max"] = int(max(pop))
        if pty and any(pty):
            r["pty"] = "강수"
        return r

    for name, lat, lon, rep in CITIES:
        c: dict = {"stn": CITY_OBS_STN.get(name), "daily": []}
        stn = CITY_OBS_STN.get(name)
        detail = name in REP6
        if stn and not ob.empty:
            o = ob[ob["STN"] == stn].sort_values("TM")
            last = o.dropna(subset=["TA"]).tail(1)
            if len(last):
                c["obs_now"] = {"time": last["TM"].iloc[0].strftime("%m-%d %H시"), "TA": _r(last["TA"].iloc[0]),
                                "CA": _r(last["CA_TOT"].iloc[0], 0), "WS": _r(last["WS"].iloc[0]) if "WS" in last else None}
            for lab, d in (("today", today), ("yesterday", today - dt.timedelta(days=1))):
                g = o[o["TM"].dt.date == d]
                if len(g):
                    c["obs_" + lab] = {"tmax": _r(g["TA"].max()), "tmin": _r(g["TA"].min()), "n_h": int(g["TA"].notna().sum()),
                                       "ca_mean": _r(g["CA_TOT"].mean()), "si_sum": _r(g["SI"].sum()),
                                       "ws_max": _r(g["WS"].max()) if "WS" in g else None}
            if detail:
                h24 = o[o["TM"] >= pd.Timestamp(now) - pd.Timedelta(hours=24)]
                c["obs_24h"] = [[r.TM.strftime("%d%H"), _r(r.TA), _r(r.CA_TOT, 0)] for r in h24.itertuples()]
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
                                    "sw_day": _r(day["dswrf_avg_Wm2"].mean(), 0) if len(day) and "dswrf_avg_Wm2" in day else None}
            tmaxs = [v["tmax"] for v in row["models"].values() if v["tmax"] is not None]
            if len(tmaxs) >= 2:
                row["spread_tmax"] = _r(max(tmaxs) - min(tmaxs))
                row["spread_warn"] = row["spread_tmax"] > SPREAD_WARN
            k = kma_daily(kma_issue, name, d)
            if k:
                row["kma"] = k
            if detail:
                kp = kma_daily(kma_prev, name, d)
                if kp:
                    row["kma_prev"] = kp
            if mid.get(name, {}).get(d.strftime("%Y%m%d")):
                v = mid[name][d.strftime("%Y%m%d")]
                row["mid"] = {"tmax": v.get("max"), "tmin": v.get("min")}
            c["daily"].append(row)
        if name in COAST and kma.get(f"{name}#WSD"):
            c["wind"] = []
            for d in days[:3]:
                pre = d.strftime("%Y%m%d")
                ws = {k: v for k, v in kma[f"{name}#WSD"].items() if k[:8] == pre}
                if ws:
                    kmax = max(ws, key=ws.get)
                    c["wind"].append({"date": d.strftime("%m-%d"), "ws_max": _r(ws[kmax]), "at": kmax[8:] + "시",
                                      "dir": _dir(kma.get(f"{name}#VEC", {}).get(kmax))})
        if detail and not sub.empty:
            c["series3h"] = []
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
                    rec["KMA"] = [_r(kma[name][k]), SKY_KMA.get(kma.get(f"{name}#SKY", {}).get(k), ""),
                                  kma.get(f"{name}#POP", {}).get(k),
                                  _dir(kma.get(f"{name}#VEC", {}).get(k)), _r(kma.get(f"{name}#WSD", {}).get(k))]
                c["series3h"].append(rec)
        if detail and upper:
            c["upper"] = []
            steps = sorted({int(s) for d_ in upper.values() for s in d_["cities"].get(name, {}).get("t850", {})})
            for st in steps:
                if st > 72:
                    continue
                rec = {"step": st}
                for m, d_ in upper.items():
                    cc = d_["cities"].get(name)
                    if not cc:
                        continue
                    run = dt.datetime.strptime(d_["run"], "%Y%m%d%H")
                    rec.setdefault("valid", (run + dt.timedelta(hours=st + 9)).strftime("%d일%H시"))
                    rec[SHORT.get(m, m)] = [cc["t850"].get(str(st)), cc["r700"].get(str(st)), cc["gh500"].get(str(st)), cc["ws300"].get(str(st))]
                if len(rec) > 2:
                    c["upper"].append(rec)
        out["cities"][name] = c
    return out


def to_markdown(b: dict) -> str:
    f = lambda v: "" if v is None else v
    L = [f"# 브리핑 묶음 — 생성 {b['generated_kst']} KST",
         "런/발표: " + " · ".join(f"{k} {v}" for k, v in b.get("runs", {}).items()), "",
         "주의: " + " / ".join(b["notes"]), ""]
    w = b.get("warnings") or []
    if w:
        by = {}
        for x in w:
            by.setdefault((x["종류"], x["수준"], x["명령"]), []).append(x["구역"])
        L.append("## 특보 현황 (육상, 해상 제외)")
        for (k, lv, cmd), regs in by.items():
            L.append(f"- {k} {lv} {cmd}: {', '.join(regs[:12])}" + (f" 외 {len(regs) - 12}곳" if len(regs) > 12 else ""))
        L.append("")
    else:
        L += ["## 특보 현황", "- 육상 특보 없음(또는 조회 실패)", ""]
    ov = b.get("overview")
    if ov:
        L += [f"## 기상청 종합 개황 ({ov['tm_fc']} 발표, 전국)", "```", ov["text"], "```", ""]
    if b.get("skill_7d"):
        L += ["## 최근 7일 모델 성적 (전 도시, 예측−실측)", "| 모델 | 기온 MAE | 기온 ME | 운량 MAE | 운량 ME | n(기온) |", "|---|---|---|---|---|---|"]
        for m in MODELS:
            s = b["skill_7d"].get(m, {}); t, c = s.get("t2m", {}), s.get("tcc", {})
            L.append(f"| {m} | {f(t.get('MAE'))} | {f(t.get('ME'))} | {f(c.get('MAE'))} | {f(c.get('ME'))} | {f(t.get('n'))} |")
        L.append("")
    if b.get("charts"):
        L.append("## 층별 일기도 (동아시아, 6h) — 링크")
        for m, ch in b["charts"].items():
            parts = []
            for panel, lab in (("sfc", "지상"), ("p850", "850"), ("p700", "700"), ("p500", "500"), ("p300", "300")):
                if panel in ch["links"]:
                    parts.append(lab + " " + " ".join(f"[{st}]({u})" for st, u in ch["links"][panel].items()))
            L.append(f"- {m} 런 {ch['run'][4:6]}-{ch['run'][6:8]} {ch['run'][8:]}z: " + " · ".join(parts))
        L.append("")
    for name, c in b["cities"].items():
        L.append(f"## {name}")
        on = c.get("obs_now")
        if on:
            ot, oy = c.get("obs_today", {}), c.get("obs_yesterday", {})
            L.append(f"관측: 지금 {on['TA']}℃ ({on['time']}, 운량 {f(on['CA'])}/10, 풍속 {f(on.get('WS'))}m/s) · 오늘 지금까지 최고 {f(ot.get('tmax'))} / 최저 {f(ot.get('tmin'))} "
                     f"({ot.get('n_h', 0)}시간, 최대풍속 {f(ot.get('ws_max'))}) · 어제 최고 {f(oy.get('tmax'))} / 최저 {f(oy.get('tmin'))} · 어제 일사합 {f(oy.get('si_sum'))} MJ/㎡")
            if c.get("obs_24h"):
                L.append("최근 24h 기온(일시:값): " + " ".join(f"{t}:{ta}" for t, ta, _ in c["obs_24h"] if ta is not None))
        else:
            L.append("관측: 해당 ASOS 지점 없음")
        L += ["", "| 날짜 | 평년 최고/최저 | EC 최고/최저 | GFS | KIM | 폭 | 기상청 단기 | 중기 | 낮운량% EC/GFS/KIM | 강수mm EC/GFS/KIM |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for d in c["daily"]:
            mm = d["models"]
            mx = lambda m: f"{f(mm[m]['tmax'])}/{f(mm[m]['tmin'])}" if m in mm else ""
            nr = d.get("normal", {}); k = d.get("kma", {}); mid = d.get("mid", {})
            ks = (f"{f(k.get('tmax'))}/{f(k.get('tmin'))}" + (f" {k['sky']}" if k.get("sky") else "") + (f" 강수확률{k['pop_max']}%" if k.get("pop_max") else "")) if k else ""
            ms = f"{f(mid.get('tmax'))}/{f(mid.get('tmin'))}" if mid else ""
            sp = f"{d['spread_tmax']}{' ⚠' if d.get('spread_warn') else ''}" if d.get("spread_tmax") is not None else ""
            tcc = "/".join("" if mm[m]["tcc_day"] is None else str(mm[m]["tcc_day"]) for m in MODELS if m in mm)
            tp = "/".join("" if mm[m]["tp_sum"] is None else str(mm[m]["tp_sum"]) for m in MODELS if m in mm)
            L.append(f"| {d['date']} | {f(nr.get('tmax'))}/{f(nr.get('tmin'))} | {mx('ECMWF')} | {mx('GFS')} | {mx('KIM')} | {sp} | {ks} | {ms} | {tcc} | {tp} |")
        cmp_rows = [d for d in c["daily"][:3] if d.get("kma") and d.get("kma_prev")]
        if cmp_rows:
            L += ["", f"기상청 발표분 비교 (직전 {b['runs'].get('직전 발표', '')} → 최신): 최고/최저·하늘, Δ최고",
                  "| 날짜 | 직전 | 최신 | Δ최고 |", "|---|---|---|---|"]
            for d in cmp_rows:
                a, z = d["kma_prev"], d["kma"]
                dl = None if a["tmax"] is None or z["tmax"] is None else round(z["tmax"] - a["tmax"], 1)
                L.append(f"| {d['date']} | {f(a['tmax'])}/{f(a['tmin'])} {f(a.get('sky'))} | {f(z['tmax'])}/{f(z['tmin'])} {f(z.get('sky'))} | {'' if dl is None else ('+' if dl > 0 else '') + str(dl)} |")
        if c.get("wind"):
            L.append("\n기상청 예보 바람(일 최대풍속, 그때 풍향): " + " · ".join(f"{w['date']} {w['ws_max']}m/s {f(w['dir'])}({w['at']})" for w in c["wind"]))
        if c.get("series3h"):
            L += ["", "3시간 시계열 (모델: 기온℃ / 운량% / 강수mm / 하늘 · 기상청: 기온 / 하늘 / 강수확률% / 풍향 / 풍속m/s)",
                  "| 시각 | EC | GFS | KIM | 기상청 |", "|---|---|---|---|---|"]
            for r in c["series3h"]:
                cell = lambda k: " ".join(str(f(x)) for x in r[k]) if k in r else ""
                L.append(f"| {r['time']} | {cell('EC')} | {cell('GFS')} | {cell('KIM')} | {cell('KMA')} |")
        if c.get("upper"):
            L += ["", "상층 지점값 (850기온℃ / 700습도% / 500고도m / 300풍속m/s)", "| 유효 | EC | GFS | KIM |", "|---|---|---|---|"]
            for r in c["upper"]:
                cell = lambda k: " ".join(str(f(x)) for x in r[k]) if k in r else ""
                L.append(f"| {r.get('valid', '')}(+{r['step']}h) | {cell('EC')} | {cell('GFS')} | {cell('KIM')} |")
        L.append("")
    return "\n".join(L)


def export(site_dir: str) -> None:
    b = build(site_dir=site_dir)
    od = os.path.join(site_dir, "briefing")
    os.makedirs(od, exist_ok=True)
    with open(os.path.join(od, "latest.json"), "w", encoding="utf-8") as fp:
        json.dump(b, fp, ensure_ascii=False, separators=(",", ":"))
    md = to_markdown(b)
    with open(os.path.join(od, "latest.md"), "w", encoding="utf-8") as fp:
        fp.write(md)
    # 시각 붙은 사본 (2026-09-08 사용자): LLM 웹페치가 같은 URL 을 대화 안에서 캐시해 구버전을 다시 읽는다 →
    # 매시 고유 주소 briefing/YYYYMMDDHH.md 를 만들고 48시간 지난 것은 지운다. 주소는 시계만 보고 만들 수 있다.
    stamp = dt.datetime.now().strftime("%Y%m%d%H")
    with open(os.path.join(od, f"{stamp}.md"), "w", encoding="utf-8") as fp:
        fp.write(md)
    cut = (dt.datetime.now() - dt.timedelta(hours=48)).strftime("%Y%m%d%H")
    for fp_ in glob.glob(os.path.join(od, "??????????.md")):
        if os.path.basename(fp_)[:10] < cut:
            os.remove(fp_)
    print(f"[site] 브리핑 묶음: md {len(md.encode('utf-8')) / 1024:.0f}KB, 도시 {len(b['cities'])}, 특보 {len(b.get('warnings') or [])}건, "
          f"개황 {'있음' if b.get('overview') else '없음'}, 상층링크 {list(b.get('charts', {}).keys())}")


if __name__ == "__main__":
    import sys
    export(sys.argv[1] if len(sys.argv) > 1 else "site_build")
