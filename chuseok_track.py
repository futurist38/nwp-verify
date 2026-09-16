# -*- coding: utf-8 -*-
"""
추석 연휴 예보 추적 (2026-09-16 사용자 요청) — 8대도시 × 대상일(9/23~27), 발표시각별 기온·개황 변화.

자료
  · 단기예보(동네예보, typ02 getVilageFcst): 발표 05/11/17시(+15분께 가용). 대상일이 발표 후 3일 안에 들면
    TMX(15시)·TMN(06시)·SKY/PTY(하늘·강수형태)·POP 로 일 요약. 발표분은 불변 → 캐시.
  · 중기예보(typ02 MidFcstInfoService): 발표 06/18시. getMidTa(도시별 최저/최고 ±범위) + getMidLandFcst(육상 권역 개황 wf·강수확률).
    실측(2026-09-16): 06시 발표 = D+4~D+10, 18시 발표 = D+5~D+10. D+7 까지는 오전/오후 개황, D+8~10 은 하루 하나.
  · 우선순위: 대상일이 단기 범위면 단기, 아니면 중기. 없는 날은 비워 둔다(나오면 채움).
캐시: verification/chuseok/{발표YYYYMMDDHH}_{short|mid}.json  (커밋 대상)
산출: output/chuseok/chuseok.json (사이트 탭용) · output/chuseok/chuseok_latest.png (카톡·메일용)
사용: python chuseok_track.py [--backfill 2026091606] [--no-plot]
"""
import argparse, math
import datetime as dt
import json
import os

import requests

import sslfix  # noqa: F401
from config import BASE_DIR, OUT_DIR, VERIF_DIR
from kma_vilage import auth_key, fetch as fetch_short

KST = dt.timezone(dt.timedelta(hours=9))
TARGET_DATES = [dt.date(2026, 9, d) for d in range(23, 28)]        # 9/23(수)~9/27(일)
LAST_ISSUE = dt.datetime(2026, 9, 23, 11, tzinfo=KST)              # 마지막 발표(9/23 11시 단기)
SHORT_HOURS = (5, 11, 17)
MID_HOURS = (6, 18)
# (동네예보 격자 nx,ny, 중기 기온 예보구역, 중기 육상 권역)
CITIES = {
    "서울": ((60, 127), "11B10101", "11B00000"),
    "인천": ((54, 125), "11B20201", "11B00000"),
    "수원": ((60, 120), "11B20601", "11B00000"),
    "원주": ((76, 122), "11D10401", "11D10000"),
    "대전": ((67, 101), "11C20401", "11C20000"),
    "대구": ((90, 91), "11H10701", "11H10000"),
    "광주": ((59, 75), "11F20501", "11F20000"),
    "부산": ((97, 74), "11H20201", "11H20000"),
}
CACHE_DIR = os.path.join(VERIF_DIR, "chuseok")
OUT = os.path.join(OUT_DIR, "chuseok")
MID_API = "https://apihub-pub.kma.go.kr/api/typ02/openApi/MidFcstInfoService"
SKY_TXT = {1: "맑음", 3: "구름많음", 4: "흐림"}
PTY_TXT = {1: "비", 2: "비/눈", 3: "눈", 4: "소나기", 5: "빗방울", 6: "빗방울/눈날림", 7: "눈날림"}


# ── 발표 목록 ──────────────────────────────────────────────────────────
def issuances(now: dt.datetime, start: dt.datetime) -> list[tuple[str, dt.datetime]]:
    """start 이후 ~ now 까지 가용해진 발표 (kind, 발표시각 KST). 단기는 +15분, 중기는 +10분 뒤 가용으로 본다."""
    out = []
    d = start.date()
    while d <= min(now.date(), LAST_ISSUE.date()):
        for h in SHORT_HOURS:
            t = dt.datetime(d.year, d.month, d.day, h, tzinfo=KST)
            if start <= t <= LAST_ISSUE and t + dt.timedelta(minutes=15) <= now:
                out.append(("short", t))
        for h in MID_HOURS:
            t = dt.datetime(d.year, d.month, d.day, h, tzinfo=KST)
            if start <= t <= LAST_ISSUE and t + dt.timedelta(minutes=10) <= now:
                out.append(("mid", t))
        d += dt.timedelta(days=1)
    return sorted(out, key=lambda x: x[1])


def _cache_path(kind: str, t: dt.datetime) -> str:
    return os.path.join(CACHE_DIR, f"{t:%Y%m%d%H}_{kind}.json")


