# -*- coding: utf-8 -*-
"""
일일 요약 메일 (로드맵 ②, 푸시형) — 첨부 없이 본문 문구·표만.

본문 구성 (2026-08-18 개편: 도시×모델 행 구조 — KIM 추가 시 행만 늘어남):
  1. 내일(KST D+1) 06~21시 대표 5지점 표 — 모델별 행으로 원수치 병기, 발산 셀 강조
  2. 모델 발산 플래그 (스프레드 최대-최소 기준, config.DIVERGENCE_THRESHOLDS)
  3. 전일 검증 표 — 관측(ASOS) 행 + 모델별 "예측(오차)" 행. 요청 반영:
     모델들과 관측을 한 표에서 대조 (관측은 과거에만 존재하므로 이 표에 들어간다)
  4. 전일 요약 문장(모델별 ME/MAE·최대오차)과 신규 사례 알림

원칙: 모델 간 발산은 평균·중재하지 않는다. 항상 모델별 원수치를 병기한다.

발송: Gmail SMTP 465 (stdlib smtplib). 인증은 앱 비밀번호.
  환경변수/.env: GMAIL_ADDR, GMAIL_APP_PASSWORD(공백 포함 표시형식 허용),
  (선택) MAIL_TO. 미설정이면 발송을 건너뛰고 정상 종료한다.

사용:
    python send_summary.py --dry-run     # 발송 없이 summary_mail.html 생성
    python send_summary.py               # 실발송
"""
import argparse
import datetime as dt
import glob
import os
import re
import smtplib
import socket
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pandas as pd

import sslfix  # noqa: F401  (AVG Web/Mail Shield 는 SMTP TLS 도 가로챈다)
from config import (BASE_DIR, OUT_DIR, VERIF_DIR, DIVERGENCE_THRESHOLDS,
                    IMPACT_COEF, IMPACT_SOLAR_HOURS, IMPACT_TEMP_HOURS)

REP_CITIES = ["서울", "대전", "대구", "광주", "부산"]
HOURS_KST = list(range(6, 22, 3))          # 06,09,12,15,18,21
MODEL_ORDER = ["ECMWF", "GFS", "KIM"]      # 표 행 순서 (없는 모델은 자동 생략)
MODEL_SHORT = {"ECMWF": "EC", "GFS": "GFS", "KIM": "KIM"}

TD = 'style="border:1px solid #ccc;padding:3px 6px;text-align:center"'
TDH = 'style="border:1px solid #ccc;padding:3px 6px;background:#f0f0f0"'
TDD = 'style="border:1px solid #ccc;padding:3px 6px;text-align:center;background:#ffe3e3;font-weight:bold"'


def _env(name: str) -> str | None:
    v = os.environ.get(name)
    if not v:
        env_path = os.path.join(BASE_DIR, ".env")
        if os.path.exists(env_path):
            for line in open(env_path, encoding="utf-8"):
                m = re.match(rf"\s*{name}\s*=\s*(.+?)\s*$", line)
                if m:
                    v = m.group(1)
                    break
    if v and name == "GMAIL_APP_PASSWORD":
        v = v.replace(" ", "")  # Google 표시 형식(xxxx xxxx …)의 공백 허용
    return v


def _fmt(v, nd):
    return "-" if v is None or pd.isna(v) else f"{v:.{nd}f}"


# ══════════════════════════════════════════════════════════
# 자료 수집
# ══════════════════════════════════════════════════════════

def load_latest_forecast() -> pd.DataFrame:
    cands = sorted(glob.glob(os.path.join(OUT_DIR, "*", "city_forecast.csv")))
    if not cands:
        raise SystemExit("city_forecast.csv 없음 — plot_charts.py 먼저 실행")
    df = pd.read_csv(cands[-1])
    df["valid_kst"] = pd.to_datetime(df["valid_kst"])
    return df


