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
  # ── Cloudflare R2 (2026-09-08): 그림은 R2, site-data 는 JSON·나우캐스트만. R2_BUCKET 이 비면 예전 방식 그대로 ──
  if [ -n "${R2_BUCKET:-}" ]; then
    # NO_CHECK_BUCKET: 버킷 한정 토큰은 버킷 목록·생성 권한이 없어 rclone 의 버킷 확인이 403 으로 실패한다.
    # R2_ENDPOINT 는 로컬 시험용(rclone serve s3) — 평소엔 비워 두면 Cloudflare 주소.
    export RCLONE_CONFIG_R2_TYPE=s3 RCLONE_CONFIG_R2_PROVIDER=Cloudflare RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true \
           RCLONE_CONFIG_R2_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" RCLONE_CONFIG_R2_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
           RCLONE_CONFIG_R2_ENDPOINT="${R2_ENDPOINT:-https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com}" RCLONE_CONFIG_R2_ACL=private
    # 보존 정리 — build_site.py 의 로컬 정리와 같은 규칙(날짜 폴더명 기준): MAX_DAYS 지나면 폴더째,
    # UPPER_MAX_DAYS 지나면 상층(p925~p200)만. 업로드 시각(modtime)으로 고르면 객체마다 HEAD 요청이라 폴더명으로 판정.
    # tr -d '\r': 윈도우 python 은 파이프에도 CRLF 를 쓴다 — 로컬 시험에서 "7\r" 이 들어가 숫자 비교가 깨졌다(2026-09-09)
    read -r MAXD UPD < <({ python -c "import build_site as b; print(b.MAX_DAYS, b.UPPER_MAX_DAYS)" 2>/dev/null || echo "14 7"; } | tr -d '\r')
    CUT=$(date -u -d "-${MAXD} days" +%Y%m%d); CUT_UP=$(date -u -d "-${UPD} days" +%Y%m%d)
    for d in $(rclone lsf --dirs-only "r2:${R2_BUCKET}/archive" 2>/dev/null | tr -d /); do
      [[ "$d" =~ ^[0-9]{8}$ ]] || continue
      if [ "$d" -lt "$CUT" ]; then
        { rclone purge "r2:${R2_BUCKET}/archive/$d" -q && echo "[publish] R2 정리: $d 폴더 삭제"; } || true
      elif [ "$d" -lt "$CUT_UP" ]; then
        rclone delete "r2:${R2_BUCKET}/archive/$d" --include "*_f???_p[0-9][0-9][0-9].webp" -q || true
      fi
    done
    rclone lsf -R --files-only "r2:${R2_BUCKET}/archive" > .r2_listing 2>/dev/null \
      || { echo "::warning::[publish] R2 목록 조회 실패 — 이번 manifest 는 러너 산출만 반영"; : > .r2_listing; }
    export R2_LISTING="$(pwd)/.r2_listing" IMG_BASE="${R2_PUBLIC_URL:-}"
    echo "[publish] R2 목록 $(wc -l < .r2_listing)개, 접두어 ${IMG_BASE:-없음}"
  fi
  python build_site.py --site-dir "$SITE" "$@"
  if [ -n "${R2_BUCKET:-}" ]; then
    UP_OK=1
    if [ -d "$SITE/archive" ]; then
      # 새 그림 업로드(있는 것은 건너뜀). --size-only: 그림은 한 번 만들면 안 바뀐다 — modtime 비교는 객체마다 HEAD 라 뺀다
      rclone copy "$SITE/archive" "r2:${R2_BUCKET}/archive" --size-only --transfers 32 --checkers 32 -q \
        && echo "[publish] archive → R2 업로드" \
        || { UP_OK=0; echo "::warning::[publish] R2 업로드 실패 — 이번엔 site-data 에 그림을 다 남긴다"; }
    fi
    # 최근 창은 site-data(github.io)에도 둔다 — 회사망이 r2.dev 를 막는다(2026-09-09 실측). 창 = build_site.local_cuts()
    # (지도 LOCAL_DAYS_MAPS일, 지상·상층 LOCAL_DAYS_UPPER일 — manifest.local_cut 과 같은 값). 창 밖은 지우고 창 안은 R2 에서
    # 채운다(첫 전환·복구 때 내려받고 평소엔 목록 비교만). 업로드가 실패했으면 아무것도 지우지 않는다.
    if [ "$UP_OK" = 1 ]; then
      read -r CUT_LM CUT_LU < <(python -c "import build_site as b; print(*b.local_cuts())" | tr -d '\r')
      mkdir -p "$SITE/archive"
      for d in "$SITE"/archive/????????; do
        [ -d "$d" ] || continue; n=$(basename "$d")
        if [ "$n" -lt "$CUT_LM" ]; then rm -rf "$d"
        elif [ "$n" -lt "$CUT_LU" ]; then
          find "$d" -type f \( -name '*_f???_sfc.webp' -o -name '*_f???_p[0-9][0-9][0-9].webp' \) -delete
        fi
      done
      {
        for n in $(rclone lsf --dirs-only "r2:${R2_BUCKET}/archive" 2>/dev/null | tr -d /); do
          [[ "$n" =~ ^[0-9]{8}$ ]] && [ "$n" -ge "$CUT_LM" ] || continue
          if [ "$n" -lt "$CUT_LU" ]; then echo "- /$n/*_f???_sfc.webp"; echo "- /$n/*_f???_p[0-9][0-9][0-9].webp"; fi
          echo "+ /$n/**"
        done
        echo "- **"
      } > .r2_filter
      rclone copy "r2:${R2_BUCKET}/archive" "$SITE/archive" --filter-from .r2_filter --size-only --transfers 32 --checkers 32 -q \
        && echo "[publish] site-data 창 유지: 지도 ≥$CUT_LM, 지상·상층 ≥$CUT_LU — $(find "$SITE/archive" -type f | wc -l)장" \
        || echo "::warning::[publish] R2→site-data 창 복원 실패 — 뷰어가 R2 로 대체 시도한다"
    fi
  fi
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
