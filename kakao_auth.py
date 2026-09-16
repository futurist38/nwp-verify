# -*- coding: utf-8 -*-
"""
카카오톡 "나에게 보내기" 1회 인증 (로컬 PC에서 한 번만 실행) — 2026-09-16 추석 예보 추적용.

준비 (developers.kakao.com, 5~10분):
  1) 내 애플리케이션 → 애플리케이션 추가 (이름 아무거나) → 앱 키에서 **REST API 키** 복사
  2) 앱 설정 → 플랫폼 → Web 사이트 도메인 등록: https://futurist38.github.io
  3) 제품 설정 → 카카오 로그인 → 활성화 ON, Redirect URI 등록: http://localhost:8765/oauth
  4) 제품 설정 → 카카오 로그인 → 동의항목 → "카카오톡 메시지 전송(talk_message)" 를 '선택 동의' 로 설정
     (동의항목 목록에 없으면 "카카오톡 메시지 전송" 사용 권한을 앱 권한 신청에서 켠다)
  5) (보안 탭에서 Client Secret 을 '사용함' 으로 켰다면) 그 값도 아래 입력

실행:  python kakao_auth.py
  → REST API 키(+선택: Client Secret) 입력 → 브라우저가 열림 → 카카오 로그인·동의 → 자동으로 코드를 받아 토큰 발급
  → 결과: .env 에 KAKAO_REST_KEY / KAKAO_REFRESH_TOKEN 저장 + GitHub 시크릿 등록 명령 안내.
토큰: access 6시간 · refresh 60일 (남은 기간 30일 미만일 때만 갱신 시 재발급). 9/23 까지는 갱신 없이 충분.
"""
import http.server
import json
import os
import threading
import urllib.parse
import webbrowser

import requests

import sslfix  # noqa: F401

REDIRECT = "http://localhost:8765/oauth"
ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
_code = {}


class _H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _code["code"] = q.get("code", [""])[0]
        _code["error"] = q.get("error", [""])[0]
        _code["state"] = q.get("state", [""])[0]
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
        self.wfile.write("<h3>인증 코드를 받았습니다. 이 창을 닫고 터미널로 돌아가세요.</h3>".encode("utf-8"))

    def log_message(self, *a):
        pass


def main():
    rest = input("REST API 키: ").strip()
    secret = input("Client Secret (없으면 Enter): ").strip()
    import secrets as _s
    state = _s.token_urlsafe(16)
    url = ("https://kauth.kakao.com/oauth/authorize?response_type=code&client_id=" + rest
           + "&redirect_uri=" + urllib.parse.quote(REDIRECT, safe="") + "&scope=talk_message&state=" + state)
    srv = http.server.HTTPServer(("localhost", 8765), _H)
    th = threading.Thread(target=srv.handle_request, daemon=True); th.start()
    print("브라우저를 엽니다. 안 열리면 이 주소를 직접 여세요:"); print(url)
    webbrowser.open(url)
    th.join(300)
    if not _code.get("code"):
        raise SystemExit("인증 코드를 받지 못했습니다: " + str(_code.get("error") or "시간 초과"))
    if _code.get("state") != state:
        raise SystemExit("state 불일치 — 다시 시도하세요")
    data = {"grant_type": "authorization_code", "client_id": rest, "redirect_uri": REDIRECT, "code": _code["code"]}
    if secret:
        data["client_secret"] = secret
    r = requests.post("https://kauth.kakao.com/oauth/token", data=data, timeout=30)
    tok = r.json()
    if "refresh_token" not in tok:
        raise SystemExit("토큰 발급 실패: " + json.dumps(tok, ensure_ascii=False))
    print("발급 OK: scope =", tok.get("scope"), "| refresh 만료(초) =", tok.get("refresh_token_expires_in"))
    # .env 갱신 (기존 KAKAO_* 줄 교체)
    lines = open(ENV, encoding="utf-8").read().splitlines() if os.path.exists(ENV) else []
    lines = [l for l in lines if not l.startswith(("KAKAO_REST_KEY=", "KAKAO_REFRESH_TOKEN=", "KAKAO_CLIENT_SECRET="))]
    lines += ["KAKAO_REST_KEY=" + rest, "KAKAO_REFRESH_TOKEN=" + tok["refresh_token"]]
    if secret:
        lines.append("KAKAO_CLIENT_SECRET=" + secret)
    open(ENV, "w", encoding="utf-8").write(chr(10).join(lines) + chr(10))
    print(".env 저장 완료. 시험 발송: python kakao_send.py --test")
    print("GitHub 시크릿 등록 (PowerShell):")
    print('  gh secret set KAKAO_REST_KEY --body "' + rest + '"')
    print('  gh secret set KAKAO_REFRESH_TOKEN --body "' + tok["refresh_token"] + '"')
    if secret:
        print('  gh secret set KAKAO_CLIENT_SECRET --body "' + secret + '"')


if __name__ == "__main__":
    main()
