"""
Suite de testes — Integração MySQL para antFraud_Sys
=====================================================

Cobre os 11 cenários obrigatórios definidos na spec de migração:

  1.  Conexão com o MySQL.
  2.  Inicialização do esquema (CREATE TABLE IF NOT EXISTS).
  3.  Criação de uma transação.
  4.  Consulta de transações.
  5.  Criação de um caso suspeito.
  6.  Associação de um caso a uma transação.
  7.  Comportamento de exclusão com ON DELETE SET NULL.
  8.  Validação de pontuação de risco (risk_score).
  9.  Gravação e leitura dos campos JSON.
 10.  Tratamento de falhas de conexão.
 11.  Compatibilidade das rotas da API com a nova camada de persistência.

REQUISITOS PARA EXECUÇÃO LOCAL
──────────────────────────────
1. MySQL Server em execução com o banco `antfraud_db` criado.
2. Arquivo .env com DATABASE_URL configurada, ex.:
       DATABASE_URL=mysql+pymysql://antfraud_user:SENHA@localhost:3306/antfraud_db
3. Instalar dependências:
       pip install -r requirements.txt
       pip install pytest httpx
4. Executar:
       pytest tests/test_mysql.py -v

QUANDO O MYSQL NÃO ESTÁ DISPONÍVEL
────────────────────────────────────
Os testes 1–9 são marcados como `skip` automaticamente quando
`is_db_available()` retorna False (DATABASE_URL vazia ou servidor inacessível).

O teste 10 (falha de conexão) e o teste 11 (rotas API) rodam sem MySQL.
"""
import os
import uuid
import pytest

# ─── Configuração ──────────────────────────────────────────────────────────────

# Permite que os testes encontrem a raiz do projeto
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Garante que não há cache de settings de outros testes
from app.core.config import get_settings
get_settings.cache_clear()


# ─── Fixtures ──────────────────────────────────────────────────────────────────

def _unique_tx_id() -> str:
    return f"TEST-TX-{uuid.uuid4().hex[:8].upper()}"


def _unique_case_id() -> str:
    return f"TEST-CASE-{uuid.uuid4().hex[:8].upper()}"


def _sample_transaction(tx_id: str | None = None) -> dict:
    return {
        "transaction_id": tx_id or _unique_tx_id(),
        "customer_id": "CLI-TEST-001",
        "receiver_id": "CLI-TEST-002",
        "amount": 1250.75,
        "datetime": "2024-07-15T14:30:00",
        "location": "São Paulo, SP",
        "channel": "internet_banking",
        "device": "notebook_pessoal",
        "label": "normal",
        "reason": "Transação dentro dos parâmetros normais.",
    }


def _sample_case_payload(case_id: str, tx_id: str) -> dict:
    return {
        "case_id": case_id,
        "transaction_id": tx_id,
        "agent_1_risk": {
            "transaction_id": tx_id,
            "criteria_evaluation": {
                "valor_elevado": True,
                "horario_incomum": True,
                "frequencia_elevada": False,
                "valor_repetido": True,
                "mudanca_geografica": False,
                "dispositivo_desconhecido": False,
            },
            "total_criteria_met": 3,
            "escalate_to_investigation": True,
            "classification": "suspeita",
            "confidence": 0.87,
            "justification": "Valor elevado + horário incomum + valor repetido.",
        },
        "agent_2_investigation": {
            "transaction_id": tx_id,
            "investigation_summary": "Perfil do remetente apresenta inconsistências.",
            "crossed_indicators": ["valor_elevado", "horario_incomum"],
            "data_collection_status": "completo",
            "missing_data": [],
            "sender_profile": {"risk": "high"},
            "receiver_profile": {"risk": "low"},
        },
        "agent_3_evidence": {
            "transaction_id": tx_id,
            "case_id": case_id,
            "suspicion_confirmed": True,
            "confirmation_confidence": 0.91,
            "refutation_arguments": [],
            "confirmation_arguments": ["Padrão consistente com fraude por fracionamento."],
            "evidence_summary": {"confirmação": ["Valor elevado em horário incomum"]},
            "consolidated_case": {},
            "data_quality": "alta",
            "information_gaps": [],
            "recommendation_to_master": "Bloquear preventivamente.",
        },
        "agent_4_master": {
            "transaction_id": tx_id,
            "case_id": case_id,
            "risk_score": 82,
            "risk_level": "crítico",
            "urgency": "imediata",
            "score_breakdown": {"valor": 30, "horario": 20, "repetido": 32},
            "recommended_action": "Bloquear transação e notificar compliance.",
            "cybersecurity_alert": {
                "subject": "ALERTA CRÍTICO",
                "priority": "P1",
                "timestamp": "2024-07-15T14:30:00",
                "message": "Transação suspeita detectada.",
                "immediate_actions": ["Bloquear conta", "Notificar titular"],
                "case_summary": "Fraude provável por fracionamento.",
            },
            "disclaimer": "Decisão requer validação humana.",
        },
    }


