# -*- coding: utf-8 -*-
"""
KIM 등압면(pres) 상층 자료 수신 — 필요한 메시지만 남긴다 (2026-09-08).

실측(2026-09-07): API허브 typ06 `nwp=k512&sub=pres` 는 스텝당 302MB GRIB2, 192메시지(wz·gh·r·rhw·t·u·v·? 8변수
× 24층), 메시지 크기 전부 1,575,091B 고정(grid_simple). 층·변수 파라미터와 HTTP Range 는 서버가 무시한다.
→ 통째로 스트리밍하며 메시지 단위로 잘라 gh·t·u·v·r × (925,850,700,500,300,200) 30개(47MB)만 파일에 쓰고
  나머지는 버린다. 마지막 필요한 메시지(v 200hPa, 168번째) 뒤는 연결을 끊어 12% 를 아낀다.
런당 13스텝(0~72h, 6h) ≈ 3.9GB 수신 → 병렬 8 로 7분 안팎(8.9MB/s 실측). 일 트래픽 한도는 API허브에서 확인 필요.

산출: data/upper_kim_{run}.grib2  (plot_upper.py 가 kim 상층 패널을 그린다)
사용: python fetch_kim_pres.py [--run YYYYMMDD HH] [--workers 8] [--max-minutes 15]
"""
import argparse
import concurrent.futures as cf
import os
import sys
import time

import eccodes
import requests

import sslfix  # noqa: F401
from config import DATA_DIR
from fetch_kim import API, NWP, _auth_key, find_latest_run

STEPS = list(range(0, 73, 6))
KEEP_VARS = {"gh", "t", "u", "v", "r"}
KEEP_LEVELS = {925, 850, 700, 500, 300, 200}
LAST_NEEDED_INDEX = 167          # v 50hPa — 그 뒤(unknown 24개)는 필요 없어 끊는다


def _stream_step(tmfc: str, step: int, key: str) -> bytes | None:
    """한 스텝을 스트리밍하며 필요한 메시지 바이트만 이어 붙여 반환. 실패 시 None."""
    for attempt in range(3):
        try:
            r = requests.get(API, params={"nwp": NWP, "sub": "pres", "tmfc": tmfc, "ef": str(step),
                                          "authKey": key}, timeout=900, stream=True)
            buf = bytearray()
            out = bytearray()
            idx = 0
            first = True
            for chunk in r.iter_content(1 << 20):
                buf += chunk
                if first:
                    if buf[:4] != b"GRIB":
                        raise ValueError("GRIB 아님 (파일 미존재/오류 응답)")
                    first = False
                while len(buf) >= 16:
                    if buf[:4] != b"GRIB":
                        raise ValueError(f"메시지 경계 어긋남 (idx {idx})")
                    ln = int.from_bytes(bytes(buf[8:16]), "big")
                    if len(buf) < ln:
                        break
                    msg = bytes(buf[:ln]); del buf[:ln]
                    gid = eccodes.codes_new_from_message(msg)
                    try:
                        sn, lev = eccodes.codes_get(gid, "shortName"), int(eccodes.codes_get(gid, "level"))
                    finally:
                        eccodes.codes_release(gid)
                    if sn in KEEP_VARS and lev in KEEP_LEVELS:
                        out += msg
                    idx += 1
                if idx > LAST_NEEDED_INDEX:
                    break
            r.close()
            if not out:
                raise ValueError("필요한 메시지를 하나도 못 찾음")
            return bytes(out)
        except Exception as e:
            print(f"[KIM-P]  ef{step:03d} 실패({attempt + 1}/3): {e}")
            time.sleep(3 * (attempt + 1))
    return None


def fetch(tmfc: str | None, workers: int, max_minutes: float) -> str:
    key = _auth_key()
    if tmfc is None:
        tmfc = find_latest_run(key)
    target = os.path.join(DATA_DIR, f"upper_kim_{tmfc}.grib2")
    if os.path.exists(target) and os.path.getsize(target) > 0:
        print(f"[KIM-P] 이미 수신됨: {target}")
        return target
    os.makedirs(DATA_DIR, exist_ok=True)
    print(f"[KIM-P] 런 {tmfc} 상층 {len(STEPS)}스텝, 병렬 {workers}")
    t0 = time.time()
    got: dict[int, bytes | None] = {}
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {}
        for st in STEPS:
            if max_minutes and (time.time() - t0) / 60 >= max_minutes:
                print(f"[KIM-P] 시간 상한 — ef{st:03d} 이후 포기")
                break
            futs[ex.submit(_stream_step, tmfc, st, key)] = st
        for f in cf.as_completed(futs):
            got[futs[f]] = f.result()
    ok = [st for st in STEPS if got.get(st)]
    if not ok:
        raise RuntimeError("KIM 상층 스텝을 하나도 받지 못했습니다")
    with open(target + ".part", "wb") as dst:
        for st in STEPS:
            if got.get(st):
                dst.write(got[st])
    os.replace(target + ".part", target)
    el = time.time() - t0
    print(f"[KIM-P] 완료: {target} ({os.path.getsize(target) / 1e6:.0f}MB 보존, 스텝 {len(ok)}/{len(STEPS)}, "
          f"{el:.0f}s ≈ 원본 {302 * len(ok) / max(1, el):.1f}MB/s)")
    return target


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run", nargs=2, metavar=("YYYYMMDD", "HH"), default=None)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--max-minutes", type=float, default=0.0)
    a = p.parse_args()
    try:
        fetch((a.run[0] + a.run[1]) if a.run else None, a.workers, a.max_minutes)
    except Exception as e:
        print(f"[KIM-P] 실패: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