def tomorrow_data(df: pd.DataFrame, target: dt.date):
    """val[(city, model, hour)] = (t2m, tcc), 모델 목록, 런 정보."""
    day = df[(df["valid_kst"].dt.date == target) & (df["rep"] == 1)]
    present = list(day["model"].unique())
    models = [m for m in MODEL_ORDER if m in present] + \
             [m for m in present if m not in MODEL_ORDER]
    val, runs = {}, {}
    for model, g in day.groupby("model"):
        runs[model] = g["run_utc"].iloc[0]
        for r in g.itertuples():
            if r.valid_kst.hour in HOURS_KST:
                val[(r.city, model, r.valid_kst.hour)] = (r.t2m_C, r.tcc_pct)
    return val, models, runs


def spread_flags(val: dict, models: list[str]) -> list[str]:
    """모델 스프레드(최대-최소) 임계 초과 목록. 2모델이면 |차이|와 동일."""
    out = []
    for h in HOURS_KST:
        for city in REP_CITIES:
            for vi, var, unit, nd, th in [
                    (0, "기온", "℃", 1, DIVERGENCE_THRESHOLDS["t2m"]),
                    (1, "운량", "%p", 0, DIVERGENCE_THRESHOLDS["tcc"])]:
                vals = {m: val[(city, m, h)][vi] for m in models
                        if (city, m, h) in val and pd.notna(val[(city, m, h)][vi])}
                if len(vals) < 2:
                    continue
                spread = max(vals.values()) - min(vals.values())
                if spread >= th:
                    detail = " / ".join(f"{MODEL_SHORT.get(m, m)} {v:.{nd}f}"
                                        for m, v in vals.items())
                    out.append(f"{city} {h:02d}시 {var} 스프레드 {spread:.{nd}f}{unit} ({detail})")
    return out


def _spread(val, models, city, h, vi):
    vv = [val[(city, m, h)][vi] for m in models
          if (city, m, h) in val and pd.notna(val[(city, m, h)][vi])]
    return (max(vv) - min(vv)) if len(vv) >= 2 else None


def headline(val: dict, models: list[str], flags: list[str]):
    """신호등 + 영향 번역 헤드라인.
    발산 '폭'을 GW로 환산한 어림 — 단일값 추천이 아니다. 원수치는 본문 표에 보존."""
    n = len(flags)
    if n == 0:
        signal = ("🟢", "합의일 — 모델 간 대체로 일치. 아래 표 확인만으로 충분.")
    elif n <= 5:
        signal = ("🟡", f"부분 분기 — 발산 {n}건. 해당 시간대만 리스크 점검.")
    else:
        signal = ("🔴", f"분기일 — 발산 {n}건. 시나리오 폭을 잡고 들어갈 것.")

    lines = []
    # 태양광: 피크창 운량 스프레드 → 이용률 폭 → GW 폭
    cs = [s for city in REP_CITIES for h in IMPACT_SOLAR_HOURS
          if (s := _spread(val, models, city, h, 1)) is not None]
    if cs:
        c_mean = sum(cs) / len(cs)
        util = c_mean * IMPACT_COEF["util_pct_per_cloud_pct"]
        gw = util * IMPACT_COEF["pv_gw_per_util_pct"]
        lines.append(f"태양광: 피크창({IMPACT_SOLAR_HOURS[0]:02d}~{IMPACT_SOLAR_HOURS[-1]:02d}시) "
                     f"운량 스프레드 평균 {c_mean:.0f}%p → 이용률 약 {util:.0f}%p ≈ {gw:.1f}GW 폭")
    # 냉방: 오후 기온 스프레드 → GW 폭
    ts = {(city, h): s for city in REP_CITIES for h in IMPACT_TEMP_HOURS
          if (s := _spread(val, models, city, h, 0)) is not None}
    if ts:
        t_mean = sum(ts.values()) / len(ts)
        (wc, wh), wmax = max(ts.items(), key=lambda kv: kv[1])
        gw = t_mean * IMPACT_COEF["demand_gw_per_degC"]
        lines.append(f"냉방: 오후({IMPACT_TEMP_HOURS[0]:02d}~{IMPACT_TEMP_HOURS[-1]:02d}시) "
                     f"기온 스프레드 평균 {t_mean:.1f}℃(최대 {wc} {wh:02d}시 {wmax:.1f}℃) "
                     f"≈ {gw:.1f}GW 폭")
    note = ("환산은 공개 수급보고서 역산 계수(太0.283GW/%p·최고기온 1.47GW/℃)와 "
            "운량→이용률 어림(0.6)을 쓴 리스크 폭이며 단일값 추천이 아님. 원수치는 아래 표.")
    return signal, lines, note


