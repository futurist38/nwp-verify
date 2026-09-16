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
import argparse
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
            if len(tmp) < 24:                       # 하루가 온전히 예보 범위에 들 때만 (부분 일자는 제외 — Sol 검토 9/16)
                continue
            tmax = f["TMX"].get(f"{ds}15")
            tmin = f["TMN"].get(f"{ds}06")
            if tmax is None:
                tmax = max(tmp)
            if tmin is None:
                tmin = min(tmp)
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
            days[ds] = {"tmax": float(tmax), "tmin": float(tmin), "sky": txt,
                        "pop": (max(pops) if pops else None), "src": "short"}
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
            rec = {"tmax": float(ta[f"taMax{n}"]), "tmin": float(ta[f"taMin{n}"]),
                   "tmax_l": float(ta.get(f"taMax{n}Low", 0)), "tmax_h": float(ta.get(f"taMax{n}High", 0)),
                   "tmin_l": float(ta.get(f"taMin{n}Low", 0)), "tmin_h": float(ta.get(f"taMin{n}High", 0)),
                   "sky": None, "pop": None, "src": "mid"}
            if land:
                if f"wf{n}Am" in land:
                    am, pm = land.get(f"wf{n}Am", ""), land.get(f"wf{n}Pm", "")
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
def plot(m: dict, path: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for f in ("Malgun Gothic", "NanumGothic", "Noto Sans CJK KR", "Noto Sans KR"):
        if any(f == x.name for x in font_manager.fontManager.ttflist):
            matplotlib.rc("font", family=f); break
    matplotlib.rcParams["axes.unicode_minus"] = False
    dates = m["targets"]; cities = m["city_order"]
    used = {x["issue"] for c in cities for ds in dates for x in m["cities"][c][ds]}
    iss = [i for i in m["issuances"] if i["key"] in used]          # 자료 있는 발표만 축에
    idx = {i["key"]: k for k, i in enumerate(iss)}
    fig, axes = plt.subplots(len(cities), len(dates), figsize=(3.1 * len(dates), 1.75 * len(cities) + 1.2), sharex=True)
    wd = ["월", "화", "수", "목", "금", "토", "일"]
    for r, city in enumerate(cities):
        for c, ds in enumerate(dates):
            ax = axes[r][c]
            recs = m["cities"][city][ds]
            xs = [idx[x["issue"]] for x in recs]
            for var, color in (("tmax", "#c22"), ("tmin", "#1a5fb4")):
                ys = [x[var] for x in recs]
                if xs:
                    ax.plot(xs, ys, "-o", ms=3.5, lw=1.2, color=color)
                    for x, y, rec in zip(xs, ys, recs):
                        if rec["src"] == "mid":
                            lo, hi = rec.get(f"{var}_l", 0) or 0, rec.get(f"{var}_h", 0) or 0
                            ax.plot([x, x], [y - lo, y + hi], color=color, lw=0.8, alpha=0.5)
                        else:
                            ax.plot(x, y, "s", ms=5, color=color)   # 단기예보 = 네모
                    ax.annotate(f"{ys[-1]:.0f}", (xs[-1], ys[-1]), xytext=(4, 0), textcoords="offset points",
                                fontsize=8, color=color, va="center")
            if recs:
                last = recs[-1]
                sky = last.get("sky") or "-"
                pop = f" {last['pop']}%" if last.get("pop") is not None else ""
                ax.text(0.02, 0.04, f"{sky}{pop}", transform=ax.transAxes, fontsize=7.5,
                        color="#333" if last["src"] == "short" else "#777", va="bottom")
                if len(recs) >= 2:
                    p_rec, l_rec = recs[-2], recs[-1]
                    dmx, dmn = l_rec["tmax"] - p_rec["tmax"], l_rec["tmin"] - p_rec["tmin"]
                    if dmx or dmn:
                        ax.text(0.98, 0.9, f"Δ최고 {dmx:+.0f} Δ최저 {dmn:+.0f}", transform=ax.transAxes, fontsize=7,
                                ha="right", va="top", color="#a00" if abs(dmx) >= 2 or abs(dmn) >= 2 else "#555")
            else:
                ax.text(0.5, 0.5, "예보 없음", transform=ax.transAxes, ha="center", va="center", fontsize=8, color="#999")
            ax.set_xlim(-0.5, max(len(iss) - 0.5, 0.5)); ax.set_ylim(8, 34); ax.grid(alpha=0.25)
            ax.tick_params(labelsize=7)
            if r == 0:
                d = dt.datetime.strptime(ds, "%Y%m%d")
                ax.set_title(f"{d.month}/{d.day}({wd[d.weekday()]})" + (" 추석" if ds == "20260925" else ""), fontsize=10, weight="bold")
            if c == 0:
                ax.set_ylabel(city, fontsize=10, weight="bold", rotation=0, ha="right", va="center", labelpad=18)
            if r == len(cities) - 1:
                ax.set_xticks(range(len(iss)))
                ax.set_xticklabels([i["label"][:8] for i in iss], rotation=60, fontsize=6.5)
    title = f"추석 연휴 예보 추적 — 8대도시 최고(빨강)·최저(파랑) ℃ · 발표시각 순 · 최신 {m.get('latest_label') or '-'}"
    fig.suptitle(title, fontsize=12, weight="bold", y=0.995)
    fig.text(0.01, 0.005, "○ 중기예보(세로선=기상청 예보범위) · ■ 단기예보 · 칸 아래 = 최신 개황·강수확률 · Δ = 직전 발표 대비 · 발표 05/11/17시(단기)·06/18시(중기)",
             fontsize=8, color="#555")
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
        cell, colr = [], []
        prev = {c: None for c in cities}
        for i in rows:
            row, crow = [], []
            for c in cities:
                rec = next((x for x in m["cities"][c][ds] if x["issue"] == i["key"]), None)
                if rec is None:
                    row.append("—"); crow.append("#f4f4f4"); continue
                txt = f"{rec['tmax']:.0f}/{rec['tmin']:.0f} {_short_sky(rec.get('sky'))}"
                col = "#ffffff" if rec["src"] == "short" else "#f0f4fa"
                p = prev[c]
                if p is not None and (p["tmax"] != rec["tmax"] or p["tmin"] != rec["tmin"] or (p.get("sky") or "") != (rec.get("sky") or "")):
                    col = "#fff2cc"                 # 직전 발표와 달라진 칸
                row.append(txt); crow.append(col); prev[c] = rec
            cell.append(row); colr.append(crow)
        per_date.append((ds, rows, cell, colr))
        n_rows_total += max(len(rows), 1)
    # 날짜별 개별 그림 + 합본
    for ds, rows, cell, colr in per_date:
        d = dt.datetime.strptime(ds, "%Y%m%d")
        title = f"{d.month}/{d.day}({wd[d.weekday()]}){' 추석' if ds == '20260925' else ''} 예보 이력 — 행: 발표시각, 열: 도시 (최고/최저 ℃ · 개황)"
        fig, ax = plt.subplots(figsize=(9.6, 0.42 * max(len(rows), 1) + 1.3)); ax.axis("off")
        if rows:
            tbl = ax.table(cellText=cell, rowLabels=[i["label"] for i in rows], colLabels=cities, cellColours=colr, loc="center", cellLoc="center")
            tbl.auto_set_font_size(False); tbl.set_fontsize(8.5); tbl.scale(1.0, 1.55)
            for (r, c), cl in tbl.get_celld().items():
                if r == 0 or c == -1: cl.set_text_props(weight="bold"); cl.set_facecolor("#e8e8e8")
        else:
            ax.text(0.5, 0.5, "아직 이 날짜의 예보가 없습니다", ha="center", va="center", fontsize=10, color="#888")
        fig.suptitle(title, fontsize=11, weight="bold", y=0.98)
        fig.text(0.5, 0.02, "흰칸 = 단기예보 · 연파랑 = 중기예보 · 노랑 = 직전 발표와 달라짐", ha="center", fontsize=8, color="#555")
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
        if m.get("latest_key"):                     # 발표 키가 붙은 불변 사본 — 카톡은 이 주소가 실제로 서비스되는지 확인한 뒤 보낸다
            for base in ("chuseok_latest", "chuseok_card", "chuseok_history", "chuseok_hist_20260925"):
                shutil.copy2(os.path.join(OUT, base + ".png"), os.path.join(OUT, base + "_" + m["latest_key"] + ".png"))
        print(f"[추석] 그림 → {OUT}/chuseok_latest.png, chuseok_card.png, chuseok_history.png (+ 키 사본)")


if __name__ == "__main__":
    main()