# ─── Helper de skip ─────────────────────────────────────────────────────────────

def _require_db():
    """Pula o teste se o MySQL não estiver disponível."""
    from app.db.database import is_db_available
    if not is_db_available():
        pytest.skip(
            "MySQL não disponível — configure DATABASE_URL no .env e garanta que "
            "o servidor está em execução antes de rodar estes testes."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Teste 1 — Conexão com o MySQL
# ═══════════════════════════════════════════════════════════════════════════════

def test_01_mysql_connection():
    """Verifica que a aplicação consegue conectar ao MySQL e executar SELECT 1."""
    _require_db()
    from app.db.database import get_engine
    from sqlalchemy import text

    engine = get_engine()
    assert engine is not None, "Engine não foi criado — verifique DATABASE_URL."

    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1")).scalar()
    assert result == 1, "SELECT 1 deveria retornar 1."


# ═══════════════════════════════════════════════════════════════════════════════
# Teste 2 — Inicialização do esquema
# ═══════════════════════════════════════════════════════════════════════════════

def test_02_schema_init():
    """
    Garante que init_db() cria as tabelas `transactions` e `cases`
    sem erros e sem destruir dados existentes (idempotente).
    """
    _require_db()
    from app.db.models import init_db
    from app.db.database import get_engine
    from sqlalchemy import inspect

    # Deve ser idempotente: pode ser chamado N vezes
    init_db()
    init_db()

    inspector = inspect(get_engine())
    tables = inspector.get_table_names()
    assert "transactions" in tables, "Tabela 'transactions' não encontrada."
    assert "cases" in tables, "Tabela 'cases' não encontrada."


# ═══════════════════════════════════════════════════════════════════════════════
# Teste 3 — Criação de uma transação
# ═══════════════════════════════════════════════════════════════════════════════

def test_03_create_transaction():
    """Persiste uma transação e verifica que ela aparece no banco."""
    _require_db()
    from app.db import crud
    from app.db.database import get_session
    from app.db.models import Transaction
    from sqlalchemy import select

    tx = _sample_transaction()
    tx_id = tx["transaction_id"]

    result = crud.save_transaction(tx)
    assert result is True, "save_transaction deveria retornar True quando MySQL disponível."

    with get_session() as session:
        row = session.scalar(select(Transaction).where(Transaction.transaction_id == tx_id))
        assert row is not None, f"Transação {tx_id} não encontrada no banco."
        assert float(row.amount) == pytest.approx(1250.75)
        assert row.customer_id == "CLI-TEST-001"
        assert row.label == "normal"


# ═══════════════════════════════════════════════════════════════════════════════
# Teste 4 — Consulta de transações
# ═══════════════════════════════════════════════════════════════════════════════

def test_04_query_transactions():
    """Insere múltiplas transações e verifica a contagem mínima."""
    _require_db()
    from app.db import crud
    from app.db.database import get_session
    from app.db.models import Transaction
    from sqlalchemy import select, func

    # Insere 3 transações distintas
    ids = [_unique_tx_id() for _ in range(3)]
    for tx_id in ids:
        crud.save_transaction(_sample_transaction(tx_id))

    with get_session() as session:
        count = session.scalar(select(func.count()).select_from(Transaction))

    assert count >= 3, "Deveria haver pelo menos 3 transações no banco."


# ═══════════════════════════════════════════════════════════════════════════════
# Teste 5 — Criação de um caso suspeito
# ═══════════════════════════════════════════════════════════════════════════════

def test_05_create_case():
    """Persiste um caso suspeito e verifica que os campos principais foram gravados."""
    _require_db()
    from app.db import crud
    from app.db.database import get_session
    from app.db.models import Case
    from sqlalchemy import select

    tx_id = _unique_tx_id()
    case_id = _unique_case_id()
    payload = _sample_case_payload(case_id, tx_id)

    # Garante que a transação existe antes de criar o caso
    crud.save_transaction(_sample_transaction(tx_id))
    result = crud.save_case(case_id, payload)
    assert result is True, "save_case deveria retornar True quando MySQL disponível."

    with get_session() as session:
        row = session.scalar(select(Case).where(Case.case_id == case_id))
        assert row is not None, f"Caso {case_id} não encontrado no banco."
        assert row.risk_score == 82
        assert row.risk_level == "crítico"
        assert row.urgency == "imediata"
        assert row.status == "open"


# ═══════════════════════════════════════════════════════════════════════════════
# Teste 6 — Associação de um caso a uma transação
# ═══════════════════════════════════════════════════════════════════════════════

def test_06_case_linked_to_transaction():
    """Verifica que cases.transaction_id aponta para a transação correta."""
    _require_db()
    from app.db import crud
    from app.db.database import get_session
    from app.db.models import Case, Transaction
    from sqlalchemy import select

    tx_id = _unique_tx_id()
    case_id = _unique_case_id()

    crud.save_transaction(_sample_transaction(tx_id))
    crud.save_case(case_id, _sample_case_payload(case_id, tx_id))

    with get_session() as session:
        case_row = session.scalar(select(Case).where(Case.case_id == case_id))
        assert case_row is not None
        assert case_row.transaction_id == tx_id

        # Valida através do relacionamento ORM
        tx_row = session.scalar(
            select(Transaction).where(Transaction.transaction_id == tx_id)
        )
        assert tx_row is not None
        # A lista de casos do relacionamento deve conter o caso criado
        case_ids = [c.case_id for c in tx_row.cases]
        assert case_id in case_ids, "O caso deveria estar associado à transação via FK."


# ═══════════════════════════════════════════════════════════════════════════════
# Teste 7 — ON DELETE SET NULL ao excluir uma transação
# ═══════════════════════════════════════════════════════════════════════════════

def test_07_on_delete_set_null():
    """
    Ao excluir uma transação, os casos associados devem ter transaction_id = NULL.
    Isso preserva o histórico dos casos sem violar a integridade referencial.
    """
    _require_db()
    from app.db import crud
    from app.db.database import get_session
    from app.db.models import Case, Transaction
    from sqlalchemy import select, delete

    tx_id = _unique_tx_id()
    case_id = _unique_case_id()

    crud.save_transaction(_sample_transaction(tx_id))
    crud.save_case(case_id, _sample_case_payload(case_id, tx_id))

    # Exclui a transação diretamente via SQL
    with get_session() as session:
        session.execute(delete(Transaction).where(Transaction.transaction_id == tx_id))

    # O caso deve persistir com transaction_id = NULL
    with get_session() as session:
        case_row = session.scalar(select(Case).where(Case.case_id == case_id))
        assert case_row is not None, "Caso deveria persistir após exclusão da transação."
        assert case_row.transaction_id is None, (
            "ON DELETE SET NULL: cases.transaction_id deveria ser NULL após exclusão da transação."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Teste 8 — Validação de pontuação de risco
# ═══════════════════════════════════════════════════════════════════════════════

def test_08_risk_score_range():
    """
    Verifica que risk_score é gravado e lido corretamente nos limites 0 e 100.
    A restrição CHECK é aplicada na camada Pydantic; testamos os valores extremos.
    """
    _require_db()
    from app.db import crud
    from app.db.database import get_session
    from app.db.models import Case
    from sqlalchemy import select

    for score in (0, 50, 100):
        tx_id = _unique_tx_id()
        case_id = _unique_case_id()
        payload = _sample_case_payload(case_id, tx_id)
        payload["agent_4_master"]["risk_score"] = score

        crud.save_transaction(_sample_transaction(tx_id))
        crud.save_case(case_id, payload)

        with get_session() as session:
            row = session.scalar(select(Case).where(Case.case_id == case_id))
            assert row is not None
            assert row.risk_score == score, f"risk_score={score} não foi gravado corretamente."


# ═══════════════════════════════════════════════════════════════════════════════
# Teste 9 — Gravação e leitura dos campos JSON
# ═══════════════════════════════════════════════════════════════════════════════

def test_09_json_fields_roundtrip():
    """
    Verifica que agent_results e final_result são gravados e lidos como dicionários
    Python nativos (não strings), usando o tipo JSON nativo do MySQL.
    """
    _require_db()
    from app.db import crud
    from app.db.database import get_session
    from app.db.models import Case
    from sqlalchemy import select

    tx_id = _unique_tx_id()
    case_id = _unique_case_id()
    payload = _sample_case_payload(case_id, tx_id)

    crud.save_transaction(_sample_transaction(tx_id))
    crud.save_case(case_id, payload)

    with get_session() as session:
        row = session.scalar(select(Case).where(Case.case_id == case_id))

        # agent_results deve ser um dict, não uma string
        assert isinstance(row.agent_results, dict), (
            f"agent_results deveria ser dict, mas é {type(row.agent_results)}"
        )
        assert "agent_1_risk" in row.agent_results
        assert "agent_2_investigation" in row.agent_results
        assert "agent_3_evidence" in row.agent_results

        # final_result deve ser um dict com os campos do agente 4
        assert isinstance(row.final_result, dict), (
            f"final_result deveria ser dict, mas é {type(row.final_result)}"
        )
        assert row.final_result.get("risk_score") == 82

        # Valida estrutura aninhada preservada
        criteria = row.agent_results["agent_1_risk"]["criteria_evaluation"]
        assert criteria["valor_elevado"] is True
        assert criteria["frequencia_elevada"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# Teste 10 — Tratamento de falhas de conexão
# ═══════════════════════════════════════════════════════════════════════════════

def test_10_connection_failure_graceful():
    """
    Verifica que a aplicação se degrada graciosamente quando o MySQL não está
    disponível: is_db_available() retorna False e as funções CRUD retornam
    valores neutros (False / None / []) sem lançar exceções.

    Este teste roda sem MySQL — simula a falha de conexão com URL inválida.
    """
    import importlib

    # Força uma URL inválida temporariamente em um engine isolado
    from sqlalchemy import create_engine
    from sqlalchemy.exc import OperationalError

    bad_engine = create_engine(
        "mysql+pymysql://invalid_user:wrong_password@127.0.0.1:1/nonexistent_db",
        connect_args={"connect_timeout": 2},
    )

    # A conexão deve falhar
    with pytest.raises(Exception):
        with bad_engine.connect() as conn:
            from sqlalchemy import text
            conn.execute(text("SELECT 1"))

    # Com DATABASE_URL vazia, is_db_available() deve retornar False
    from unittest.mock import patch
    with patch("app.db.database._engine", None), \
         patch("app.db.database._SessionLocal", None):
        # Limpa o cache de settings para testar DATABASE_URL vazia
        get_settings.cache_clear()
        original_url = os.environ.get("DATABASE_URL", "")
        os.environ["DATABASE_URL"] = ""

        try:
            from app.db.database import is_db_available, get_engine
            # Recria o módulo state para simular ambiente sem URL
            import app.db.database as db_module
            db_module._engine = None
            db_module._SessionLocal = None

            # is_db_available deve retornar False sem lançar exceção
            available = is_db_available()
            assert available is False, "is_db_available() deveria retornar False sem DATABASE_URL."

            # CRUD deve retornar valores neutros
            from app.db import crud
            assert crud.save_transaction({"transaction_id": "X"}) is False
            assert crud.save_case("X", {}) is False
            assert crud.load_case("X") is None
            assert crud.list_cases() == []
        finally:
            # Restaura o estado original
            if original_url:
                os.environ["DATABASE_URL"] = original_url
            else:
                os.environ.pop("DATABASE_URL", None)
            get_settings.cache_clear()
            # Reinicializa o engine
            import app.db.database as db_module
            db_module._engine = None
            db_module._SessionLocal = None


# ═══════════════════════════════════════════════════════════════════════════════
# Teste 11 — Compatibilidade das rotas da API
# ═══════════════════════════════════════════════════════════════════════════════

def test_11_api_routes_with_db_layer():
    """
    Verifica que as rotas da API FastAPI funcionam corretamente com a nova
    camada de persistência MySQL, usando o TestClient do FastAPI.

    Testa:
    - GET /api/v1/health  → deve retornar 200 (sem MySQL obrigatório)
    - GET /              → deve retornar informações da API
    - GET /api/v1/transactions → deve retornar a lista do dataset JSON
    - GET /api/v1/cases  → deve retornar lista (vazia ou com dados) sem erro 500
    """
    import os
    os.environ.setdefault("API_SECRET_KEY", "test-key")
    get_settings.cache_clear()

    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("httpx não instalado — execute: pip install httpx")

    from main import app

    # Reinicia o cache de settings para usar a chave de teste
    get_settings.cache_clear()

    # Recria o cliente com a chave correta
    api_key = get_settings().api_secret_key

    client = TestClient(app, raise_server_exceptions=False)

    # ── Root endpoint ─────────────────────────────────────────────────────────
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert "projeto" in data
    assert "versao" in data

    # ── Health check (não requer MySQL) ───────────────────────────────────────
    resp = client.get("/api/v1/health", headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    health = resp.json()
    assert health["status"] == "ok"

    # ── Listagem de transações do dataset JSON ────────────────────────────────
    resp = client.get("/api/v1/transactions", headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    transactions = resp.json()
    assert isinstance(transactions, list)
    assert len(transactions) > 0, "O dataset deveria ter pelo menos 1 transação."

    # ── Listagem de casos (pode estar vazia, mas não deve dar erro 500) ───────
    resp = client.get("/api/v1/cases", headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    cases = resp.json()
    assert isinstance(cases, list)

    # ── Autenticação inválida deve retornar 401 ───────────────────────────────
    resp = client.get("/api/v1/transactions", headers={"X-API-Key": "chave-errada"})
    assert resp.status_code == 401