# ── 단기예보 → 대상일 요약 ─────────────────────────────────────────────
def collect_short(t: dt.datetime, key: str) -> dict:
    """{city: {YYYYMMDD: {tmax, tmin, sky, pop, src:'short'}}} — 발표 t 의 예보 중 대상일만."""
    bdt = t.strftime("%Y%m%d%H")
    res = {}
    for city, ((nx, ny), _, _) in CITIES.items():
        try:
            f = fetch_short(nx, ny, bdt, key, cats=("TMP", "TMX", "TMN", "SKY", "PTY", "POP"))
        except Exception as e:                      # noqa: BLE001
            print(f"[추석] 단기 {bdt} {city} 실패: {str(e)[:80]}")
            res["_incomplete"] = True               # 한 도시라도 실패하면 캐시하지 않는다(다음 실행에 재시도)
            continue
        days = {}
        for d in TARGET_DATES:
            ds = d.strftime("%Y%m%d")
            hours = [f"{ds}{h:02d}" for h in range(0, 24)]
            tmp = [f["TMP"][h] for h in hours if h in f["TMP"]]
            tmax = f["TMX"].get(f"{ds}15"); tmax_src = "TMX"
            tmin = f["TMN"].get(f"{ds}06"); tmin_src = "TMN"
            if tmax is None and len(tmp) == 24:     # 공식값이 없으면 하루 전체 시간값이 있을 때만 대체 (부분 일자 극값 금지)
                tmax, tmax_src = max(tmp), "hourly"
            if tmin is None and len(tmp) == 24:
                tmin, tmin_src = min(tmp), "hourly"
            if tmax is None or tmin is None:        # 9/23 11시 발표처럼 그 날 일부만 남은 경우 → 그 날짜는 이 발표에서 제외
                continue
            # 개황: 낮(09~18시) 하늘상태 최빈값 + 강수형태 유무, 강수확률 낮 최대
            day_h = [f"{ds}{h:02d}" for h in range(9, 19)]
            skys = [int(f["SKY"][h]) for h in day_h if h in f["SKY"]]
            ptys = [int(f["PTY"][h]) for h in day_h if h in f["PTY"]]
            pops = [int(f["POP"][h]) for h in day_h if h in f["POP"]]
            # 하늘 최빈값(동률이면 더 흐린 쪽), 강수형태는 종류 나열(코드는 순서가 아님)
            sky = max(sorted(set(skys)), key=lambda k: (skys.count(k), k)) if skys else None
            kinds = sorted({p for p in ptys if p})
            txt = SKY_TXT.get(sky, "?") if sky else "?"
            if kinds:
                txt += "·" + "/".join(PTY_TXT.get(p, "강수") for p in kinds)
            all_pty = sorted({int(f["PTY"][h]) for h in hours if h in f["PTY"] and int(f["PTY"][h])})
            days[ds] = {"tmax": float(tmax), "tmin": float(tmin), "sky": txt,
                        "pop": (max(pops) if pops else None), "src": "short",
                        "tmax_src": tmax_src, "tmin_src": tmin_src, "n_hours": len(tmp),
                        "pty_day": [PTY_TXT.get(p, "강수") for p in all_pty]}   # 하루 전체 강수형태(낮 창 밖 포함)
        res[city] = days
    return res


# ── 중기예보 → 대상일 요약 ─────────────────────────────────────────────
def _mid_get(path: str, reg: str, tmfc: str, key: str) -> dict | None:
    for attempt in range(3):
        try:
            r = requests.get(f"{MID_API}/{path}", params={"regId": reg, "tmFc": tmfc, "pageNo": 1, "numOfRows": 10,
                                                          "dataType": "JSON", "authKey": key}, timeout=60)
            j = r.json()
            items = j["response"]["body"]["items"]["item"]
            return items[0] if items else None
        except Exception as e:                      # noqa: BLE001
            last = e
    print(f"[추석] 중기 {path} {reg} {tmfc} 실패: {str(last)[:80]}")
    return None


def collect_mid(t: dt.datetime, key: str) -> dict:
    """{city: {YYYYMMDD: {tmax, tmin, tmax_l, tmax_h, tmin_l, tmin_h, sky, pop, src:'mid'}}}"""
    tmfc = t.strftime("%Y%m%d%H00")
    res = {}
    land_cache: dict[str, dict | None] = {}
    for city, (_, reg_ta, reg_land) in CITIES.items():
        ta = _mid_get("getMidTa", reg_ta, tmfc, key)
        if reg_land not in land_cache:
            land_cache[reg_land] = _mid_get("getMidLandFcst", reg_land, tmfc, key)
        land = land_cache[reg_land]
        if ta is None or land is None:
            res["_incomplete"] = True               # 응답 실패는 캐시하지 않는다 (자료가 정말 없는 것과 구분)
        days = {}
        for d in TARGET_DATES:
            n = (d - t.date()).days
            if ta is None or f"taMax{n}" not in ta:
                continue
            def _r(k):
                v = ta.get(k)
                return float(v) if v is not None and str(v) != "" else None
            rec = {"tmax": float(ta[f"taMax{n}"]), "tmin": float(ta[f"taMin{n}"]),
                   "tmax_l": _r(f"taMax{n}Low"), "tmax_h": _r(f"taMax{n}High"),
                   "tmin_l": _r(f"taMin{n}Low"), "tmin_h": _r(f"taMin{n}High"),
                   "sky": None, "sky_am": None, "sky_pm": None, "pop": None, "src": "mid"}
            if land:
                if f"wf{n}Am" in land:
                    am, pm = land.get(f"wf{n}Am", ""), land.get(f"wf{n}Pm", "")
                    rec["sky_am"], rec["sky_pm"] = am, pm
                    rec["sky"] = am if am == pm else f"{am}/{pm}"
                    pops = [land.get(f"rnSt{n}Am"), land.get(f"rnSt{n}Pm")]
                    pops = [int(p) for p in pops if p is not None]
                    rec["pop"] = max(pops) if pops else None
                elif f"wf{n}" in land:
                    rec["sky"] = land.get(f"wf{n}")
                    rec["pop"] = int(land[f"rnSt{n}"]) if land.get(f"rnSt{n}") is not None else None
            days[d.strftime("%Y%m%d")] = rec
        res[city] = days
    return res


# ── 수집(캐시) · 병합 ──────────────────────────────────────────────────
def collect(now: dt.datetime, start: dt.datetime, key: str) -> list[dict]:
    os.makedirs(CACHE_DIR, exist_ok=True)
    got = []
    for kind, t in issuances(now, start):
        p = _cache_path(kind, t)
        if os.path.exists(p):
            got.append(json.load(open(p, encoding="utf-8")))
            continue
        data = collect_short(t, key) if kind == "short" else collect_mid(t, key)
        incomplete = bool(data.pop("_incomplete", False))
        n_days = sum(len(v) for v in data.values())
        rec = {"kind": kind, "issue": t.strftime("%Y-%m-%d %H:00"), "issue_key": f"{t:%Y%m%d%H}",
               "cities": data, "n_days": n_days, "fetched_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M")}
        if incomplete:
            print(f"[추석] 수집 {kind} {t:%m-%d %H시}: 일부 실패 — 캐시하지 않음(다음 실행에 재시도), 임시 표시 항목 {n_days}")
        elif len(data) == len(CITIES):
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fp:
                json.dump(rec, fp, ensure_ascii=False, indent=0); fp.flush(); os.fsync(fp.fileno())
            os.replace(tmp, p)
            print(f"[추석] 수집 {kind} {t:%m-%d %H시}: 대상일 항목 {n_days}")
        got.append(rec)
    return got


