# -*- coding: utf-8 -*-
"""
M4: FMI CloudCast 파인튜닝 모델 추론 (겨울 보완 게이트용).

규격은 코랩 노트북(dl/finetune_cloudcast_gk2a.ipynb v2)과 동일해야 함 (FMI 코드 실측):
  · 입력 512², 6채널 = [hist4(10분 간격, 운량 0..1) | k/12 상수평면 | 태양고도]
    (가중치명 oh=False → 원핫이 아니라 스칼라 리드타임. sun은 고도각(도) 프레임별 min-max)
  · k → +10*(k+1)분 예측. 리드가 lc 범위를 넘으면 창 재귀(자기 예측 4장이 새 hist)
    — v5(lc=36)는 +6h가 lc 안에 들어와 재귀 없음(재귀가 장리드 표류의 원인이었음)
  · 출력은 벤치 격자(N_PIX, 기본 450)로 리사이즈해 반환 — 채점 조건 동일화
  · Keras 3는 구형 저장본 미지원 → tf_keras + h5 사용

사용: nowcast_bench.py --dl (dl/gk2a_finetuned.h5 필요)
"""
import datetime as dt
import math
import os

import numpy as np
import cv2

from dl_dataset import load_ca_native
from nowcast_bench import CLA_DIR, N_PIX

# 우선순위: 환경변수 > v5(+6h 직접) > scratch(라이선스 클린) > 파인튜닝판(연구용)
_CAND = [os.environ.get("DL_MODEL", ""),
         os.path.join("dl", "gk2a_v5.h5"),
         os.path.join("dl", "gk2a_scratch.h5"),
         os.path.join("dl", "gk2a_allseason.h5"),
         os.path.join("dl", "gk2a_finetuned.h5")]
MODEL_H5 = next(p for p in _CAND if p and os.path.exists(p))
SIZE = 512
STEP = 10   # 분

# 리드 컨디셔닝 깊이 — 사이드카 JSON이 있으면 그 값(v5=36), 없으면 12(v4 이전)
_SIDECAR = os.path.splitext(MODEL_H5)[0] + ".json"
if os.path.exists(_SIDECAR):
    import json
    _spec = json.load(open(_SIDECAR, encoding="utf-8"))
    N_LC, STEP = int(_spec.get("lc", 12)), int(_spec.get("step_min", 10))
else:
    N_LC = 12

# 노트북 3)과 동일한 근사 위경도 (태양고도 채널)
_LATS = np.linspace(46.0, 29.7, SIZE)[:, None] * np.ones((1, SIZE))
_LONS = np.ones((SIZE, 1)) * np.linspace(113.0, 139.5, SIZE)[None, :]


def _sun(t: dt.datetime) -> np.ndarray:
    doy = t.timetuple().tm_yday
    decl = -23.44 * math.cos(math.radians(360 / 365 * (doy + 10)))
    hour = t.hour + t.minute / 60
    ha = (hour * 15 - 180) + _LONS
    s = (np.sin(np.radians(_LATS)) * math.sin(math.radians(decl)) +
         np.cos(np.radians(_LATS)) * math.cos(math.radians(decl)) * np.cos(np.radians(ha)))
    el = np.degrees(np.arcsin(np.clip(s, -1, 1)))
    if el.max() > el.min():
        el = (el - el.min()) / np.ptp(el)
    return el.astype(np.float32)


def _build_unet_f32(tf_keras):
    """FMI model.py의 U-Net을 float32로 재구축 — mixed_float16 저장본은 CPU에서
    에뮬레이션으로 매우 느림(230s/발령 실측). 동일 구조라 h5 가중치가 순서 이식됨."""
    L = tf_keras.layers
    inputs = L.Input((SIZE, SIZE, 6))

    def conv_block(inp, n):
        x = L.Conv2D(n, 3, padding="same")(inp)
        x = L.BatchNormalization()(x)
        x = L.Activation("relu")(x)
        x = L.Conv2D(n, 3, padding="same")(x)
        x = L.BatchNormalization()(x)
        return L.Activation("relu")(x)

    def enc(inp, n):
        x = conv_block(inp, n)
        return x, L.MaxPooling2D((2, 2))(x)

    def dec(inp, skip, n):
        x = L.Conv2DTranspose(n, (2, 2), strides=2, padding="same")(inp)
        x = L.Concatenate()([x, skip])
        return conv_block(x, n)

    s1, p1 = enc(inputs, 64)
    s2, p2 = enc(p1, 128)
    s3, p3 = enc(p2, 256)
    s4, p4 = enc(p3, 512)
    b1 = conv_block(p4, 1024)
    d1 = dec(b1, s4, 512)
    d2 = dec(d1, s3, 256)
    d3 = dec(d2, s2, 128)
    d4 = dec(d3, s1, 64)
    outputs = L.Conv2D(1, 1, padding="same", activation="sigmoid")(d4)
    return tf_keras.Model(inputs, outputs)


