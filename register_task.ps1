# Windows 작업 스케줄러에 일일 배치(매일 05:00)를 등록합니다.
# 실행: PowerShell 에서  powershell -ExecutionPolicy Bypass -File .\register_task.ps1
# 해제: Unregister-ScheduledTask -TaskName "RealEstateDaily" -Confirm:$false
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$action = New-ScheduledTaskAction -Execute $python -Argument "run_daily.py" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At 5:00am
# PC 가 05:00 에 꺼져 있었으면 켜진 뒤 실행
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 6) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "RealEstateDaily" -Action $action -Trigger $trigger -Settings $settings `
    -Description "부동산 정보 조회 시스템 일일 수집" -Force | Out-Null
Write-Host "등록 완료: RealEstateDaily (매일 05:00)"
