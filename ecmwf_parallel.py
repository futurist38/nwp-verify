# -*- coding: utf-8 -*-
"""
ECMWF 오픈데이터 병렬 수신 (2026-09-07).

오픈데이터는 스텝마다 파일이 따로라 스텝 단위 요청이 서로 독립이다. 서버는 연결 하나당 ~0.34MB/s
로 묶여 있어(이 PC 실측) ecmwf-opendata 클라이언트의 순차 수신은 300MB 에 15분이 걸렸다.
스텝을 나눠 동시에 받으면 6개 1.1MB/s, 21개 1.9MB/s (503 없음).

retrieve_parallel(client, req, target, workers, fallbacks)
  · req["step"] 의 각 스텝을 따로 받아 순서대로 이어 붙인다.
  · fallbacks: 스텝이 실패하면 차례로 시도할 param 목록(예: tcc 미제공 런 → tcc 뺀 목록).
  · 반환: {"ok": [스텝...], "fail": [스텝...], "params": {스텝: 실제 받은 param}}
"""
import concurrent.futures as cf
import os
import shutil
import time


def _one(client, req, step, part, fallbacks):
    params_list = [req["param"]] + list(fallbacks or [])
    last = None
    for params in params_list:
        for attempt in range(2):
            try:
                client.retrieve(target=part, **{**req, "step": [step], "param": list(params)})
                return step, list(params), None
            except Exception as e:           # 인덱스 없음(미제공)·일시 오류 모두 여기로
                last = e
                time.sleep(2 * (attempt + 1))
    return step, None, last


def retrieve_parallel(client, req: dict, target: str, workers: int = 21, fallbacks=None,
                      log=print, tag="[ECMWF]") -> dict:
    steps = list(req["step"])
    parts = {st: f"{target}.s{st:03d}.part" for st in steps}
    t0 = time.time()
    res = {"ok": [], "fail": [], "params": {}}
    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = [ex.submit(_one, client, req, st, parts[st], fallbacks) for st in steps]
        for f in cf.as_completed(futs):
            st, params, err = f.result()
            if params is None:
                res["fail"].append(st)
                log(f"{tag} step {st} 실패: {str(err)[:80]}")
            else:
                res["ok"].append(st)
                res["params"][st] = params
    res["ok"].sort(); res["fail"].sort()
    with open(target + ".part", "wb") as dst:
        for st in steps:
            p = parts[st]
            if os.path.exists(p):
                with open(p, "rb") as src:
                    shutil.copyfileobj(src, dst, 1 << 20)
                os.remove(p)
    os.replace(target + ".part", target)
    mb = os.path.getsize(target) / 1e6
    dt_ = max(1e-3, time.time() - t0)
    log(f"{tag} 수신 {mb:.0f}MB, {dt_:.0f}s ({mb / dt_:.2f}MB/s, 병렬 {workers}, "
        f"스텝 {len(res['ok'])}/{len(steps)}" + (f", 실패 {res['fail']}" if res["fail"] else "") + ")")
    return res