class DLNowcaster:
    def __init__(self):
        import tf_keras  # 지연 임포트 (--dl 시에만) — Keras 2 호환 로더
        # TF 파일IO는 한글 경로 불가(netCDF4와 동일 함정) → ASCII 임시경로로 복사 후 로드
        import shutil
        import tempfile
        path = os.path.abspath(MODEL_H5)
        try:
            path.encode("ascii")
        except UnicodeEncodeError:
            cache = os.path.join(tempfile.gettempdir(), os.path.basename(path))
            if (not os.path.exists(cache)
                    or os.path.getsize(cache) != os.path.getsize(path)):
                shutil.copy2(path, cache)
            path = cache
        self.model = _build_unet_f32(tf_keras)
        self.model.load_weights(path)   # 전체 h5에서 순서 기반 이식
        self.n_lc = N_LC
        print(f"[M4] 모델 로드(f32 재구축): {MODEL_H5} (lc {self.n_lc})")

    def _frame(self, stamp: str) -> np.ndarray | None:
        path = os.path.join(CLA_DIR, f"{stamp}.nc")
        if not os.path.exists(path):
            return None
        ca = load_ca_native(path)
        if ca is None:
            return None
        small = cv2.resize(ca, (SIZE, SIZE), interpolation=cv2.INTER_AREA)
        return np.nan_to_num(small, nan=50.0).astype(np.float32) / 100.0

    def _steps(self, hist: list[np.ndarray], base_t: dt.datetime,
               ks: list[int]) -> dict[int, np.ndarray]:
        """같은 hist에서 여러 k를 배치 1회로 예측."""
        xs = []
        for k in ks:
            tgt = base_t + dt.timedelta(minutes=STEP * (k + 1))
            lt = np.full((SIZE, SIZE), k / self.n_lc, np.float32)
            xs.append(np.stack(hist + [lt, _sun(tgt)], -1))
        xb = np.stack(xs)
        if len(xs) == 1:      # oneDNN 배치1 conv 경로가 ~90배 느림(실측 76s vs 0.8s)
            xb = np.concatenate([xb, xb])
        y = self.model.predict(xb, verbose=0)[..., 0]
        return {k: np.clip(y[i].astype(np.float32), 0, 1) for i, k in enumerate(ks)}

    def predict(self, issue: dt.datetime, leads_min: list[int]) -> dict[int, np.ndarray] | None:
        """발령시각(UTC naive) → {lead: 벤치격자 %장}. hist 결측 시 None."""
        hist = []
        for i in range(3, -1, -1):
            f = self._frame((issue - dt.timedelta(minutes=STEP * i)).strftime("%Y%m%d%H%M"))
            if f is None:
                return None
            hist.append(f)

        span = STEP * self.n_lc                      # 창 하나가 커버하는 리드(분)
        out: dict[int, np.ndarray] = {}
        base_t, base_off = issue, 0
        while base_off < max(leads_min):
            in_win = [m for m in leads_min if base_off < m <= base_off + span]
            advance = base_off + span < max(leads_min)
            ks = {(m - base_off) // STEP - 1 for m in in_win}
            if advance:                              # 창 전진용 마지막 4스텝도 같은 배치에
                ks |= set(range(self.n_lc - 4, self.n_lc))
            res = self._steps(hist, base_t, sorted(ks))
            for m in in_win:
                out[m] = res[(m - base_off) // STEP - 1]
            if not advance:
                break
            hist = [res[k] for k in range(self.n_lc - 4, self.n_lc)]
            base_t += dt.timedelta(minutes=span)
            base_off += span
        return {m: cv2.resize(f * 100.0, (N_PIX, N_PIX), interpolation=cv2.INTER_AREA)
                for m, f in out.items()}