def merge(records: list[dict]) -> dict:
    """사이트·그림용 구조: {issuances: [...], cities: {city: {date: [{issue, ...}, ...]}}}"""
    iss = [{"key": r["issue_key"], "label": f"{r['issue'][5:10]} {r['issue'][11:13]}시", "kind": r["kind"]} for r in records]
    cities = {c: {d.strftime("%Y%m%d"): [] for d in TARGET_DATES} for c in CITIES}
    for r in records:
        for city, days in r["cities"].items():
            for ds, rec in days.items():
                if ds in cities[city]:
                    cities[city][ds].append({"issue": r["issue_key"], **rec})
    used = {x["issue"] for c in cities.values() for lst in c.values() for x in lst}
    eff = [i for i in iss if i["key"] in used]                     # 대상일 자료가 실제로 있는 발표만 (제목·카톡 키용)
    return {"generated_kst": dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "targets": [d.strftime("%Y%m%d") for d in TARGET_DATES],
            "issuances": iss, "effective_issuances": eff, "latest_key": (eff[-1]["key"] if eff else None),
            "latest_label": (eff[-1]["label"] if eff else None), "cities": cities, "city_order": list(CITIES)}


# ── 그림 ──────────────────────────────────────────────────────────────
def plot(m: dict, path: str, ds: str = "20260925", max_units: float = 40.0) -> None:
    """발표별 변경 로그 그림(대상일 하나, 기본 추석 당일). 발표마다 머리띠(발표시각·중기/단기·요약) 아래에
    기온이나 개황이 바뀐 도시만 한 줄씩: 도시 | 최고 27→29 (+2) / 최저 17→16 (=) | 개황 맑음→구름많음.
    기온 칸 테두리 위/아래 절반 = Δ최고/Δ최저(빨강 상승·파랑 하락, 진할수록 큼), 개황 칸 노랑 = 개황 변화.
    한 장에 들어가지 않으면 최근 발표부터 채우고 앞부분은 생략 표시(전체는 페이지)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.patches import Rectangle
    for f in ("Malgun Gothic", "NanumGothic", "Noto Sans CJK KR", "Noto Sans KR"):
        if any(f == x.name for x in font_manager.fontManager.ttflist):
            matplotlib.rc("font", family=f); break
    matplotlib.rcParams["axes.unicode_minus"] = False
    wd = ["월", "화", "수", "목", "금", "토", "일"]
    d = dt.datetime.strptime(ds, "%Y%m%d")
    dlabel = f"{d.month}/{d.day}({wd[d.weekday()]}){' 추석' if ds == '20260925' else ''}"
    groups = change_log(m, ds)
    H_HEAD, H_ROW, H_GAP = 1.0, 2.0, 0.35
    def units(g): return H_HEAD + H_ROW * len(g["changed"]) + H_GAP
    # 뒤(최신)에서부터 채워 넣는다
    shown, total = [], 0.0
    for g in reversed(groups):
        if shown and total + units(g) > max_units:
            break
        shown.insert(0, g); total += units(g)
    skipped = len(groups) - len(shown)
    fig_h = 0.175 * max(total, 4) + 1.25
    fig, ax = plt.subplots(figsize=(9.0, fig_h)); ax.set_xlim(0, 1); ax.set_ylim(max(total, 3.0) + (0.8 if skipped else 0.2), -0.2); ax.axis("off")
    X_CITY, X_T0, X_T1, X_S0, X_S1 = 0.005, 0.105, 0.455, 0.465, 0.995
    y = 0.0
    if skipped:
        ax.text(0.5, 0.3, f"… 이전 {skipped}개 발표는 페이지의 전체 로그에서 (여기엔 최근 {len(shown)}개 발표)", ha="center", va="center", fontsize=8.5, color="#888")
        y = 0.8
    if not groups:
        ax.text(0.5, 1.5, "아직 이 날짜의 예보가 없습니다", ha="center", va="center", fontsize=11, color="#888")
    def frame(x0, y0, x1, y1, top, bot):
        xm = 0.004; ym = (y0 + y1) / 2
        if top:
            ax.plot([x0 + xm, x0 + xm, x1 - xm, x1 - xm], [ym, y0 + 0.06, y0 + 0.06, ym], color=top, lw=3, solid_capstyle="butt", solid_joinstyle="miter", zorder=3)
        if bot:
            ax.plot([x0 + xm, x0 + xm, x1 - xm, x1 - xm], [ym, y1 - 0.06, y1 - 0.06, ym], color=bot, lw=3, solid_capstyle="butt", solid_joinstyle="miter", zorder=3)
    for g in shown:
        ax.add_patch(Rectangle((0, y), 1, H_HEAD, facecolor="#e6e9ee", edgecolor="none", zorder=1))
        ax.text(0.01, y + H_HEAD / 2, _issue_title(g), va="center", fontsize=10.5, weight="bold", color="#222", zorder=2)
        parts = []
        nc = len(g["changed"])
        if nc: parts.append(f"변경 {nc}도시")
        if g["unchanged"]: parts.append(f"변경 없음 {len(g['unchanged'])}")
        if g["handoff_only"]: parts.append("중기→단기 전환(변경 없음) " + "·".join(g["handoff_only"]))
        if g["new"]:
            parts.append("초기 기준선 8도시" if len(g["new"]) == len(m["city_order"]) else "신규 " + "·".join(g["new"]))
        if g["missing"]: parts.append("미갱신 " + "·".join(g["missing"]))
        ax.text(0.99, y + H_HEAD / 2, " · ".join(parts), va="center", ha="right", fontsize=8.5, color="#444", zorder=2)
        y += H_HEAD
        for ch in g["changed"]:
            pv, rc = ch["prev"], ch["rec"]
            ax.add_patch(Rectangle((0, y), 1, H_ROW, facecolor="white", edgecolor="#e0e0e0", lw=0.6, zorder=1))
            ax.text(X_CITY + 0.045, y + H_ROW / 2, ch["city"], ha="center", va="center", fontsize=10.5, weight="bold", zorder=2)
            sub = []
            if ch["handoff"]: sub.append("중→단")
            if ch["prev"]["issue"] != g["prev_common"]: sub.append("← " + ch["prev"]["issue"][4:6] + "-" + ch["prev"]["issue"][6:8] + " " + ch["prev"]["issue"][8:10] + "시")
            if sub:
                ax.text(X_CITY + 0.045, y + H_ROW * 0.82, " ".join(sub), ha="center", va="center", fontsize=6.3, color="#777", zorder=2)
            # 기온 칸
            ax.add_patch(Rectangle((X_T0, y + 0.05), X_T1 - X_T0, H_ROW - 0.1, facecolor="white", edgecolor="#d0d0d0", lw=0.6, zorder=1))
            frame(X_T0, y + 0.05, X_T1, y + H_ROW - 0.05, _edge_color(ch["dmax"]), _edge_color(ch["dmin"]))
            t1 = f"최고 {pv['tmax']:.0f}→{rc['tmax']:.0f} ({_sgn(ch['dmax'])})" if ch["dmax"] else f"최고 {rc['tmax']:.0f} (=)"
            t2 = f"최저 {pv['tmin']:.0f}→{rc['tmin']:.0f} ({_sgn(ch['dmin'])})" if ch["dmin"] else f"최저 {rc['tmin']:.0f} (=)"
            ax.text(X_T0 + 0.025, y + H_ROW * 0.31, t1, va="center", fontsize=9.5, color="#8E0000" if ch["dmax"] > 0 else ("#0D3B70" if ch["dmax"] < 0 else "#666"), weight="bold" if ch["dmax"] else "normal", zorder=4)
            ax.text(X_T0 + 0.025, y + H_ROW * 0.69, t2, va="center", fontsize=9.5, color="#8E0000" if ch["dmin"] > 0 else ("#0D3B70" if ch["dmin"] < 0 else "#666"), weight="bold" if ch["dmin"] else "normal", zorder=4)
            # 개황 칸
            ax.add_patch(Rectangle((X_S0, y + 0.05), X_S1 - X_S0, H_ROW - 0.1, facecolor="#fff2cc" if ch["wx"] else "white", edgecolor="#d0d0d0", lw=0.6, zorder=1))
            sk = f"개황 {pv.get('sky') or '-'} → {rc.get('sky') or '-'}" if ch["wx"] else f"개황 {rc.get('sky') or '-'} (=)"
            if rc.get("pop") is not None: sk += f" · 강수확률 {rc['pop']}%"
            if ch["handoff"]: sk += " · 중기→단기 전환"
            ax.text(X_S0 + 0.012, y + H_ROW / 2, sk, va="center", fontsize=9.5, color="#222" if ch["wx"] else "#666", weight="bold" if ch["wx"] else "normal", zorder=4, wrap=True)
            y += H_ROW
        y += H_GAP
    fig.suptitle(f"{dlabel} 예보 변경 로그 — 이전 발표 → 이번 발표에서 바뀐 도시만 · 최신 {m.get('latest_label') or '-'}", fontsize=12, weight="bold", y=0.995)
    fig.text(0.5, 0.006, "기온 칸 테두리 위쪽 절반 = 최고기온, 아래쪽 절반 = 최저기온 변화(빨강 상승·파랑 하락, 진할수록 큼: 1·2·3℃↑) · 노랑 = 개황 변화 · 비교 = 그 도시·날짜의 직전 유효 발표",
             ha="center", fontsize=7.5, color="#555")
    fig.tight_layout(rect=[0, 0.02, 1, 0.975])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fig.savefig(path, dpi=130); plt.close(fig)


def plot_card(m: dict, path: str) -> None:
    """카톡 카드용 요약표: 행=도시, 열=대상일. 칸 = 최고/최저 · 개황 · (직전 대비 Δ). 800×700 근처."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for f in ("Malgun Gothic", "NanumGothic", "Noto Sans CJK KR", "Noto Sans KR"):
        if any(f == x.name for x in font_manager.fontManager.ttflist):
            matplotlib.rc("font", family=f); break
    dates = m["targets"]; cities = m["city_order"]
    wd = ["월", "화", "수", "목", "금", "토", "일"]
    fig, ax = plt.subplots(figsize=(8.0, 0.62 * len(cities) + 1.6))
    ax.axis("off")
    cols = []
    for ds in dates:
        d = dt.datetime.strptime(ds, "%Y%m%d"); cols.append(f"{d.month}/{d.day}({wd[d.weekday()]})" + ("★" if ds == "20260925" else ""))
    cell, colors = [], []
    for city in cities:
        row, crow = [], []
        for ds in dates:
            recs = m["cities"][city][ds]
            if not recs:
                row.append("—"); crow.append("#f4f4f4"); continue
            l = recs[-1]; txt = f"{l['tmax']:.0f} / {l['tmin']:.0f}" + chr(10) + f"{(l.get('sky') or '-')}"
            if l.get("pop") is not None: txt += f" {l['pop']}%"
            if len(recs) >= 2:
                dmx, dmn = l["tmax"] - recs[-2]["tmax"], l["tmin"] - recs[-2]["tmin"]
                if dmx or dmn: txt += chr(10) + f"Δ{dmx:+.0f}/{dmn:+.0f}"
            row.append(txt); crow.append("#ffffff" if l["src"] == "short" else "#f0f4fa")
        cell.append(row); colors.append(crow)
    tbl = ax.table(cellText=cell, rowLabels=cities, colLabels=cols, cellColours=colors, loc="center", cellLoc="center")
    tbl.auto_set_font_size(False); tbl.set_fontsize(8.5); tbl.scale(1.0, 2.6)
    for (r, c), cl in tbl.get_celld().items():
        if r == 0 or c == -1: cl.set_text_props(weight="bold"); cl.set_facecolor("#e8e8e8")
    latest = m.get("latest_label") or "-"
    fig.suptitle(f"추석 연휴 예보 · 8대도시 · 최신 발표 {latest}", fontsize=12, weight="bold", y=0.98)
    fig.text(0.5, 0.02, "최고/최저 ℃ · 개황 · 강수확률 · Δ = 직전 발표 대비(최고/최저) · 흰칸 = 단기예보, 연파랑 = 중기예보", ha="center", fontsize=8, color="#555")
    fig.savefig(path, dpi=150, bbox_inches="tight"); plt.close(fig)



