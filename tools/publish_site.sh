#!/usr/bin/env bash
# site-data 브랜치 발행 — 낙관적 잠금(force-with-lease) + 재시도 (2026-09-06).
#
# 왜: daily·obs-hourly 가 동시성 그룹 하나를 나눠 쓰던 시절, 시간별 관측 갱신이
#     daily 전체(기상청 API 가 막히는 날 80~100분)를 기다리다가 다음 시간분에 밀려
#     취소됐다 → 관측·예보-관측이 2~3시간씩 멈춤 (9/5 실측). 그룹을 분리하되
#     발행이 서로를 덮어쓰지 않게 여기서 '내가 본 site-data 위에만 push' 를 보장한다.
#
# 절차: 1) 최신 site-data 를 site_build 에 복원  2) 이번 러너 산출을 얹음(build_site.py)
#       3) 복원 시점 SHA 를 전제로 push. 그 사이 다른 워크플로가 먼저 발행했으면 거부되므로
#          1)부터 다시 — 복원본이 새것이 되고 build_site 의 무회귀 가드가 더 오래된
#          관측으로 되돌리는 일을 막는다.
# 사용: tools/publish_site.sh "커밋 메시지" [build_site.py 추가 인자 — 예: --hourly]
set -euo pipefail
MSG="$1"; shift
SITE="${SITE_DIR:-site_build}"   # 테스트 때 다른 폴더를 쓰려면 SITE_DIR
IDX="$(pwd)/.git/site-index"
# commit-tree 도 작성자 정보가 필요하다 — 이 스크립트가 잡의 첫 git 쓰기일 수 있으니 여기서
git config user.name  >/dev/null 2>&1 || git config user.name "nwp-bot"
git config user.email >/dev/null 2>&1 || git config user.email "actions@users.noreply.github.com"
for i in 1 2 3 4 5 6; do
  mkdir -p "$SITE"
  BASE=""
  if git fetch -q origin site-data 2>/dev/null; then
    BASE=$(git rev-parse FETCH_HEAD)
    git --work-tree="$SITE" checkout -q FETCH_HEAD -- .
    git reset -q                       # 인덱스 원복 (--work-tree checkout 이 인덱스를 바꿈)
  fi
  python build_site.py --site-dir "$SITE" "$@"
  rm -f "$IDX"
  GIT_INDEX_FILE="$IDX" git --work-tree="$SITE" add -A
  TREE=$(GIT_INDEX_FILE="$IDX" git write-tree)
  COMMIT=$(git commit-tree "$TREE" -m "$MSG")
  if [ "${DRY_RUN:-}" = "1" ]; then
    echo "[publish] DRY_RUN — push 생략. 기준 ${BASE:0:7}, 트리 ${TREE:0:7}, 커밋 ${COMMIT:0:7}"; exit 0
  fi
  # BASE 가 비면 '브랜치가 아직 없다' 는 전제 — 처음 발행할 때만 해당
  if git push -q --force-with-lease="refs/heads/site-data:${BASE}" origin "$COMMIT:refs/heads/site-data"; then
    echo "[publish] site-data 발행 완료 (시도 $i, 기준 ${BASE:0:7})"; exit 0
  fi
  echo "::warning::[publish] site-data 가 그 사이 바뀜 — 재시도 $i"
  sleep $((RANDOM % 20 + 5))
done
echo "::error::[publish] site-data 발행 실패 (6회 충돌)"; exit 1
