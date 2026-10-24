# ╔══════════════════════════════════════════════════════════════╗
# ║         AntFraud_Sys — Script de Inicialização              ║
# ╚══════════════════════════════════════════════════════════════╝

Set-Location $PSScriptRoot

Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║       🛡  AntFraud_Sys — Iniciando Sistema          ║" -ForegroundColor Cyan
Write-Host "  ╚══════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── 1. Verificar Python ─────────────────────────────────────────────────────
Write-Host "[1/4] Verificando Python..." -ForegroundColor Yellow
try {
    $pyVersion = python --version 2>&1
    Write-Host "      ✅ $pyVersion encontrado" -ForegroundColor Green
} catch {
    Write-Host "      ❌ Python não encontrado. Instale em https://python.org" -ForegroundColor Red
    Read-Host "Pressione Enter para sair"
    exit 1
}

# ── 2. Criar .env se não existir ────────────────────────────────────────────
Write-Host ""
Write-Host "[2/4] Verificando arquivo .env..." -ForegroundColor Yellow

if (-Not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "      📄 Arquivo .env criado a partir do .env.example" -ForegroundColor Green
    Write-Host ""
    Write-Host "  ┌─────────────────────────────────────────────────────┐" -ForegroundColor Magenta
    Write-Host "  │  ⚠️  AÇÃO NECESSÁRIA                                │" -ForegroundColor Magenta
    Write-Host "  │                                                     │" -ForegroundColor Magenta
    Write-Host "  │  Abra o arquivo .env e preencha:                    │" -ForegroundColor Magenta
    Write-Host "  │                                                     │" -ForegroundColor Magenta
    Write-Host "  │  GEMINI_API_KEY=sua_chave_aqui                      │" -ForegroundColor Magenta
    Write-Host "  │    → Obtenha em: https://aistudio.google.com        │" -ForegroundColor Magenta
    Write-Host "  │                                                     │" -ForegroundColor Magenta
    Write-Host "  │  API_SECRET_KEY=sua-chave-secreta                   │" -ForegroundColor Magenta
    Write-Host "  │    → Use no campo X-API-Key do frontend             │" -ForegroundColor Magenta
    Write-Host "  └─────────────────────────────────────────────────────┘" -ForegroundColor Magenta
    Write-Host ""

    # Abre o .env no notepad para edição imediata
    Start-Process notepad ".env"
    Read-Host "  Edite o .env, salve e pressione Enter para continuar"
} else {
    Write-Host "      ✅ .env já existe" -ForegroundColor Green

    # Checa se GEMINI_API_KEY foi preenchida
    $envContent = Get-Content ".env" -Raw
    if ($envContent -match "GEMINI_API_KEY=your_gemini_api_key_here" -or $envContent -match "GEMINI_API_KEY=$") {
        Write-Host ""
        Write-Host "  ⚠️  GEMINI_API_KEY não configurada no .env!" -ForegroundColor Yellow
        Write-Host "     Abra o .env e preencha sua chave Gemini." -ForegroundColor Yellow
        Start-Process notepad ".env"
        Read-Host "  Edite, salve e pressione Enter para continuar"
    }
}

# ── 3. Instalar dependências ─────────────────────────────────────────────────
Write-Host ""
Write-Host "[3/4] Instalando dependências Python..." -ForegroundColor Yellow
pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "      ❌ Erro ao instalar dependências. Verifique sua conexão e o pip." -ForegroundColor Red
    Read-Host "Pressione Enter para sair"
    exit 1
}
Write-Host "      ✅ Dependências instaladas" -ForegroundColor Green

# ── 4. Abrir frontend no browser ─────────────────────────────────────────────
Write-Host ""
Write-Host "[4/4] Abrindo frontend no browser..." -ForegroundColor Yellow

$frontendPath = Join-Path $PSScriptRoot "frontend\index.html"
if (Test-Path $frontendPath) {
    # Inicia servidor HTTP simples para o frontend (evita bloqueio CORS de file://)
    $frontendJob = Start-Job -ScriptBlock {
        param($dir)
        Set-Location $dir
        python -m http.server 3000 --directory frontend 2>&1
    } -ArgumentList $PSScriptRoot

    Start-Sleep -Seconds 1
    Start-Process "http://localhost:3000"
    Write-Host "      ✅ Frontend disponível em http://localhost:3000" -ForegroundColor Green
} else {
    Write-Host "      ⚠️  frontend/index.html não encontrado, pulando..." -ForegroundColor Yellow
}

# ── Subindo API ───────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ┌─────────────────────────────────────────────────────┐" -ForegroundColor Cyan
Write-Host "  │  🚀 Subindo servidor na porta 8000...               │" -ForegroundColor Cyan
Write-Host "  │                                                     │" -ForegroundColor Cyan
Write-Host "  │  Backend:  http://localhost:8000                    │" -ForegroundColor Cyan
Write-Host "  │  Docs API: http://localhost:8000/docs               │" -ForegroundColor Cyan
Write-Host "  │  Frontend: http://localhost:3000                    │" -ForegroundColor Cyan
Write-Host "  │                                                     │" -ForegroundColor Cyan
Write-Host "  │  Pressione Ctrl+C para encerrar                     │" -ForegroundColor Cyan
Write-Host "  └─────────────────────────────────────────────────────┘" -ForegroundColor Cyan
Write-Host ""

uvicorn main:app --reload --host 0.0.0.0 --port 8000
