# Build Diarcat as portable Windows application (onedir mode)

param(
  [switch]$SkipSmokeTest
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  Write-Host "Creating virtual environment..."
  & python -m venv .venv
  if ($LASTEXITCODE -ne 0) { throw "Failed to create virtual environment" }
}

$lockFile = Join-Path $root "packaging\requirements-release.lock"

function Ensure-Command {
  param([string]$Name)
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    throw "Missing command: $Name"
  }
}

function Invoke-Checked {
  param(
    [Parameter(Mandatory=$true)][string]$Description,
    [Parameter(Mandatory=$true)][scriptblock]$Action
  )
  & $Action
  if ($LASTEXITCODE -ne 0) {
    throw "$Description failed with exit code $LASTEXITCODE"
  }
}

function Ensure-FfmpegBinaries {
  $ffmpegExe = Join-Path $root "vendor\ffmpeg\ffmpeg.exe"
  $ffprobeExe = Join-Path $root "vendor\ffmpeg\ffprobe.exe"
  if ((Test-Path $ffmpegExe) -and (Test-Path $ffprobeExe)) {
    return
  }

  New-Item -ItemType Directory -Force "vendor\ffmpeg" | Out-Null
  $zipPath = Join-Path $root "temp\ffmpeg-release-essentials.zip"
  New-Item -ItemType Directory -Force "temp" | Out-Null

  $url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
  Write-Host "Downloading ffmpeg from $url"
  Invoke-WebRequest -Uri $url -OutFile $zipPath

  $extractDir = Join-Path $root "temp\ffmpeg-extract"
  if (Test-Path $extractDir) { Remove-Item -Recurse -Force $extractDir }
  Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force

  $ffmpegCandidate = Get-ChildItem -Path $extractDir -Recurse -Filter ffmpeg.exe | Select-Object -First 1
  $ffprobeCandidate = Get-ChildItem -Path $extractDir -Recurse -Filter ffprobe.exe | Select-Object -First 1
  if (-not $ffmpegCandidate -or -not $ffprobeCandidate) {
    throw "Failed to locate ffmpeg.exe/ffprobe.exe in downloaded archive."
  }

  Copy-Item $ffmpegCandidate.FullName -Destination $ffmpegExe -Force
  Copy-Item $ffprobeCandidate.FullName -Destination $ffprobeExe -Force
}

function Clean-BuildArtifacts {
  foreach ($path in @("build")) {
    $target = Join-Path $root $path
    if (Test-Path $target) {
      Write-Host "Cleaning $target"
      Remove-Item -Recurse -Force $target
    }
  }
}

# Verify Python is available
$actualPython = & $venvPython -c "import platform;print(platform.python_version())"
Write-Host "Using Python $($actualPython.Trim()) from $venvPython"

Ensure-Command npm

if (-not (Test-Path $lockFile)) {
  throw "Missing release lockfile: $lockFile`nGenerate it with: .\.venv\Scripts\python -m pip freeze --exclude-editable > packaging\requirements-release.lock"
}

Clean-BuildArtifacts

Write-Host "Installing locked release dependencies"
Invoke-Checked -Description "pip upgrade" -Action { & $venvPython -m pip install --upgrade pip }
Invoke-Checked -Description "pip install lockfile" -Action { & $venvPython -m pip install -r $lockFile }
Invoke-Checked -Description "pip install editable package" -Action { & $venvPython -m pip install --no-deps -e .[dev] }

Write-Host "Installing frontend dependencies"
Push-Location frontend
Invoke-Checked -Description "npm ci" -Action { npm ci }
Write-Host "Building frontend"
Invoke-Checked -Description "npm run build" -Action { npm run build }
Pop-Location

Ensure-FfmpegBinaries

Write-Host "Building executable with PyInstaller (onedir mode)"
Invoke-Checked -Description "PyInstaller build" -Action { & $venvPython -m PyInstaller --noconfirm --clean packaging/diaricat.spec }

$oneDirSource = Join-Path $root "dist\Diarcat\Diarcat.exe"
if (-not (Test-Path $oneDirSource)) {
  throw "Expected build output not found at dist\Diarcat\Diarcat.exe"
}

Write-Host ""
Write-Host "============================================="
Write-Host " BUILD COMPLETE (onedir)"
Write-Host " Executable: dist\Diarcat\Diarcat.exe"
Write-Host " Full app:   dist\Diarcat\"
Write-Host "============================================="
Write-Host ""
Write-Host "To run: .\dist\Diarcat\Diarcat.exe"
Write-Host "To distribute: copy the entire dist\Diarcat\ folder."

if (-not $SkipSmokeTest) {
  $smokeScript = Join-Path $root "scripts\smoke_test_packaged.ps1"
  if (Test-Path $smokeScript) {
    Write-Host "Running packaged smoke test"
    Invoke-Checked -Description "packaged smoke test" -Action {
      & $smokeScript `
        -ExePath $oneDirSource `
        -PythonExe $venvPython `
        -StartupTimeoutSec 120 `
        -MinimumFreeSpaceGb 2
    }
  }
}
