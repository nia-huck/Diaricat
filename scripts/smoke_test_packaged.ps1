param(
  [Parameter(Mandatory=$true)][string]$ExePath,
  [Parameter(Mandatory=$true)][string]$PythonExe,
  [int]$Port = 8876,
  [int]$StartupTimeoutSec = 600,
  [int]$MinimumFreeSpaceGb = 6,
  [bool]$KillExistingProcesses = $true
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ExePath)) {
  throw "Executable not found: $ExePath"
}

if (-not (Test-Path $PythonExe)) {
  throw "Python executable not found: $PythonExe"
}

$exeResolved = (Resolve-Path $ExePath).Path
$exeDir = Split-Path -Parent $exeResolved
$startupTracePath = Join-Path $exeDir "startup-trace.log"
$stdoutPath = Join-Path $exeDir "packaged-api-stdout.log"
$stderrPath = Join-Path $exeDir "packaged-api-stderr.log"

$exeDriveRoot = [System.IO.Path]::GetPathRoot($exeResolved)
$driveInfo = [System.IO.DriveInfo]::new($exeDriveRoot)
$freeSpaceGb = [Math]::Round($driveInfo.AvailableFreeSpace / 1GB, 2)
if ($freeSpaceGb -lt $MinimumFreeSpaceGb) {
  throw "Insufficient free disk on $exeDriveRoot for onefile startup. Free=${freeSpaceGb}GB required>=${MinimumFreeSpaceGb}GB."
}
Write-Host "Smoke preflight OK: drive=$exeDriveRoot free=${freeSpaceGb}GB timeout=${StartupTimeoutSec}s"

function Get-LogText {
  param([Parameter(Mandatory=$true)][string]$Path)

  if (-not (Test-Path $Path)) {
    return @()
  }

  try {
    $bytes = [System.IO.File]::ReadAllBytes($Path)
  } catch {
    return @("(unavailable: file is locked by another process)")
  }
  if (-not $bytes -or $bytes.Length -eq 0) {
    return @()
  }

  $nullBytes = 0
  foreach ($b in $bytes) {
    if ($b -eq 0) { $nullBytes++ }
  }

  if ($nullBytes -gt [int]($bytes.Length / 8)) {
    $text = [System.Text.Encoding]::Unicode.GetString($bytes)
  } else {
    $text = [System.Text.Encoding]::UTF8.GetString($bytes)
  }

  $clean = $text -replace "`0", ""
  return ($clean -split "`r?`n")
}

function Write-LogTail {
  param(
    [Parameter(Mandatory=$true)][string]$Title,
    [Parameter(Mandatory=$true)][string]$Path,
    [int]$Lines = 120
  )

  Write-Host "---- $Title ($Path) ----"
  if (-not (Test-Path $Path)) {
    Write-Host "(missing)"
    return
  }

  $info = Get-Item $Path
  Write-Host ("size={0} bytes updated={1}" -f $info.Length, $info.LastWriteTime)
  $all = Get-LogText -Path $Path
  if ($all.Count -eq 0) {
    Write-Host "(empty)"
    return
  }
  $start = [Math]::Max(0, $all.Count - $Lines)
  $all[$start..($all.Count - 1)]
}

