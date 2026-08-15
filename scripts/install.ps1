# litkit installer — Windows (PowerShell)
# Usage:
#   .\scripts\install.ps1                # install from PyPI (after release)
#   .\scripts\install.ps1 -Source wheel  # install from local dist\*.whl
#   .\scripts\install.ps1 -Source git    # install from git URL
param(
    [ValidateSet("pypi", "wheel", "git")]
    [string]$Source = "pypi",
    [string]$GitUrl = "https://github.com/bpshil/litkit-search.git"
)
$ErrorActionPreference = "Stop"

Write-Host "== litkit installer (Windows) ==" -ForegroundColor Cyan

# 1. Python check (>= 3.11)
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "ERROR: python not found. Install Python 3.11+ from https://python.org" -ForegroundColor Red
    exit 1
}
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: need Python >= 3.11 (found $(& python --version))" -ForegroundColor Red
    exit 1
}

# 2. Virtual environment
if (-not (Test-Path ".venv")) { python -m venv .venv }
$pyExe = Join-Path (Get-Location) ".venv\Scripts\python.exe"
Write-Host "Using venv: $pyExe"

# 3. Install
switch ($Source) {
    "pypi"  { & $pyExe -m pip install --upgrade litkit-search }
    "wheel" { Get-ChildItem dist\*.whl -ErrorAction Stop | ForEach-Object { & $pyExe -m pip install $_.FullName } }
    "git"   { & $pyExe -m pip install "git+$GitUrl" }
}

# 4. Environment self-check
Write-Host "`n== litkit doctor ==" -ForegroundColor Cyan
& (Join-Path (Get-Location) ".venv\Scripts\litkit.exe") doctor