UP = ["#E57373", "#D32F2F", "#8E0000"]        # |Δ| 1 / 2 / ≥3 ℃ 상승
DOWN = ["#64B5F6", "#1E6FC0", "#0D3B70"]      # |Δ| 1 / 2 / ≥3 ℃ 하락


def _edge_color(delta):
    a = abs(delta)
    if a == 0:
        return None
    i = 0 if a < 2 else (1 if a < 3 else 2)
    return UP[i] if delta > 0 else DOWN[i]


def _sgn(d):
    return f"{d:+.0f}" if d else "="


def _sky(t):
    """개황 비교용 정규화(앞뒤·중복 공백 제거). 모든 뷰가 이 함수로 비교한다."""
    return " ".join((t or "").split())


def change_log(m: dict, ds: str) -> list[dict]:
    """대상일 ds 의 발표별 변경 로그(발표 순). 도시마다 그 도시·날짜의 직전 유효 기록과 비교.
    group = {key,label,kind, changed:[{city,prev,rec,dmax,dmin,wx,handoff}], unchanged:[city], new:[city], missing:[city], handoff_only:[city]}"""
    cities = m["city_order"]; out = []
    lab = {i["key"]: i for i in m["issuances"]}
    for i in m["effective_issuances"]:
        k = i["key"]
        if not any(x["issue"] == k for c in cities for x in m["cities"][c][ds]):
            continue
        g = {"key": k, "label": i["label"], "kind": i["kind"], "changed": [], "unchanged": [], "new": [], "missing": [], "handoff_only": [],
             "prev_of": {}, "prev_common": None, "prev_label": None, "prev_kind": None}
        for c in cities:
            recs = m["cities"][c][ds]
            rec = next((x for x in recs if x["issue"] == k), None)
            before = [x for x in recs if x["issue"] < k]
            if rec is None:
                if before:
                    g["missing"].append(c)
                continue
            if not before:
                g["new"].append(c); continue
            pv = before[-1]; g["prev_of"][c] = pv["issue"]
            dmax, dmin = rec["tmax"] - pv["tmax"], rec["tmin"] - pv["tmin"]
            wx = _sky(rec.get("sky")) != _sky(pv.get("sky"))
            ho = pv["src"] == "mid" and rec["src"] == "short"
            if dmax or dmin or wx:
                g["changed"].append({"city": c, "prev": pv, "rec": rec, "dmax": dmax, "dmin": dmin, "wx": wx, "handoff": ho})
            elif ho:
                g["handoff_only"].append(c)
            else:
                g["unchanged"].append(c)
        if g["prev_of"]:                                   # 가장 많은 도시가 비교한 이전 발표 = 머리띠의 '→' 왼쪽
            pk = max(set(g["prev_of"].values()), key=lambda x: (list(g["prev_of"].values()).count(x), x))
            g["prev_common"] = pk
            g["prev_label"] = lab[pk]["label"] if pk in lab else pk
            g["prev_kind"] = lab[pk]["kind"] if pk in lab else ""
        out.append(g)
    return out


