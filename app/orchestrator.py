"""
Orquestrador do Pipeline de Detecção de Fraudes
────────────────────────────────────────────────
Fluxo hierárquico com 4 agentes:

  ┌─────────────────────────────────────────────────┐
  │  Transação recebida                             │
  └──────────────────┬──────────────────────────────┘
                     │
              [Agente 1 — Análise de Risco]
              Avalia os 6 critérios
                     │
           ┌─────────┴──────────┐
       < 3 critérios        >= 3 critérios
           │                    │
       NORMAL              SUSPEITA → escala
   (fluxo banco)               │
                         [Agente 2 — Investigação]
                         Coleta dados remetente + destinatário
                                │
                         [Agente 3 — Evidências]
                         Confirma/refuta + organiza dossiê
                                │
                    [Agente 4 — IA Mestre] (hierarquia superior)
                    Score de risco 0-100 + alerta Cybersecurity
                                │
                    Persiste caso + retorna resultado
"""
import json
import logging
from pathlib import Path
from typing import Any

from app.agents import (
    agent_rule_screener,
    agent_context_analyst,
    agent_report_generator,
    agent_master,
)
from app import case_storage

logger = logging.getLogger(__name__)

_DATASET_PATH = Path(__file__).parent / "data" / "transactions.json"


def _load_dataset() -> list[dict]:
    with open(_DATASET_PATH, encoding="utf-8") as f:
        return json.load(f)


def _build_customer_index(transactions: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for tx in transactions:
        cid = tx["customer_id"]
        index.setdefault(cid, []).append(tx)
    return index


def analyze_transaction(
    transaction: dict[str, Any],
    customer_history: list[dict] | None = None,
    all_transactions: list[dict] | None = None,
) -> dict[str, Any]:
    """
    Executa o pipeline completo para uma única transação.

    Retorna resultado com campos de todos os agentes que foram executados
    e indica se o caso foi persistido.
    """
    history = customer_history or []

    # ── Agente 1: Análise de Risco ────────────────────────────────────────────
    risk = agent_rule_screener.run(transaction, history)
    should_escalate = risk.get("escalate_to_investigation", False)

    investigation: dict | None = None
    evidence: dict | None = None
    master: dict | None = None
    case_persisted = False

    if should_escalate:
        logger.info(
            "Transação %s escalada (%d critérios). Acionando Agentes 2, 3 e Mestre.",
            transaction.get("transaction_id"),
            risk.get("total_criteria_met", 0),
        )

        # ── Agente 2: Investigação de Ameaças ─────────────────────────────────
        investigation = agent_context_analyst.run(
            transaction, risk, history, all_transactions
        )

        # ── Agente 3: Base de Dados e Evidências ──────────────────────────────
        evidence = agent_report_generator.run(transaction, risk, investigation)

        # ── Agente 4: IA Mestre ────────────────────────────────────────────────
        master = agent_master.run(transaction, risk, investigation, evidence)

        # ── Persistência ──────────────────────────────────────────────────────
        case_id = evidence.get("case_id") or f"{transaction.get('transaction_id')}_CASE"
        full_case = {
            "case_id": case_id,
            "transaction_id": transaction.get("transaction_id"),
            "transaction": transaction,
            "agent_1_risk": risk,
            "agent_2_investigation": investigation,
            "agent_3_evidence": evidence,
            "agent_4_master": master,
        }
        try:
            case_storage.save_case(case_id, full_case)
            case_persisted = True
        except OSError as exc:
            logger.error("[Orchestrator] Falha ao persistir caso %s: %s", case_id, exc)

    else:
        logger.info(
            "Transação %s classificada como NORMAL (%d critérios). Fluxo regular.",
            transaction.get("transaction_id"),
            risk.get("total_criteria_met", 0),
        )

    return {
        "transaction_id": transaction.get("transaction_id"),
        "customer_id": transaction.get("customer_id"),
        "total_criteria_met": risk.get("total_criteria_met", 0),
        "escalated": should_escalate,
        "case_persisted": case_persisted,
        "agent_1_risk": risk,
        "agent_2_investigation": investigation,
        "agent_3_evidence": evidence,
        "agent_4_master": master,
    }


def analyze_all_transactions() -> list[dict[str, Any]]:
    """Executa o pipeline em todas as transações do dataset."""
    transactions = _load_dataset()
    customer_index = _build_customer_index(transactions)
    results = []

    for tx in transactions:
        all_client_tx = customer_index.get(tx["customer_id"], [])
        history = [t for t in all_client_tx if t["transaction_id"] != tx["transaction_id"]]
        result = analyze_transaction(tx, history, transactions)
        results.append(result)

    return results


def analyze_single_by_id(transaction_id: str) -> dict[str, Any] | None:
    """Localiza e analisa uma transação do dataset pelo ID."""
    transactions = _load_dataset()
    customer_index = _build_customer_index(transactions)

    target = next((t for t in transactions if t["transaction_id"] == transaction_id), None)
    if target is None:
        return None

    history = [
        t for t in customer_index.get(target["customer_id"], [])
        if t["transaction_id"] != transaction_id
    ]
    return analyze_transaction(target, history, transactions)


def get_all_transactions() -> list[dict]:
    return _load_dataset()
