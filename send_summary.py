# -*- coding: utf-8 -*-
"""
일일 요약 메일 (로드맵 ②, 푸시형) — 첨부 없이 본문 문구·표만.

본문 구성:
  1. 내일(KST D+1) 06~21시 대표 5지점 표 — ECMWF/GFS 기온·운량 원수치 병기, 발산 셀 강조
  2. 모델 발산 플래그 문장 (|ΔT|≥2℃ 또는 |Δ운량|≥30%p — config.DIVERGENCE_THRESHOLDS)
  3. 전일 오답노트 요약 — 모델별 ME/MAE 와 최대 오차, 신규 사례 알림
     ("어제 발산이 실제 어느 쪽으로 갈렸는가"를 매일 노출 — 브리프 7절 자동화 안주 방어)

원칙: 모델 간 발산은 평균·중재하지 않는다. 표에는 항상 두 모델 원수치를 병기한다.

발송: Gmail SMTP 465 (stdlib smtplib). 인증은 앱 비밀번호.
  환경변수/.env: GMAIL_ADDR, GMAIL_APP_PASSWORD, (선택) MAIL_TO — 미설정 시 자기 자신에게.
  미설정이면 발송을 건너뛰고 정상 종료한다 (배치를 막지 않기 위함).

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
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pandas as pd

import sslfix  # noqa: F401  (AVG Web/Mail Shield 는 SMTP TLS 도 가로챈다)
from config import BASE_DIR, OUT_DIR, VERIF_DIR, DIVERGENCE_THRESHOLDS, CASE_THRESHOLDS

REP_CITIES = ["서울", "대전", "대구", "광주", "부산"]
HOURS_KST = list(range(6, 22, 3))  # 06,09,12,15,18,21


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


def tomorrow_table(df: pd.DataFrame, target: dt.date):
    """대표 5지점 × 시각 — {(city, hour): {'EC_t':…, 'GF_t':…, 'EC_c':…, 'GF_c':…}}"""
    day = df[(df["valid_kst"].dt.date == target) & (df["rep"] == 1)]
    cell = {}
    runs = {}
    for model, g in day.groupby("model"):
        runs[model] = g["run_utc"].iloc[0] if not g.empty else "?"
        for r in g.itertuples():
            h = r.valid_kst.hour
            if h not in HOURS_KST:
                continue
            c = cell.setdefault((r.city, h), {})
            tag = "EC" if model == "ECMWF" else "GF"
            c[f"{tag}_t"] = r.t2m_C
            c[f"{tag}_c"] = r.tcc_pct
    return cell, runs


def divergences(cell: dict) -> list[str]:
    out = []
    for (city, h), c in sorted(cell.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        et, gt = c.get("EC_t"), c.get("GF_t")
        ec, gc = c.get("EC_c"), c.get("GF_c")
        if et is not None and gt is not None and pd.notna(et) and pd.notna(gt):
            d = et - gt
            if abs(d) >= DIVERGENCE_THRESHOLDS["t2m"]:
                out.append(f"{city} {h:02d}시 기온 ΔT {d:+.1f}℃ (EC {et:.1f} / GFS {gt:.1f})")
        if ec is not None and gc is not None and pd.notna(ec) and pd.notna(gc):
            d = ec - gc
            if abs(d) >= DIVERGENCE_THRESHOLDS["tcc"]:
                out.append(f"{city} {h:02d}시 운량 ΔC {d:+.0f}%p (EC {ec:.0f} / GFS {gc:.0f})")
    return out


def yesterday_verification(yday: dt.date):
    """전일 채점 요약 문구 + 신규 사례 목록. 자료 없으면 (None, [])."""
    path = os.path.join(VERIF_DIR, "scores", f"{yday:%Y-%m}.csv")
    if not os.path.exists(path):
        return None, []
    sc = pd.read_csv(path, parse_dates=["valid_kst"])
    sc = sc[(sc["valid_kst"].dt.date == yday)].dropna(subset=["err"])
    if sc.empty:
        return None, []

    lines = []
    for var, unit, nd in [("t2m", "℃", 1), ("tcc", "%p", 0)]:
        g = sc[sc["var"] == var]
        if g.empty:
            continue
        parts = []
        for model, gm in g.groupby("model"):
            parts.append(f"{model} ME {gm['err'].mean():+.{nd}f}{unit}"
                         f" (MAE {gm['err'].abs().mean():.{nd}f})")
        worst = g.loc[g["err"].abs().idxmax()]
        lines.append(f"{'기온' if var == 't2m' else '운량'}: " + " / ".join(parts)
                     + f" · 최대오차 {worst['city']} {worst['model']}"
                       f" {worst['err']:+.{nd}f}{unit}"
                       f" ({pd.Timestamp(worst['valid_kst']):%H}시, 예측 {worst['fcst']} vs 실황 {worst['obs']})")

    cases = sorted(os.path.basename(p) for p in
                   glob.glob(os.path.join(VERIF_DIR, "cases", f"{yday:%Y%m%d}_*.md")))
    return lines, cases


# ══════════════════════════════════════════════════════════
# 렌더링
# ══════════════════════════════════════════════════════════

def render(target: dt.date, cell, runs, div, verif_lines, cases):
    """(subject, text, html) 반환."""
    n_div = len(div)
    yo = "월화수목금토일"[target.weekday()]
    subject = f"[모델요약] {target:%m/%d}({yo}) 발산 {n_div}건"
    if verif_lines:
        m = re.search(r"GFS ME ([+\-\d.]+)", verif_lines[0])
        if m:
            subject += f" · 어제 GFS 기온 {m.group(1)}℃"

    def fmt(v, nd):
        return "-" if v is None or pd.isna(v) else f"{v:.{nd}f}"

    # ── 텍스트판 ──
    t = [f"■ 내일 {target:%m/%d} 대표 5지점 (각 셀: EC/GFS)",
         f"  런: " + ", ".join(f"{k} {v}UTC" for k, v in runs.items()), ""]
    hdr = "      " + "".join(f"{h:02d}시".rjust(12) for h in HOURS_KST)
    t.append("[기온 ℃]"); t.append(hdr)
    for city in REP_CITIES:
        row = f"{city:　<3}"
        for h in HOURS_KST:
            c = cell.get((city, h), {})
            row += f"{fmt(c.get('EC_t'),1)}/{fmt(c.get('GF_t'),1)}".rjust(12)
        t.append(row)
    t.append(""); t.append("[전운량 %]"); t.append(hdr)
    for city in REP_CITIES:
        row = f"{city:　<3}"
        for h in HOURS_KST:
            c = cell.get((city, h), {})
            row += f"{fmt(c.get('EC_c'),0)}/{fmt(c.get('GF_c'),0)}".rjust(12)
        t.append(row)
    t.append("")
    t.append(f"■ 모델 발산 (|ΔT|≥{DIVERGENCE_THRESHOLDS['t2m']:.0f}℃ 또는 |ΔC|≥{DIVERGENCE_THRESHOLDS['tcc']:.0f}%p)")
    t += ["  · " + s for s in div] if div else ["  없음 — 두 모델 대체로 일치"]
    t.append("")
    yday = target - dt.timedelta(days=2)
    t.append(f"■ 전일({yday:%m/%d}) 오답노트")
    if verif_lines:
        t += ["  · " + s for s in verif_lines]
        if cases:
            t.append(f"  · 신규 사례 파일 {len(cases)}건: " + ", ".join(cases))
    else:
        t.append("  · 채점 자료 없음 (배치 순서/PC 꺼짐 여부 확인)")
    t.append("")
    t.append("― 개인 연구 프로젝트 · ECMWF Open Data(CC-BY 4.0, 0.25° 재격자)/NOAA GFS/KMA ASOS")
    text = "\n".join(t)

    # ── HTML판 ──
    th = DIVERGENCE_THRESHOLDS
    def cell_html(c, key_e, key_g, nd, limit):
        e, g = c.get(key_e), c.get(key_g)
        s = f"{fmt(e,nd)}/{fmt(g,nd)}"
        if e is not None and g is not None and pd.notna(e) and pd.notna(g) and abs(e - g) >= limit:
            return f'<td style="border:1px solid #ccc;padding:3px 6px;text-align:center;background:#ffe3e3;font-weight:bold">{s}</td>'
        return f'<td style="border:1px solid #ccc;padding:3px 6px;text-align:center">{s}</td>'

    def table(kind, key_e, key_g, nd, limit):
        rows = [f'<tr><th style="border:1px solid #ccc;padding:3px 6px;background:#f0f0f0">{kind}</th>'
                + "".join(f'<th style="border:1px solid #ccc;padding:3px 6px;background:#f0f0f0">{h:02d}시</th>'
                          for h in HOURS_KST) + "</tr>"]
        for city in REP_CITIES:
            tds = "".join(cell_html(cell.get((city, h), {}), key_e, key_g, nd, limit)
                          for h in HOURS_KST)
            rows.append(f'<tr><td style="border:1px solid #ccc;padding:3px 6px;font-weight:bold">{city}</td>{tds}</tr>')
        return '<table style="border-collapse:collapse;font-size:13px">' + "".join(rows) + "</table>"

    h = [f"<h3>내일 {target:%m/%d} 대표 5지점 — 각 셀: ECMWF/GFS (발산 셀 강조)</h3>",
         f'<p style="color:#666;font-size:12px">런: ' + ", ".join(f"{k} {v}UTC" for k, v in runs.items()) + "</p>",
         table("기온℃", "EC_t", "GF_t", 1, th["t2m"]),
         "<br>", table("운량%", "EC_c", "GF_c", 0, th["tcc"]),
         f"<h3>모델 발산 (|ΔT|≥{th['t2m']:.0f}℃ · |ΔC|≥{th['tcc']:.0f}%p)</h3>"]
    h.append("<ul>" + "".join(f"<li>{s}</li>" for s in div) + "</ul>" if div
             else "<p>없음 — 두 모델 대체로 일치</p>")
    h.append(f"<h3>전일({yday:%m/%d}) 오답노트</h3>")
    if verif_lines:
        h.append("<ul>" + "".join(f"<li>{s}</li>" for s in verif_lines) + "</ul>")
        if cases:
            h.append(f'<p style="color:#c00;font-weight:bold">신규 사례 파일 {len(cases)}건: '
                     + ", ".join(cases) + "</p>")
    else:
        h.append("<p>채점 자료 없음 (배치 순서/PC 꺼짐 여부 확인)</p>")
    h.append('<hr><p style="color:#999;font-size:11px">개인 연구 프로젝트 — 공공기관 공식 서비스 아님 · '
             'ECMWF Open Data(CC-BY 4.0, 0.25° 재격자) · NOAA GFS · KMA API허브 ASOS(공공누리)</p>')
    html = f'<div style="font-family:Malgun Gothic,sans-serif">{"".join(h)}</div>'
    return subject, text, html


# ══════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="발송 없이 summary_mail.html 생성")
    p.add_argument("--date", default=None, help="표 대상일 YYYY-MM-DD (기본: 내일)")
    args = p.parse_args()

    target = (dt.date.fromisoformat(args.date) if args.date
              else dt.date.today() + dt.timedelta(days=1))

    df = load_latest_forecast()
    cell, runs = tomorrow_table(df, target)
    if not cell:
        raise SystemExit(f"[메일] {target} 유효 예측이 없습니다")
    div = divergences(cell)
    verif_lines, cases = yesterday_verification(dt.date.today() - dt.timedelta(days=1))
    subject, text, html = render(target, cell, runs, div, verif_lines, cases)

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


if __name__ == "__main__":
    main()
