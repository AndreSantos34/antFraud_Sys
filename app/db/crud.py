"""
CRUD — operações de banco de dados para antFraud_Sys.

Funções disponíveis:
    save_transaction(tx_data)       → persiste/atualiza uma transação.
    save_case(case_id, payload)     → persiste/atualiza um caso suspeito.
    load_case(case_id)              → recupera um caso pelo ID.
    list_cases()                    → lista todos os casos com metadados resumidos.

Todas as funções retornam silenciosamente quando o MySQL não está disponível
(DATABASE_URL vazia ou servidor inacessível), deixando a aplicação operacional
com a persistência em arquivo JSON como fallback.

Campos obrigatórios no banco (NOT NULL sem DEFAULT):
    transactions: transaction_datetime, location, channel, device
    Se ausentes no tx_data, save_transaction() usa datetime.utcnow() /
    strings vazias e emite um aviso — a inserção não falha silenciosamente.
"""
import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select

from app.db.database import get_session, is_db_available
from app.db.models import Transaction, Case

logger = logging.getLogger(__name__)


# ── helpers internos ──────────────────────────────────────────────────────────

def _parse_datetime(value: Any) -> datetime | None:
    """Converte string ISO-8601 em datetime; retorna None em caso de falha."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


# ── Transações ────────────────────────────────────────────────────────────────

def save_transaction(tx_data: dict[str, Any]) -> bool:
    """
    Persiste uma transação no MySQL.

    Se a transação já existir (transaction_id duplicado), atualiza os campos
    mutáveis (label, reason) sem re-inserir o registro.

    Args:
        tx_data: Dicionário com os dados da transação.  Os campos esperados são
                 os mesmos usados pelo pipeline (transaction_id, customer_id, …).

    Returns:
        True se a operação foi bem-sucedida, False se o MySQL não está disponível
        ou ocorreu algum erro.
    """
    if not is_db_available():
        return False

    tx_id = tx_data.get("transaction_id") or tx_data.get("id")
    if not tx_id:
        logger.warning("[CRUD] save_transaction: transaction_id ausente — ignorado.")
        return False

    try:
        with get_session() as session:
            existing = session.scalar(
                select(Transaction).where(Transaction.transaction_id == tx_id)
            )
            if existing:
                # Atualiza apenas campos que podem mudar após análise
                existing.label = tx_data.get("label", existing.label)
                existing.reason = tx_data.get("reason", existing.reason)
            else:
                dt_field = tx_data.get("transaction_datetime") or tx_data.get("datetime")
                parsed_dt = _parse_datetime(dt_field)

                # transaction_datetime é NOT NULL no banco — usa utcnow() como fallback
                # e emite aviso para que o chamador saiba que o campo estava ausente.
                if parsed_dt is None:
                    logger.warning(
                        "[CRUD] save_transaction %s: transaction_datetime ausente — "
                        "usando datetime.utcnow() como fallback.",
                        tx_id,
                    )
                    parsed_dt = datetime.utcnow()

                # location, channel e device são NOT NULL no banco.
                # Usa strings vazias como fallback e avisa quando ausentes.
                location = tx_data.get("location") or ""
                channel  = tx_data.get("channel")  or ""
                device   = tx_data.get("device")   or ""
                for fname, fval in (("location", location), ("channel", channel), ("device", device)):
                    if not fval:
                        logger.warning(
                            "[CRUD] save_transaction %s: campo obrigatório '%s' ausente — "
                            "gravando string vazia.",
                            tx_id, fname,
                        )

                session.add(Transaction(
                    transaction_id=tx_id,
                    customer_id=tx_data.get("customer_id", ""),
                    receiver_id=tx_data.get("receiver_id"),
                    amount=tx_data.get("amount", 0),
                    transaction_datetime=parsed_dt,
                    location=location,
                    channel=channel,
                    device=device,
                    label=tx_data.get("label"),
                    reason=tx_data.get("reason"),
                ))
        return True
    except SQLAlchemyError as exc:
        logger.error("[CRUD] Erro ao salvar transação %s: %s", tx_id, exc)
        return False


# ── Casos ─────────────────────────────────────────────────────────────────────

def save_case(case_id: str, payload: dict[str, Any]) -> bool:
    """
    Persiste ou atualiza um caso suspeito no MySQL.

    Os campos agent_results e final_result são armazenados como JSON nativo.
    Se o caso já existir, seus resultados e status são atualizados.

    Args:
        case_id: Identificador único do caso.
        payload: Dicionário completo gerado pelo pipeline (inclui saídas de todos os agentes).

    Returns:
        True se persistido com sucesso, False em caso de erro ou MySQL indisponível.
    """
    if not is_db_available():
        return False

    try:
        master: dict = payload.get("agent_4_master") or {}
        agent_results = {
            "agent_1_risk": payload.get("agent_1_risk"),
            "agent_2_investigation": payload.get("agent_2_investigation"),
            "agent_3_evidence": payload.get("agent_3_evidence"),
        }

        with get_session() as session:
            existing = session.scalar(
                select(Case).where(Case.case_id == case_id)
            )
            if existing:
                existing.risk_score = master.get("risk_score", existing.risk_score)
                existing.risk_level = master.get("risk_level", existing.risk_level)
                existing.urgency = master.get("urgency", existing.urgency)
                existing.recommended_action = master.get("recommended_action", existing.recommended_action)
                existing.agent_results = agent_results
                existing.final_result = master
                existing.updated_at = datetime.utcnow()
            else:
                session.add(Case(
                    case_id=case_id,
                    transaction_id=payload.get("transaction_id"),
                    risk_score=master.get("risk_score"),
                    risk_level=master.get("risk_level"),
                    urgency=master.get("urgency"),
                    status="open",
                    reason=payload.get("agent_1_risk", {}).get("justification"),
                    recommended_action=master.get("recommended_action"),
                    agent_results=agent_results,
                    final_result=master,
                ))
        return True
    except SQLAlchemyError as exc:
        logger.error("[CRUD] Erro ao salvar caso %s: %s", case_id, exc)
        return False


def load_case(case_id: str) -> dict | None:
    """
    Recupera um caso do MySQL pelo ID.

    Returns:
        Dicionário com os dados do caso ou None se não encontrado / MySQL indisponível.
    """
    if not is_db_available():
        return None

    try:
        with get_session() as session:
            row = session.scalar(
                select(Case).where(Case.case_id == case_id)
            )
            if row is None:
                return None
            return {
                "case_id": row.case_id,
                "transaction_id": row.transaction_id,
                "risk_score": row.risk_score,
                "risk_level": row.risk_level,
                "urgency": row.urgency,
                "status": row.status,
                "reason": row.reason,
                "recommended_action": row.recommended_action,
                "agent_results": row.agent_results,
                "final_result": row.final_result,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
    except SQLAlchemyError as exc:
        logger.error("[CRUD] Erro ao carregar caso %s: %s", case_id, exc)
        return None


def list_cases() -> list[dict]:
    """
    Lista todos os casos do MySQL com metadados resumidos.

    Returns:
        Lista de dicionários compatível com CaseSummary.
        Retorna lista vazia se MySQL indisponível.
    """
    if not is_db_available():
        return []

    try:
        with get_session() as session:
            rows = session.scalars(select(Case).order_by(Case.created_at.desc())).all()
            return [
                {
                    "case_id": r.case_id,
                    "transaction_id": r.transaction_id,
                    "risk_score": r.risk_score,
                    "risk_level": r.risk_level,
                    "urgency": r.urgency,
                    "recommended_action": r.recommended_action,
                    "saved_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
    except SQLAlchemyError as exc:
        logger.error("[CRUD] Erro ao listar casos: %s", exc)
        return []
