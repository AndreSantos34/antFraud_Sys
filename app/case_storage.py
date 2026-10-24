"""
Persistência de Casos — armazena e recupera dossiês de transações suspeitas.

Estratégia de persistência (dual-write):
  1. MySQL (primário): quando DATABASE_URL estiver configurada e o servidor
     estiver acessível, os casos são gravados e lidos do banco antfraud_db.
  2. Arquivo JSON (fallback): os casos são SEMPRE gravados também em
     app/data/cases/<case_id>.json, independente do MySQL.
     Isso garante que a aplicação funcione mesmo sem banco de dados.

A leitura segue a ordem: MySQL → arquivo JSON.
Se o MySQL retornar None para load_case/list_cases, o código cai para o arquivo.

Essa abordagem preserva 100% do comportamento existente e adiciona o MySQL
sem nenhuma perda de funcionalidade.
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


# ── Escrita ───────────────────────────────────────────────────────────────────

def save_case(case_id: str, payload: dict[str, Any]) -> Path:
    """
    Persiste o dossiê completo de um caso suspeito.

    Grava em dois destinos:
    - MySQL (se disponível): via app.db.crud.save_case()
    - Arquivo JSON local: app/data/cases/<case_id>.json (sempre)

    Args:
        case_id: Identificador único do caso (ex: TXN-013_CASE).
        payload: Dicionário com todos os dados do pipeline.

    Returns:
        Caminho do arquivo JSON gravado.
    """
    # 1. Persiste no MySQL (não bloqueia se indisponível)
    try:
        from app.db import crud as db_crud
        persisted = db_crud.save_case(case_id, payload)
        if persisted:
            logger.info("[Storage] Caso %s salvo no MySQL.", case_id)
        else:
            logger.debug("[Storage] MySQL indisponível — caso %s gravado apenas em arquivo.", case_id)
    except Exception as exc:  # pragma: no cover
        logger.warning("[Storage] Falha ao salvar caso %s no MySQL: %s", case_id, exc)

    # 2. Persiste no arquivo JSON (fallback garantido)
    _ensure_dir()
    payload["_saved_at"] = datetime.now().isoformat()
    file_path = _CASES_DIR / f"{case_id}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logger.info("[Storage] Caso %s salvo em %s", case_id, file_path)
    return file_path


# ── Leitura ───────────────────────────────────────────────────────────────────

def load_case(case_id: str) -> dict | None:
    """
    Carrega um caso pelo ID.

    Tenta o MySQL primeiro; se não encontrar, tenta o arquivo JSON.
    Retorna None se não encontrado em nenhum destino.
    """
    # Tenta MySQL
    try:
        from app.db import crud as db_crud
        from app.db.database import is_db_available
        if is_db_available():
            db_result = db_crud.load_case(case_id)
            if db_result is not None:
                return db_result
    except Exception as exc:  # pragma: no cover
        logger.debug("[Storage] MySQL indisponível para load_case: %s", exc)

    # Fallback: arquivo JSON
    file_path = _CASES_DIR / f"{case_id}.json"
    if not file_path.exists():
        return None
    with open(file_path, encoding="utf-8") as f:
        return json.load(f)


def list_cases() -> list[dict]:
    """
    Lista todos os casos persistidos com metadados resumidos.

    Se o MySQL estiver disponível e retornar resultados, usa-o.
    Caso contrário, lê os arquivos JSON locais (comportamento original).
    """
    # Tenta MySQL
    try:
        from app.db import crud as db_crud
        from app.db.database import is_db_available
        if is_db_available():
            db_cases = db_crud.list_cases()
            if db_cases:  # retorna do MySQL se houver registros
                return db_cases
    except Exception as exc:  # pragma: no cover
        logger.debug("[Storage] MySQL indisponível para list_cases: %s", exc)

    # Fallback: arquivos JSON locais (comportamento original)
    _ensure_dir()
    cases = []
    for file_path in sorted(_CASES_DIR.glob("*.json")):
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            cases.append({
                "case_id": data.get("case_id", file_path.stem),
                "transaction_id": data.get("transaction_id"),
                "risk_score": data.get("agent_4_master", {}).get("risk_score"),
                "risk_level": data.get("agent_4_master", {}).get("risk_level"),
                "urgency": data.get("agent_4_master", {}).get("urgency"),
                "recommended_action": data.get("agent_4_master", {}).get("recommended_action"),
                "saved_at": data.get("_saved_at"),
            })
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("[Storage] Erro ao ler caso %s: %s", file_path.name, exc)
    return cases
