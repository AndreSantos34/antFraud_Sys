"""
AntFraud_Sys — Backend de Detecção de Fraudes Financeiras
──────────────────────────────────────────────────────────
Ponto de entrada da aplicação FastAPI.

Pipeline de 4 agentes (Google Gemini):
  Agente 1 — Detecção: triagem 100% determinística + justificativa LLM (temp 0.1)
  Agente 2 — Investigação: perfil histórico + correlação cruzada          (temp 0.3)
  Agente 3 — Risco: Gravidade/Prioridade/Confiança + recomendações         (temp 0.2)
  Agente 4 — Mestre: relatório executivo PT-BR + orquestração final        (temp 0.3)

Monitor background: consome transações simuladas continuamente — independente
de WebSocket. Emite estados ANALYZING/COMPLETED/REQUIRES_HUMAN_REVIEW/FAILED.

Novo endpoint de ingestão: POST /api/v1/transactions/ingest (fire-and-forget, HTTP 202)

Uso:
  uvicorn main:app --reload
"""
import asyncio
import logging
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.routes.fraud import router as fraud_router
from app.routes.websocket import router as ws_router
from app.monitor import fraud_monitor

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
settings = get_settings()


# ── Lifespan — inicia/encerra o monitor junto com a API ──────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia o ciclo de vida da aplicação."""
    monitor_task = None

    if settings.monitor_autostart:
        logger.info("🚀 Iniciando monitor background de transações...")
        monitor_task = asyncio.create_task(fraud_monitor.start())
    else:
        logger.info("ℹ️  Monitor background desativado (MONITOR_AUTOSTART=false).")

    yield  # API rodando

    # Shutdown
    logger.info("🛑 Encerrando monitor background...")
    fraud_monitor.stop()
    if monitor_task:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
    logger.info("✅ Shutdown completo.")


# ── Aplicação ─────────────────────────────────────────────────────────────────
app = FastAPI(
    title="AntFraud_Sys — Detecção de Fraudes Financeiras",
    description=(
        "Protótipo acadêmico de IA agêntica para prevenção de fraudes. "
        "Pipeline de 4 agentes Google Gemini com arquitetura híbrida "
        "(regras determinísticas + LLM). "
        "Ingestão assíncrona (POST /api/v1/transactions/ingest), "
        "WebSocket de alertas em tempo real (/ws/alerts). "
        "Autenticação via header **X-API-Key**. "
        "Sistema consultivo — NÃO executa operações financeiras."
    ),
    version="3.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # restringir para domínios da Núclea em produção
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Rotas ─────────────────────────────────────────────────────────────────────
app.include_router(fraud_router)
app.include_router(ws_router)


@app.get("/", tags=["root"])
def root():
    return {
        "projeto": "AntFraud_Sys — Detecção de Fraudes Financeiras",
        "versao": "3.0.0",
        "docs": "/docs",
        "health": "/api/v1/health",
        "ingest": "POST /api/v1/transactions/ingest (fire-and-forget, HTTP 202)",
        "analyze": "POST /api/v1/analyze (síncrono)",
        "websocket_alerts": "ws://<host>:8000/ws/alerts?api_key=<API_SECRET_KEY>",
        "autenticacao": "Header X-API-Key obrigatório em todos os endpoints /api/v1/",
        "aviso": "Sistema consultivo — NÃO executa operações financeiras.",
    }


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("Iniciando servidor Núclea na porta %s", settings.app_port)
    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
        log_level="info",
    )
