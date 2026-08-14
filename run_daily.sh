#!/usr/bin/env bash
# KPX 모델 표출 일일 실행 스크립트
# 예: crontab -e 에 아래 한 줄 추가 (매일 06:10 KST — 00UTC 런 배포 완료 후)
#   10 6 * * * /path/to/kpx-model-charts/run_daily.sh >> /path/to/kpx-model-charts/cron.log 2>&1
set -e
cd "$(dirname "$0")"

echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') 실행 시작 ====="

python3 fetch_ecmwf.py || echo "[경고] ECMWF 수신 실패 — GFS만으로 진행"
python3 fetch_gfs.py   || echo "[경고] GFS 수신 실패 — ECMWF만으로 진행"
python3 plot_charts.py

# 30일 지난 원본 GRIB 정리 (디스크 관리)
find data -name "*.grib2" -mtime +30 -delete 2>/dev/null || true

echo "===== 실행 종료 ====="
