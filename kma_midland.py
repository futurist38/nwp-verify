"""비교 화면용 중기 개황 원문 보관. 과거 기온 파일에 개황을 추정해서 넣지 않는다."""
import argparse
import datetime as dt
from pathlib import Path
import time

import requests
import sslfix  # noqa: F401
from config import VERIF_DIR
from forecast_compare import CITY_REGIONS, mid_weather, number, read, write, merge
from kma_midfcst import REGS
from kma_vilage import auth_key

URL = "https://apihub-pub.kma.go.kr/api/typ02/openApi/MidFcstInfoService/"


def temperature_days(item, issued):
    days = {}
    for n in range(1, 15):
        lo, hi = number(item.get(f"taMin{n}")), number(item.get(f"taMax{n}"))
        if lo is not None or hi is not None:
            rec = {"min": lo, "max": hi}
            for metric, field in (("min", "taMin"), ("max", "taMax")):
                for suffix, key in (("Low", "_l"), ("High", "_h")):
                    rec[metric + key] = number(item.get(f"{field}{n}{suffix}"), 0, 50)
            days[(issued + dt.timedelta(days=n)).strftime("%Y%m%d")] = rec
    return days


def fetch(region, issue, key, product="getMidLandFcst"):
    for _ in range(2):
        try:
            response = requests.get(URL + product, params={"regId": region, "tmFc": issue + "00",
                "pageNo": 1, "numOfRows": 10, "dataType": "JSON", "authKey": key}, timeout=20)
            response.raise_for_status()
            j = response.json()["response"]
            if str(j["header"]["resultCode"]) != "00":
                continue
            items = j["body"]["items"]["item"]
            if items and (any(mid_weather(v, None) for k, v in items[0].items() if k.startswith("wf")) or
                          any(number(v) is not None for k, v in items[0].items() if k.startswith("taMin"))):
                return items[0]
        except (requests.RequestException, ValueError, KeyError, TypeError):
            # 요청 URL/authKey를 로그에 노출하지 않는다.
            pass
    return None


def collect(days=2, budget=160):
    key = auth_key()
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).replace(tzinfo=None)
    start = time.monotonic()
    regions = sorted(set(CITY_REGIONS.values()))
    for back in range(days):
        for hour in (18, 6):
            issued = (now - dt.timedelta(days=back)).replace(hour=hour, minute=0, second=0, microsecond=0)
            if issued > now - dt.timedelta(minutes=15):
                continue
            issue = issued.strftime("%Y%m%d%H")
            path = Path(VERIF_DIR) / "midland" / (issue + ".json")
            raw = read(path)
            known_temps = read(Path(VERIF_DIR) / "midfcst" / (issue + ".json"))
            for city, region in REGS.items():
                if city in known_temps or city in raw.get("_temperature_ranges_checked", []):
                    continue
                if time.monotonic() - start > budget:
                    return
                item = fetch(region, issue, key, "getMidTa")
                if item:
                    days = temperature_days(item, issued)
                    if days:
                        old = raw.setdefault("_temperatures", {}).get(city)
                        raw["_temperatures"][city] = merge(old, days)
                        raw.setdefault("_temperature_ranges_checked", []).append(city)
                        write(path, raw)
            for region in regions:
                if region in raw:
                    continue
                if time.monotonic() - start > budget:
                    print("[중기 개황] 수집 시간 상한 — 다음 실행에서 이어 수집")
                    return
                item = fetch(region, issue, key)
                if item:
                    raw[region] = item
                    write(path, raw)  # 지역별 즉시 저장, timeout에도 수신분 보존
                else:
                    print(f"[중기 개황] {issue} {region} 자료 미수신")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=2)
    args = parser.parse_args()
    collect(args.days)
