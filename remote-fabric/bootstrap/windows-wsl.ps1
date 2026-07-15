[CmdletBinding(DefaultParameterSetName = 'Plan')]
param(
  [Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9._-]+$')][string]$Distro,
  [Parameter(ParameterSetName = 'Plan')][switch]$Plan,
  [Parameter(ParameterSetName = 'Apply')][switch]$Apply,
  [Parameter(ParameterSetName = 'Validate')][switch]$Validate
)
$ErrorActionPreference = 'Stop'
$wsl = (Get-Command wsl.exe -ErrorAction Stop).Source
$distros = @(& $wsl --list --quiet) | ForEach-Object { $_.Trim([char]0).Trim() }
if ($distros -notcontains $Distro) { throw "WSL distro not found: $Distro" }
$args = @('--distribution', $Distro, '--exec', '/bin/sh', '-lc', 'cd "$HOME"; case "$PWD" in /mnt/*) exit 12;; esac; command -v git python3 tmux pi >/dev/null 2>&1')
if ($Plan) {
  [pscustomobject]@{ schema = 1; action = 'plan'; distro = $Distro; wslArgv = $args } | ConvertTo-Json -Compress
  exit 0
}
& $wsl @args
if ($LASTEXITCODE -ne 0) { throw "WSL guest validation failed ($LASTEXITCODE)" }
if ($Apply) {
  $taskName = 'RemoteFabric-WSL-' + $Distro
  $action = New-ScheduledTaskAction -Execute $wsl -Argument ('--distribution "{0}" --exec /bin/sleep infinity' -f $Distro)
  $trigger = New-ScheduledTaskTrigger -AtLogOn
  $principalId = (& whoami).Trim()
  $principal = New-ScheduledTaskPrincipal -UserId $principalId -LogonType S4U -RunLevel Limited
  Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
  Start-ScheduledTask -TaskName $taskName
}
[pscustomobject]@{ schema = 1; action = $(if ($Apply) {'apply'} else {'validate'}); distro = $Distro; ready = $true } | ConvertTo-Json -Compress
