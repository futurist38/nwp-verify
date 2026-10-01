"""발표별 비교 자료. 원자료와 이미 발행한 자료를 합쳐 누락으로 되돌리지 않는다.

python forecast_compare.py --site-dir site_build [--archive]
--archive는 시간별 작업만 사용: 단기 일별 캐시를 작은 발표별 기록으로 영구 보관.
"""
import argparse
from collections import Counter
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re

from config import VERIF_DIR

CITY_REGIONS = {"서울": "11B00000", "인천": "11B00000", "수원": "11B00000",
                "대전": "11C20000", "대구": "11H10000", "부산": "11H20000",
                "광주": "11F20000", "전주": "11F10000", "강릉": "11D20000", "제주": "11G00000"}
SKY = {1: ("clear", "맑음"), 3: ("partly", "구름많음"), 4: ("overcast", "흐림")}
PTY = {1: "비", 2: "비/눈", 3: "눈", 4: "소나기"}
VERSION = 1


def number(value, lo=-60, hi=60):
    try:
        v = float(value)
        return v if math.isfinite(v) and lo <= v <= hi else None
    except (ValueError, TypeError):
        return None


def read(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def write(path, data):
    content = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def weather(base, rain, label, basis, pop=None):
    return {"key": base + "|" + ",".join(sorted(rain)),
            "code": "rain" if rain else base, "label": label,
            "basis": basis, "pop": number(pop, 0, 100)}


def short_weather(raw, city, day, start):
    keys = [f"{day}{h:02d}" for h in range(start, start + 12)]
    skies = [raw.get(city + "#SKY", {}).get(k) for k in keys]
    rain = [raw.get(city + "#PTY", {}).get(k) for k in keys]
    if any(v not in SKY for v in skies) or any(v not in (0, 1, 2, 3, 4) for v in rain):
        return None
    counts = Counter(skies)
    sky = max(counts, key=lambda v: (counts[v], v))
    base, label = SKY[sky]
    kinds = sorted({PTY[v] for v in rain if v})
    if kinds:
        label += " · " + ", ".join(kinds)
    pops = [number(raw.get(city + "#POP", {}).get(k), 0, 100) for k in keys]
    return weather(base, kinds, label, "시간예보 12시간 요약", max(pops) if all(v is not None for v in pops) else None)


def mid_weather(value, pop):
    if not isinstance(value, str) or not value.strip():
        return None
    value = re.sub(r"\s+", "", value)
    base = "clear" if "맑" in value else "partly" if "구름많" in value else "overcast" if "흐" in value else None
    if base is None:
        return None
    rain = ["소나기"] if "소나기" in value else ["비/눈"] if "비" in value and "눈" in value else ["눈"] if "눈" in value else ["비"] if "비" in value else []
    label = {"clear": "맑음", "partly": "구름많음", "overcast": "흐림"}[base]
    if rain:
        label += " · " + ", ".join(rain)
    return weather(base, rain, label, "중기 공식 개황", pop)


def normalize_short(issue, raw):
    cities = {}
    for city, hours in raw.items():
        if "#" in city or city not in CITY_REGIONS:
            continue
        dates = sorted({k[:8] for suffix in ("", "#TMN", "#TMX", "#SKY", "#PTY")
                        for k in raw.get(city + suffix, {}) if re.fullmatch(r"\d{10}", k)})
        days = {}
        for day in dates:
            # 당일의 남은 시간만으로 일 극값을 만들지 않는다.
            vals = [number(hours.get(f"{day}{h:02d}")) for h in range(24)]
            rec = {"wx_am": short_weather(raw, city, day, 0),
                   "wx_pm": short_weather(raw, city, day, 12), "wx_day": None}
            for metric, cat, hour, fn in (("min", "TMN", 6, min), ("max", "TMX", 15, max)):
                v = number(raw.get(city + "#" + cat, {}).get(f"{day}{hour:02d}"))
                rec["t" + metric] = ({"value": v, "basis": cat} if v is not None else
                    {"value": fn(vals), "basis": "TMP24"} if all(v is not None for v in vals) else None)
            if rec["tmin"] and rec["tmax"] and rec["tmin"]["value"] > rec["tmax"]["value"]:
                rec["tmin"] = rec["tmax"] = None
            if any(v is not None for v in rec.values()):
                days[day] = rec
        if days:
            cities[city] = days
    return {"schema": VERSION, "issue": issue, "kind": "short", "cities": cities}


def normalize_mid(issue, temps, land):
    temps = merge(temps, land.get("_temperatures", {}))
    cities = {}
    issued = dt.datetime.strptime(issue, "%Y%m%d%H").date()
    for city, region in CITY_REGIONS.items():
        raw = land.get(region, {})
        dates = set(temps.get(city, {}))
        for key in raw:
            m = re.fullmatch(r"wf(\d+)(?:Am|Pm)?", key)
            if m:
                dates.add((issued + dt.timedelta(days=int(m[1]))).strftime("%Y%m%d"))
        days = {}
        for day in sorted(dates):
            n = (dt.datetime.strptime(day, "%Y%m%d").date() - issued).days
            rec = {}
            for metric in ("min", "max"):
                t = temps.get(city, {}).get(day, {})
                v = number(t.get(metric))
                rec["t" + metric] = {"value": v, "basis": "MID"} if v is not None else None
            for suffix, field in (("Am", "wx_am"), ("Pm", "wx_pm"), ("", "wx_day")):
                rec[field] = mid_weather(raw.get(f"wf{n}{suffix}"), raw.get(f"rnSt{n}{suffix}"))
            if any(v is not None for v in rec.values()):
                days[day] = rec
        if days:
            cities[city] = days
    return {"schema": VERSION, "issue": issue, "kind": "mid", "cities": cities}


def merge(old, new):
    """동일 발표의 누락만 채움. 공식 일 극값은 24시간 추정치보다 우선.

    이미 저장한 비결측 공식 값은 불변으로 취급하여 오래된 러너의 역행을 막는다.
    """
    if old is None:
        return new
    if new is None:
        return old
    if isinstance(old, dict) and isinstance(new, dict):
        if "value" in old and "basis" in old:
            if old["basis"] == "TMP24" and new.get("basis") in ("TMN", "TMX"):
                return new
            return old
        return {k: merge(old.get(k), new.get(k)) for k in old.keys() | new.keys()}
    return old


def snapshots(verif):
    out = {}
    def add(doc):
        key = doc["issue"] + "-" + doc["kind"]
        out[key] = merge(out.get(key), doc)
    for path in sorted((verif / "forecast_compare").glob("*.json")):
        doc = read(path)
        if doc.get("schema") == VERSION:
            add(doc)
    raw_issues = {}
    for path in sorted((verif / "kmafcst").glob("????????.json")):
        for issue, raw in read(path).items():
            if re.fullmatch(r"\d{10}", issue):
                raw_issues[issue] = merge(raw_issues.get(issue), raw)
    for issue, raw in raw_issues.items():
        add(normalize_short(issue, raw))
    mid_issues = {p.stem for folder in ("midfcst", "midland") for p in (verif / folder).glob("??????????.json")}
    for issue in sorted(mid_issues):
        add(normalize_mid(issue, read(verif / "midfcst" / (issue + ".json")),
                          read(verif / "midland" / (issue + ".json"))))
    return out


def export(site_dir, verif_dir=VERIF_DIR, archive=False):
    verif, dest = Path(verif_dir), Path(site_dir) / "forecast_compare"
    for key, doc in snapshots(verif).items():
        if not doc["cities"]:
            continue
        if archive:
            write(verif / "forecast_compare" / (key + ".json"), doc)
        path = dest / "issues" / (key + ".json")
        write(path, merge(read(path) or None, doc))
    entries = []
    for path in sorted((dest / "issues").glob("*.json")):
        doc = read(path)
        if doc.get("schema") != VERSION:
            continue
        entries.append({"issue": doc["issue"], "kind": doc["kind"], "file": "issues/" + path.name,
                        "rev": hashlib.sha256(path.read_bytes()).hexdigest()[:12],
                        "cities": sorted(doc["cities"]),
                        "temperature_cities": sorted(c for c, days in doc["cities"].items()
                                                     if any(r.get("tmin") or r.get("tmax") for r in days.values())),
                        "weather_cities": sorted(c for c, days in doc["cities"].items()
                                                 if any(r.get("wx_am") or r.get("wx_pm") or r.get("wx_day") for r in days.values())),
                        "targets": sorted({d for days in doc["cities"].values() for d in days})})
    write(dest / "index.json", {"schema": VERSION, "timezone": "Asia/Seoul", "issues": entries})
    print(f"[예보 비교] 발표별 자료 {len(entries)}건")
    return entries


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--site-dir", default="site_build")
    p.add_argument("--archive", action="store_true")
    args = p.parse_args()
    export(args.site_dir, archive=args.archive)
