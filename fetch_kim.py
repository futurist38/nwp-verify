# -*- coding: utf-8 -*-
"""
KIM(한국형모델, GDAPS) 전구 수신 — KMA API허브 typ06 NWP 파일 API.

실측 확정 (2026-08-21):
  · 호스트는 apihub-pub.kma.go.kr (apihub는 일반키 403 — 지상관측 typ01과 동일 함정)
  · nwp=k512 → kim_g512_ne36 (0.35°×0.23° 전구, GRIB2, centre=rksl)
    nwp=k128 → 0.125° 전구 — 스텝당 402MB라 일일 자동화에는 과함 (k512=76MB)
  · sub=unis 단일면 전변수 통파일만 제공(변수 필터 없음) → 수신 후 필요 변수만
    추출해 저장 (스텝당 76MB → 약 2MB)
  · ef는 3시간 단위(1h 없음), 288h까지. 런은 00/06/12/18z.
  · UM 계열(g128 등)은 2026-03-31 12z 자료까지만 — KIM 전환으로 종료.
  · 변수: 2t, tcc(entireAtmosphere), lcc/mcc/hcc(typeOfLevel unknown — KIM은
    층별 운량 제공! ECMWF 오픈데이터에는 없음), avg_sdswrf(일사, 구간 평균)

사용:
    python fetch_kim.py                    # 최신 런 자동 탐지
    python fetch_kim.py --run 20260820 12
"""
import argparse
import datetime as dt
import os
import sys
import tempfile
import time

import requests
import eccodes

import sslfix  # noqa: F401
from config import KIM_STEPS, DATA_DIR

API = "https://apihub-pub.kma.go.kr/api/typ06/url/nwp_file_down.php"
NWP = "k512"
# 강수 (2026-09-06 실측): k512 의 'tp' 는 전 스텝 최대 0.02mm 로 사실상 빈 필드다. 실제 강수는
# lswp(=ncpcp, 대규모 수적 강수)·cwp(대류성) 에 있고 눈은 snol·snoc 로 따로 온다 — 3h 창 누적.
KEEP_SHORTNAMES = {"2t", "tcc", "lcc", "mcc", "hcc", "avg_sdswrf", "lswp", "cwp", "snol", "snoc",
                   "prmsl"}   # prmsl: 지상 기압장(plot_upper.py) 2026-09-07


def _auth_key() -> str:
    key = os.environ.get("KMA_AUTH_KEY")
    if key:
        return key.strip()
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        import re
        m = re.search(r"KMA_AUTH_KEY\s*=\s*(\S+)", open(env_path, encoding="utf-8").read())
        if m:
            return m.group(1)
    raise RuntimeError("KMA_AUTH_KEY가 없습니다")


def _head_is_grib(tmfc: str, ef: int, key: str) -> bool:
    try:
        r = requests.get(API, params={"nwp": NWP, "sub": "unis", "tmfc": tmfc,
                                      "ef": str(ef), "authKey": key},
                         timeout=60, stream=True)
        head = next(r.iter_content(8), b"")
        r.close()
        return head[:4] == b"GRIB"
    except requests.RequestException:
        return False


def find_latest_run(key: str) -> str:
    """마지막 스텝(KIM_STEPS[-1])까지 존재하는 최신 런 탐색 (6시간 간격 역순)."""
    now = dt.datetime.now(dt.timezone.utc)
    for back_h in range(0, 49, 6):
        t = now - dt.timedelta(hours=back_h)
        tmfc = t.strftime("%Y%m%d") + f"{(t.hour // 6) * 6:02d}"
        if _head_is_grib(tmfc, KIM_STEPS[-1], key):
            return tmfc
        time.sleep(0.3)
    raise RuntimeError("최근 48시간 내 완결된 KIM 런을 찾지 못했습니다")


def _filter_append(src_path: str, dst, keep=KEEP_SHORTNAMES) -> int:
    """GRIB 파일에서 필요한 shortName 메시지만 dst 파일객체에 원시 바이트로 추가."""
    n = 0
    with open(src_path, "rb") as f:
        while True:
            gid = eccodes.codes_grib_new_from_file(f)
            if gid is None:
                break
            try:
                if eccodes.codes_get(gid, "shortName") in keep:
                    dst.write(eccodes.codes_get_message(gid))
                    n += 1
            finally:
                eccodes.codes_release(gid)
    return n


