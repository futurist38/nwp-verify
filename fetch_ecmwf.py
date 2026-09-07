# -*- coding: utf-8 -*-
"""
ECMWF Open Data (IFS 0.25°) 수신
- ecmwf-opendata 패키지 사용 (pip install ecmwf-opendata)
- 최신 가용 런을 자동 탐지해 2t, tcc를 GRIB2로 저장
- tcc는 2025-11-20부터 오픈데이터에 추가됐으나 일부 런에서만 제공될 수 있음
  → 요청 실패 시 tcc를 빼고 재시도

사용:
    python fetch_ecmwf.py            # 최신 런
    python fetch_ecmwf.py --time 12  # 12UTC 런 지정
"""
import argparse
import os
import sys
import datetime as dt

import sslfix  # noqa: F401  (AVG TLS 검사 대응 — 모듈 주석 참조)
from config import ECMWF_PARAMS, ECMWF_STEPS, DATA_DIR


def fetch(run_time: int | None = None, source: str = "ecmwf", workers: int = 16) -> str:
    """ECMWF 오픈데이터 GRIB 다운로드. 저장 경로를 반환.
    2026-09-07: 스텝 병렬 수신(ecmwf_parallel) — 순차 0.34MB/s → 병렬 ~1.9MB/s (이 PC 실측).
    tcc·tp·ssrd 가 없는 런/스텝은 스텝 단위로 param 을 줄여 다시 받는다(예전엔 파일 전체를 2t 만으로)."""
    from ecmwf.opendata import Client

    client = Client(source=source, model="ifs", resol="0p25")

    request = {
        "type": "fc",
        "step": ECMWF_STEPS,
        "param": list(ECMWF_PARAMS),
    }
    if run_time is not None:
        request["time"] = run_time

    # 최신 가용 런 확인
    try:
        latest = client.latest(**request)
        print(f"[ECMWF] 최신 가용 런: {latest}")
    except Exception as e:
        print(f"[ECMWF] 최신 런 조회 실패({e}) — param 축소 후 재시도")
        request["param"] = ["2t"]
        latest = client.latest(**request)
        print(f"[ECMWF] (2t만) 최신 가용 런: {latest}")

    os.makedirs(DATA_DIR, exist_ok=True)
    tag = latest.strftime("%Y%m%d%H")
    target = os.path.join(DATA_DIR, f"ecmwf_ifs025_{tag}.grib2")

    if os.path.exists(target) and os.path.getsize(target) > 0:
        print(f"[ECMWF] 이미 수신됨: {target}")
        return target

    # 스텝 병렬 수신 (.part 에 받고 완료 후 개명 — 중단 파일을 '수신됨' 으로 오인하지 않게)
    from ecmwf_parallel import retrieve_parallel
    full = list(request["param"])
    fallbacks = [[p for p in full if p != "tcc"], ["2t"]]
    request["time"] = latest.hour
    res = retrieve_parallel(client, request, target, workers, fallbacks=fallbacks, tag="[ECMWF]")
    if not res["ok"]:
        raise RuntimeError("ECMWF 스텝을 하나도 받지 못했습니다")
    reduced = {st: p for st, p in res["params"].items() if p != full}
    if reduced:
        print(f"[ECMWF] param 축소 스텝 {len(reduced)}개 (예: {min(reduced)} → {reduced[min(reduced)]})")
    size_mb = os.path.getsize(target) / 1e6
    print(f"[ECMWF] 수신 완료: {target} ({size_mb:.1f} MB)")
    return target


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--time", type=int, default=None, choices=[0, 6, 12, 18],
                   help="런 시각(UTC). 생략 시 최신 런")
    p.add_argument("--source", default="ecmwf", choices=["ecmwf", "azure", "aws"],
                   help="다운로드 소스. 본 서버가 느리면 azure/aws 미러 사용")
    p.add_argument("--workers", type=int, default=16, help="스텝 병렬 수신 수")
    args = p.parse_args()
    try:
        path = fetch(args.time, args.source, args.workers)
        print(path)
    except Exception as e:
        print(f"[ECMWF] 수신 실패: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
