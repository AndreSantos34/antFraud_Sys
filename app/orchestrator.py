"""
Orquestrador do Pipeline de Detecção de Fraudes
────────────────────────────────────────────────
Coordena a execução sequencial dos 4 agentes, gerencia case_id/trace_id,
isola falhas por agente (um agente com erro não aborta os seguintes)
e persiste o caso completo no case_storage.

Fluxo:
  Transação
    └─ Agente 1: Detecção determinística
        ├─ < 3 critérios → NORMAL (para aqui, retorna status COMPLETED)
        └─ >= 3 critérios → SUSPEITA → escala:
              ├─ Agente 2: Investigação + Correlação
              ├─ Agente 3: Avaliação de Risco + Recomendações
              └─ Agente 4: Relatório Executivo + Alerta SOC
                    └─ Persiste caso → retorna MasterResult
"""
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from app.agents import (
    agent_rule_screener,
    agent_context_analyst,
    agent_risk_analyzer,
    agent_master,
)
from app import case_storage

logger = logging.getLogger(__name__)

_DATASET_PATH = Path(__file__).parent / "data" / "transactions.json"


# ── Utilitários ───────────────────────────────────────────────────────────────

def _load_dataset() -> list[dict]:
    with open(_DATASET_PATH, encoding="utf-8") as f:
        return json.load(f)


def _primary_transactions(dataset: list[dict]) -> list[dict]:
    """
    Retorna apenas as transações primárias do dataset — exclui registros marcados
    como `"_history_record": true`, que existem apenas para fornecer contexto
    histórico a outras transações e não devem ser processados como casos independentes.
    """
    return [t for t in dataset if not t.get("_history_record", False)]


def _build_customer_history_index(dataset: list[dict]) -> dict[str, list[dict]]:
    """
    Constrói um índice cliente→histórico a partir dos registros de histórico embutidos
    (`"_history_record": true`) e também das transações primárias que precedem a atual.

    Registros com `"_history": [...]` embutido têm sua própria lista de histórico explícita.
    """
    index: dict[str, list[dict]] = {}
    for tx in dataset:
        cid = tx.get("customer_id", "")
        index.setdefault(cid, []).append(tx)
    return index


def _make_ids(transaction_id: str) -> tuple[str, str]:
    """Gera case_id e trace_id únicos e rastreáveis."""
    trace_id = str(uuid.uuid4())
    case_id = f"{transaction_id}_CASE_{trace_id[:8].upper()}"
    return case_id, trace_id


# ── Pipeline principal ────────────────────────────────────────────────────────

