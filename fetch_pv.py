# -*- coding: utf-8 -*-
"""
태양광 지역별 시간별 발전량(전력시장 계량분) 수집 — 공공데이터포털 B552115.

실측 확정 (2026-08-23):
  · GET apis.data.go.kr/B552115/PvAmountByLocHr/getPvAmountByLocHr
  · 필드: tradeYmd(거래일), tradeNo(1~24 거래시간), regionNm(17시도), amgo(발전량)
  · 이력 2021-01-01 ~ (갱신 지연 약 7주). 정렬은 최신일 우선(desc)
  · 키: .env DATA_GO_KR_KEY (Encoding/Decoding 모두 허용 — 자동 판별)

저장: verification/pv/YYYY.csv (연 단위, 키 tradeYmd+tradeNo+regionNm)
사용:
    python fetch_pv.py --full            # 전체 이력 최초 적재
    python fetch_pv.py                   # 증분 (저장된 최신일 이후만)
"""
import argparse
import datetime as dt
import glob
import os
import re
import time
import urllib.parse

import pandas as pd
import requests

import sslfix  # noqa: F401
from config import BASE_DIR, VERIF_DIR

URL = "https://apis.data.go.kr/B552115/PvAmountByLocHr/getPvAmountByLocHr"
PV_DIR = os.path.join(VERIF_DIR, "pv")
PAGE_TRY = 10000   # 일일 트래픽 100회 제한(사용자 확인) → 호출당 최대한 크게.
                   # 첫 응답의 실제 행수로 유효 페이지 크기를 자동 감지한다.
CALL_BUDGET = 95   # 한도 100회 대비 안전 여유


def _key() -> str:
    k = os.environ.get("DATA_GO_KR_KEY")
    if not k:
        m = re.search(r"DATA_GO_KR_KEY\s*=\s*(\S+)",
                      open(os.path.join(BASE_DIR, ".env"), encoding="utf-8").read())
        k = m.group(1)
    return urllib.parse.unquote(k) if "%" in k else k


class QuotaExceeded(Exception):
    """일일 요청 한도 초과 (returnReasonCode 22) — 재시도 무의미, 자정(KST) 리셋."""


def _get(params: dict) -> dict:
    last_body = ""
    for attempt in range(5):
        try:
            r = requests.get(URL, params={"serviceKey": _key(), "dataType": "json",
                                          **params}, timeout=120)
            last_body = r.text[:200]
            if "LIMITED_NUMBER_OF_SERVICE_REQUESTS" in r.text[:300]:
                raise QuotaExceeded("일일 요청 한도 초과 — 자정 이후 --resume")
            j = r.json()["response"]
            if j["header"]["resultCode"] != "00":
                raise RuntimeError(j["header"]["resultMsg"])
            return j["body"]
        except QuotaExceeded:
            raise
        except Exception as e:
            if attempt == 4:
                print(f"[PV] 원시응답: {last_body}")
                raise
            print(f"[PV] 재시도({attempt + 1}): {e}")
            time.sleep(min(5 * 3 ** attempt, 60))  # 5,15,45,60s — 분당 스로틀 대비


def latest_saved() -> str | None:
    files = sorted(glob.glob(os.path.join(PV_DIR, "????.csv")))
    if not files:
        return None
    df = pd.read_csv(files[-1], dtype={"tradeYmd": str})
    return df["tradeYmd"].max()


def save(df: pd.DataFrame):
    os.makedirs(PV_DIR, exist_ok=True)
    df["tradeYmd"] = df["tradeYmd"].astype(str)
    for yr, g in df.groupby(df["tradeYmd"].str[:4]):
        path = os.path.join(PV_DIR, f"{yr}.csv")
        if os.path.exists(path):
            old = pd.read_csv(path, dtype={"tradeYmd": str})
            g = pd.concat([old, g], ignore_index=True)
        g = (g.drop_duplicates(subset=["tradeYmd", "tradeNo", "regionNm"], keep="last")
              .sort_values(["tradeYmd", "tradeNo", "regionNm"]))
        g.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"[PV] {path}: {len(g)}행")


def fetch_all(stop_before: str | None = None, start_page: int = 1,
              resume: bool = False) -> int:
    """최신일부터 페이지 순회, 100페이지마다 저장(체크포인트).
    stop_before(YYYYMMDD) 이하를 만나면 중단(증분용). 반환: 저장한 총 행수."""
    def flush(rows):
        if not rows:
            return 0
        df = pd.DataFrame(rows)[["tradeYmd", "tradeNo", "regionNm", "amgo"]]
        df["tradeNo"] = df["tradeNo"].astype(int)
        if stop_before:
            df = df[df["tradeYmd"].astype(str) > stop_before]
        if len(df):
            save(df)
        return len(df)

    rows, page, total, n_saved, n_calls = [], start_page, None, 0, 0
    page_size = PAGE_TRY
    while True:
        if n_calls >= CALL_BUDGET:
            n_saved += flush(rows)
            print(f"[PV] 호출예산({CALL_BUDGET}회) 소진 — p{page}에서 정지, "
                  f"{n_saved}행 저장. 내일 --resume")
            return n_saved
        try:
            body = _get({"numOfRows": page_size, "pageNo": page})
            n_calls += 1
        except QuotaExceeded as e:
            n_saved += flush(rows)
            print(f"[PV] {e} — p{page}에서 중단, {n_saved}행 저장됨")
            return n_saved
        total = total or int(body["totalCount"])
        items = body.get("items", {}).get("item", [])
        if not items:
            break
        if n_calls == 1:
            if len(items) < page_size and len(items) < total:
                # 서버가 페이지 크기를 제한(clamp)함 → 실효 크기로 재설정
                page_size = len(items)
                print(f"[PV] 페이지 크기 실효값: {page_size}행/호출")
            if resume:
                done = saved_rows()
                jump = max(1, done // page_size)  # 겹침 1페이지(dedup 흡수)
                if jump > page:
                    print(f"[PV] 재개: 저장 {done}행 → p{jump}로 점프")
                    rows, page = [], jump
                    continue
        rows.extend(items)
        oldest = min(str(i["tradeYmd"]) for i in items)
        print(f"[PV] p{page}/{-(-total // page_size)} 호출{n_calls} ({oldest}까지)")
        if page % 10 == 0:
            n_saved += flush(rows)
            rows = []
        if stop_before and oldest <= stop_before:
            break
        if page * page_size >= total:
            break
        page += 1
        time.sleep(0.5)
    n_saved += flush(rows)
    return n_saved


def saved_rows() -> int:
    return sum(max(0, sum(1 for _ in open(f, encoding="utf-8-sig")) - 1)
               for f in glob.glob(os.path.join(PV_DIR, "????.csv")))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--full", action="store_true", help="전체 이력 적재")
    p.add_argument("--resume", action="store_true",
                   help="중단 지점부터 재개 (저장 행수 기반 페이지 추정)")
    args = p.parse_args()
    since = None
    if not args.full and not args.resume:
        since = latest_saved()
        if since:
            print(f"[PV] 증분 수집: {since} 이후")
    n = fetch_all(stop_before=since, resume=args.resume)
    print(f"[PV] 저장 {n}행 완료")


if __name__ == "__main__":
    main()
