# NWP 모델 표출·오답노트 일일 배치 (Windows 작업 스케줄러용)
#
# 주의: 이 파일은 반드시 UTF-8 with BOM 으로 저장할 것.
#   PS5.1은 BOM 없는 UTF-8 스크립트를 CP949로 읽어 한글 리터럴이 깨진다 (2026-08-18 실측).
#
# 등록 (창 숨김 — 창을 닫으면 배치가 죽는 사고 방지):
#   powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "...\run_daily.ps1"
#   kpx-model-06 (06:10 KST): 대개 ECMWF 전일 12UTC + GFS 당일 18UTC(전일 기준) 런
#   kpx-model-10 (10:30 KST): 당일 00UTC 런 (ECMWF 00Z는 09~10 KST 배포)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$py = Join-Path $root '.venv\Scripts\python.exe'
$log = Join-Path $root 'cron.log'

# 콘솔·로그 한글 깨짐 방지
$env:PYTHONIOENCODING = 'utf-8'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}

function Write-Log([string]$line) {
    Add-Content -LiteralPath $log -Value $line -Encoding UTF8
    Write-Host $line
}

function Step([string]$name, [string[]]$cmdArgs) {
    Write-Log "===== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $name ====="
    # 2>&1 의 ErrorRecord 를 즉시 문자열화한다. PS5.1은 네이티브 stderr를
    # NativeCommandError로 포장해 빨간 오류처럼 표시하기 때문 (ECMWF 안내문 등 무해한 출력 포함).
    # tqdm 진행바 줄('… 45%|████ …')은 로그에서 제외.
    & $py @cmdArgs 2>&1 | ForEach-Object { "$_" } |
        Where-Object { $_ -notmatch '\d+%\|' } |
        ForEach-Object { Write-Log $_ }
    if ($LASTEXITCODE -ne 0) {
        Write-Log "[경고] $name 실패 (exit $LASTEXITCODE) — 계속 진행"
    }
}

Step 'ECMWF 수신'   @('fetch_ecmwf.py')
Step 'GFS 수신'     @('fetch_gfs.py')
Step 'KIM 수신'     @('fetch_kim.py')
Step '표출'         @('plot_charts.py')
Step '예측 적재'    @('verify.py', 'archive')
Step '채점(어제)'   @('verify.py', 'score')
Step '집계'         @('verify.py', 'report')
Step '관측 지도'    @('plot_obsmap.py')
Step '오차 지도'    @('plot_verifmap.py')
Step '메일 발송'    @('send_summary.py')   # GMAIL_* 미설정 시 자동 건너뜀

# 30일 지난 GRIB 정리
Get-ChildItem (Join-Path $root 'data') -Filter '*.grib2' -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -Force -Confirm:$false

Write-Log "===== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') 배치 종료 ====="
