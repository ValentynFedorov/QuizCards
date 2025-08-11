# PowerShell script to run the FastAPI backend server
# Usage: .\run_server.ps1

Write-Host "Starting PDF Flashcards Backend Server..." -ForegroundColor Green

# Check if Python is installed
try {
    $pythonVersion = python --version 2>&1
    Write-Host "Found Python: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "Python is not installed or not in PATH" -ForegroundColor Red
    exit 1
}

# Check if we're in a virtual environment or if uv is available
$uvAvailable = $false
try {
    uv --version | Out-Null
    $uvAvailable = $true
    Write-Host "Found uv package manager" -ForegroundColor Green
} catch {
    Write-Host "uv not found, will use pip/venv approach" -ForegroundColor Yellow
}

# Start the server
try {
    if ($uvAvailable) {
        Write-Host "Starting server with uv..." -ForegroundColor Blue
        uv run python main.py
    } else {
        Write-Host "Starting server with python..." -ForegroundColor Blue
        python main.py
    }
} catch {
    Write-Host "Failed to start server. Please check dependencies are installed." -ForegroundColor Red
    Write-Host "Try running: pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}
