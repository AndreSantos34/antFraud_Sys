# AntFraud_Sys -- Script de inicializacao (PowerShell)
# Uso: .\start.ps1
# Inicia o backend (porta 8000) e o frontend (porta 3000) em paralelo.

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host ""
Write-Host "  AntFraud_Sys - Iniciando..." -ForegroundColor Cyan
Write-Host ""

$uvicorn = if (Test-Path ".\.venv\Scripts\uvicorn.exe") { ".\.venv\Scripts\uvicorn.exe" } else { "uvicorn" }
$python  = if (Test-Path ".\.venv\Scripts\python.exe")  { ".\.venv\Scripts\python.exe"  } else { "python"  }

Write-Host "  [1/2] Iniciando backend (http://localhost:8000)..." -ForegroundColor Green
Start-Process -FilePath "powershell.exe" -ArgumentList "-NoExit", "-Command", "Set-Location '$root'; & '$uvicorn' main:app --reload --port 8000" -WindowStyle Normal

Start-Sleep -Seconds 2

Write-Host "  [2/2] Iniciando frontend (http://localhost:3000)..." -ForegroundColor Green
Start-Process -FilePath "powershell.exe" -ArgumentList "-NoExit", "-Command", "Set-Location '$root'; & '$python' -m http.server 3000 --directory frontend" -WindowStyle Normal

Start-Sleep -Seconds 1

Write-Host ""
Write-Host "  Backend:  http://localhost:8000" -ForegroundColor Yellow
Write-Host "  Docs:     http://localhost:8000/docs" -ForegroundColor Yellow
Write-Host "  Frontend: http://localhost:3000" -ForegroundColor Yellow
Write-Host ""

Start-Sleep -Seconds 3
Start-Process "http://localhost:3000"