$process = $null
$prevTrace = $env:DIARICAT_STARTUP_TRACE
$prevTracePath = $env:DIARICAT_STARTUP_TRACE_PATH
try {
  if ($KillExistingProcesses) {
    Get-Process Diarcat -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  }

  Remove-Item $startupTracePath,$stdoutPath,$stderrPath -ErrorAction SilentlyContinue
  $env:DIARICAT_STARTUP_TRACE = "1"
  $env:DIARICAT_STARTUP_TRACE_PATH = $startupTracePath

  $process = Start-Process -FilePath $ExePath -ArgumentList @("api", "--host", "127.0.0.1", "--port", "$Port") -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru
  Start-Sleep -Seconds 1

  @"
import json
import math
import struct
import tempfile
import time
import wave
from pathlib import Path

import requests

base = "http://127.0.0.1:$Port/v1"
startup_timeout = int($StartupTimeoutSec)

def wait_health():
    deadline = time.time() + startup_timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{base}/health", timeout=1)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"Packaged API did not become healthy in time (timeout={startup_timeout}s).")

def create_sample_wav(path: Path):
    sample_rate = 16000
    phase_seconds = 4
    amplitudes = (14000, 16000, 18000)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for amp in amplitudes:
            for i in range(sample_rate * phase_seconds):
                t = i / sample_rate
                signal = (0.75 * math.sin(2 * math.pi * 220 * t)) + (0.25 * math.sin(2 * math.pi * 330 * t))
                value = int(amp * signal)
                wav.writeframesraw(struct.pack("<h", value))

wait_health()

diag = requests.get(f"{base}/system/diagnostics", timeout=10).json()
required = ("torch", "faster_whisper", "ctranslate2", "speechbrain", "llama_cpp")
for key in required:
    if key not in diag.get("components", {}):
        raise RuntimeError(f"Missing diagnostics component: {key}")
if not diag["components"]["torch"]["ok"]:
    raise RuntimeError(f"Torch diagnostic failed: {diag['components']['torch'].get('error_hint')}")

with tempfile.TemporaryDirectory() as td:
    audio = Path(td) / "smoke.wav"
    create_sample_wav(audio)

    with audio.open("rb") as fh:
        upload = requests.post(f"{base}/system/upload", files={"file": ("smoke.wav", fh, "audio/wav")}, timeout=60)
    upload.raise_for_status()
    stored = upload.json()["stored_path"]

    project = requests.post(
        f"{base}/projects",
        json={"source_path": stored, "device_mode": "auto", "language_hint": "auto"},
        timeout=30,
    )
    project.raise_for_status()
    project_id = project.json()["id"]

    run = requests.post(
        f"{base}/projects/{project_id}/run",
        json={"run_correction": False, "run_summary": False},
        timeout=30,
    )
    run.raise_for_status()
    job_id = run.json()["job_id"]

    deadline = time.time() + 180
    while time.time() < deadline:
        job = requests.get(f"{base}/jobs/{job_id}", timeout=15).json()
        status = job.get("status")
        if status == "done":
            break
        if status == "failed":
            detail = str(job.get("error_detail") or "")
            if "shm.dll" in detail.lower() or "winerror 126" in detail.lower():
                raise RuntimeError(f"ASR DLL smoke test failed: {detail}")
            raise RuntimeError(f"Pipeline failed in smoke test: {detail}")
        time.sleep(1.0)
    else:
        raise RuntimeError("Smoke pipeline timeout.")

print(json.dumps({"status": "ok"}))
"@ | & $PythonExe -

  $probeExit = $LASTEXITCODE
  if ($probeExit -ne 0) {
    Write-Host "Packaged smoke probe failed with exit code $probeExit"
    if ($process -and -not $process.HasExited) {
      Write-Host ("Process still running (pid={0})" -f $process.Id)
      Get-NetTCPConnection -OwningProcess $process.Id -State Listen -ErrorAction SilentlyContinue | Select-Object LocalAddress,LocalPort,State,OwningProcess
      Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    } elseif ($process) {
      Write-Host ("Process exited (pid={0}, code={1})" -f $process.Id, $process.ExitCode)
    }
    Write-LogTail -Title "startup trace" -Path $startupTracePath
    Write-LogTail -Title "stdout" -Path $stdoutPath
    Write-LogTail -Title "stderr" -Path $stderrPath
    throw "Packaged smoke test failed (probe exit=$probeExit)."
  }
}
finally {
  $env:DIARICAT_STARTUP_TRACE = $prevTrace
  $env:DIARICAT_STARTUP_TRACE_PATH = $prevTracePath
  if ($process -and -not $process.HasExited) {
    Stop-Process -Id $process.Id -Force
  }
}
