# 매물 자동 수집을 Windows 작업 스케줄러에 등록합니다.
#   - 매일 20:00, 그리고 PC 를 켜고 로그인할 때(1분 뒤) 실행
#   - 전원선/배터리 상관없이 실행
#   - 그날 이미 전체 매물 수집을 마쳤으면 건너뜀 (run_daily.py --auto 가 판단)
# 실행: powershell -ExecutionPolicy Bypass -File .\register_task.ps1
# 해제: powershell -ExecutionPolicy Bypass -File .\register_task.ps1 -Remove
param([switch]$Remove)

$TaskName = "RealEstateListing"
foreach ($old in @("RealEstateDaily", $TaskName)) {
    if (Get-ScheduledTask -TaskName $old -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $old -Confirm:$false
    }
}
if ($Remove) { Write-Host "해제 완료: $TaskName"; exit 0 }

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"   # 창이 뜨지 않는 Python
if (-not (Test-Path $pythonw)) { Write-Host "먼저 '대시보드 실행.bat' 을 한 번 실행해 프로그램을 설치하세요."; exit 1 }

$action = New-ScheduledTaskAction -Execute $pythonw -Argument "run_daily.py --auto" -WorkingDirectory $root
$daily = New-ScheduledTaskTrigger -Daily -At 8:00pm
$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$logon.Delay = "PT1M"   # 로그인 1분 뒤 (인터넷 연결 대기)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 4) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($daily, $logon) -Settings $settings `
    -Description "부동산 정보 조회 시스템: 네이버 매물 자동 수집 (하루 한 번)" | Out-Null
Write-Host "등록 완료: $TaskName (매일 20:00 + 로그인 시, 하루 한 번)"