def yesterday_data(yday: dt.date):
    """전일 검증 표 재료: obs[(var,city,h)], fc[(var,city,model,h)]=(fcst,err), 모델 목록."""
    path = os.path.join(VERIF_DIR, "scores", f"{yday:%Y-%m}.csv")
    if not os.path.exists(path):
        return None, None, []
    sc = pd.read_csv(path, parse_dates=["valid_kst", "run_utc"])
    sc = sc[(sc["valid_kst"].dt.date == yday)
            & (sc["city"].isin(REP_CITIES))
            & (sc["valid_kst"].dt.hour.isin(HOURS_KST))
            & (sc["var"].isin(["t2m", "tcc"]))]
    if sc.empty:
        return None, None, []
    # 같은 유효시각에 여러 런이 채점돼 있으면 최단 리드(최신 런)만 표에 사용
    sc = sc.sort_values("step_h").drop_duplicates(
        subset=["valid_kst", "city", "model", "var"], keep="first")

    obs, fc = {}, {}
    for r in sc.itertuples():
        h = r.valid_kst.hour
        if pd.notna(r.obs):
            obs[(r.var, r.city, h)] = r.obs
        fc[(r.var, r.city, r.model, h)] = (r.fcst, r.err)
    present = list(sc["model"].unique())
    models = [m for m in MODEL_ORDER if m in present] + \
             [m for m in present if m not in MODEL_ORDER]
    return obs, fc, models


def yesterday_summary_lines(yday: dt.date):
    """모델별 ME/MAE·최대오차 문장 + 신규 사례 목록."""
    path = os.path.join(VERIF_DIR, "scores", f"{yday:%Y-%m}.csv")
    if not os.path.exists(path):
        return [], []
    sc = pd.read_csv(path, parse_dates=["valid_kst"])
    sc = sc[sc["valid_kst"].dt.date == yday].dropna(subset=["err"])
    lines = []
    for var, unit, nd in [("t2m", "℃", 1), ("tcc", "%p", 0)]:
        g = sc[sc["var"] == var]
        if g.empty:
            continue
        parts = [f"{m} ME {gm['err'].mean():+.{nd}f}{unit} (MAE {gm['err'].abs().mean():.{nd}f})"
                 for m, gm in g.groupby("model")]
        w = g.loc[g["err"].abs().idxmax()]
        lines.append(f"{'기온' if var == 't2m' else '운량'}: " + " / ".join(parts)
                     + f" · 최대오차 {w['city']} {w['model']} {w['err']:+.{nd}f}{unit}"
                       f" ({pd.Timestamp(w['valid_kst']):%H}시, 예측 {w['fcst']} vs 실황 {w['obs']})")
    cases = sorted(os.path.basename(p) for p in
                   glob.glob(os.path.join(VERIF_DIR, "cases", f"{yday:%Y%m%d}_*.md")))
    return lines, cases


# ══════════════════════════════════════════════════════════
# 렌더링 (텍스트 + HTML)
# ══════════════════════════════════════════════════════════

