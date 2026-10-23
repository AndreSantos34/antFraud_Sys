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