def _issue_title(g: dict) -> str:
    """머리띠 제목: '09-16 18시 중기 → 09-17 06시 중기 발표' (이전 발표가 없으면 '09-16 18시 중기 발표')."""
    kind = "중기" if g["kind"] == "mid" else "단기"
    if g["prev_common"]:
        pk = "중기" if g["prev_kind"] == "mid" else "단기"
        return f"{g['prev_label']} {pk} → {g['label']} {kind} 발표"
    return f"{g['label']} {kind} 발표"


def _draw_edges(fig, tbl, edges):
    """matplotlib 표 위에 칸 테두리 색을 덧그린다. edges: {(row, col): (top_color|None, bottom_color|None)} (row 1 = 첫 자료행)."""
    from matplotlib.lines import Line2D
    fig.canvas.draw()
    inv = fig.transFigure.inverted()
    for (r, c), (top, bot) in edges.items():
        if not (top or bot):
            continue
        cell = tbl[r, c]
        bb = cell.get_window_extent(fig.canvas.get_renderer())
        (x0, y0), (x1, y1) = inv.transform([[bb.x0, bb.y0], [bb.x1, bb.y1]])
        ym = (y0 + y1) / 2; dx = 0.0012; dy = 0.0025          # 선 두께의 절반만큼 안쪽으로
        def _poly(pts, col):
            fig.add_artist(Line2D([p[0] for p in pts], [p[1] for p in pts], transform=fig.transFigure, color=col, lw=3.0, solid_capstyle="butt", solid_joinstyle="miter"))
        if top:   # 상반 프레임: 왼쪽 중간 → 왼쪽 위 → 오른쪽 위 → 오른쪽 중간
            _poly([(x0 + dx, ym), (x0 + dx, y1 - dy), (x1 - dx, y1 - dy), (x1 - dx, ym)], top)
        if bot:   # 하반 프레임
            _poly([(x0 + dx, ym), (x0 + dx, y0 + dy), (x1 - dx, y0 + dy), (x1 - dx, ym)], bot)