def _download_step(tmfc: str, step: int, key: str) -> str | None:
    """한 스텝(76MB)을 임시 파일로. 실패 시 None (3회 재시도)."""
    for attempt in range(3):
        tmp_in = None
        try:
            r = requests.get(API, params={"nwp": NWP, "sub": "unis", "tmfc": tmfc,
                                          "ef": str(step), "authKey": key},
                             timeout=600, stream=True)
            with tempfile.NamedTemporaryFile(dir=DATA_DIR, delete=False) as tf:
                tmp_in = tf.name
                for chunk in r.iter_content(1 << 20):
                    tf.write(chunk)
            with open(tmp_in, "rb") as chk:
                if chk.read(4) != b"GRIB":
                    raise ValueError("GRIB 아님 (파일 미존재/오류 응답)")
            return tmp_in
        except Exception as e:
            if tmp_in:
                try:
                    os.remove(tmp_in)
                except OSError:
                    pass
            print(f"[KIM]  ef{step:03d} 실패({attempt + 1}/3): {e}")
            time.sleep(3 * (attempt + 1))
    return None


def fetch(tmfc: str | None = None, max_minutes: float = 0.0, workers: int = 4) -> str:
    """스텝을 병렬(workers)로 받아 순서대로 필터·결합한다 (2026-09-07 병렬화).
    API허브는 변수 필터가 없어 스텝당 76MB 를 다 받아 11변수(13MB)만 남긴다 — 이것이 구조적 한계.
    max_minutes>0 이면 그 시간을 넘긴 뒤로는 새 스텝을 시작하지 않고, 받은 데까지 완성한다
    (2026-08-26 실측: 외부 timeout 에 걸리면 .part 만 남아 KIM 표출이 통째로 사라졌다)."""
    import concurrent.futures as cf
    key = _auth_key()
    if tmfc is None:
        tmfc = find_latest_run(key)
    print(f"[KIM] 수신 대상 런: {tmfc} ({NWP}), 병렬 {workers}")

    os.makedirs(DATA_DIR, exist_ok=True)
    target = os.path.join(DATA_DIR, f"kim_{NWP}_{tmfc}.grib2")
    done_mark = target + ".done"
    if os.path.exists(target) and os.path.getsize(target) > 0 and os.path.exists(done_mark):
        print(f"[KIM] 이미 수신됨: {target}")
        return target

    t_start = time.time()
    got: dict[int, str | None] = {}
    n_skip = 0
    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {}
        for step in KIM_STEPS:
            if max_minutes and (time.time() - t_start) / 60 >= max_minutes:
                n_skip += 1
                continue
            futs[ex.submit(_download_step, tmfc, step, key)] = step
            # 제출을 살짝 띄워 시간 상한이 제출 단계에서 먹히게 (워커가 차 있으면 어차피 대기)
            while max_minutes and len([f for f in futs if not f.done()]) >= workers \
                    and (time.time() - t_start) / 60 < max_minutes:
                time.sleep(1)
        for f in cf.as_completed(futs):
            got[futs[f]] = f.result()
    if n_skip:
        print(f"[KIM] 시간 상한 {max_minutes}분 도달 — 남은 {n_skip}스텝 포기, 받은 데까지 마무리")

    tmp_out = target + ".part"
    n_ok = n_fail = 0
    with open(tmp_out, "wb") as dst:
        for step in KIM_STEPS:
            path = got.get(step)
            if path is None:
                if step in got:
                    n_fail += 1
                    print(f"[KIM]  ef{step:03d} 수신 실패 (건너뜀 — 누락 기록)")
                continue
            kept = _filter_append(path, dst)
            os.remove(path)
            print(f"[KIM]  ef{step:03d}: 변수 {kept}개 추출")
            n_ok += 1

    if n_ok == 0:
        os.remove(tmp_out)
        raise RuntimeError("KIM 스텝을 하나도 받지 못했습니다")
    os.replace(tmp_out, target)
    if n_skip == 0 and n_fail == 0:
        open(done_mark, "w").close()          # 전 스텝 확보 시에만 완료 표식
    elif os.path.exists(done_mark):
        os.remove(done_mark)
    el = time.time() - t_start
    print(f"[KIM] 수신 완료: {target} ({os.path.getsize(target)/1e6:.1f} MB, "
          f"성공 {n_ok} / 실패 {n_fail} / 미수신 {n_skip} 스텝, {el:.0f}s ≈ 원본 {76 * n_ok / max(1, el):.1f}MB/s)")
    return target


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run", nargs=2, metavar=("YYYYMMDD", "HH"), default=None)
    p.add_argument("--max-minutes", type=float, default=0.0,
                   help="시간 상한(분). 초과 시 받은 스텝까지만 사용")
    p.add_argument("--workers", type=int, default=4, help="스텝 병렬 수신 수")
    args = p.parse_args()
    tmfc = (args.run[0] + args.run[1]) if args.run else None
    try:
        print(fetch(tmfc, args.max_minutes, args.workers))
    except Exception as e:
        print(f"[KIM] 수신 실패: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
