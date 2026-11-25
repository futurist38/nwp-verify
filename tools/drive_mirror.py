"""브리핑 묶음(briefing/latest.md)을 구글 드라이브의 고정 파일 하나에 덮어쓴다 (2026-11-25).

왜: Claude 는 셸에서 curl 로 briefing/YYYYMMDDHH.md 를 읽지만, Gemini 앱처럼 URL 을 직접
    못 읽는 AI 는 드라이브 파일만 불러올 수 있다. 매시 새 파일을 만들지 않고 파일 하나를
    덮어써서 'AI 가 늘 같은 파일을 연다'를 보장한다.

방식: 서비스 계정은 개인 드라이브에 새 파일을 소유할 수 없다(저장 용량 없음). 그래서
      사용자가 미리 만든 파일을 서비스 계정에 '편집자'로 공유해 두고, 여기서는 그 파일의
      내용만 바꾼다. .md 파일은 UTF-8 Markdown으로 저장한다.

환경변수:
  GDRIVE_SA_JSON  서비스 계정 키 JSON 원문 (GitHub Secret)
  GDRIVE_FILE_ID  덮어쓸 드라이브 파일 ID (GitHub Variable 또는 Secret)
둘 중 하나라도 비어 있으면 아무것도 하지 않고 정상 종료한다(설정 전 머지해도 안전).

사용: python tools/drive_mirror.py <latest.md 경로>
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sys
import uuid

PAGES = "https://futurist38.github.io/nwp-verify/briefing"
GDOC = "application/vnd.google-apps.document"
MARKDOWN = "text/markdown"
_GEN = re.compile(r"생성\s+(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})\s*KST")


def source_stamp(md: str) -> str | None:
    """첫 줄 '# 브리핑 묶음 — 생성 2026-11-25 09:30 KST' 에서 YYYYMMDDHH 를 뽑는다."""
    m = _GEN.search(md.split("\n", 1)[0])
    return "".join(m.groups()[:4]) if m else None


def build_payload(md: str, now_kst: dt.datetime) -> str:
    """AI 가 신선도를 스스로 판단할 수 있게 머리말 두 줄을 붙인다."""
    stamp = source_stamp(md)
    src = f"{PAGES}/{stamp}.md" if stamp else f"{PAGES}/ (생성 시각 판독 실패)"
    head = (
        f"> 드라이브 사본 · 원본 {src} · 사본 갱신 {now_kst:%Y-%m-%d %H:%M} KST\n"
        "> 바로 아래 '생성' 시각이 지금보다 2시간 이상 이르면 구자료로 취급하고 그 사실을 밝힐 것.\n\n"
    )
    return head + md


def content_hash(md: str) -> str:
    # 머리말(갱신 시각)은 매번 바뀌므로 원본 본문만으로 비교한다.
    return hashlib.sha256(md.encode("utf-8")).hexdigest()[:16]


def _token(sa_json: str) -> str:
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request

    creds = service_account.Credentials.from_service_account_info(
        json.loads(sa_json), scopes=["https://www.googleapis.com/auth/drive"])
    creds.refresh(Request())
    return creds.token


def mirror(md_path: str, sa_json: str, file_id: str, session=None, token: str | None = None,
           now_kst: dt.datetime | None = None) -> str:
    """반환: 'skipped' (내용 동일) 또는 'updated'."""
    if session is None:
        import requests
        session = requests.Session()
    tok = token or _token(sa_json)
    hdr = {"Authorization": f"Bearer {tok}"}
    with open(md_path, encoding="utf-8") as fp:
        md = fp.read()
    if not md.strip():
        raise SystemExit("::error::[drive] 원본 브리핑이 비어 있음 — 덮어쓰지 않음")

    meta = session.get(f"https://www.googleapis.com/drive/v3/files/{file_id}",
                 params={"fields": "id,name,mimeType,appProperties", "supportsAllDrives": "true"},
                 headers=hdr, timeout=30)
    if meta.status_code == 404:
        raise SystemExit("::error::[drive] 파일을 찾을 수 없음 — GDRIVE_FILE_ID 와 서비스 계정 '편집자' 공유를 확인")
    meta.raise_for_status()
    info = meta.json()
    mime = info["mimeType"]
    if mime == GDOC:
        media_type = "text/plain"
    elif info["name"].lower().endswith(".md") and mime in (MARKDOWN, "text/plain", "text/x-markdown", "application/octet-stream"):
        media_type = MARKDOWN
    elif mime == "text/plain" and info["name"].lower().endswith(".txt"):
        media_type = "text/plain"
    else:
        raise SystemExit("::error::[drive] 대상 파일 형식을 확인하세요 (.md, .txt, Google 문서)")
    target_type = GDOC if mime == GDOC else media_type
    h = content_hash(md)
    if (info.get("appProperties") or {}).get("src_sha") == h and mime == target_type:
        print(f"[drive] 변경 없음 — 건너뜀 ({info.get('name')})")
        return "skipped"

    now_kst = now_kst or dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    body = build_payload(md, now_kst).encode("utf-8")
    boundary = uuid.uuid4().hex
    meta_part = json.dumps({
        "mimeType": target_type,
        "appProperties": {"src_sha": h, "src_stamp": source_stamp(md) or ""},
    })
    multipart = (
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta_part}\r\n"
        f"--{boundary}\r\nContent-Type: {media_type}; charset=UTF-8\r\n\r\n"
    ).encode("utf-8") + body + f"\r\n--{boundary}--\r\n".encode("utf-8")
    r = session.patch(f"https://www.googleapis.com/upload/drive/v3/files/{file_id}",
                params={"uploadType": "multipart", "supportsAllDrives": "true", "fields": "id,name,mimeType"},
                headers={**hdr, "Content-Type": f"multipart/related; boundary={boundary}"},
                data=multipart, timeout=60)
    if r.status_code == 403:
        raise SystemExit("::error::[drive] 권한 거부 — 서비스 계정이 '편집자'인지, Drive API 가 켜져 있는지 확인")
    r.raise_for_status()
    kind = r.json()["mimeType"]
    if kind != target_type:
        raise SystemExit(f"::error::[drive] 업로드 후 대상 MIME 형식 확인 필요 ({kind})")
    print(f"[drive] 갱신 완료 — {info.get('name')} ({kind}), 원본 {source_stamp(md)}, {len(body) / 1024:.0f}KB")
    return "updated"


def main(argv: list[str]) -> int:
    md_path = argv[1] if len(argv) > 1 else "site/briefing/latest.md"
    sa, fid = os.environ.get("GDRIVE_SA_JSON", ""), os.environ.get("GDRIVE_FILE_ID", "")
    if not sa.strip() or not fid.strip():
        print("::notice::[drive] GDRIVE_SA_JSON / GDRIVE_FILE_ID 미설정 — 드라이브 사본 건너뜀")
        return 0
    if not os.path.exists(md_path):
        print(f"::error::[drive] 원본 없음: {md_path}")
        return 1
    mirror(md_path, sa, fid.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
