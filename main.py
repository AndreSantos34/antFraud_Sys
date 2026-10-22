"""
Núclea / IBM — Backend de Prevenção de Fraudes Financeiras
──────────────────────────────────────────────────────────
Ponto de entrada da aplicação FastAPI.

Pipeline de 4 agentes WatsonX (hierárquicos):
  Agente 1 (granite-13b)  → Análise de Risco          (temp 0.1)
  Agente 2 (granite-20b)  → Investigação de Ameaças    (temp 0.4)
  Agente 3 (granite-34b)  → Base de Dados e Evidências (temp 0.35)
  Agente 4 (granite-34b)  → IA Mestre — Score + Alerta (temp 0.55)

Monitor background: consome transações simuladas em tempo real e
aciona o pipeline automaticamente ao detectar >= 3 critérios.

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
    title="Núclea/IBM — Prevenção de Fraudes Financeiras",
    description=(
        "Protótipo de detecção de fraudes financeiras com 4 agentes de IA "
        "hierárquicos baseados na API IBM WatsonX. Monitor background em tempo real. "
        "Autenticação via header **X-API-Key**."
    ),
    version="2.0.0",
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
        "projeto": "Núclea/IBM — Prevenção de Fraudes Financeiras",
        "versao": "2.0.0",
        "docs": "/docs",
        "health": "/api/v1/health",
        "websocket_alerts": "ws://<host>:8000/ws/alerts?api_key=<API_SECRET_KEY>",
        "autenticacao": "Header X-API-Key obrigatório em todos os endpoints /api/v1/",
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
