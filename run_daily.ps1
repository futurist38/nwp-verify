# KPX 모델 표출·오답노트 일일 배치 (Windows 작업 스케줄러용)
#
# 등록 예 (관리자 불필요, 매일 06:10 / 10:30 KST 2회):
#   schtasks /Create /TN "kpx-model-06" /SC DAILY /ST 06:10 /TR "powershell -NoProfile -ExecutionPolicy Bypass -File \"D:\Research\웹기반 모델프로젝트\kpx-model-charts\run_daily.ps1\""
#   schtasks /Create /TN "kpx-model-10" /SC DAILY /ST 10:30 /TR "powershell -NoProfile -ExecutionPolicy Bypass -File \"D:\Research\웹기반 모델프로젝트\kpx-model-charts\run_daily.ps1\""
#
# 06:10 실행은 대개 ECMWF 전일 12UTC + GFS 당일 18UTC(전일 기준) 런,
# 10:30 실행은 당일 00UTC 런이 잡힌다 (ECMWF 오픈데이터 00Z는 09~10 KST 배포).

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$py = Join-Path $root '.venv\Scripts\python.exe'
$log = Join-Path $root 'cron.log'

# 콘솔·로그 한글 깨짐 방지
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [Text.Encoding]::UTF8

function Step([string]$name, [string[]]$cmdArgs) {
    "===== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $name =====" | Tee-Object -FilePath $log -Append
    & $py @cmdArgs 2>&1 | Tee-Object -FilePath $log -Append
    if ($LASTEXITCODE -ne 0) {
        "[경고] $name 실패 (exit $LASTEXITCODE) — 계속 진행" | Tee-Object -FilePath $log -Append
    }
}

Step 'ECMWF 수신'   @('fetch_ecmwf.py')
Step 'GFS 수신'     @('fetch_gfs.py')
Step '표출'         @('plot_charts.py')
Step '예측 적재'    @('verify.py', 'archive')
Step '채점(어제)'   @('verify.py', 'score')
Step '집계'         @('verify.py', 'report')

# 30일 지난 GRIB 정리
Get-ChildItem (Join-Path $root 'data') -Filter '*.grib2' -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -Force -Confirm:$false

# 커밋 전 인증키 노출 점검용 리마인더 (git 커밋은 수동)
"===== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') 배치 종료 =====" | Tee-Object -FilePath $log -Append