def compare_cells(m: dict) -> dict:
    """칸(도시, 대상일)마다 최신 발표 기준 비교 상태 (Astra 제안 9/17):
       none(예보 없음) / not_updated(이번 발표엔 이 칸 자료 없음) / new(첫 기록) / handoff(중기→단기 첫 전환) / changed / unchanged.
       Δ 는 그 칸의 직전 유효 기록 대비. 개황 변화는 표시 문자열 비교(강수확률 제외)."""
    latest = m.get("latest_key")
    out = {}
    for city in m["city_order"]:
        for ds in m["targets"]:
            recs = m["cities"][city][ds]
            if not recs:
                out[(city, ds)] = {"state": "none", "latest": None, "prev": None, "dmax": None, "dmin": None, "wx": False}
                continue
            l = recs[-1]
            if l["issue"] != latest:
                out[(city, ds)] = {"state": "not_updated", "latest": l, "prev": None, "dmax": None, "dmin": None, "wx": False}
                continue
            if len(recs) == 1:
                out[(city, ds)] = {"state": "new", "latest": l, "prev": None, "dmax": None, "dmin": None, "wx": False}
                continue
            p = recs[-2]
            dmax, dmin = l["tmax"] - p["tmax"], l["tmin"] - p["tmin"]
            wx = _sky(l.get("sky")) != _sky(p.get("sky"))
            if l["src"] == "short" and p["src"] == "mid":
                state = "handoff"
            else:
                state = "changed" if (dmax or dmin or wx) else "unchanged"
            out[(city, ds)] = {"state": state, "latest": l, "prev": p, "dmax": dmax, "dmin": dmin, "wx": wx}
    return out


def digest(m: dict, cmp: dict) -> str:
    """카톡 설명·페이지 머리 한 줄: 발표 · 갱신/변경 칸 수 · 최대 기온 변경 · 개황 변화 · 전환."""
    label = m.get("latest_label") or "-"
    upd = [v for v in cmp.values() if v["state"] in ("new", "handoff", "changed", "unchanged")]
    new = [v for v in cmp.values() if v["state"] == "new"]
    if upd and len(new) == len(upd):
        n_none = sum(1 for v in cmp.values() if v["state"] == "none")
        return f"{label} 발표 · 초기 기준선 {len(new)}칸 기록" + (f" · 미발표 {n_none}칸" if n_none else "") + " · 비교는 다음 발표부터"
    chg = [(k, v) for k, v in cmp.items() if v["state"] == "changed" or (v["state"] == "handoff" and (v["dmax"] or v["dmin"] or v["wx"]))]
    ho = sum(1 for v in cmp.values() if v["state"] == "handoff" and not (v["dmax"] or v["dmin"] or v["wx"]))
    parts = [f"{label} 발표 · 갱신 {len(upd)}칸 중 변경 {len(chg)}칸"]
    if chg:
        k, v = max(chg, key=lambda kv: max(abs(kv[1]["dmax"] or 0), abs(kv[1]["dmin"] or 0)))
        d = k[1]; which = "최고" if abs(v["dmax"]) >= abs(v["dmin"]) else "최저"
        a, b = (v["prev"]["tmax"], v["latest"]["tmax"]) if which == "최고" else (v["prev"]["tmin"], v["latest"]["tmin"])
        if a != b:
            parts.append(f"최대 변경 {d[4:6].lstrip('0')}/{d[6:8].lstrip('0')} {k[0]} {which} {a:.0f}→{b:.0f}℃")
        wx = [k for k, v in chg if v["wx"]]
        if wx:
            k0 = wx[0]; parts.append(f"개황 변화 {len(wx)}칸(예: {k0[1][4:6].lstrip('0')}/{k0[1][6:8].lstrip('0')} {k0[0]} {cmp[k0]['prev'].get('sky') or '-'}→{cmp[k0]['latest'].get('sky') or '-'})")
    if ho:
        parts.append(f"중기→단기 전환(변화 없음) {ho}칸")
    n_new = len(new)
    if n_new:
        parts.append(f"신규 {n_new}칸")
    return " · ".join(parts)


