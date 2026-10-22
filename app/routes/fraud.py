"""
Rotas da API — Detecção de Fraudes Financeiras
"""
import logging
from fastapi import APIRouter, HTTPException, Depends

from app.models.schemas import TransactionIn, AnalysisResponse, CaseSummary
from app import orchestrator, case_storage
from app.core.security import require_api_key
from app.monitor import fraud_monitor

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["fraud-detection"])


# ── Transações ────────────────────────────────────────────────────────────────

@router.get(
    "/transactions",
    summary="Lista todas as transações do dataset",
    dependencies=[Depends(require_api_key)],
)
def list_transactions():
    """Retorna o dataset completo sem processar pelos agentes."""
    return orchestrator.get_all_transactions()


# ── Análise ───────────────────────────────────────────────────────────────────

@router.post(
    "/analyze",
    response_model=AnalysisResponse,
    summary="Analisa uma transação ad-hoc pelos 4 agentes",
    dependencies=[Depends(require_api_key)],
)
def analyze_transaction(payload: TransactionIn):
    """
    Recebe uma transação em JSON e executa o pipeline:
    - Agente 1 sempre executa (triagem dos 6 critérios)
    - Se >= 3 critérios → Agentes 2, 3 e 4 (IA Mestre) são acionados
    - Caso suspeito é persistido automaticamente
    """
    try:
        result = orchestrator.analyze_transaction(payload.model_dump())
        return result
    except Exception as exc:
        logger.exception("Erro ao analisar transação %s", payload.transaction_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/analyze/{transaction_id}",
    response_model=AnalysisResponse,
    summary="Analisa uma transação do dataset pelo ID",
    dependencies=[Depends(require_api_key)],
)
def analyze_by_id(transaction_id: str):
    """
    Localiza a transação no dataset e executa o pipeline completo,
    passando o histórico do cliente como contexto para os agentes.
    """
    result = orchestrator.analyze_single_by_id(transaction_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Transação '{transaction_id}' não encontrada no dataset.",
        )
    return result


@router.post(
    "/analyze/batch",
    summary="Analisa todas as transações do dataset",
    dependencies=[Depends(require_api_key)],
)
def analyze_batch():
    """
    Executa o pipeline nas 20 transações do dataset.
    Transações suspeitas (>= 3 critérios) passam por todos os 4 agentes.
    """
    try:
        results = orchestrator.analyze_all_transactions()
        escalated = [r for r in results if r["escalated"]]
        normal = [r for r in results if not r["escalated"]]
        return {
            "total": len(results),
            "escalated_to_investigation": len(escalated),
            "normal_flow": len(normal),
            "results": results,
        }
    except Exception as exc:
        logger.exception("Erro no processamento em lote")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Casos persistidos ─────────────────────────────────────────────────────────

@router.get(
    "/cases",
    response_model=list[CaseSummary],
    summary="Lista todos os casos suspeitos persistidos",
    dependencies=[Depends(require_api_key)],
)
def list_cases():
    """Retorna resumo de todos os casos suspeitos salvos pelo sistema."""
    return case_storage.list_cases()


@router.get(
    "/cases/{case_id}",
    summary="Recupera o dossiê completo de um caso pelo ID",
    dependencies=[Depends(require_api_key)],
)
def get_case(case_id: str):
    """Retorna todos os dados do caso incluindo saídas dos 4 agentes."""
    case = case_storage.load_case(case_id)
    if case is None:
        raise HTTPException(
            status_code=404,
            detail=f"Caso '{case_id}' não encontrado.",
        )
    return case


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health", summary="Health check da API, WatsonX e monitor")
def health_check():
    from app.core.config import get_settings
    settings = get_settings()
    watsonx_configured = bool(settings.watsonx_api_key and settings.watsonx_project_id)
    return {
        "status": "ok",
        "watsonx_configured": watsonx_configured,
        "watsonx_url": settings.watsonx_url,
        "agents": {
            "agent_1": "ibm/granite-13b-instruct-v2 (temp=0.1)",
            "agent_2": "ibm/granite-20b-multilingual (temp=0.4)",
            "agent_3": "ibm/granite-34b-code-instruct (temp=0.35)",
            "agent_4_master": "ibm/granite-34b-code-instruct (temp=0.55)",
        },
        "escalation_rule": "minimo_3_criterios",
        "dataset_loaded": True,
        "monitor": fraud_monitor.stats(),
    }


@router.post(
    "/monitor/start",
    summary="Inicia o monitor background manualmente",
    dependencies=[Depends(require_api_key)],
)
async def start_monitor():
    """Inicia o monitor se estiver parado."""
    if fraud_monitor.running:
        return {"status": "já em execução", **fraud_monitor.stats()}
    import asyncio
    asyncio.create_task(fraud_monitor.start())
    return {"status": "iniciado"}


@router.post(
    "/monitor/stop",
    summary="Para o monitor background",
    dependencies=[Depends(require_api_key)],
)
def stop_monitor():
    """Para o monitor de transações em background."""
    fraud_monitor.stop()
    return {"status": "parado", **fraud_monitor.stats()}


@router.get(
    "/monitor/stats",
    summary="Estatísticas do monitor em tempo real",
    dependencies=[Depends(require_api_key)],
)
def monitor_stats():
    """Retorna contadores do monitor: transações processadas, escaladas e taxa."""
    return fraud_monitor.stats()


@router.post(
    "/simulate/transaction",
    summary="Gera e analisa uma transação simulada imediatamente",
    dependencies=[Depends(require_api_key)],
)
def simulate_one(force_suspicious: bool = False):
    """
    Gera uma transação fictícia e executa o pipeline completo.
    Use force_suspicious=true para garantir uma transação suspeita.
    """
    from app.simulator import generate_single
    tx = generate_single(force_suspicious=force_suspicious)
    try:
        result = orchestrator.analyze_transaction(tx)
        return {"simulated_transaction": tx, "analysis": result}
    except Exception as exc:
        logger.exception("Erro ao simular transação")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
