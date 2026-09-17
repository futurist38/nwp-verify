# -*- coding: utf-8 -*-
"""
카카오톡 "나에게 보내기" — 추석 예보 추적 카드 발송 (2026-09-16).

동작: refresh 토큰으로 access 토큰을 받고, 최신 05·11·17시 검토 카드(사이트에 발행된 PNG 주소)를 피드 메시지로 보낸다.
      같은 검토본을 두 번 보내지 않도록 verification/chuseok/_kakao_sent.txt 에 마지막 발송 키를 남긴다(커밋 대상).
환경변수(또는 .env): KAKAO_REST_KEY, KAKAO_REFRESH_TOKEN, (선택) KAKAO_CLIENT_SECRET
사용: python kakao_send.py            # 새 발표가 있을 때만 발송
      python kakao_send.py --test     # 표시 여부와 무관하게 1회 발송(로컬 시험)
      python kakao_send.py --force    # 마지막 발송 키와 같아도 발송
"""
import argparse
import datetime as dt
import json
import os
import re

import requests

import sslfix  # noqa: F401
from config import OUT_DIR, VERIF_DIR

SITE = "https://futurist38.github.io/nwp-verify"
SENT = os.path.join(VERIF_DIR, "chuseok", "_kakao_sent.txt")
ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def _env(name: str) -> str | None:
    v = os.environ.get(name)
    if v:
        return v.strip().strip('"').strip("'")
    if os.path.exists(ENV):
        m = re.search(name + r"\s*=\s*(\S+)", open(ENV, encoding="utf-8").read())
        if m:
            return m.group(1).strip().strip('"').strip("'")
    return None


def access_token() -> str:
    rest, refresh = _env("KAKAO_REST_KEY"), _env("KAKAO_REFRESH_TOKEN")
    if not rest or not refresh:
        raise SystemExit("KAKAO_REST_KEY / KAKAO_REFRESH_TOKEN 이 없습니다 (kakao_auth.py 먼저)")
    data = {"grant_type": "refresh_token", "client_id": rest, "refresh_token": refresh}
    sec = _env("KAKAO_CLIENT_SECRET")
    if sec:
        data["client_secret"] = sec
    r = requests.post("https://kauth.kakao.com/oauth/token", data=data, timeout=30)
    j = r.json()
    if "access_token" not in j:
        raise SystemExit("토큰 갱신 실패: " + json.dumps({k: v for k, v in j.items() if k != "refresh_token"}, ensure_ascii=False))
    if j.get("refresh_token"):
        print("[카톡] 주의: refresh 토큰이 재발급됨 — GitHub 시크릿 KAKAO_REFRESH_TOKEN 을 갱신해야 다음 갱신이 된다")
    return j["access_token"]


def wait_published(url: str, tries: int = 12, pause: int = 10) -> bool:
    """발행 직후 Pages/CDN 반영 지연 대비: 불변 주소가 200 을 돌려줄 때까지 최대 tries×pause 초 기다린다."""
    import time
    for _ in range(tries):
        try:
            r = requests.head(url, timeout=20, allow_redirects=True)
            if r.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(pause)
    return False


def send(token: str, key: str, label: str, summary: str) -> None:
    card = f"{SITE}/chuseok/chuseok_revision_{key}.png"        # 카드 이미지 = 이번 검토 변경 행렬(8도시×5일, Δ)
    full = f"{SITE}/chuseok/chuseok_history_{key}.png"          # 버튼 = 5일 전체 이력표 합본
    page = f"{SITE}/chuseok.html"
    if not wait_published(card):
        raise SystemExit(f"발행본에서 {card} 를 아직 받을 수 없음 — 다음 실행에 재시도")
    tpl = {"object_type": "feed",
           "content": {"title": f"추석 연휴 예보 · 8대도시 · {label} 검토본",
                       "description": summary[:200],
                       "image_url": card,
                       "link": {"web_url": full, "mobile_web_url": full}},
           "buttons": [{"title": "5일 전체 이력표", "link": {"web_url": full, "mobile_web_url": full}},
                       {"title": "사이트", "link": {"web_url": page, "mobile_web_url": page}}]}
    r = requests.post("https://kapi.kakao.com/v2/api/talk/memo/default/send",
                      headers={"Authorization": "Bearer " + token},
                      data={"template_object": json.dumps(tpl, ensure_ascii=False)}, timeout=30)
    if r.status_code != 200 or r.json().get("result_code") != 0:
        raise SystemExit(f"발송 실패: HTTP {r.status_code} {r.text[:200]}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--test", action="store_true"); p.add_argument("--force", action="store_true")
    a = p.parse_args()
    m = json.load(open(os.path.join(OUT_DIR, "chuseok", "chuseok.json"), encoding="utf-8"))
    key, label = m.get("latest_key"), m.get("latest_label")
    if not key:
        print("[카톡] 대상일 자료가 있는 검토본 없음"); return
    last_sent = open(SENT, encoding="utf-8").read().strip() if os.path.exists(SENT) else ""
    if key == last_sent and not (a.test or a.force):
        print(f"[카톡] 이미 보낸 검토본({label}) — 생략"); return
    summary = m.get("digest") or "대상일 예보 갱신"
    send(access_token(), key, label, summary)
    os.makedirs(os.path.dirname(SENT), exist_ok=True)
    open(SENT, "w", encoding="utf-8").write(key)
    print(f"[카톡] 발송 완료: {label} ({dt.datetime.now():%H:%M})")


if __name__ == "__main__":
    main()