def render(target, val, models, runs, flags, signal, impact_lines, impact_note,
           yday, obs, yfc, ymodels, verif_lines, cases):
    yo = "월화수목금토일"[target.weekday()]
    subject = f"{signal[0]}[모델요약] {target:%m/%d}({yo}) 발산 {len(flags)}건"
    if verif_lines:
        m = re.search(r"GFS ME ([+\-\d.]+)", verif_lines[0])
        if m:
            subject += f" · 어제 GFS 기온 {m.group(1)}℃"

    def hdr_txt_w(w):
        return "          " + "".join(f"{h:02d}시".rjust(w) for h in HOURS_KST)
    hdr_txt = hdr_txt_w(8)
    hdr_txt_wide = hdr_txt_w(12)

    # ── 내일 표 (텍스트) ──
    def fc_rows_txt(vi, nd):
        rows = []
        for city in REP_CITIES:
            for i, mdl in enumerate(models):
                label = (city if i == 0 else "　　") + f" {MODEL_SHORT.get(mdl, mdl):<4}"
                cells = "".join(
                    _fmt(val.get((city, mdl, h), (None, None))[vi], nd).rjust(8)
                    for h in HOURS_KST)
                rows.append(label + cells)
        return rows

    t = [f"■ {signal[0]} {signal[1]}"]
    t += ["  · " + s for s in impact_lines]
    t += [f"  ※ {impact_note}", "",
          f"■ 내일 {target:%m/%d}({yo}) 대표 5지점 — 행: 모델별 예측",
         "  런: " + ", ".join(f"{m} {runs[m]}UTC" for m in models), "",
         "[기온 ℃]", hdr_txt, *fc_rows_txt(0, 1), "",
         "[전운량 %]", hdr_txt, *fc_rows_txt(1, 0), "",
         f"■ 모델 발산 (스프레드 기온 ≥{DIVERGENCE_THRESHOLDS['t2m']:.0f}℃ · 운량 ≥{DIVERGENCE_THRESHOLDS['tcc']:.0f}%p)"]
    t += ["  · " + s for s in flags] if flags else ["  없음 — 모델 간 대체로 일치"]

    # ── 전일 검증 표 (텍스트) ──
    t += ["", f"■ 전일({yday:%m/%d}) 검증 — 관측과 모델별 예측(괄호: 오차)"]
    if obs:
        for var, name, nd in [("t2m", "기온 ℃", 1), ("tcc", "운량 %", 0)]:
            t += [f"[{name}]", hdr_txt_wide]
            for city in REP_CITIES:
                cells = "".join(_fmt(obs.get((var, city, h)), nd).rjust(12) for h in HOURS_KST)
                t.append(f"{city} 관측 " + cells)
                for mdl in ymodels:
                    cells = ""
                    for h in HOURS_KST:
                        fe = yfc.get((var, city, mdl, h))
                        cells += ("-".rjust(12) if fe is None else
                                  f"{_fmt(fe[0], nd)}({fe[1]:+.{nd}f})".rjust(12) if pd.notna(fe[1])
                                  else f"{_fmt(fe[0], nd)}(-)".rjust(12))
                    t.append(f"　　 {MODEL_SHORT.get(mdl, mdl):<4}" + cells)
            t.append("")
    else:
        t.append("  채점 자료 없음 (배치 순서/PC 꺼짐 여부 확인)")
    if verif_lines:
        t += ["  · " + s for s in verif_lines]
    if cases:
        t.append(f"  · 신규 사례 파일 {len(cases)}건: " + ", ".join(cases))
    t += ["", "― 개인 연구 프로젝트 · ECMWF Open Data(CC-BY 4.0, 0.25° 재격자)/NOAA GFS/KMA ASOS"]
    text = "\n".join(t)

    # ── HTML ──
    def table_fc(vi, nd, th_limit):
        rows = ['<tr><th ' + TDH + '>지점/모델</th>'
                + "".join(f"<th {TDH}>{h:02d}시</th>" for h in HOURS_KST) + "</tr>"]
        for city in REP_CITIES:
            # 발산 셀 판정용 스프레드
            spread_h = {}
            for h in HOURS_KST:
                vv = [val[(city, m, h)][vi] for m in models
                      if (city, m, h) in val and pd.notna(val[(city, m, h)][vi])]
                spread_h[h] = (max(vv) - min(vv)) if len(vv) >= 2 else 0
            for i, mdl in enumerate(models):
                name = f"{city} {MODEL_SHORT.get(mdl, mdl)}" if i == 0 else MODEL_SHORT.get(mdl, mdl)
                tds = ""
                for h in HOURS_KST:
                    v = val.get((city, mdl, h), (None, None))[vi]
                    style = TDD if spread_h[h] >= th_limit else TD
                    tds += f"<td {style}>{_fmt(v, nd)}</td>"
                rows.append(f"<tr><td {TDH}>{name}</td>{tds}</tr>")
        return '<table style="border-collapse:collapse;font-size:13px">' + "".join(rows) + "</table>"

    def table_verif(var, nd):
        rows = ['<tr><th ' + TDH + '>지점</th>'
                + "".join(f"<th {TDH}>{h:02d}시</th>" for h in HOURS_KST) + "</tr>"]
        for city in REP_CITIES:
            tds = "".join(f"<td {TD}><b>{_fmt(obs.get((var, city, h)), nd)}</b></td>"
                          for h in HOURS_KST)
            rows.append(f"<tr><td {TDH}>{city} 관측</td>{tds}</tr>")
            for mdl in ymodels:
                tds = ""
                for h in HOURS_KST:
                    fe = yfc.get((var, city, mdl, h))
                    if fe is None:
                        tds += f"<td {TD}>-</td>"
                    elif pd.notna(fe[1]):
                        color = "#c00" if abs(fe[1]) >= (3 if var == "t2m" else 40) else "#555"
                        tds += (f"<td {TD}>{_fmt(fe[0], nd)}"
                                f'<span style="color:{color};font-size:11px"> ({fe[1]:+.{nd}f})</span></td>')
                    else:
                        tds += f"<td {TD}>{_fmt(fe[0], nd)} (-)</td>"
                rows.append(f"<tr><td {TDH}>　{MODEL_SHORT.get(mdl, mdl)}</td>{tds}</tr>")
        return '<table style="border-collapse:collapse;font-size:13px">' + "".join(rows) + "</table>"

    banner_bg = {"🟢": "#e8f5e9", "🟡": "#fff8e1", "🔴": "#ffebee"}[signal[0]]
    h = [f'<div style="background:{banner_bg};border-radius:6px;padding:10px 14px;margin-bottom:8px">'
         f'<b style="font-size:15px">{signal[0]} {signal[1]}</b>'
         + ("<ul style='margin:6px 0 2px'>" + "".join(f"<li>{s}</li>" for s in impact_lines) + "</ul>"
            if impact_lines else "")
         + f'<div style="color:#888;font-size:11px">※ {impact_note}</div></div>',
         f"<h3>내일 {target:%m/%d}({yo}) 대표 5지점 — 행: 모델별 예측 (발산 셀 강조)</h3>",
         '<p style="color:#666;font-size:12px">런: '
         + ", ".join(f"{m} {runs[m]}UTC" for m in models) + "</p>",
         "<b>기온 ℃</b>", table_fc(0, 1, DIVERGENCE_THRESHOLDS["t2m"]), "<br>",
         "<b>전운량 %</b>", table_fc(1, 0, DIVERGENCE_THRESHOLDS["tcc"]),
         f"<h3>모델 발산 (스프레드 기온 ≥{DIVERGENCE_THRESHOLDS['t2m']:.0f}℃ · 운량 ≥{DIVERGENCE_THRESHOLDS['tcc']:.0f}%p)</h3>"]
    h.append("<ul>" + "".join(f"<li>{s}</li>" for s in flags) + "</ul>" if flags
             else "<p>없음 — 모델 간 대체로 일치</p>")
    h.append(f"<h3>전일({yday:%m/%d}) 검증 — 관측 vs 모델별 예측(괄호: 오차)</h3>")
    if obs:
        h += ["<b>기온 ℃</b>", table_verif("t2m", 1), "<br>",
              "<b>운량 %</b>", table_verif("tcc", 0)]
    else:
        h.append("<p>채점 자료 없음 (배치 순서/PC 꺼짐 여부 확인)</p>")
    if verif_lines:
        h.append("<ul>" + "".join(f"<li>{s}</li>" for s in verif_lines) + "</ul>")
    if cases:
        h.append(f'<p style="color:#c00;font-weight:bold">신규 사례 파일 {len(cases)}건: '
                 + ", ".join(cases) + "</p>")
    h.append('<hr><p style="color:#999;font-size:11px">개인 연구 프로젝트 — 공공기관 공식 서비스 아님 · '
             'ECMWF Open Data(CC-BY 4.0, 0.25° 재격자) · NOAA GFS · KMA API허브 ASOS(공공누리)</p>')
    html = f'<div style="font-family:Malgun Gothic,sans-serif">{"".join(h)}</div>'
    return subject, text, html


