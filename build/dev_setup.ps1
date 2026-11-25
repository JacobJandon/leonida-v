<#
.SYNOPSIS
  Set up a Leonida V development environment on Windows in one go.

.DESCRIPTION
  Run from anywhere inside your clone:
      powershell -ExecutionPolicy Bypass -File build\dev_setup.ps1
  It finds Python 3.10+ (the "py" launcher first, then "python"), makes .venv in the repo root (once), installs
  Leonida with its dev and GUI extras (pip install -e ".[dev,gui]"), then runs ruff and the tests. The tests never
  need GTA V: they use fake game folders and archives, and never touch your real game, registry or Start menu.

.PARAMETER NoTests
  Only make the venv and install; skip ruff and pytest.

.PARAMETER Recreate
  Delete .venv first and start fresh.
#>
param(
    [switch]$NoTests,
    [switch]$Recreate
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$venv = Join-Path $repo ".venv"
$py = Join-Path $venv "Scripts\python.exe"

function Find-Python {
    $candidates = @(
        @("py", "-3.13"), @("py", "-3.12"), @("py", "-3.11"), @("py", "-3.10"), @("py", "-3"), @("python")
    )
    foreach ($c in $candidates) {
        $exe = $c[0]
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        $rest = @($c | Select-Object -Skip 1)
        $ver = & $exe @rest -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $ver) { continue }
        $parts = $ver.Trim().Split(".")
        if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 10) { return , $c }
    }
    return $null
}

if ($Recreate -and (Test-Path $venv)) {
    Write-Host "Removing the old .venv" -ForegroundColor Yellow
    Remove-Item -Recurse -Force $venv
}

if (-not (Test-Path $py)) {
    $found = Find-Python
    if (-not $found) {
        Write-Host "Python 3.10 or newer was not found." -ForegroundColor Red
        Write-Host "Install it from https://www.python.org/downloads/windows/ (tick 'Add python.exe to PATH'), then run this again."
        exit 1
    }
    $exe = $found[0]
    $rest = @($found | Select-Object -Skip 1)
    Write-Host "Making .venv with: $($found -join ' ')" -ForegroundColor Cyan
    & $exe @rest -m venv $venv
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "Installing Leonida V with the dev and GUI extras" -ForegroundColor Cyan
& $py -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py -m pip install -e ".[dev,gui]"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($NoTests) {
    Write-Host "Done (tests skipped). Activate with: .\.venv\Scripts\Activate.ps1" -ForegroundColor Green
    exit 0
}

Write-Host "ruff check ." -ForegroundColor Cyan
& $py -m ruff check .
$ruff = $LASTEXITCODE

Write-Host "pytest -q (a few minutes)" -ForegroundColor Cyan
$env:QT_QPA_PLATFORM = "offscreen"   # the GUI tests run without opening windows
$env:LEONIDA_NO_NET = "1"            # nothing reaches the internet
$env:LEONIDA_NO_OPEN = "1"           # no browser tabs or folders open
& $py -m pytest -q
$tests = $LASTEXITCODE

if ($ruff -ne 0 -or $tests -ne 0) {
    Write-Host "Set up, but ruff or the tests failed (see above)." -ForegroundColor Red
    exit 1
}
Write-Host ""
Write-Host "All set. Activate the venv with: .\.venv\Scripts\Activate.ps1" -ForegroundColor Green
Write-Host "Then: leonida --help   |   leonida-gui   |   pytest -q   |   ruff check ."
