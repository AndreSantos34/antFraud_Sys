"""
Persistência Temporária de Casos — AntFraud_Sys
────────────────────────────────────────────────
Armazena e recupera dossiês de casos suspeitos em arquivos JSON individuais
em app/data/cases/. Esta implementação é temporária para desenvolvimento e
testes autônomos do backend — substituir por banco de dados na integração final.

Interface pública preservada para compatibilidade com o banco de dados futuro:
  save_case(case_id, payload) → Path
  load_case(case_id) → dict | None
  list_cases() → list[dict]
  save_action_result(case_id, result) → None
  list_action_results(case_id) → list[dict]
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CASES_DIR = Path(__file__).parent / "data" / "cases"


def _ensure_dir() -> None:
    _CASES_DIR.mkdir(parents=True, exist_ok=True)


def save_case(case_id: str, payload: dict[str, Any]) -> Path:
    """
    Persiste o dossiê completo de um caso suspeito em JSON.

    Args:
        case_id: Identificador único do caso (ex: TXN-013_CASE_A1B2C3D4).
        payload: Dicionário com todos os dados do pipeline.

    Returns:
        Caminho do arquivo gravado.
    """
    _ensure_dir()
    payload["_saved_at"] = datetime.now().isoformat()
    file_path = _CASES_DIR / f"{case_id}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logger.info("[Storage] Caso %s salvo em %s", case_id, file_path)
    return file_path


def load_case(case_id: str) -> dict | None:
    """Carrega um caso pelo ID. Retorna None se não encontrado."""
    file_path = _CASES_DIR / f"{case_id}.json"
    if not file_path.exists():
        return None
    with open(file_path, encoding="utf-8") as f:
        return json.load(f)


def list_cases() -> list[dict]:
    """Lista todos os casos persistidos com metadados resumidos."""
    _ensure_dir()
    cases = []
    for file_path in sorted(_CASES_DIR.glob("*.json"), reverse=True):
        # Ignora arquivos de ações (sufixo _actions)
        if file_path.stem.endswith("_actions"):
            continue
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)

            master = data.get("agent_4_master", {}) or {}
            cases.append({
                "case_id":           data.get("case_id", file_path.stem),
                "transaction_id":    data.get("transaction_id"),
                "trace_id":          data.get("trace_id"),
                "processing_status": master.get("processing_status"),
                "final_risk_score":  master.get("final_risk_score"),
                "final_risk_level":  master.get("final_risk_level"),
                "urgency":           master.get("urgency"),
                "recommended_action": master.get("recommended_action"),
                "saved_at":          data.get("_saved_at"),
            })
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("[Storage] Erro ao ler caso %s: %s", file_path.name, exc)
    return cases


def save_action_result(case_id: str, result: dict[str, Any]) -> None:
    """
    Persiste o resultado de uma decisão (aprovação/rejeição) sobre uma ação.

    As decisões são armazenadas em arquivo separado do dossiê principal
    para não sobrescrever os dados do pipeline.

    Args:
        case_id: ID do caso ao qual a ação pertence.
        result:  Dicionário com os dados da decisão (ActionResult).
    """
    _ensure_dir()
    actions_file = _CASES_DIR / f"{case_id}_actions.json"

    # Carrega lista existente ou cria nova
    actions: list[dict] = []
    if actions_file.exists():
        try:
            with open(actions_file, encoding="utf-8") as f:
                actions = json.load(f)
        except (json.JSONDecodeError, OSError):
            actions = []

    result["_recorded_at"] = datetime.now().isoformat()
    actions.append(result)

    with open(actions_file, "w", encoding="utf-8") as f:
        json.dump(actions, f, ensure_ascii=False, indent=2)

    logger.info(
        "[Storage] Decisão registrada | case=%s | action=%s | status=%s",
        case_id, result.get("action_id"), result.get("status"),
    )


def list_action_results(case_id: str) -> list[dict]:
    """
    Retorna todas as decisões registradas para um caso.

    Returns:
        Lista de ActionResult em ordem cronológica (mais recente por último).
        Lista vazia se nenhuma decisão foi registrada ainda.
    """
    actions_file = _CASES_DIR / f"{case_id}_actions.json"
    if not actions_file.exists():
        return []
    try:
        with open(actions_file, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("[Storage] Erro ao ler ações do caso %s: %s", case_id, exc)
        return []