def plot_revision(m: dict, cmp: dict, path: str) -> None:
    """카톡 카드: 변경 행렬 8도시 × 5일 — 칸 = 이번 발표의 Δ최고/Δ최저(직전 유효 기록 대비).
       신규 / · (무변경) / 미갱신 / 전환 표기. 강조: |Δ|≥2 또는 개황 변화. 아래에 최신 절대값 표는 두지 않는다(페이지 담당)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for f in ("Malgun Gothic", "NanumGothic", "Noto Sans CJK KR", "Noto Sans KR"):
        if any(f == x.name for x in font_manager.fontManager.ttflist):
            matplotlib.rc("font", family=f); break
    matplotlib.rcParams["axes.unicode_minus"] = False
    wd = ["월", "화", "수", "목", "금", "토", "일"]
    cities, dates = m["city_order"], m["targets"]
    fig = plt.figure(figsize=(7.2, 7.2)); ax = fig.add_axes([0.09, 0.22, 0.89, 0.66]); ax.axis("off")   # 왼쪽 여백 = 도시 행머리
    cols = []
    for ds in dates:
        d = dt.datetime.strptime(ds, "%Y%m%d"); cols.append(f"{d.month}/{d.day}({wd[d.weekday()]})" + ("★" if ds == "20260925" else ""))
    cell, colr, edges = [], [], {}
    for ri, city in enumerate(cities, 1):
        row, crow = [], []
        for ci, ds in enumerate(dates):
            v = cmp[(city, ds)]; st = v["state"]; l = v["latest"]
            if st == "none":
                row.append("—"); crow.append("#f4f4f4")
            elif st == "not_updated":
                row.append(f"미갱신\n{l['tmax']:.0f}/{l['tmin']:.0f}"); crow.append("#ececec")
            elif st == "new":
                row.append(f"신규\n{l['tmax']:.0f}/{l['tmin']:.0f} {_short_sky(l.get('sky'))}"); crow.append("#ffffff" if l["src"] == "short" else "#f0f4fa")
            else:
                dmax, dmin = v["dmax"], v["dmin"]
                txt = f"{dmax:+.0f}/{dmin:+.0f}" if (dmax or dmin) else "·"
                if st == "handoff":
                    txt = "전환 " + txt
                if v["wx"]:
                    txt += " ※"
                txt += f"\n{l['tmax']:.0f}/{l['tmin']:.0f} {_short_sky(l.get('sky'))}"
                emph = v["wx"]
                edges[(ri, ci)] = (_edge_color(dmax), _edge_color(dmin))
                row.append(txt); crow.append("#ffe08a" if emph else ("#ffffff" if l["src"] == "short" else "#f0f4fa"))
        cell.append(row); colr.append(crow)
    tbl = ax.table(cellText=cell, rowLabels=cities, colLabels=cols, cellColours=colr, loc="center", cellLoc="center")
    tbl.auto_set_font_size(False); tbl.set_fontsize(9); tbl.scale(1.0, 2.35)
    for (r, c), cl in tbl.get_celld().items():
        if r == 0 or c == -1: cl.set_text_props(weight="bold"); cl.set_facecolor("#e8e8e8")
    _draw_edges(fig, tbl, edges)
    fig.text(0.5, 0.955, f"추석 연휴 예보 변화 · {m.get('latest_label') or '-'} 발표", ha="center", fontsize=14, weight="bold")
    fig.text(0.5, 0.915, "칸 위 = 직전 발표 대비 Δ최고/Δ최저 ℃ (· 무변경, ※ 개황 변화, 전환 = 중기→단기) · 칸 아래 = 최신 최고/최저·개황", ha="center", fontsize=8.5, color="#444")
    # 아래: 요약·상위 변경
    chg = sorted([(k, v) for k, v in cmp.items() if v["state"] in ("changed", "handoff") and (v["dmax"] or v["dmin"] or v["wx"])],
                 key=lambda kv: -max(abs(kv[1]["dmax"] or 0), abs(kv[1]["dmin"] or 0), 1.5 if kv[1]["wx"] else 0))
    import textwrap
    lines = textwrap.wrap(digest(m, cmp), 62)[:2] or [digest(m, cmp)]   # 요약이 길면 두 줄로
    for k, v in chg[:3]:
        d = k[1]; bits = []
        if v["dmax"]: bits.append(f"최고 {v['prev']['tmax']:.0f}→{v['latest']['tmax']:.0f}")
        if v["dmin"]: bits.append(f"최저 {v['prev']['tmin']:.0f}→{v['latest']['tmin']:.0f}")
        if v["wx"]: bits.append(f"개황 {v['prev'].get('sky') or '-'}→{v['latest'].get('sky') or '-'}")
        lines.append(f"{d[4:6].lstrip('0')}/{d[6:8].lstrip('0')} {k[0]}: " + ", ".join(bits))
    y = 0.165; n_sum = len(textwrap.wrap(digest(m, cmp), 62)[:2] or [1])
    for i, ln in enumerate(lines):
        fig.text(0.04, y - 0.028 * i, ln, fontsize=9 if i < n_sum else 8.5, color="#222" if i < n_sum else "#a04000", ha="left")
    fig.text(0.5, 0.015, "흰칸 단기 · 연파랑 중기 · 노랑 = 개황 변화 · 회색 = 이번 발표 자료 없음 · 테두리 위/아래 절반 = 최고/최저 변화(빨강↑ 파랑↓, 진할수록 큼)", ha="center", fontsize=7.5, color="#555")
    fig.savefig(path, dpi=150); plt.close(fig)


def _short_sky(txt):
    if not txt:
        return "-"
    return (txt.replace("구름많음", "구름").replace("구름조금", "조금").replace("소나기", "소낙")
               .replace("빗방울", "빗방울"))


def plot_history(m: dict, out_dir: str) -> list[str]:
    """대상일마다 이력표 그림: 행 = 발표시각(자료 있는 것), 열 = 8도시, 칸 = 최고/최저 개황. 직전 행 대비 변한 칸은 색.
    chuseok_hist_{YYYYMMDD}.png 5장 + 전체를 세로로 이어 붙인 chuseok_history.png."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for f in ("Malgun Gothic", "NanumGothic", "Noto Sans CJK KR", "Noto Sans KR"):
        if any(f == x.name for x in font_manager.fontManager.ttflist):
            matplotlib.rc("font", family=f); break
    matplotlib.rcParams["axes.unicode_minus"] = False
    wd = ["월", "화", "수", "목", "금", "토", "일"]
    cities = m["city_order"]; iss = m["effective_issuances"]
    paths = []
    n_rows_total = 0
    per_date = []
    for ds in m["targets"]:
        rows = [i for i in iss if any(x["issue"] == i["key"] for c in cities for x in m["cities"][c][ds])]
        cell, colr, edges = [], [], {}
        prev = {c: None for c in cities}
        for ri, i in enumerate(rows, 1):
            row, crow = [], []
            for ci, c in enumerate(cities):
                rec = next((x for x in m["cities"][c][ds] if x["issue"] == i["key"]), None)
                if rec is None:
                    row.append("—"); crow.append("#f4f4f4"); continue
                txt = f"{rec['tmax']:.0f}/{rec['tmin']:.0f} {_short_sky(rec.get('sky'))}"
                col = "#ffffff" if rec["src"] == "short" else "#f0f4fa"
                p = prev[c]
                if p is not None:
                    dmax, dmin = rec["tmax"] - p["tmax"], rec["tmin"] - p["tmin"]
                    if _sky(p.get("sky")) != _sky(rec.get("sky")):
                        col = "#fff2cc"             # 개황이 달라진 칸
                    edges[(ri, ci)] = (_edge_color(dmax), _edge_color(dmin))   # 위=최고, 아래=최저
                    txt += f"\nΔ {dmax:+.0f}/{dmin:+.0f}"
                else:
                    txt += "\n기준"
                row.append(txt); crow.append(col); prev[c] = rec
            cell.append(row); colr.append(crow)
        if rows:                                   # 합계 행: 처음→최신 (기온 = 최신−첫 기록, 개황 = 인접 발표 간 바뀐 횟수)
            frow = []
            for c in cities:
                recs = [x for x in m["cities"][c][ds]]
                if len(recs) < 2:
                    frow.append("비교 없음"); continue
                nwx = sum(1 for a, b in zip(recs, recs[1:]) if _sky(a.get("sky")) != _sky(b.get("sky")))
                frow.append(f"Δ {recs[-1]['tmax'] - recs[0]['tmax']:+.0f}/{recs[-1]['tmin'] - recs[0]['tmin']:+.0f}\n개황 변경 {nwx}회")
            cell.append(frow); colr.append(["#e4e4e4"] * len(cities))
        per_date.append((ds, rows, cell, colr, edges))
        n_rows_total += max(len(rows), 1)
    # 날짜별 개별 그림 + 합본
    for ds, rows, cell, colr, edges in per_date:
        d = dt.datetime.strptime(ds, "%Y%m%d")
        title = f"{d.month}/{d.day}({wd[d.weekday()]}){' 추석' if ds == '20260925' else ''} 예보 이력 — 행: 발표시각, 열: 도시 (최고/최저 ℃ · 개황)"
        fig, ax = plt.subplots(figsize=(9.6, 0.47 * (max(len(rows), 1) + 1) + 1.1)); ax.axis("off")
        if rows:
            rl = [i["label"] + (" 중" if i["kind"] == "mid" else " 단") for i in rows] + ["처음→최신"]
            tbl = ax.table(cellText=cell, rowLabels=rl, colLabels=cities, cellColours=colr, loc="center", cellLoc="center")
            tbl.auto_set_font_size(False); tbl.set_fontsize(8.2); tbl.scale(1.0, 2.35)
            for (r, c), cl in tbl.get_celld().items():
                if r == 0 or c == -1: cl.set_text_props(weight="bold"); cl.set_facecolor("#e8e8e8")
                if r == len(rows) + 1: cl.set_text_props(weight="bold")
            _draw_edges(fig, tbl, edges)
        else:
            ax.text(0.5, 0.5, "아직 이 날짜의 예보가 없습니다", ha="center", va="center", fontsize=10, color="#888")
        fig.suptitle(title, fontsize=11, weight="bold", y=0.98)
        fig.text(0.5, 0.02, "흰칸 단기 · 연파랑 중기 · Δ = 직전 발표 대비 최고/최저 · 노랑 = 개황 변화 · 칸 테두리 위/아래 절반 = 최고/최저 변화(빨강 상승·파랑 하락, 진할수록 큼) · 마지막 행 = 첫 발표→최신 누적", ha="center", fontsize=8, color="#555")
        p = os.path.join(out_dir, f"chuseok_hist_{ds}.png"); fig.savefig(p, dpi=150, bbox_inches="tight"); plt.close(fig); paths.append(p)
    # 합본 (세로)
    from PIL import Image
    ims = [Image.open(p) for p in paths]
    w = max(im.width for im in ims); h = sum(im.height for im in ims) + 10 * (len(ims) - 1)
    canvas = Image.new("RGB", (w, h), "white"); y = 0
    for im in ims:
        canvas.paste(im, (0, y)); y += im.height + 10
    hp = os.path.join(out_dir, "chuseok_history.png"); canvas.save(hp); paths.append(hp)
    return paths


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--backfill", default="2026091617", help="추적 시작 발표(YYYYMMDDHH, KST). 기본 9/16 17시(사용자 지정 시작)")
    p.add_argument("--no-plot", action="store_true")
    a = p.parse_args()
    start = dt.datetime.strptime(a.backfill, "%Y%m%d%H").replace(tzinfo=KST)
    now = dt.datetime.now(KST)
    records = collect(now, start, auth_key())
    m = merge(records)
    os.makedirs(OUT, exist_ok=True)
    json.dump(m, open(os.path.join(OUT, "chuseok.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"[추석] 발표 {len(m['issuances'])}건 병합 → {OUT}/chuseok.json")
    if not a.no_plot:
        import shutil
        plot(m, os.path.join(OUT, "chuseok_latest.png"))
        plot_card(m, os.path.join(OUT, "chuseok_card.png"))
        plot_history(m, OUT)
        cmp = compare_cells(m)
        plot_revision(m, cmp, os.path.join(OUT, "chuseok_revision.png"))
        m["digest"] = digest(m, cmp)
        m["cell_states"] = {f"{c}|{d}": v["state"] for (c, d), v in cmp.items()}
        json.dump(m, open(os.path.join(OUT, "chuseok.json"), "w", encoding="utf-8"), ensure_ascii=False)
        if m.get("latest_key"):                     # 발표 키가 붙은 불변 사본 — 카톡은 이 주소가 실제로 서비스되는지 확인한 뒤 보낸다
            for base in ("chuseok_latest", "chuseok_card", "chuseok_history", "chuseok_hist_20260925", "chuseok_revision"):
                shutil.copy2(os.path.join(OUT, base + ".png"), os.path.join(OUT, base + "_" + m["latest_key"] + ".png"))
        print(f"[추석] 그림 → {OUT}/chuseok_latest.png, chuseok_card.png, chuseok_history.png (+ 키 사본)")


if __name__ == "__main__":
    main()
