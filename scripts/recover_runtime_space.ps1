param(
  [int]$RecommendedFreeGb = 6
)

$ErrorActionPreference = "Stop"

function Remove-StaleOnefileTemp {
  param([string]$BaseDir)
  if (-not (Test-Path $BaseDir)) {
    return 0
  }

  $removed = 0
  Get-ChildItem -Path $BaseDir -Directory -Filter "_MEI*" -ErrorAction SilentlyContinue | ForEach-Object {
    try {
      Remove-Item -Path $_.FullName -Recurse -Force -ErrorAction Stop
      $removed++
    } catch {
      # Best-effort cleanup only.
    }
  }
  return $removed
}

$tempDir = $env:TEMP
$removedFromTemp = Remove-StaleOnefileTemp -BaseDir $tempDir
$removedFromDistTemp = Remove-StaleOnefileTemp -BaseDir (Join-Path (Get-Location).Path "dist\temp")

$drive = Get-PSDrive C
$freeGb = [Math]::Round($drive.Free / 1GB, 2)

Write-Host ("Removed stale onefile dirs: temp={0}, dist\\temp={1}" -f $removedFromTemp, $removedFromDistTemp)
Write-Host ("Current free space on C:: {0} GB" -f $freeGb)

if ($freeGb -lt $RecommendedFreeGb) {
  Write-Warning ("Low disk space for Diarcat onefile extraction. Recommended >= {0} GB free." -f $RecommendedFreeGb)
  exit 2
}

Write-Host "Runtime space check: OK"
