"""
Rotas da API — AntFraud_Sys Backend
─────────────────────────────────────
Endpoints REST para ingestão, análise, consulta de casos e controle do monitor.
Todos os endpoints /api/v1/ requerem autenticação via header X-API-Key.
"""
import asyncio
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends, Query

from app.models.schemas import (
    ActionDecision,
    ActionResult,
    AnalysisResponse,
    CaseSummary,
    IngestResponse,
    TransactionIn,
)
from app import orchestrator, case_storage, action_executor
from app.core.security import require_api_key
from app.monitor import fraud_monitor

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["fraud-detection"])


# ══════════════════════════════════════════════════════════════════════════════
# Ingestão — fire-and-forget assíncrona
# ══════════════════════════════════════════════════════════════════════════════

def _run_pipeline_background(transaction: dict) -> None:
    """Executa o pipeline em thread separada (BackgroundTasks é síncrono)."""
    try:
        orchestrator.analyze_transaction(transaction)
    except Exception as exc:
        logger.error("[Ingest] Erro no pipeline background para %s: %s",
                     transaction.get("transaction_id"), exc)


@router.post(
    "/transactions/ingest",
    response_model=IngestResponse,
    summary="Ingestão assíncrona de transação (fire-and-forget)",
    status_code=202,
    dependencies=[Depends(require_api_key)],
)
def ingest_transaction(payload: TransactionIn, background_tasks: BackgroundTasks):
    """
    Aceita a transação imediatamente (HTTP 202) e processa em background.

    O pipeline completo de 4 agentes executa de forma assíncrona.
    Use o WebSocket /ws/alerts ou GET /api/v1/cases para acompanhar o resultado.
    """
    trace_id = str(uuid.uuid4())
    tx_dict = payload.model_dump()
    background_tasks.add_task(_run_pipeline_background, tx_dict)

    logger.info("[Ingest] Transação %s aceita para processamento | trace=%s",
                payload.transaction_id, trace_id)

    return IngestResponse(
        accepted=True,
        transaction_id=payload.transaction_id,
        trace_id=trace_id,
        message=(
            f"Transação {payload.transaction_id} aceita para análise. "
            "Use o WebSocket /ws/alerts ou GET /api/v1/cases para acompanhar o resultado."
        ),
    )


