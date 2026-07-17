[CmdletBinding(DefaultParameterSetName = 'Plan')]
param(
  [Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9._-]+$')][string]$Distro,
  [Parameter(ParameterSetName = 'Plan')][switch]$Plan,
  [Parameter(ParameterSetName = 'Apply')][switch]$Apply,
  [Parameter(ParameterSetName = 'Validate')][switch]$Validate,
  [ValidateRange(0, 65535)][int]$LoopbackForwardPort = 0,
  [ValidatePattern('^[0-9A-Fa-f:.]+/[0-9]{1,3}$')][string]$LanRecoverySubnet = ''
)
$ErrorActionPreference = 'Stop'
$wsl = (Get-Command wsl.exe -ErrorAction Stop).Source
$distros = @(& $wsl --list --quiet) | ForEach-Object { $_.Trim([char]0).Trim() }
if ($distros -notcontains $Distro) { throw "WSL distro not found: $Distro" }
$args = @('--distribution', $Distro, '--exec', '/bin/sh', '-lc', 'cd "$HOME"; case "$PWD" in /mnt/*) exit 12;; esac; command -v git python3 tmux pi >/dev/null 2>&1')
if ($Plan) {
  [pscustomobject]@{
    schema = 1
    action = 'plan'
    distro = $Distro
    wslArgv = $args
    loopbackForwardPort = $LoopbackForwardPort
    lanRecoverySubnet = $LanRecoverySubnet
  } | ConvertTo-Json -Compress
  exit 0
}
& $wsl @args
if ($LASTEXITCODE -ne 0) { throw "WSL guest validation failed ($LASTEXITCODE)" }
if ($Apply) {
  $taskName = 'RemoteFabric-WSL-' + $Distro
  $stateDirectory = Join-Path $env:LOCALAPPDATA 'RemoteFabric'
  $keepalivePath = Join-Path $stateDirectory 'wsl-keepalive.ps1'
  New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
  @'
param(
  [Parameter(Mandatory = $true)][string]$WslPath,
  [Parameter(Mandatory = $true)][string]$Distro,
  [ValidateRange(0, 65535)][int]$LoopbackForwardPort = 0
)
$ErrorActionPreference = 'Stop'
while ($true) {
  $process = Start-Process -FilePath $WslPath -ArgumentList @('--distribution', $Distro, '--exec', '/bin/sleep', 'infinity') -PassThru -WindowStyle Hidden
  try {
    if ($LoopbackForwardPort -gt 0) {
      $guestAddress = $null
      for ($attempt = 0; $attempt -lt 30 -and -not $guestAddress; $attempt++) {
        Start-Sleep -Milliseconds 500
        $addresses = (& $WslPath --distribution $Distro --exec hostname -I) -replace [char]0, ''
        $guestAddress = ([regex]::Matches($addresses, '(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])') | Select-Object -First 1).Value
      }
      if (-not $guestAddress) { throw "Could not determine the WSL guest address" }
      & netsh.exe interface portproxy delete v4tov4 listenaddress=127.0.0.1 listenport=$LoopbackForwardPort | Out-Null
      & netsh.exe interface portproxy add v4tov4 listenaddress=127.0.0.1 listenport=$LoopbackForwardPort connectaddress=$guestAddress connectport=$LoopbackForwardPort | Out-Null
    }
    Wait-Process -Id $process.Id
  } finally {
    if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
  }
  Start-Sleep -Seconds 2
}
'@ | Set-Content -Path $keepalivePath -Encoding UTF8

  $actionArguments = @(
    '-NoProfile',
    '-ExecutionPolicy', 'Bypass',
    '-File', ('"{0}"' -f $keepalivePath),
    '-WslPath', ('"{0}"' -f $wsl),
    '-Distro', $Distro,
    '-LoopbackForwardPort', $LoopbackForwardPort
  ) -join ' '
  $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $actionArguments
  $startupTrigger = New-ScheduledTaskTrigger -AtStartup
  $watchdogTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Days 3650)
  $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable
  $principalId = (& whoami).Trim()
  $principal = New-ScheduledTaskPrincipal -UserId $principalId -LogonType S4U -RunLevel Highest
  Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($startupTrigger, $watchdogTrigger) -Settings $settings -Principal $principal -Force | Out-Null
  Start-ScheduledTask -TaskName $taskName

  if ($LanRecoverySubnet) {
    $firewallName = 'RemoteFabric-SSH-LAN-Recovery'
    Get-NetFirewallRule -DisplayName $firewallName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName $firewallName -Direction Inbound -Action Allow -Protocol TCP -LocalPort 22 -RemoteAddress $LanRecoverySubnet -Profile Any | Out-Null
  }
}
[pscustomobject]@{
  schema = 1
  action = $(if ($Apply) {'apply'} else {'validate'})
  distro = $Distro
  loopbackForwardPort = $LoopbackForwardPort
  lanRecoverySubnet = $LanRecoverySubnet
  ready = $true
} | ConvertTo-Json -Compress
