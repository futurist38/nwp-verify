# -*- coding: utf-8 -*-
"""
KIM 전지구(NE57, 8km) 수신 — KMA API허브 "KIM 자료 조회(NC)" 격자 텍스트 API (2026-09-16).

배경: 기상청 API허브 공지(2026-09-11) — 2026-10-01 부로 KIM GRIB 생산 중단. 우리가 쓰던
  typ06 nwp_file_down.php(k512 GRIB, fetch_kim.py·fetch_kim_pres.py) 가 "중단" 대상.
  실측으로는 9/15 부터 이미 완결된 GRIB 런이 없다.
대체: typ01 `nph-kim_nc_xy_txt2` (NetCDF 기반, 영역 지정 ASCII 격자). 실측(2026-09-16):
  · 호스트 apihub-pub.kma.go.kr, **기관키(KMA_INSTITUTION_AUTH_KEY) 필요** — 일반키는 403.
    403 이면 즉시 실패한다 (재시도·런 탐색 없음). 요청 URL 의 authKey 는 로그에 남기지 않는다.
  · 격자: 전구 1/12° 규칙 위경도. 인덱스 x = lon*12+1, y = (lat+90)*12+1 (lat -90 부터)
  · 한반도 영역(config LON 120~135, LAT 31~44) = 181×157, 요청당 ~374KB, 0.2~0.7s.
    동아시아(100~150E, 20~55N) = 601×421, 요청당 ~3.4MB — 상층·지상장은 3점 간격(1/4°)으로 줄여 저장.
  · 스텝 hf: 1~135 매시, 138~288 3시간. 런 00/06/12/18z
  · 단일면(data=U) 변수: t2m[K] psl[Pa] tcld/lcld/mcld/hcld[0~1] dswrsfc[W/m²] prec_acc[kg/m², 런 시작 누적, hf=0 은 0]
    등압면(data=P): hgt[m] T[K] u v[m/s] rh[%] (level=hPa)
  · 응답 행 순서는 j=1 이 남쪽(lat1) — 수신 후 북→남으로 뒤집어 저장 (기존 판독기 규약; 실측 검증 9/16: 남쪽 행이 더 따뜻함)

산출 (npz, **SI 원단위 그대로** — °C·% 변환은 판독기가 한다. schema=1):
  data/kim_NE57_{run}.npz    lats(북→남) lons run steps + t2m psl tcld lcld mcld hcld prec_acc [step,ny,nx]
                             + dswrf(3h 평균, dswrf_steps·dswrf_win) + tp(창 누적 mm, tp_steps·tp_win)
  data/upper_kim_{run}.npz   (--upper) 동아시아 1/4°: hgt_925 … rh_700 [step,ny,nx] (steps 0~72h/6h)
                             + 지상장 psl·t2m (sfc_steps — plot_upper._sfc_ok 규칙) — 상층 지도의 지상 패널용
  data/kim_nc_run.txt        지상 수신이 고른 런 — --upper 가 --run 없이 같은 런을 쓰도록 (1·2단계 런 불일치 방지)
완결 관문: 지상은 t2m·psl·tcld·prec_acc 가 72h 이내 전 스텝 + 120h 이내 90% 이상(빠진 스텝은 NaN 면). 상층은 48h 이내 전부 +
  전체 90%, 동아시아 지상장은 72h 전부 + 120h 90%. 관문을 못 넘으면 파일을 만들지 않고 exit 1 → 워크플로가 GRIB 대체(10/1 전)로.
사용:
    python fetch_kim_nc.py                      # 최신 완결 런 자동 탐지, 지상
    python fetch_kim_nc.py --upper              # 상층 (+동아시아 지상장), 런은 kim_nc_run.txt
    python fetch_kim_nc.py --run 20260916 00 --max-minutes 8 --workers 4
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import os
import re
import sys
import threading
import time

import numpy as np
import requests

import sslfix  # noqa: F401
from config import KIM_STEPS, KIM_FAR_END, DATA_DIR, LON_MIN, LON_MAX, LAT_MIN, LAT_MAX, model_steps

API = "https://apihub-pub.kma.go.kr/api/typ01/cgi-bin/url/nph-kim_nc_xy_txt2"
NWP = "NE57"
GROUP = "KIMG"
SCHEMA = 1
RES = 12                      # 1/12° 격자 → 도당 12칸
SFC_VARS = ("t2m", "psl", "tcld", "lcld", "mcld", "hcld", "prec_acc")
GATE_VARS = ("t2m", "psl", "tcld", "prec_acc")   # 완결 관문 대상
GATE_MAX_STEP = 120
DSWRF_MAX_STEP = 120          # 매시 자료로 3h 평균을 만들 수 있는 구간(≤135); KIM_STEPS 기준 120
UPPER_STEPS = list(range(0, 73, 6))
UPPER_VARS = {925: ("hgt", "T", "u", "v"), 850: ("hgt", "T", "u", "v"), 700: ("hgt", "rh", "u", "v"),
              500: ("hgt", "u", "v"), 300: ("hgt", "u", "v"), 200: ("hgt", "u", "v")}   # plot_upper.PL_VARS 와 동일
UPPER_LON_MIN, UPPER_LON_MAX, UPPER_LAT_MIN, UPPER_LAT_MAX = 100.0, 150.0, 20.0, 55.0    # fetch_upper 와 동일
UPPER_DECIMATE = 3            # 1/12° → 1/4°
RUN_FILE = os.path.join(DATA_DIR, "kim_nc_run.txt")


class AuthError(RuntimeError):
    """403 — 키 문제. 재시도·탐색 없이 즉시 종료."""


def _clean_key(raw: str) -> str:
    """앞뒤 공백·따옴표 제거. 실측(2026-09-16): GitHub 시크릿에 따옴표째 들어가 길이 24(정상 22)가 되자 API 가 400 을 돌려줬다."""
    return raw.strip().strip("\"'").strip()


def _auth_key() -> str:
    key = os.environ.get("KMA_INSTITUTION_AUTH_KEY")
    if key and _clean_key(key):
        return _clean_key(key)
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        m = re.search(r"KMA_INSTITUTION_AUTH_KEY\s*=\s*(\S+)", open(env_path, encoding="utf-8").read())
        if m:
            return _clean_key(m.group(1))
    raise RuntimeError("KMA_INSTITUTION_AUTH_KEY가 없습니다 (NC 조회는 기관키 필요 — 일반키 KMA_AUTH_KEY 는 403)")


def sub_box(lon0, lon1, lat0, lat1) -> str:
    return f"{int(round(lon0 * RES)) + 1},{int(round((lat0 + 90) * RES)) + 1}," \
           f"{int(round(lon1 * RES)) + 1},{int(round((lat1 + 90) * RES)) + 1}"


def _steps(run_hour: int) -> list[int]:
    """런 시각에 맞춘 KIM 스텝 (config.KIM_STEPS 는 00z 용): 3h→120h, 그 뒤 유효시각 00/12UTC 인 12h 간격.
    00/12z 는 132·144·…, 06/18z 는 126·138·… (Sol 검토 2026-09-16: 06/18z 먼 스텝 오류 수정)."""
    return model_steps(run_hour, 120, KIM_FAR_END)


def _sfc_steps(run_hour: int) -> list[int]:
    """plot_upper._sfc_ok 와 같은 규칙: 120h 까지 6h, 그 뒤 12h 스텝 중 유효시각이 00/12UTC 인 것."""
    st = _steps(run_hour)
    return [s for s in st if s <= 120 and s % 6 == 0] + [s for s in st if s > 120 and (run_hour + s) % 12 == 0]


def parse(text: str, name: str, level: int):
    """API 텍스트 → (2D 배열 남→북 행순, meta). 오류 응답·헤더 불일치·값 수 불일치는 ValueError."""
    if "# ERROR" in text:
        raise ValueError(next((l for l in text.splitlines() if "ERROR" in l), "API 오류 응답")[:160])
    m = re.search(r"변수명\s*=\s*(\S+),\s*unit\s*=\s*([^,]+),\s*level\s*=\s*(\d+),\s*i\s*=\s*(\d+),\s*j\s*=\s*(\d+)"
                  r".*?lon1\s*=\s*([\d.]+),\s*lat1\s*=\s*([\d.]+),\s*lon2\s*=\s*([\d.]+),\s*lat2\s*=\s*([\d.]+)", text)
    if not m:
        raise ValueError(f"헤더 없음({name})")
    if m.group(1) != name or int(m.group(3)) != level:
        raise ValueError(f"헤더 불일치: 변수 {m.group(1)}/{name}, 층 {m.group(3)}/{level}")
    ni, nj = int(m.group(4)), int(m.group(5))
    rows = re.split(r"^# j\s*=\s*\d+\s*$", text, flags=re.M)[1:]
    if len(rows) != nj:
        raise ValueError(f"행 수 불일치 {len(rows)} != {nj}")
    a = np.empty((nj, ni), np.float32)
    for k, row in enumerate(rows):
        tok = " ".join(l for l in row.splitlines() if not l.lstrip().startswith("#"))
        v = np.fromstring(tok, sep=" ", dtype=np.float32)
        if v.size != ni:
            raise ValueError(f"j={k + 1} 값 수 {v.size} != {ni}")
        a[k] = v
    meta = {"unit": m.group(2).strip(), "level": int(m.group(3)), "ni": ni, "nj": nj,
            "lon1": float(m.group(6)), "lat1": float(m.group(7)), "lon2": float(m.group(8)), "lat2": float(m.group(9))}
    exp_ni = int(round((meta["lon2"] - meta["lon1"]) * RES)) + 1
    exp_nj = int(round((meta["lat2"] - meta["lat1"]) * RES)) + 1
    if (ni, nj) != (exp_ni, exp_nj):
        raise ValueError(f"격자 크기 불일치 {ni}x{nj} != {exp_ni}x{exp_nj}")
    return a, meta


def _redact(msg: str, key: str) -> str:
    return str(msg).replace(key, "***")


def _get(session, key, sub, tmfc, hf, name, data="U", level=0, tries=3):
    """한 필드. 403 → AuthError(즉시). 429/5xx/네트워크 → 재시도. 그 외 HTTP/파싱 오류 → 재시도 없이 ValueError."""
    q = dict(group=GROUP, nwp=NWP, data=data, name=name, level=level, map="S", sub=sub,
             tmfc=tmfc, hf=hf, disp="A", help=1, authKey=key)
    last = None
    for attempt in range(tries):
        try:
            r = session.get(API, params=q, timeout=(10, 90))
            if r.status_code == 403:
                raise AuthError("HTTP 403 — 기관키 권한 없음/만료")
            if r.status_code == 429 or r.status_code >= 500:
                ra = r.headers.get("Retry-After")
                time.sleep(min(60, float(ra)) if ra and ra.isdigit() else 3 * (attempt + 1))
                last = ValueError(f"HTTP {r.status_code}")
                continue
            if r.status_code != 200:
                raise ValueError(f"HTTP {r.status_code}")
            return parse(r.content.decode("euc-kr", "replace"), name, level)
        except AuthError:
            raise
        except ValueError as e:
            raise ValueError(f"{name}/{level} hf={hf}: {_redact(e, key)}") from None
        except requests.RequestException as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{name}/{level} hf={hf}: {_redact(last, key)}")


_probe_log = []


def _available(session, key, tmfc, hf, sub) -> bool:
    try:
        _get(session, key, sub, tmfc, hf, "t2m", tries=1)
        return True
    except AuthError:
        raise
    except Exception as e:                          # noqa: BLE001
        _probe_log.append(f"{tmfc} hf={hf}: {_redact(e, key)[:140]}")
        return False


def find_latest_run(session, key, sub, last_step: int, attempts: int = 3, pause: int = 60) -> str:
    """마지막 스텝까지 존재하는 최신 런 (6시간 간격 역순, 48시간)."""
    for attempt in range(1, attempts + 1):
        now = dt.datetime.now(dt.timezone.utc)
        for back_h in range(0, 49, 6):
            t = now - dt.timedelta(hours=back_h)
            tmfc = t.strftime("%Y%m%d") + f"{(t.hour // 6) * 6:02d}"
            if _available(session, key, tmfc, last_step, sub):
                return tmfc
        # 실패 사유를 남긴다 (러너에서 왜 못 찾았는지 — 연결 끊김·오류 응답·파싱 — 를 로그로 구분, 2026-09-16)
        for line in _probe_log[-3:]:
            print(f"[KIM-NC]  탐색 실패 사유: {line}", flush=True)
        if attempt < attempts:
            print(f"[KIM-NC] 런 탐색 실패 ({attempt}/{attempts}) — {pause}초 뒤 재시도", flush=True)
            time.sleep(pause)
    raise RuntimeError("최근 48시간 내 완결된 KIM(NE57) 런을 찾지 못했습니다")


def _run_jobs(jobs, key, tmfc, workers, max_minutes, post=None):
    """병렬 수신. 시간 상한을 넘기면 남은 요청만 취소한다 — 이미 시작된 요청은 제 타임아웃(10+90s)까지 끝날 수 있으므로
    이 상한은 느슨하다. 진짜 상한은 워크플로의 바깥 `timeout`.
    jobs: [(data, name, level, hf, sub)]. post: 배열 후처리(예: 3점 간격 추출). 반환 {job: array}, meta(첫 응답)."""
    got, meta0 = {}, {}
    n_ok = n_fail = 0
    t0 = time.time()
    local = threading.local()
    auth_err = []

    def work(job):
        data, name, level, hf, sub = job
        if auth_err:
            raise RuntimeError("중단")
        sess = getattr(local, "s", None) or setattr(local, "s", requests.Session()) or local.s
        a, meta = _get(sess, key, sub, tmfc, hf, name, data, level)
        return job, (post(a) if post else a), meta

    ex = cf.ThreadPoolExecutor(workers)
    futs = [ex.submit(work, j) for j in jobs]
    try:
        for f in cf.as_completed(futs):
            try:
                job, a, meta = f.result()
                got[job] = a; meta0.setdefault(job[4], meta); n_ok += 1
            except AuthError as e:
                auth_err.append(e); break
            except Exception as e:                  # noqa: BLE001
                n_fail += 1
                if n_fail <= 5:
                    print(f"[KIM-NC]  실패: {_redact(e, key)}", flush=True)
            if max_minutes and time.time() - t0 > max_minutes * 60:
                print(f"[KIM-NC] 시간 상한 {max_minutes}분 — 남은 요청 취소", flush=True)
                break
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    if auth_err:
        raise auth_err[0]
    print(f"[KIM-NC] 수신 {n_ok}건 성공 / {n_fail}건 실패, {time.time() - t0:.0f}초", flush=True)
    return got, meta0


def _coords(meta, decimate=1):
    """헤더 lon1/lat1/lon2/lat2 → (lats 북→남, lons)."""
    nj, ni = meta["nj"], meta["ni"]
    lats_sn = np.linspace(meta["lat1"], meta["lat2"], nj)[::decimate].astype(np.float32)
    lons = np.linspace(meta["lon1"], meta["lon2"], ni)[::decimate].astype(np.float32)
    return lats_sn[::-1], lons


def _save(out_path: str, out: dict):
    tmp = out_path + ".part.npz"
    np.savez_compressed(tmp, **out)
    os.replace(tmp, out_path)


def fetch_surface(tmfc: str, key: str, out_path: str, workers: int, max_minutes: float) -> str:
    sub = sub_box(LON_MIN, LON_MAX, LAT_MIN, LAT_MAX)
    steps = _steps(int(tmfc[8:10]))              # 런 시각별 스텝 (3h→120h, 12h→288h, 유효 00/12UTC)
    jobs = [("U", v, 0, s, sub) for s in steps for v in SFC_VARS]
    # 일사: 3h 평균용 매시 3장 (s-2, s-1, s), 0 < s ≤ DSWRF_MAX_STEP → 시각 1..120 (중복 없음)
    dsw_hours = sorted({h for s in steps if 0 < s <= DSWRF_MAX_STEP for h in (s - 2, s - 1, s) if h >= 1})
    jobs += [("U", "dswrsfc", 0, h, sub) for h in dsw_hours]
    print(f"[KIM-NC] 런 {tmfc} 지상 {len(steps)}스텝, 요청 {len(jobs)}건, 병렬 {workers}", flush=True)
    got, meta0 = _run_jobs(jobs, key, tmfc, workers, max_minutes)
    if not got:
        raise RuntimeError("지상 자료를 하나도 받지 못했습니다")
    lats, lons = _coords(meta0[sub])
    nj, ni = lats.size, lons.size
    # 완결 관문: 72h 이내는 모든 스텝, 120h 이내는 90% 이상의 스텝에 GATE_VARS 가 있어야 한다.
    # (아카이브 런에는 빠진 시각이 있다 — 실측 2026-09-07 06z 의 ft090. 한 스텝 결손으로 런 전체를 버리지 않는다.)
    ok_steps = [s for s in steps if all(("U", v, 0, s, sub) in got for v in GATE_VARS)]
    near = [s for s in steps if s <= 72]
    gate = [s for s in steps if s <= GATE_MAX_STEP]
    miss_near = [s for s in near if s not in ok_steps]
    n_gate_ok = sum(1 for s in gate if s in ok_steps)
    if miss_near or n_gate_ok < 0.9 * len(gate):
        raise RuntimeError(f"완결 관문 실패 — 72h 이내 결손 스텝 {miss_near}, 120h 이내 확보 {n_gate_ok}/{len(gate)} → 파일 미생성")
    if n_gate_ok < len(gate):
        print(f"[KIM-NC] 경고: 120h 이내 결손 스텝 {[s for s in gate if s not in ok_steps]} — 해당 스텝만 비운다", flush=True)
    nan = np.full((nj, ni), np.nan, np.float32)

    def stack(name, hfs):
        return np.stack([got.get(("U", name, 0, h, sub), nan) for h in hfs])[:, ::-1, :]   # 북→남으로 뒤집기

    out = {"schema": SCHEMA, "run": tmfc, "lats": lats, "lons": lons, "steps": np.array(ok_steps, np.int32),
           "source": f"KMA API허브 nph-kim_nc_xy_txt2 {GROUP}/{NWP} data=U 1/12deg ({dt.datetime.now(dt.timezone.utc):%Y-%m-%dT%H:%MZ})"}
    for v in SFC_VARS:
        out[v] = stack(v, ok_steps)
    # 일사 3h 평균 (매시값 3장의 산술평균). dswrsfc 가 순간값인지 시간평균인지 문서에 없다 —
    # 9/7 06z 런을 GRIB avg_sdswrf 와 대조해 확정한다 (검증 기록은 커밋 메시지·README 참조).
    dsw_steps, dsw_arr = [], []
    for s in ok_steps:
        if 0 < s <= DSWRF_MAX_STEP:
            trio = [got.get(("U", "dswrsfc", 0, h, sub)) for h in (s - 2, s - 1, s)]
            if all(t is not None for t in trio):
                dsw_steps.append(s); dsw_arr.append(np.mean(trio, axis=0)[::-1, :])
    out["dswrf_steps"] = np.array(dsw_steps, np.int32)
    out["dswrf"] = np.stack(dsw_arr) if dsw_arr else np.zeros((0, nj, ni), np.float32)
    out["dswrf_win"] = np.full(len(dsw_steps), 3, np.int32)
    # 강수: 런 시작 누적(prec_acc)의 연속 스텝 차분. 3h 스텝은 3h 창, 12h 간격 스텝은 12h 창 (win_h 로 표기).
    # 06/18z 런의 첫 먼 스텝(132h)도 직전 스텝(120h)과의 12h 창이다. 음수 차분은 부동소수 잡음(|x|<0.05mm)만 0 으로.
    tp_steps, tp_arr, tp_win = [], [], []
    acc = {s: got.get(("U", "prec_acc", 0, s, sub)) for s in ok_steps}
    for i, s in enumerate(ok_steps):
        if i == 0:
            continue
        prev = ok_steps[i - 1]
        d = acc[s] - acc[prev]
        if (d < -0.05).mean() > 0.001:
            print(f"[KIM-NC] 경고: prec_acc 감소 픽셀 {(d < -0.05).mean():.2%} (hf {prev}→{s}) — 누적 리셋 의심, 강수 창 제외", flush=True)
            continue
        tp_steps.append(s); tp_arr.append(np.maximum(d, 0.0)[::-1, :]); tp_win.append(s - prev)
    out["tp_steps"] = np.array(tp_steps, np.int32)
    out["tp"] = np.stack(tp_arr) if tp_arr else np.zeros((0, nj, ni), np.float32)
    out["tp_win"] = np.array(tp_win, np.int32)
    _save(out_path, out)
    with open(RUN_FILE, "w", encoding="utf-8") as fp:
        fp.write(tmfc)
    print(f"[KIM-NC] 저장: {out_path} ({os.path.getsize(out_path) / 1e6:.1f}MB, 스텝 {len(ok_steps)}/{len(steps)}, "
          f"일사 {len(dsw_steps)}, 강수 {len(tp_steps)})", flush=True)
    return out_path


def fetch_upper(tmfc: str, key: str, out_path: str, workers: int, max_minutes: float) -> str:
    sub = sub_box(UPPER_LON_MIN, UPPER_LON_MAX, UPPER_LAT_MIN, UPPER_LAT_MAX)
    sfc_steps = _sfc_steps(int(tmfc[8:10]))
    jobs = [("P", v, L, s, sub) for s in UPPER_STEPS for L, vs in UPPER_VARS.items() for v in vs]
    jobs += [("U", v, 0, s, sub) for s in sfc_steps for v in ("psl", "t2m")]
    print(f"[KIM-NC] 런 {tmfc} 상층 {len(UPPER_STEPS)}스텝 + 지상장 {len(sfc_steps)}스텝, 요청 {len(jobs)}건, 병렬 {workers}", flush=True)
    got, meta0 = _run_jobs(jobs, key, tmfc, workers, max_minutes,
                           post=lambda a: a[::UPPER_DECIMATE, ::UPPER_DECIMATE].copy())
    if not got:
        raise RuntimeError("상층 자료를 하나도 받지 못했습니다")
    lats, lons = _coords(meta0[sub], UPPER_DECIMATE)
    nj, ni = lats.size, lons.size
    a0 = next(iter(got.values()))
    assert a0.shape == (nj, ni), (a0.shape, nj, ni)
    ok_steps = [s for s in UPPER_STEPS if all(("P", v, L, s, sub) in got for L, vs in UPPER_VARS.items() for v in vs)]
    ok_sfc = [s for s in sfc_steps if all(("U", v, 0, s, sub) in got for v in ("psl", "t2m"))]
    # 완결 관문(Sol 검토 9/16): 상층은 48h 까지 전부 + 전체 90% 이상, 지상장은 72h 까지 전부 + 120h 이내 90% 이상.
    # 못 넘으면 파일을 만들지 않고 실패 → 워크플로가 GRIB 대체(10/1 전)로 넘어간다.
    miss_up = [s for s in UPPER_STEPS if s <= 48 and s not in ok_steps]
    sfc_gate = [s for s in sfc_steps if s <= 120]
    miss_sfc = [s for s in sfc_steps if s <= 72 and s not in ok_sfc]
    if miss_up or len(ok_steps) < 0.9 * len(UPPER_STEPS) or miss_sfc \
            or sum(1 for s in sfc_gate if s in ok_sfc) < 0.9 * len(sfc_gate):
        raise RuntimeError(f"완결 관문 실패 — 상층 결손(≤48h) {miss_up}, 상층 확보 {len(ok_steps)}/{len(UPPER_STEPS)}, "
                           f"지상장 결손(≤72h) {miss_sfc}, 지상장 확보 {len(ok_sfc)}/{len(sfc_steps)} → 파일 미생성")
    out = {"schema": SCHEMA, "run": tmfc, "lats": lats, "lons": lons, "steps": np.array(ok_steps, np.int32),
           "sfc_steps": np.array(ok_sfc, np.int32),
           "source": f"KMA API허브 nph-kim_nc_xy_txt2 {GROUP}/{NWP} data=P/U, 1/4deg(3점 추출)"}
    for L, vs in UPPER_VARS.items():
        for v in vs:
            out[f"{v}_{L}"] = np.stack([got[("P", v, L, s, sub)] for s in ok_steps])[:, ::-1, :] if ok_steps \
                else np.zeros((0, nj, ni), np.float32)
    for v in ("psl", "t2m"):
        out[v] = np.stack([got[("U", v, 0, s, sub)] for s in ok_sfc])[:, ::-1, :] if ok_sfc \
            else np.zeros((0, nj, ni), np.float32)
    _save(out_path, out)
    print(f"[KIM-NC] 저장: {out_path} ({os.path.getsize(out_path) / 1e6:.1f}MB, 상층 {len(ok_steps)}/{len(UPPER_STEPS)}, "
          f"지상장 {len(ok_sfc)}/{len(sfc_steps)})", flush=True)
    return out_path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run", nargs=2, metavar=("YYYYMMDD", "HH"), default=None)
    p.add_argument("--upper", action="store_true", help="상층(등압면)+동아시아 지상장 → data/upper_kim_{run}.npz")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--max-minutes", type=float, default=8.0)
    a = p.parse_args()
    key = _auth_key()
    print(f"[KIM-NC] 기관키 길이 {len(key)}자 (정상 22자)", flush=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    sess = requests.Session()
    probe_sub = sub_box(LON_MIN, LON_MAX, LAT_MIN, LAT_MAX)
    if a.run:
        tmfc = a.run[0] + a.run[1]
        if not _available(sess, key, tmfc, 0, probe_sub):      # 예비 점검: 키·런 존재 (403 이면 여기서 AuthError)
            raise RuntimeError(f"런 {tmfc} hf=0 조회 실패 — 런 없음 또는 API 불가")
    elif a.upper and os.path.exists(RUN_FILE):
        tmfc = open(RUN_FILE, encoding="utf-8").read().strip()
        print(f"[KIM-NC] 지상 수신이 고른 런 사용: {tmfc}", flush=True)
    else:
        tmfc = find_latest_run(sess, key, probe_sub, UPPER_STEPS[-1] if a.upper else KIM_STEPS[-1])
    if a.upper:
        fetch_upper(tmfc, key, os.path.join(DATA_DIR, f"upper_kim_{tmfc}.npz"), a.workers, a.max_minutes)
    else:
        fetch_surface(tmfc, key, os.path.join(DATA_DIR, f"kim_{NWP}_{tmfc}.npz"), a.workers, a.max_minutes)


if __name__ == "__main__":
    try:
        main()
    except AuthError as e:
        print(f"[KIM-NC] 인증 실패: {e} — GRIB 대체로 넘어가지 말고 키를 확인할 것", flush=True)
        sys.exit(3)
    except Exception as e:                          # noqa: BLE001
        print(f"[KIM-NC] 수신 실패: {e}", flush=True)
        sys.exit(1)
