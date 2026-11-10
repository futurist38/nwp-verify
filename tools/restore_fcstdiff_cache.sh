#!/usr/bin/env bash
# Call before collection: a queued/re-run workflow may check out an older SHA.
# Restore only immutable forecast inputs; never checkout/reset source or history.
set -euo pipefail
if ! git fetch -q origin main; then
  echo '::warning::[예보변화] 최신 캐시 조회 실패 — 체크아웃의 캐시 사용'
  exit 0
fi
if git cat-file -e FETCH_HEAD:verification/fcstdiff 2>/dev/null; then
  git archive FETCH_HEAD verification/fcstdiff | tar -x
  echo '[예보변화] 최신 main의 발표 캐시 복원'
else
  echo '[예보변화] 저장된 발표 캐시 없음 — 첫 수집 필요'
fi