# ══════════════════════════════════════════════════════════════════════════════
# Análise síncrona (aguarda pipeline completo)
# ══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/analyze",
    response_model=AnalysisResponse,
    summary="Analisa uma transação ad-hoc (síncrono — aguarda resultado)",
    dependencies=[Depends(require_api_key)],
)
def analyze_transaction(payload: TransactionIn):
    """
    Executa o pipeline de 4 agentes e retorna o resultado completo.
    Use /transactions/ingest para processamento assíncrono (fire-and-forget).
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
    summary="Analisa uma transação do dataset pelo ID (síncrono)",
    dependencies=[Depends(require_api_key)],
)
def analyze_by_id(transaction_id: str):
    """Localiza a transação no dataset e executa o pipeline completo."""
    result = orchestrator.analyze_single_by_id(transaction_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Transação '{transaction_id}' não encontrada no dataset.",
        )
    return result


@router.post(
    "/analyze/batch",
    summary="Analisa todas as transações do dataset (síncrono — pode demorar)",
    dependencies=[Depends(require_api_key)],
)
def analyze_batch():
    """Executa o pipeline nas transações do dataset. Pode levar vários minutos."""
    try:
        results = orchestrator.analyze_all_transactions()
        escalated = [r for r in results if r["escalated"]]
        normal    = [r for r in results if not r["escalated"]]
        return {
            "total":                      len(results),
            "escalated_to_investigation": len(escalated),
            "normal_flow":                len(normal),
            "results":                    results,
        }
    except Exception as exc:
        logger.exception("Erro no processamento em lote")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ══════════════════════════════════════════════════════════════════════════════
# Dataset
# ══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/transactions",
    summary="Lista todas as transações do dataset (sem análise)",
    dependencies=[Depends(require_api_key)],
)
def list_transactions():
    """Retorna o dataset completo sem processar pelos agentes."""
    return orchestrator.get_all_transactions()


# ══════════════════════════════════════════════════════════════════════════════
# Casos persistidos
# ══════════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════════
# Health check
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/health", summary="Health check da API, Gemini e monitor")
def health_check():
    from app.core.config import get_settings
    settings = get_settings()
    gemini_ok = bool(settings.gemini_api_key)
    return {
        "status": "ok",
        "version": "3.0.0",
        "llm_provider": "Google Gemini",
        "gemini_configured": gemini_ok,
        "pipeline": {
            "agent_1_detection":      f"{settings.gemini_model_agent1} (temp=0.1) — Detecção determinística + justificativa LLM",
            "agent_2_investigation":  f"{settings.gemini_model_agent2} (temp=0.3) — Investigação + correlação cruzada",
            "agent_3_risk":           f"{settings.gemini_model_agent3} (temp=0.2) — Avaliação de risco + recomendações",
            "agent_4_master":         f"{settings.gemini_model_agent4} (temp=0.3) — Relatório executivo + orquestração",
        },
        "escalation_rule":  "minimo_3_criterios_deterministicos",
        "retry_config": {
            "attempts": settings.gemini_retry_attempts,
            "delay_s":  settings.gemini_retry_delay_s,
        },
        "monitor": fraud_monitor.stats(),
        "endpoints": {
            "ingest":   "POST /api/v1/transactions/ingest (fire-and-forget, HTTP 202)",
            "analyze":  "POST /api/v1/analyze (síncrono)",
            "cases":    "GET  /api/v1/cases",
            "websocket":"ws://<host>/ws/alerts?api_key=<key>",
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# Controle do monitor
# ══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/monitor/start",
    summary="Inicia o monitor background manualmente",
    dependencies=[Depends(require_api_key)],
)
async def start_monitor():
    """Inicia o monitor se estiver parado."""
    if fraud_monitor.running:
        return {"status": "já em execução", **fraud_monitor.stats()}
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


# ══════════════════════════════════════════════════════════════════════════════
# Fluxo de Aprovação Humana
# ══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/cases/{case_id}/actions/{action_id}/approve",
    response_model=ActionResult,
    summary="Aprova uma ação sugerida — executa via executor simulado",
    dependencies=[Depends(require_api_key)],
)
def approve_action(case_id: str, action_id: str, body: ActionDecision):
    """
    O analista de cibersegurança aprova uma ação sugerida pelo Agente 4.

    O backend:
    1. Carrega o caso e localiza a ação pelo action_id.
    2. Marca a ação como APPROVED.
    3. Chama o executor (simulado no protótipo) para executar a ação.
    4. Persiste o resultado da execução no histórico do caso.
    5. Retorna o resultado completo para o frontend.
    """
    case = case_storage.load_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Caso '{case_id}' não encontrado.")

    # Localiza a ação nas sugestões do Agente 4
    master = case.get("agent_4_master") or {}
    suggested = master.get("suggested_actions", [])
    action = next((a for a in suggested if a.get("action_id") == action_id), None)

    if action is None:
        raise HTTPException(
            status_code=404,
            detail=f"Ação '{action_id}' não encontrada no caso '{case_id}'.",
        )

    if action.get("status") != "PENDING":
        raise HTTPException(
            status_code=409,
            detail=f"Ação '{action_id}' já foi processada (status: {action['status']}).",
        )

    customer_id = case.get("transaction", {}).get("customer_id", "desconhecido")

    # Executa via executor simulado
    result = action_executor.execute_action(
        action_id=action_id,
        action_code=action.get("action_code", "revisao_humana"),
        case_id=case_id,
        customer_id=customer_id,
        decided_by=body.decided_by,
    )

    # Persiste o resultado
    case_storage.save_action_result(case_id, result)

    logger.info(
        "[Actions] Ação %s aprovada por %s | case=%s | resultado=%s",
        action_id, body.decided_by, case_id, result["status"],
    )

    return result


@router.post(
    "/cases/{case_id}/actions/{action_id}/reject",
    response_model=ActionResult,
    summary="Rejeita uma ação sugerida — registra decisão sem executar",
    dependencies=[Depends(require_api_key)],
)
def reject_action(case_id: str, action_id: str, body: ActionDecision):
    """
    O analista de cibersegurança rejeita uma ação sugerida pelo Agente 4.

    Nenhuma chamada ao banco é feita — apenas registra a decisão de rejeição
    com o identificador do analista e justificativa opcional.
    """
    case = case_storage.load_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Caso '{case_id}' não encontrado.")

    master = case.get("agent_4_master") or {}
    suggested = master.get("suggested_actions", [])
    action = next((a for a in suggested if a.get("action_id") == action_id), None)

    if action is None:
        raise HTTPException(
            status_code=404,
            detail=f"Ação '{action_id}' não encontrada no caso '{case_id}'.",
        )

    if action.get("status") != "PENDING":
        raise HTTPException(
            status_code=409,
            detail=f"Ação '{action_id}' já foi processada (status: {action['status']}).",
        )

    result = action_executor.reject_action(
        action_id=action_id,
        action_code=action.get("action_code", "revisao_humana"),
        case_id=case_id,
        decided_by=body.decided_by,
        justification=body.justification,
    )

    case_storage.save_action_result(case_id, result)

    logger.info(
        "[Actions] Ação %s rejeitada por %s | case=%s",
        action_id, body.decided_by, case_id,
    )

    return result


@router.get(
    "/cases/{case_id}/actions",
    summary="Lista todas as decisões registradas para um caso",
    dependencies=[Depends(require_api_key)],
)
def list_case_actions(case_id: str):
    """Retorna o histórico completo de decisões (aprovações e rejeições) de um caso."""
    case = case_storage.load_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Caso '{case_id}' não encontrado.")

    actions_history = case_storage.list_action_results(case_id)
    master = (case.get("agent_4_master") or {})
    suggested = master.get("suggested_actions", [])

    return {
        "case_id":          case_id,
        "suggested_actions": suggested,
        "decisions_history": actions_history,
        "total_suggested":  len(suggested),
        "total_decided":    len(actions_history),
        "pending":          sum(1 for a in suggested if a.get("status") == "PENDING"),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Simulação
# ══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/simulate/transaction",
    summary="Gera e analisa uma transação simulada imediatamente",
    dependencies=[Depends(require_api_key)],
)
def simulate_one(force_suspicious: bool = Query(False, description="true = garante transação com >= 3 critérios")):
    """
    Gera uma transação fictícia e executa o pipeline completo de forma síncrona.
    Útil para demonstração e testes sem precisar de dados reais.
    """
    from app.simulator import generate_single
    tx = generate_single(force_suspicious=force_suspicious)
    try:
        result = orchestrator.analyze_transaction(tx)
        return {"simulated_transaction": tx, "analysis": result}
    except Exception as exc:
        logger.exception("Erro ao simular transação")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
