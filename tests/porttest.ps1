param([string]$Dosbox, [string]$Work)
# Starts DOSBox Staging once per webserver setup (tracking its PID), runs
# dlltest.exe against it, and stops exactly that process again.
$ErrorActionPreference = 'Stop'
$cases = @(
  @{ name = 'port 8086';                  conf = "webserver_enabled = on`nwebserver_port = 8086"; ini = '' },
  @{ name = 'no port set';                conf = "webserver_enabled = on"; ini = '' },
  @{ name = 'port 8080';                  conf = "webserver_enabled = on`nwebserver_port = 8080"; ini = '' },
  @{ name = 'custom port 9123';           conf = "webserver_enabled = on`nwebserver_port = 9123"; ini = '' },
  @{ name = 'all addresses, port 9125';   conf = "webserver_enabled = on`nwebserver_port = 9125`nwebserver_bind_address = 0.0.0.0"; ini = '' },
  @{ name = 'IPv6 ::1, port 9124';        conf = "webserver_enabled = on`nwebserver_port = 9124`nwebserver_bind_address = ::1"; ini = '' },
  @{ name = 'ini pins 8086, DOSBox 8080'; conf = "webserver_enabled = on`nwebserver_port = 8080"; ini = "port=8086" },
  @{ name = 'ini pins 8080, DOSBox 8080'; conf = "webserver_enabled = on`nwebserver_port = 8080"; ini = "port=8080" },
  @{ name = 'webserver off';              conf = "webserver_enabled = off"; ini = '' }
)
foreach ($c in $cases) {
  $conf = Join-Path $Work 'case.conf'
  Set-Content -Path $conf -Value ("[sdl]`nfullscreen = false`n[webserver]`n" + $c.conf + "`n[autoexec]`necho idle`n") -Encoding ascii
  $ini = Join-Path $Work 'dbxapi32.ini'
  Set-Content -Path $ini -Value ("[dbxapi]`nlog=1`n" + $c.ini + "`n") -Encoding ascii
  $log = Join-Path $Work 'dbxapi32.log'
  if (Test-Path $log) { Remove-Item $log }
  $p = Start-Process -FilePath $Dosbox -ArgumentList @('--noprimaryconf', '--nolocalconf', '-conf', "`"$conf`"") -PassThru -WindowStyle Minimized
  Start-Sleep -Seconds 4
  Write-Output ("=== {0}  (DOSBox pid {1})" -f $c.name, $p.Id)
  $out = & (Join-Path $Work 'dlltest.exe') $p.Id 2>&1
  ($out | Select-String -Pattern 'stand-in|interface|guest linear 0|write 16|after the cache|all ok|FAILED \(') | ForEach-Object { '  ' + $_.Line.Trim() }
  if (Test-Path $log) { Get-Content $log | Where-Object { $_ -match 'API on port|no DOSBox Staging API|not served' } | ForEach-Object { '  log: ' + ($_ -replace '^\S+ ', '') } }
  Stop-Process -Id $p.Id -Force
  Start-Sleep -Seconds 1
}
