param(
  [string]$Root = (Split-Path -Parent $PSScriptRoot),
  [string]$ProjectId = "",
  [int]$MaxJobFiles = 40,
  [int]$MaxFailedProjects = 8
)

$ErrorActionPreference = "Stop"

$rootPath = (Resolve-Path $Root).Path
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$bundleRoot = Join-Path $rootPath "temp\debug_bundle_$timestamp"
New-Item -ItemType Directory -Force $bundleRoot | Out-Null

function Copy-IfExists {
  param([string]$Source, [string]$Dest)
  if (Test-Path $Source) {
    New-Item -ItemType Directory -Force (Split-Path -Parent $Dest) | Out-Null
    Copy-Item -Path $Source -Destination $Dest -Recurse -Force
  }
}

function Redact-SensitiveText {
  param([string]$Text)
  if ($null -eq $Text) { return "" }

  $redacted = $Text
  $redacted = [regex]::Replace(
    $redacted,
    '(?im)^(\s*(?:hf_token|huggingface_token|openai_api_key|api_key|token|password|secret|access_key|client_secret)\s*:\s*).*$',
    '$1"<redacted>"'
  )
  $redacted = [regex]::Replace(
    $redacted,
    '(?im)^(\s*(?:hf_token|huggingface_token|openai_api_key|api_key|token|password|secret|access_key|client_secret)\s*=\s*).*$',
    '$1<redacted>'
  )
  return $redacted
}

function Write-SanitizedConfig {
  param([string]$Source, [string]$Dest)
  if (-not (Test-Path $Source)) {
    return
  }
  New-Item -ItemType Directory -Force (Split-Path -Parent $Dest) | Out-Null
  $content = Get-Content -Raw -Path $Source
  $sanitized = Redact-SensitiveText -Text $content
  $sanitized | Out-File -FilePath $Dest -Encoding utf8
}

function Write-SanitizedEnvSnapshot {
  param([string]$Dest)
  New-Item -ItemType Directory -Force (Split-Path -Parent $Dest) | Out-Null
  $sensitiveNamePattern = '(?i)(token|secret|password|api[_-]?key|access[_-]?key|credential|cookie|session)'
  Get-ChildItem Env: |
    Sort-Object Name |
    ForEach-Object {
      if ($_.Name -match $sensitiveNamePattern) {
        "{0}=<redacted>" -f $_.Name
      } else {
        "{0}={1}" -f $_.Name, $_.Value
      }
    } | Out-File -FilePath $Dest -Encoding utf8
}

Write-Host "Creating debug bundle at: $bundleRoot"

# Core logs/config
Write-SanitizedConfig (Join-Path $rootPath "config\default.yaml") (Join-Path $bundleRoot "config\default.yaml")
Copy-IfExists (Join-Path $rootPath "logs") (Join-Path $bundleRoot "logs")
Copy-IfExists (Join-Path $rootPath "dist\logs") (Join-Path $bundleRoot "dist\logs")

# Jobs snapshot (latest N)
$jobsSrc = Join-Path $rootPath "workspace\jobs"
$jobsDst = Join-Path $bundleRoot "workspace\jobs"
if (Test-Path $jobsSrc) {
  New-Item -ItemType Directory -Force $jobsDst | Out-Null
  Get-ChildItem -Path $jobsSrc -Filter *.json -File |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First $MaxJobFiles |
    ForEach-Object { Copy-Item $_.FullName (Join-Path $jobsDst $_.Name) -Force }
}

# Project snapshot: specific project or recent failed ones
$projectsSrc = Join-Path $rootPath "workspace\projects"
$projectsDst = Join-Path $bundleRoot "workspace\projects"
if (Test-Path $projectsSrc) {
  New-Item -ItemType Directory -Force $projectsDst | Out-Null
  if ($ProjectId -and (Test-Path (Join-Path $projectsSrc $ProjectId))) {
    Copy-Item -Path (Join-Path $projectsSrc $ProjectId) -Destination (Join-Path $projectsDst $ProjectId) -Recurse -Force
  } else {
    $failed = Get-ChildItem -Path $projectsSrc -Directory | Where-Object {
      $pj = Join-Path $_.FullName "project.json"
      if (-not (Test-Path $pj)) { return $false }
      try {
        $content = Get-Content -Raw $pj | ConvertFrom-Json
        return $content.pipeline_state -eq "FAILED"
      } catch {
        return $false
      }
    } | Sort-Object LastWriteTime -Descending | Select-Object -First $MaxFailedProjects

    foreach ($dir in $failed) {
      Copy-Item -Path $dir.FullName -Destination (Join-Path $projectsDst $dir.Name) -Recurse -Force
    }
  }
}

# Build/runtime metadata
$metaDir = Join-Path $bundleRoot "meta"
New-Item -ItemType Directory -Force $metaDir | Out-Null

Get-Date -Format o | Out-File -FilePath (Join-Path $metaDir "collected_at.txt") -Encoding utf8
Copy-IfExists (Join-Path $rootPath "packaging\diaricat.spec") (Join-Path $metaDir "diaricat.spec")
Copy-IfExists (Join-Path $rootPath "packaging\requirements-release.lock") (Join-Path $metaDir "requirements-release.lock")

$venvPython = Join-Path $rootPath ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
@"
import json
import platform
import sys

out = {
  "python": sys.version,
  "platform": platform.platform(),
}

for mod in ("torch", "faster_whisper", "ctranslate2", "speechbrain", "llama_cpp"):
  try:
    m = __import__(mod)
    out[mod] = {"ok": True, "version": getattr(m, "__version__", None)}
  except Exception as exc:
    out[mod] = {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}

print(json.dumps(out, ensure_ascii=False, indent=2))
"@ | & $venvPython - | Out-File -FilePath (Join-Path $metaDir "python_runtime.json") -Encoding utf8
}

Write-SanitizedEnvSnapshot -Dest (Join-Path $metaDir "env.txt")

$zipPath = Join-Path $rootPath "temp\debug_bundle_$timestamp.zip"
if (Test-Path $zipPath) {
  Remove-Item -Force $zipPath
}
Compress-Archive -Path (Join-Path $bundleRoot "*") -DestinationPath $zipPath -CompressionLevel Optimal

Write-Host "Debug bundle created: $zipPath"
