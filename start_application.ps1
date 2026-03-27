# PowerShell script to start both backend and frontend servers reliably
# Usage: .\start_application.ps1

Write-Host "=== QuizCards - Full Stack Start ===" -ForegroundColor Cyan
Write-Host ""

function Test-Command($cmdname) {
    return [bool](Get-Command -Name $cmdname -ErrorAction SilentlyContinue)
}

$rootDir = $PSScriptRoot
$backendDir = Join-Path $rootDir "backend"
$frontendDir = Join-Path $rootDir "frontend"
$backendLog = Join-Path $backendDir "backend-start.log"
$backendErrorLog = Join-Path $backendDir "backend-start.err.log"

Write-Host "Checking prerequisites..." -ForegroundColor Yellow
if (-not (Test-Command "python")) { Write-Host "[ERROR] Python not found" -ForegroundColor Red; exit 1 }
if (-not (Test-Command "node")) { Write-Host "[ERROR] Node.js not found" -ForegroundColor Red; exit 1 }
if (-not (Test-Command "npm")) { Write-Host "[ERROR] npm not found" -ForegroundColor Red; exit 1 }
Write-Host "[OK] Python / Node.js / npm found" -ForegroundColor Green

if (Test-Command "ollama") {
    $ollamaProc = Get-Process -Name ollama -ErrorAction SilentlyContinue
    if (-not $ollamaProc) {
        Write-Host "Starting Ollama daemon..." -ForegroundColor Blue
        Start-Process -FilePath ollama -ArgumentList @("serve") -WindowStyle Hidden | Out-Null
        Start-Sleep -Seconds 3
    }

    try {
        $ollamaModels = ollama list 2>$null
        Write-Host "[OK] Ollama is available for high-quality quiz mode" -ForegroundColor Green
        if ($ollamaModels -notmatch "qwen2.5:7b") {
            Write-Host "Tip: run 'ollama pull qwen2.5:7b' for best local quality mode." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "[WARN] Ollama is installed but not responding. High-quality quiz mode may fallback to fast mode." -ForegroundColor Yellow
    }
} else {
    Write-Host "[INFO] Ollama CLI not found. High-quality quiz mode will fallback to fast mode." -ForegroundColor Yellow
}

if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    Write-Host "Installing frontend dependencies..." -ForegroundColor Yellow
    npm --prefix $frontendDir install
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to install frontend dependencies" -ForegroundColor Red
        exit 1
    }
}

if (Test-Path $backendLog) {
    Remove-Item $backendLog -Force -ErrorAction SilentlyContinue
}
if (Test-Path $backendErrorLog) {
    Remove-Item $backendErrorLog -Force -ErrorAction SilentlyContinue
}

Write-Host "Starting backend..." -ForegroundColor Blue
$backendProcess = Start-Process `
    -FilePath python `
    -ArgumentList @("-m","uvicorn","main:app","--host","127.0.0.1","--port","8000","--app-dir",$backendDir) `
    -RedirectStandardOutput $backendLog `
    -RedirectStandardError $backendErrorLog `
    -PassThru

$backendReady = $false
$maxWaitSeconds = 240

for ($i = 0; $i -lt $maxWaitSeconds; $i++) {
    Start-Sleep -Seconds 1

    if ($backendProcess.HasExited) {
        break
    }

    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/"
        if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
            $backendReady = $true
            break
        }
    } catch {
        # still starting
    }
}

if (-not $backendReady) {
    Write-Host "[ERROR] Backend failed to become ready on http://127.0.0.1:8000" -ForegroundColor Red
    if (Test-Path $backendLog) {
        Write-Host ""
        Write-Host "--- Backend stdout log tail ---" -ForegroundColor Yellow
        Get-Content $backendLog -Tail 80
        Write-Host "--- End of backend stdout log tail ---" -ForegroundColor Yellow
    }
    if (Test-Path $backendErrorLog) {
        Write-Host ""
        Write-Host "--- Backend stderr log tail ---" -ForegroundColor Yellow
        Get-Content $backendErrorLog -Tail 80
        Write-Host "--- End of backend stderr log tail ---" -ForegroundColor Yellow
    }
    if (-not $backendProcess.HasExited) {
        Stop-Process -Id $backendProcess.Id -Force -ErrorAction SilentlyContinue
    }
    exit 1
}

Write-Host "[OK] Backend ready: http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "API docs: http://127.0.0.1:8000/docs" -ForegroundColor Cyan
Write-Host "Starting frontend..." -ForegroundColor Blue
Write-Host "Frontend URL: http://localhost:5173" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop both servers." -ForegroundColor Yellow
Write-Host ""

try {
    npm --prefix $frontendDir run dev
} finally {
    Write-Host ""
    Write-Host "Stopping backend..." -ForegroundColor Yellow
    if (-not $backendProcess.HasExited) {
        Stop-Process -Id $backendProcess.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "Application stopped." -ForegroundColor Green
}