# ══════════════════════════════════════════════════════════

def _smtp_connect() -> smtplib.SMTP_SSL:
    """정상 검증 우선. 이 PC의 AVG Mail Shield는 SMTP를 'AVG Web/Mail Shield
    Untrusted Root'로 가로채 OS 신뢰소(truststore)로도 검증이 불가하다(2026-08-18 실측).
    AVG가 업스트림 검증·재암호화를 수행하므로, 가로챈 주체가 AVG로 확인될 때만
    검증을 생략한다. 다른 사유의 검증 실패는 그대로 예외."""
    try:
        return smtplib.SMTP_SSL("smtp.gmail.com", 465,
                                context=ssl.create_default_context(), timeout=60)
    except ssl.SSLCertVerificationError:
        probe = ssl._create_unverified_context()
        with socket.create_connection(("smtp.gmail.com", 465), 30) as sk:
            with probe.wrap_socket(sk, server_hostname="smtp.gmail.com") as w:
                der = w.getpeercert(binary_form=True)
        if b"AVG Web/Mail Shield" not in der:
            raise
        print("[메일] AVG Mail Shield 가로채기 감지 — 로컬 AV 구간 비검증 연결")
        return smtplib.SMTP_SSL("smtp.gmail.com", 465, context=probe, timeout=60)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="발송 없이 summary_mail.html 생성")
    p.add_argument("--date", default=None, help="표 대상일 YYYY-MM-DD (기본: 내일)")
    args = p.parse_args()

    target = (dt.date.fromisoformat(args.date) if args.date
              else dt.date.today() + dt.timedelta(days=1))
    yday = dt.date.today() - dt.timedelta(days=1)

    df = load_latest_forecast()
    val, models, runs = tomorrow_data(df, target)
    if not val:
        raise SystemExit(f"[메일] {target} 유효 예측이 없습니다")
    flags = spread_flags(val, models)
    signal, impact_lines, impact_note = headline(val, models, flags)
    obs, yfc, ymodels = yesterday_data(yday)
    verif_lines, cases = yesterday_summary_lines(yday)
    subject, text, html = render(target, val, models, runs, flags,
                                 signal, impact_lines, impact_note,
                                 yday, obs, yfc, ymodels, verif_lines, cases)

    if args.dry_run:
        out = os.path.join(BASE_DIR, "summary_mail.html")
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
        print(subject); print(); print(text)
        print(f"\n[dry-run] HTML 저장: {out}")
        return

    addr = _env("GMAIL_ADDR")
    pw = _env("GMAIL_APP_PASSWORD")
    if not addr or not pw:
        print("[메일] GMAIL_ADDR/GMAIL_APP_PASSWORD 미설정 — 발송 건너뜀")
        return
    to = _env("MAIL_TO") or addr

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = addr
    msg["To"] = to
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with _smtp_connect() as s:
        s.login(addr, pw)
        s.sendmail(addr, [to], msg.as_string())
    print(f"[메일] 발송 완료 → {to} : {subject}")


if __name__ == "__main__":
    main()
