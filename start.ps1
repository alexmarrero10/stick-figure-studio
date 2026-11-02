# Starts Stick Figure Studio.
#   .\start.ps1             build the UI if needed, run the app at http://127.0.0.1:8765 and open the browser
#   .\start.ps1 -Dev        run the backend with auto-reload and the Vite dev server at http://localhost:5173
#   .\start.ps1 -Port 9000  use a different port (the dev proxy always targets 8765)
param([switch]$Dev, [int]$Port = 8765)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Warning "FFmpeg not found on PATH. Install it with:  winget install Gyan.FFmpeg  (then reopen the terminal)"
}

# Python environment
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Creating Python virtual environment..."
    python -m venv .venv
}
$reqStamp = Join-Path $root ".venv\.requirements-installed"
if (-not (Test-Path $reqStamp) -or (Get-Item backend\requirements.txt).LastWriteTime -gt (Get-Item $reqStamp).LastWriteTime) {
    Write-Host "Installing Python packages..."
    & $py -m pip install -q -r backend\requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
    New-Item -ItemType File $reqStamp -Force | Out-Null
}

if (-not (Test-Path .env)) { Copy-Item .env.example .env }

# Frontend
Push-Location frontend
if (-not (Test-Path node_modules)) {
    Write-Host "Installing UI packages..."
    npm install --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
}
Pop-Location

if ($Dev) {
    $backend = Start-Process -PassThru -NoNewWindow $py -ArgumentList "-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--reload", "--reload-dir", "backend", "--port", "8765"
    try {
        Start-Process "http://localhost:5173"
        Push-Location frontend
        npm run dev
    } finally {
        Pop-Location
        Stop-Process -Id $backend.Id -ErrorAction SilentlyContinue
    }
} else {
    $dist = Join-Path $root "frontend\dist\index.html"
    $newest = Get-ChildItem frontend\src -Recurse -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not (Test-Path $dist) -or $newest.LastWriteTime -gt (Get-Item $dist).LastWriteTime) {
        Write-Host "Building the UI..."
        Push-Location frontend
        npm run build
        if ($LASTEXITCODE -ne 0) { Pop-Location; throw "UI build failed" }
        Pop-Location
    }
    Write-Host "Stick Figure Studio is running at http://127.0.0.1:$Port  (Ctrl+C to stop)"
    Start-Job -ScriptBlock { param($p) Start-Sleep 2; Start-Process "http://127.0.0.1:$p" } -ArgumentList $Port | Out-Null
    & $py -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port $Port
}