def analyze_transaction(
    transaction: dict[str, Any],
    customer_history: list[dict] | None = None,
    all_transactions: list[dict] | None = None,
) -> dict[str, Any]:
    """
    Executa o pipeline completo de 4 agentes para uma transação.

    Falhas em agentes individuais são capturadas, registradas em pipeline_errors
    e não interrompem os agentes seguintes (degradação graciosa).

    Returns:
        Dicionário compatível com AnalysisResponse do schemas.py.
    """
    tx_id = transaction.get("transaction_id", "UNKNOWN")
    customer_id = transaction.get("customer_id", "UNKNOWN")
    history = customer_history or []
    all_txs = all_transactions or []
    case_id, trace_id = _make_ids(tx_id)
    pipeline_errors: list[str] = []

    logger.info("[Orchestrator] Iniciando pipeline | tx=%s | trace=%s", tx_id, trace_id)

    # ── Agente 1: Detecção ────────────────────────────────────────────────────
    detection: dict = {}
    try:
        detection = agent_rule_screener.run(transaction, history)
    except Exception as exc:
        logger.error("[Orchestrator] Agente 1 falhou: %s", exc)
        pipeline_errors.append(f"Agente1: {exc}")
        detection = {
            "transaction_id": tx_id,
            "criteria_flags": {},
            "total_criteria_met": 0,
            "escalate_to_investigation": False,
            "classification": "erro",
            "deterministic_evidence": [f"Agente 1 falhou: {exc}"],
            "llm_justification": None,
            "llm_confidence": None,
        }

    should_escalate = detection.get("escalate_to_investigation", False)
    total_criteria = detection.get("total_criteria_met", 0)

    # ── Transação NORMAL — encerra aqui ───────────────────────────────────────
    if not should_escalate:
        logger.info(
            "[Orchestrator] %s classificada como NORMAL (%d critério(s)).",
            tx_id, total_criteria,
        )
        return {
            "transaction_id": tx_id,
            "customer_id": customer_id,
            "case_id": case_id,
            "trace_id": trace_id,
            "processing_status": "COMPLETED",
            "total_criteria_met": total_criteria,
            "escalated": False,
            "case_persisted": False,
            "final_risk_score": 0,
            "final_risk_level": "minimo",
            "agent_1_detection": detection,
            "agent_2_investigation": None,
            "agent_3_risk": None,
            "agent_4_master": None,
        }

    logger.info(
        "[Orchestrator] %s ESCALADA (%d critério(s)). Acionando Agentes 2→3→4.",
        tx_id, total_criteria,
    )

    # ── Agente 2: Investigação e Correlação ───────────────────────────────────
    investigation: dict = {}
    try:
        investigation = agent_context_analyst.run(
            transaction, detection, history, all_txs
        )
    except Exception as exc:
        logger.error("[Orchestrator] Agente 2 falhou: %s", exc)
        pipeline_errors.append(f"Agente2: {exc}")
        investigation = {
            "transaction_id": tx_id,
            "sender_profile": {"customer_id": customer_id, "anomalies_found": [f"Agente 2 falhou: {exc}"]},
            "receiver_profile": {"receiver_id": None, "appears_in_other_suspicious": False},
            "crossed_indicators": [],
            "correlated_events": [],
            "investigation_summary": f"Investigação indisponível: {exc}",
            "data_collection_status": "insuficiente",
            "missing_data": ["Agente 2 indisponível"],
            "llm_generated": False,
        }

    # ── Agente 3: Avaliação de Risco ──────────────────────────────────────────
    risk: dict = {}
    try:
        risk = agent_risk_analyzer.run(
            transaction, detection, investigation, case_id
        )
    except Exception as exc:
        logger.error("[Orchestrator] Agente 3 falhou: %s", exc)
        pipeline_errors.append(f"Agente3: {exc}")
        # Fallback determinístico para score — usa pesos médios do novo sistema
        # Média dos pesos: (16+14+20+14+19+17)/6 ≈ 16.7 pts por critério
        fallback_score = min(total_criteria * 17, 85)
        fallback_score = max(fallback_score, 40)
        risk = {
            "transaction_id": tx_id,
            "case_id": case_id,
            "risk_score": fallback_score,
            "risk_dimensions": {
                "severity_level": "alto" if fallback_score >= 61 else "medio",
                "severity_justification": f"Score estimado: {fallback_score}/100 (Agente 3 indisponível).",
                "priority_level": "alta" if fallback_score >= 61 else "media",
                "priority_justification": "Urgência definida pelo score de fallback.",
                "confidence_score": 0.4,
                "confidence_justification": "Agente 3 indisponível — confiança reduzida.",
            },
            "critical_evidence": detection.get("deterministic_evidence", []),
            "supporting_evidence": [],
            "weak_evidence": [],
            "refutation_points": [],
            "recommendations": [{"action_code": "revisao_humana", "description": "Revisão humana imediata necessária.", "proportional": True}],
            "information_gaps": [f"Agente 3 indisponível: {exc}"],
            "score_is_fallback": True,
        }

    # ── Agente 4: Relatório e Orquestração ────────────────────────────────────
    master: dict = {}
    try:
        master = agent_master.run(
            transaction, detection, investigation, risk,
            case_id, trace_id, pipeline_errors,
        )
    except Exception as exc:
        logger.error("[Orchestrator] Agente 4 falhou: %s", exc)
        pipeline_errors.append(f"Agente4: {exc}")
        risk_score = risk.get("risk_score", 0)
        risk_level = risk.get("risk_dimensions", {}).get("severity_level", "alto")
        master = {
            "transaction_id": tx_id,
            "case_id": case_id,
            "trace_id": trace_id,
            "processing_status": "REQUIRES_HUMAN_REVIEW",
            "final_risk_score": risk_score,
            "final_risk_level": risk_level,
            "urgency": "alta",
            "recommended_action": "revisao_humana",
            "executive_report": {
                "observed_facts": detection.get("deterministic_evidence", []),
                "ai_hypotheses": [],
                "limitations": [f"Agente 4 indisponível: {exc}"],
                "risk_justification": f"Score: {risk_score}/100. Revisão humana obrigatória.",
                "full_narrative": f"Agente 4 indisponível. Transação {tx_id} requer revisão humana imediata.",
            },
            "alert_subject": f"⚠️ ALERTA — REQUER REVISÃO HUMANA — {tx_id}",
            "alert_message": f"Transação {tx_id} escalada. Score: {risk_score}/100. Relatório indisponível.",
            "immediate_actions": ["Encaminhar imediatamente para revisão humana de Nível 2."],
            "pipeline_stages_completed": ["agent_1_detection"],
            "pipeline_errors": pipeline_errors,
            "completed_at": __import__("datetime").datetime.now().isoformat(),
            "disclaimer": "Sistema acadêmico de apoio à triagem. Decisão final sob responsabilidade humana. Este sistema NÃO executa operações financeiras.",
        }

    # ── Persistência ──────────────────────────────────────────────────────────
    case_persisted = False
    full_case = {
        "case_id": case_id,
        "trace_id": trace_id,
        "transaction_id": tx_id,
        "transaction": transaction,
        "agent_1_detection": detection,
        "agent_2_investigation": investigation,
        "agent_3_risk": risk,
        "agent_4_master": master,
        "pipeline_errors": pipeline_errors,
    }
    try:
        case_storage.save_case(case_id, full_case)
        case_persisted = True
    except OSError as exc:
        logger.error("[Orchestrator] Falha ao persistir caso %s: %s", case_id, exc)

    final_risk = master.get("final_risk_score", risk.get("risk_score", 0))
    final_level = master.get("final_risk_level", "desconhecido")

    return {
        "transaction_id": tx_id,
        "customer_id": customer_id,
        "case_id": case_id,
        "trace_id": trace_id,
        "processing_status": master.get("processing_status", "COMPLETED"),
        "total_criteria_met": total_criteria,
        "escalated": True,
        "case_persisted": case_persisted,
        "final_risk_score": final_risk,
        "final_risk_level": final_level,
        "agent_1_detection": detection,
        "agent_2_investigation": investigation,
        "agent_3_risk": risk,
        "agent_4_master": master,
    }


