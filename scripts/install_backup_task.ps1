<#
Registers the hourly backup task. The job itself decides whether a backup is due.

Installed build:
  .\install_backup_task.ps1 -Exe "C:\HealthCenter\HealthCenterSystem.exe"

From source:
  .\install_backup_task.ps1 -Exe "C:\proj\.venv\Scripts\python.exe" `
      -Arguments "-m backup.backup_job" -WorkingDirectory "C:\proj"

Remove with:  Unregister-ScheduledTask -TaskName HealthCenterBackup -Confirm:$false
#>
param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [string]$Arguments = "--backup",
    [string]$WorkingDirectory = (Split-Path -Parent $Exe),
    [string]$TaskName = "HealthCenterBackup"
)

$action = New-ScheduledTaskAction -Execute $Exe -Argument $Arguments -WorkingDirectory $WorkingDirectory
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date `
    -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
# S4U: runs whether or not the user is logged on, without storing a password.
# The task must run as the same Windows user whose %APPDATA%\HealthCenterSystem\.env holds the DB settings.
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "Task '$TaskName' registered. Test it now with:  Start-ScheduledTask -TaskName $TaskName"