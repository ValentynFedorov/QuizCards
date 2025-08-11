# PowerShell script to start both backend and frontend servers
# Usage: .\start_application.ps1

Write-Host "=== PDF Flashcards Generator - Quick Start ===" -ForegroundColor Cyan
Write-Host ""

# Function to check if a command exists
function Test-Command($cmdname) {
    return [bool](Get-Command -Name $cmdname -ErrorAction SilentlyContinue)
}

# Check prerequisites
Write-Host "Checking prerequisites..." -ForegroundColor Yellow

if (-not (Test-Command "python")) {
    Write-Host "❌ Python is not installed or not in PATH" -ForegroundColor Red
    Write-Host "Please install Python 3.11+ from https://www.python.org/" -ForegroundColor Yellow
    exit 1
}
Write-Host "✅ Python found" -ForegroundColor Green

if (-not (Test-Command "node")) {
    Write-Host "❌ Node.js is not installed or not in PATH" -ForegroundColor Red
    Write-Host "Please install Node.js 16+ from https://nodejs.org/" -ForegroundColor Yellow
    exit 1
}
Write-Host "✅ Node.js found" -ForegroundColor Green

if (-not (Test-Command "npm")) {
    Write-Host "❌ npm is not installed" -ForegroundColor Red
    exit 1
}
Write-Host "✅ npm found" -ForegroundColor Green

Write-Host ""

# Check if dependencies are installed
Write-Host "Checking dependencies..." -ForegroundColor Yellow

# Backend dependencies
if (-not (Test-Path "backend\requirements.txt")) {
    Write-Host "❌ Backend requirements.txt not found" -ForegroundColor Red
    exit 1
}

# Frontend dependencies
if (-not (Test-Path "frontend\package.json")) {
    Write-Host "❌ Frontend package.json not found" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path "frontend\node_modules")) {
    Write-Host "Installing frontend dependencies..." -ForegroundColor Yellow
    Set-Location frontend
    npm install
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Failed to install frontend dependencies" -ForegroundColor Red
        exit 1
    }
    Set-Location ..
    Write-Host "✅ Frontend dependencies installed" -ForegroundColor Green
} else {
    Write-Host "✅ Frontend dependencies found" -ForegroundColor Green
}

Write-Host ""

# Start backend server in background
Write-Host "Starting backend server..." -ForegroundColor Blue
$backendJob = Start-Job -ScriptBlock {
    Set-Location $using:PWD\backend
    python main.py 2>&1
}

# Wait a moment for backend to start
Start-Sleep -Seconds 3

# Start frontend server
Write-Host "Starting frontend server..." -ForegroundColor Blue
Set-Location frontend

try {
    Write-Host ""
    Write-Host "=== Application Started ===" -ForegroundColor Green
    Write-Host "Backend:  http://localhost:8000" -ForegroundColor Cyan
    Write-Host "Frontend: http://localhost:5173" -ForegroundColor Cyan
    Write-Host "API Docs: http://localhost:8000/docs" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Press Ctrl+C to stop both servers" -ForegroundColor Yellow
    Write-Host ""
    
    # Start frontend (this will block until stopped)
    npm run dev
} finally {
    # Clean up background job when frontend stops
    Write-Host "Stopping backend server..." -ForegroundColor Yellow
    Stop-Job $backendJob -ErrorAction SilentlyContinue
    Remove-Job $backendJob -ErrorAction SilentlyContinue
    Write-Host "Application stopped." -ForegroundColor Green
}
