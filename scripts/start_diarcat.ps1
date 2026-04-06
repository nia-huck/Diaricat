param(
  [switch]$Api,
  [int]$Port = 8765
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$recoverScript = Join-Path $PSScriptRoot "recover_runtime_space.ps1"
$exePath = Join-Path $root "dist\Diarcat.exe"

if (-not (Test-Path $exePath)) {
  throw "Executable not found: $exePath"
}

& $recoverScript -RecommendedFreeGb 6
$freeGb = [Math]::Round((Get-PSDrive C).Free / 1GB, 2)
if ($freeGb -lt 6) {
  throw "Runtime space preflight failed. Free more disk space and retry."
}

if ($Api) {
  Start-Process -FilePath $exePath -ArgumentList @("api", "--host", "127.0.0.1", "--port", "$Port")
  Write-Host "Diarcat API started on http://127.0.0.1:$Port"
} else {
  Start-Process -FilePath $exePath
  Write-Host "Diarcat desktop started."
}