# ── Análise em lote ────────────────────────────────────────────────────────────

def _resolve_history(tx: dict, customer_index: dict[str, list[dict]]) -> list[dict]:
    """
    Determina o histórico relevante para uma transação.

    Prioridade:
      1. Se a transação tem campo `"_history": [...]` embutido, usa essa lista diretamente.
      2. Caso contrário, usa todas as transações do mesmo cliente que NÃO são a transação atual
         e NÃO são registros de histórico de outros clientes.
    """
    embedded = tx.get("_history")
    if embedded and isinstance(embedded, list):
        return embedded

    tx_id = tx.get("transaction_id", "")
    all_client_tx = customer_index.get(tx.get("customer_id", ""), [])
    return [t for t in all_client_tx if t.get("transaction_id") != tx_id]


def analyze_all_transactions() -> list[dict[str, Any]]:
    """
    Executa o pipeline apenas nas transações PRIMÁRIAS do dataset.
    Registros marcados com `_history_record: true` fornecem contexto histórico
    mas não são processados como casos independentes.
    """
    dataset = _load_dataset()
    customer_index = _build_customer_history_index(dataset)
    primaries = _primary_transactions(dataset)
    results = []

    for tx in primaries:
        history = _resolve_history(tx, customer_index)
        result = analyze_transaction(tx, history, primaries)
        results.append(result)

    return results


def analyze_single_by_id(transaction_id: str) -> dict[str, Any] | None:
    """Localiza e analisa uma transação do dataset pelo ID."""
    dataset = _load_dataset()
    customer_index = _build_customer_history_index(dataset)

    target = next((t for t in dataset if t.get("transaction_id") == transaction_id), None)
    if target is None:
        return None

    history = _resolve_history(target, customer_index)
    primaries = _primary_transactions(dataset)
    return analyze_transaction(target, history, primaries)


def get_all_transactions() -> list[dict]:
    """Retorna apenas as transações primárias (sem registros de histórico)."""
    return _primary_transactions(_load_dataset())
