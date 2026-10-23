"""
Testes unitários — AntFraud_Sys Backend (nova arquitetura 4 agentes)
─────────────────────────────────────────────────────────────────────
Todos os testes que envolvem agentes usam mock no gemini_client.
Nenhuma chamada real ao Gemini é feita neste arquivo.

Execução:
    python -m pytest tests/ -v
"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures compartilhadas
# ══════════════════════════════════════════════════════════════════════════════

TX_NORMAL = {
    "transaction_id": "TEST-N01",
    "customer_id": "CLI-TEST",
    "amount": 200.00,
    "datetime": "2024-06-10T10:00:00",
    "location": "São Paulo, SP",
    "channel": "app_mobile",
    "device": "smartphone_conhecido",
    "receiver_id": None,
}

TX_SUSPICIOUS = {
    "transaction_id": "TEST-S01",
    "customer_id": "CLI-TEST2",
    "amount": 9800.00,
    "datetime": "2024-06-10T02:37:00",   # horario_incomum
    "location": "Miami, EUA",             # mudanca_geografica
    "channel": "internet_banking",
    "device": "dispositivo_desconhecido", # dispositivo_desconhecido
    "receiver_id": "CLI-RECV",
}

HISTORY_SAMPLE = [
    {
        "transaction_id": "OLD-001",
        "customer_id": "CLI-TEST2",
        "amount": 200.00,
        "datetime": "2024-06-08T10:00:00",
        "location": "Rio de Janeiro, RJ",
        "channel": "app_mobile",
        "device": "smartphone_conhecido",
    }
]

DETECTION_RESULT_SUSPICIOUS = {
    "transaction_id": "TEST-S01",
    "criteria_flags": {
        "valor_elevado": True,
        "horario_incomum": True,
        "frequencia_elevada": False,
        "valor_repetido": False,
        "mudanca_geografica": True,
        "dispositivo_desconhecido": True,
    },
    "total_criteria_met": 4,
    "escalate_to_investigation": True,
    "classification": "suspeita",
    "deterministic_evidence": [
        "Valor R$ 9.800,00 excede o limiar.",
        "Transação às 02h está fora do horário habitual.",
    ],
    "llm_justification": "Múltiplos indicadores de suspeita confirmados.",
    "llm_confidence": 0.92,
}

INVESTIGATION_RESULT = {
    "transaction_id": "TEST-S01",
    "sender_profile": {
        "customer_id": "CLI-TEST2",
        "typical_amount_range": "R$ 200,00 – R$ 500,00",
        "behavioral_deviation_score": 0.75,
        "anomalies_found": [],
    },
    "receiver_profile": {
        "receiver_id": "CLI-RECV",
        "appears_in_other_suspicious": False,
        "receiver_notes": "Destinatário sem histórico suspeito.",
    },
    "crossed_indicators": ["valor_elevado + horario_incomum"],
    "correlated_events": [],
    "investigation_summary": "Transação atípica detectada.",
    "data_collection_status": "parcial",
    "missing_data": [],
    "llm_generated": True,
}


# ══════════════════════════════════════════════════════════════════════════════
# 1. Config
# ══════════════════════════════════════════════════════════════════════════════

class TestConfig:
    def test_model_names_are_valid(self):
        from app.core.config import get_settings
        s = get_settings()
        for attr in ("gemini_model_agent1", "gemini_model_agent2",
                     "gemini_model_agent3", "gemini_model_agent4"):
            model = getattr(s, attr)
            assert "gemini" in model.lower(), f"{attr}='{model}' não parece modelo Gemini"

    def test_thresholds_are_positive(self):
        from app.core.config import get_settings
        s = get_settings()
        assert s.high_value_threshold > 0
        assert s.high_freq_max_tx > 0
        assert s.high_freq_window_min > 0

    def test_retry_config_present(self):
        from app.core.config import get_settings
        s = get_settings()
        assert s.gemini_retry_attempts >= 0
        assert s.gemini_retry_delay_s > 0


# ══════════════════════════════════════════════════════════════════════════════
# 2. GeminiClient
# ══════════════════════════════════════════════════════════════════════════════

class TestGeminiClient:
    def test_raises_api_error_when_no_key(self):
        from app.core.gemini_client import GeminiClient, GeminiAPIError
        with patch("app.core.gemini_client.get_settings") as mock_s:
            mock_s.return_value.gemini_api_key = ""
            mock_s.return_value.gemini_retry_attempts = 0
            mock_s.return_value.gemini_retry_delay_s = 0.1
            client = GeminiClient()
            with pytest.raises(GeminiAPIError) as exc:
                client.generate("gemini-flash-lite-latest", "sys", "user")
            assert "GEMINI_API_KEY" in str(exc.value)

    def test_raises_on_429_after_retries(self):
        from app.core.gemini_client import GeminiClient, GeminiAPIError
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 429
        mock_resp.json.return_value = {"error": {"message": "Quota exceeded"}}
        mock_resp.text = "Quota exceeded"

        with patch("app.core.gemini_client.get_settings") as mock_s, \
             patch("app.core.gemini_client.requests.post", return_value=mock_resp), \
             patch("app.core.gemini_client.time") as mock_time:
            mock_s.return_value.gemini_api_key = "fake"
            mock_s.return_value.gemini_retry_attempts = 1
            mock_s.return_value.gemini_retry_delay_s = 0.01
            client = GeminiClient()
            with pytest.raises(GeminiAPIError) as exc:
                client.generate("gemini-flash-lite-latest", "sys", "user")
            assert exc.value.status_code == 429

    def test_generates_valid_json(self):
        from app.core.gemini_client import GeminiClient
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": '{"status":"ok"}'}]}}]
        }
        with patch("app.core.gemini_client.get_settings") as mock_s, \
             patch("app.core.gemini_client.requests.post", return_value=mock_resp):
            mock_s.return_value.gemini_api_key = "fake"
            mock_s.return_value.gemini_retry_attempts = 0
            mock_s.return_value.gemini_retry_delay_s = 0.1
            client = GeminiClient()
            result = client.generate_json("gemini-flash-lite-latest", "sys", "user")
        assert result == {"status": "ok"}


# ══════════════════════════════════════════════════════════════════════════════
# 3. Agente 1 — Detecção Determinística
# ══════════════════════════════════════════════════════════════════════════════

class TestAgent1Detection:
    def setup_method(self):
        # Limpa dedup cache entre testes
        from app.agents.agent_rule_screener import clear_dedup_cache
        clear_dedup_cache()

    def test_detects_high_value_deterministically(self):
        from app.agents import agent_rule_screener
        with patch("app.agents.agent_rule_screener.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("LLM down")
            result = agent_rule_screener.run(TX_SUSPICIOUS)
        assert result["criteria_flags"]["valor_elevado"] is True

    def test_detects_unusual_hour_deterministically(self):
        from app.agents import agent_rule_screener
        with patch("app.agents.agent_rule_screener.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("LLM down")
            result = agent_rule_screener.run(TX_SUSPICIOUS)
        assert result["criteria_flags"]["horario_incomum"] is True

    def test_detects_unknown_device_deterministically(self):
        from app.agents import agent_rule_screener
        with patch("app.agents.agent_rule_screener.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("LLM down")
            result = agent_rule_screener.run(TX_SUSPICIOUS)
        assert result["criteria_flags"]["dispositivo_desconhecido"] is True

    def test_escalates_with_3_or_more_criteria(self):
        from app.agents import agent_rule_screener
        with patch("app.agents.agent_rule_screener.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("LLM down")
            result = agent_rule_screener.run(TX_SUSPICIOUS)
        assert result["escalate_to_investigation"] is True
        assert result["classification"] == "suspeita"
        assert result["total_criteria_met"] >= 3

    def test_normal_transaction_does_not_escalate(self):
        from app.agents import agent_rule_screener
        with patch("app.agents.agent_rule_screener.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("LLM down")
            result = agent_rule_screener.run(TX_NORMAL)
        assert result["escalate_to_investigation"] is False
        assert result["classification"] == "normal"

    def test_deduplication_prevents_reprocessing(self):
        from app.agents import agent_rule_screener
        with patch("app.agents.agent_rule_screener.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("LLM down")
            first = agent_rule_screener.run(TX_SUSPICIOUS)
        # Mesmo ID — deve retornar duplicada
        with patch("app.agents.agent_rule_screener.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("LLM down")
            second = agent_rule_screener.run(TX_SUSPICIOUS)
        assert second["classification"] == "duplicada"

    def test_llm_justification_called_only_when_escalated(self):
        from app.agents import agent_rule_screener
        clear_mock = MagicMock(return_value={"justification": "OK", "confidence": 0.9})
        with patch("app.agents.agent_rule_screener.gemini_client") as mock_gc:
            mock_gc.generate_json = clear_mock
            agent_rule_screener.run(TX_SUSPICIOUS)
        clear_mock.assert_called_once()

    def test_llm_failure_does_not_affect_escalation_decision(self):
        from app.agents import agent_rule_screener
        clear_dedup = __import__("app.agents.agent_rule_screener", fromlist=["clear_dedup_cache"])
        clear_dedup.clear_dedup_cache()
        with patch("app.agents.agent_rule_screener.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("API falhou")
            result = agent_rule_screener.run(TX_SUSPICIOUS)
        # Escalada deterministicamente mesmo sem LLM
        assert result["escalate_to_investigation"] is True
        assert result["llm_justification"] is None

    def test_detects_geographic_change_from_history(self):
        from app.agents import agent_rule_screener
        tx = {**TX_SUSPICIOUS, "transaction_id": "TEST-GEO-01"}
        with patch("app.agents.agent_rule_screener.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("LLM down")
            result = agent_rule_screener.run(tx, customer_history=HISTORY_SAMPLE)
        # Miami, EUA vs histórico Rio de Janeiro, RJ → mudança geográfica
        assert result["criteria_flags"]["mudanca_geografica"] is True

    def test_detects_repeated_value_from_history(self):
        from app.agents import agent_rule_screener
        history_with_same_value = [
            {**HISTORY_SAMPLE[0], "amount": 9800.00, "transaction_id": "OLD-002"}
        ]
        tx = {**TX_SUSPICIOUS, "transaction_id": "TEST-REP-01"}
        with patch("app.agents.agent_rule_screener.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("LLM down")
            result = agent_rule_screener.run(tx, customer_history=history_with_same_value)
        assert result["criteria_flags"]["valor_repetido"] is True


# ══════════════════════════════════════════════════════════════════════════════
# 4. Agente 2 — Investigação e Correlação
# ══════════════════════════════════════════════════════════════════════════════

class TestAgent2Investigation:
    def test_builds_sender_profile_from_history(self):
        from app.agents import agent_context_analyst
        with patch("app.agents.agent_context_analyst.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("LLM down")
            result = agent_context_analyst.run(
                TX_SUSPICIOUS, DETECTION_RESULT_SUSPICIOUS, HISTORY_SAMPLE
            )
        sender = result["sender_profile"]
        assert sender["customer_id"] == TX_SUSPICIOUS["customer_id"]
        assert sender["typical_amount_range"] is not None

    def test_fallback_when_llm_unavailable(self):
        from app.agents import agent_context_analyst
        with patch("app.agents.agent_context_analyst.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("LLM down")
            result = agent_context_analyst.run(TX_SUSPICIOUS, DETECTION_RESULT_SUSPICIOUS)
        assert result["llm_generated"] is False
        assert len(result["crossed_indicators"]) > 0

    def test_no_history_returns_none_profile_fields(self):
        from app.agents import agent_context_analyst
        with patch("app.agents.agent_context_analyst.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("LLM down")
            result = agent_context_analyst.run(TX_SUSPICIOUS, DETECTION_RESULT_SUSPICIOUS, [])
        assert result["sender_profile"]["typical_amount_range"] is None

    def test_receiver_suspicion_detected(self):
        from app.agents import agent_context_analyst
        suspicious_dataset = [
            {
                "transaction_id": "DS-001",
                "customer_id": "CLI-RECV",
                "device": "dispositivo_desconhecido_X",
                "label": "suspeita",
            }
        ]
        with patch("app.agents.agent_context_analyst.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("LLM down")
            result = agent_context_analyst.run(
                TX_SUSPICIOUS, DETECTION_RESULT_SUSPICIOUS,
                all_transactions=suspicious_dataset,
            )
        assert result["receiver_profile"]["appears_in_other_suspicious"] is True


# ══════════════════════════════════════════════════════════════════════════════
# 5. Agente 3 — Avaliação de Risco
# ══════════════════════════════════════════════════════════════════════════════

class TestAgent3RiskAnalyzer:
    def test_score_reflects_criteria_count(self):
        from app.agents import agent_risk_analyzer
        with patch("app.agents.agent_risk_analyzer.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("LLM down")
            result = agent_risk_analyzer.run(
                TX_SUSPICIOUS, DETECTION_RESULT_SUSPICIOUS,
                INVESTIGATION_RESULT, "CASE-001"
            )
        # 4 critérios devem gerar score > 0
        assert result["risk_score"] > 0
        assert result["risk_score"] <= 100

    def test_risk_dimensions_present(self):
        from app.agents import agent_risk_analyzer
        with patch("app.agents.agent_risk_analyzer.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("LLM down")
            result = agent_risk_analyzer.run(
                TX_SUSPICIOUS, DETECTION_RESULT_SUSPICIOUS,
                INVESTIGATION_RESULT, "CASE-001"
            )
        dims = result["risk_dimensions"]
        assert "severity_level" in dims
        assert "priority_level" in dims
        assert "confidence_score" in dims

    def test_fallback_flag_set_when_llm_fails(self):
        from app.agents import agent_risk_analyzer
        with patch("app.agents.agent_risk_analyzer.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("LLM down")
            result = agent_risk_analyzer.run(
                TX_SUSPICIOUS, DETECTION_RESULT_SUSPICIOUS,
                INVESTIGATION_RESULT, "CASE-001"
            )
        assert result["score_is_fallback"] is True

    def test_recommendations_are_consultive_not_operational(self):
        from app.agents import agent_risk_analyzer
        with patch("app.agents.agent_risk_analyzer.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("LLM down")
            result = agent_risk_analyzer.run(
                TX_SUSPICIOUS, DETECTION_RESULT_SUSPICIOUS,
                INVESTIGATION_RESULT, "CASE-001"
            )
        recs = result.get("recommendations", [])
        assert len(recs) > 0
        # Nenhuma recomendação deve mencionar bloqueio/cancelamento
        for r in recs:
            desc = r.get("description", "").lower()
            assert "bloquear" not in desc or "preventivo" in desc or "nível" in desc

    def test_high_criteria_gives_high_score(self):
        from app.agents import agent_risk_analyzer
        detection_6 = {
            **DETECTION_RESULT_SUSPICIOUS,
            "total_criteria_met": 6,
            "criteria_flags": {k: True for k in DETECTION_RESULT_SUSPICIOUS["criteria_flags"]},
        }
        with patch("app.agents.agent_risk_analyzer.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("LLM down")
            result = agent_risk_analyzer.run(
                TX_SUSPICIOUS, detection_6, INVESTIGATION_RESULT, "CASE-001"
            )
        assert result["risk_score"] >= 60


# ══════════════════════════════════════════════════════════════════════════════
# 6. Agente 4 — Master / Relatório
# ══════════════════════════════════════════════════════════════════════════════

class TestAgent4Master:
    def _risk_result(self, score: int = 72, level: str = "alto") -> dict:
        return {
            "transaction_id": "TEST-S01",
            "case_id": "CASE-001",
            "risk_score": score,
            "risk_dimensions": {
                "severity_level": level,
                "severity_justification": "Múltiplos critérios.",
                "priority_level": "alta",
                "priority_justification": "Urgência definida pelo score.",
                "confidence_score": 0.78,
                "confidence_justification": "Dados suficientes.",
            },
            "recommendations": [{"action_code": "encaminhar_nivel2", "description": "Encaminhar para Nível 2.", "proportional": True}],
            "information_gaps": [],
            "score_is_fallback": False,
            "critical_evidence": [],
            "refutation_points": [],
        }

    def test_produces_executive_report(self):
        from app.agents import agent_master
        with patch("app.agents.agent_master.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("LLM down")
            result = agent_master.run(
                TX_SUSPICIOUS, DETECTION_RESULT_SUSPICIOUS,
                INVESTIGATION_RESULT, self._risk_result(),
                "CASE-001", "TRACE-001"
            )
        assert "executive_report" in result
        report = result["executive_report"]
        assert "full_narrative" in report
        assert "risk_justification" in report

    def test_status_requires_human_review_for_high_risk(self):
        from app.agents import agent_master
        with patch("app.agents.agent_master.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("LLM down")
            result = agent_master.run(
                TX_SUSPICIOUS, DETECTION_RESULT_SUSPICIOUS,
                INVESTIGATION_RESULT, self._risk_result(72, "alto"),
                "CASE-001", "TRACE-001"
            )
        assert result["processing_status"] == "REQUIRES_HUMAN_REVIEW"

    def test_disclaimer_always_present(self):
        from app.agents import agent_master
        with patch("app.agents.agent_master.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("LLM down")
            result = agent_master.run(
                TX_SUSPICIOUS, DETECTION_RESULT_SUSPICIOUS,
                INVESTIGATION_RESULT, self._risk_result(),
                "CASE-001", "TRACE-001"
            )
        assert "disclaimer" in result
        assert "NÃO executa" in result["disclaimer"]

    def test_pipeline_errors_propagated(self):
        from app.agents import agent_master
        with patch("app.agents.agent_master.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("LLM down")
            result = agent_master.run(
                TX_SUSPICIOUS, DETECTION_RESULT_SUSPICIOUS,
                INVESTIGATION_RESULT, self._risk_result(),
                "CASE-001", "TRACE-001",
                pipeline_errors=["Agente2: timeout"]
            )
        assert "pipeline_errors" in result


# ══════════════════════════════════════════════════════════════════════════════
# 7. Orquestrador
# ══════════════════════════════════════════════════════════════════════════════

class TestOrchestrator:
    def setup_method(self):
        from app.agents.agent_rule_screener import clear_dedup_cache
        clear_dedup_cache()

    def test_normal_transaction_does_not_escalate(self):
        from app.orchestrator import analyze_transaction
        with patch("app.agents.agent_rule_screener.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("LLM down")
            result = analyze_transaction(TX_NORMAL)
        assert result["escalated"] is False
        assert result["agent_2_investigation"] is None
        assert result["agent_3_risk"] is None
        assert result["agent_4_master"] is None

    def test_suspicious_transaction_escalates_all_agents(self):
        from app.orchestrator import analyze_transaction
        tx = {**TX_SUSPICIOUS, "transaction_id": "ORCH-TEST-01"}
        with patch("app.agents.agent_rule_screener.gemini_client") as mock_gc1, \
             patch("app.agents.agent_context_analyst.gemini_client") as mock_gc2, \
             patch("app.agents.agent_risk_analyzer.gemini_client") as mock_gc3, \
             patch("app.agents.agent_master.gemini_client") as mock_gc4:
            for mock in (mock_gc1, mock_gc2, mock_gc3, mock_gc4):
                mock.generate_json.side_effect = Exception("LLM down")
            result = analyze_transaction(tx)
        assert result["escalated"] is True
        assert result["agent_2_investigation"] is not None
        assert result["agent_3_risk"] is not None
        assert result["agent_4_master"] is not None

    def test_result_has_case_id_and_trace_id(self):
        from app.orchestrator import analyze_transaction
        tx = {**TX_SUSPICIOUS, "transaction_id": "ORCH-TEST-02"}
        with patch("app.agents.agent_rule_screener.gemini_client") as mock_gc1, \
             patch("app.agents.agent_context_analyst.gemini_client") as mock_gc2, \
             patch("app.agents.agent_risk_analyzer.gemini_client") as mock_gc3, \
             patch("app.agents.agent_master.gemini_client") as mock_gc4:
            for mock in (mock_gc1, mock_gc2, mock_gc3, mock_gc4):
                mock.generate_json.side_effect = Exception("LLM down")
            result = analyze_transaction(tx)
        assert "case_id" in result
        assert "trace_id" in result
        assert result["case_id"] != result["trace_id"]

    def test_agent_failure_does_not_abort_pipeline(self):
        """Um agente falhando não deve impedir os agentes seguintes."""
        from app.orchestrator import analyze_transaction
        tx = {**TX_SUSPICIOUS, "transaction_id": "ORCH-TEST-03"}
        with patch("app.agents.agent_rule_screener.gemini_client") as mock_gc1, \
             patch("app.agents.agent_context_analyst.gemini_client") as mock_gc2, \
             patch("app.agents.agent_risk_analyzer.gemini_client") as mock_gc3, \
             patch("app.agents.agent_master.gemini_client") as mock_gc4:
            mock_gc1.generate_json.side_effect = Exception("LLM down")
            mock_gc2.generate_json.side_effect = Exception("LLM down")
            mock_gc3.generate_json.side_effect = Exception("LLM down")
            mock_gc4.generate_json.side_effect = Exception("LLM down")
            # Não deve levantar exceção
            result = analyze_transaction(tx)
        assert result is not None
        assert "agent_4_master" in result


# ══════════════════════════════════════════════════════════════════════════════
# 8. Case Storage
# ══════════════════════════════════════════════════════════════════════════════

class TestCaseStorage:
    def test_save_and_load_case(self, tmp_path):
        from app import case_storage
        original = case_storage._CASES_DIR
        case_storage._CASES_DIR = tmp_path
        try:
            payload = {
                "case_id": "TC-001",
                "trace_id": "trace-abc",
                "transaction_id": "T-001",
                "agent_4_master": {
                    "processing_status": "COMPLETED",
                    "final_risk_score": 45,
                    "final_risk_level": "medio",
                },
            }
            case_storage.save_case("TC-001", payload)
            loaded = case_storage.load_case("TC-001")
            assert loaded is not None
            assert loaded["case_id"] == "TC-001"
            assert "_saved_at" in loaded
        finally:
            case_storage._CASES_DIR = original

    def test_list_cases_includes_trace_id(self, tmp_path):
        from app import case_storage
        original = case_storage._CASES_DIR
        case_storage._CASES_DIR = tmp_path
        try:
            case_storage.save_case("TC-002", {
                "case_id": "TC-002",
                "trace_id": "trace-xyz",
                "transaction_id": "T-002",
                "agent_4_master": {"processing_status": "COMPLETED", "final_risk_score": 20},
            })
            cases = case_storage.list_cases()
            assert any(c["trace_id"] == "trace-xyz" for c in cases)
        finally:
            case_storage._CASES_DIR = original

    def test_load_nonexistent_returns_none(self, tmp_path):
        from app import case_storage
        original = case_storage._CASES_DIR
        case_storage._CASES_DIR = tmp_path
        try:
            assert case_storage.load_case("NAO-EXISTE") is None
        finally:
            case_storage._CASES_DIR = original


# ══════════════════════════════════════════════════════════════════════════════
# 9. Schemas — validação Pydantic
# ══════════════════════════════════════════════════════════════════════════════

class TestSchemas:
    def test_transaction_in_validates_positive_amount(self):
        from app.models.schemas import TransactionIn
        with pytest.raises(Exception):
            TransactionIn(
                transaction_id="T-BAD",
                customer_id="C-001",
                amount=-100.0,
                datetime="2024-01-01T10:00:00",
                location="SP",
                channel="app",
                device="phone",
            )

    def test_risk_level_enum_values(self):
        from app.models.schemas import RiskLevel
        assert RiskLevel.BAIXO == "baixo"
        assert RiskLevel.CRITICO == "critico"

    def test_processing_status_enum_values(self):
        from app.models.schemas import ProcessingStatus
        assert ProcessingStatus.ANALYZING == "ANALYZING"
        assert ProcessingStatus.REQUIRES_HUMAN_REVIEW == "REQUIRES_HUMAN_REVIEW"


# ══════════════════════════════════════════════════════════════════════════════
# 10. Dataset e Simulador
# ══════════════════════════════════════════════════════════════════════════════

class TestDatasetAndSimulator:
    REQUIRED = ["transaction_id", "customer_id", "amount", "datetime", "location", "channel", "device"]

    def test_dataset_loads(self):
        from app.orchestrator import get_all_transactions
        txs = get_all_transactions()
        assert len(txs) > 0

    def test_dataset_has_required_fields(self):
        from app.orchestrator import get_all_transactions
        for tx in get_all_transactions():
            for field in self.REQUIRED:
                assert field in tx

    def test_dataset_has_normal_and_suspicious(self):
        from app.orchestrator import get_all_transactions
        labels = [t.get("label") for t in get_all_transactions()]
        assert "normal" in labels
        assert "suspeita" in labels

    def test_simulator_required_fields(self):
        from app.simulator import generate_single
        tx = generate_single()
        for field in self.REQUIRED:
            assert field in tx

    def test_simulator_force_suspicious(self):
        from app.simulator import generate_single
        tx = generate_single(force_suspicious=True)
        assert tx.get("simulation_profile") != "normal"

    def test_simulator_stream_count(self):
        from app.simulator import generate_stream
        txs = list(generate_stream(total=10))
        assert len(txs) == 10


# ══════════════════════════════════════════════════════════════════════════════
# 11. Executor de Ações e Fluxo de Aprovação Humana
# ══════════════════════════════════════════════════════════════════════════════

class TestActionExecutor:
    def test_execute_action_returns_executed_or_failed(self):
        from app.action_executor import execute_action
        result = execute_action(
            action_id="ACT-TEST01",
            action_code="bloquear_conta_temporariamente",
            case_id="CASE-001",
            customer_id="CLI-001",
            decided_by="analista_teste",
        )
        assert result["status"] in ("EXECUTED", "FAILED")
        assert result["simulated"] is True
        assert result["action_id"] == "ACT-TEST01"
        assert result["decided_by"] == "analista_teste"
        assert result["execution_note"] is not None

    def test_reject_action_returns_rejected(self):
        from app.action_executor import reject_action
        result = reject_action(
            action_id="ACT-TEST02",
            action_code="monitorar",
            case_id="CASE-001",
            decided_by="analista_teste",
            justification="Risco considerado aceitável.",
        )
        assert result["status"] == "REJECTED"
        assert result["executed_at"] is None
        assert "Risco considerado aceitável." in result["execution_note"]

    def test_reject_without_justification(self):
        from app.action_executor import reject_action
        result = reject_action(
            action_id="ACT-TEST03",
            action_code="monitorar",
            case_id="CASE-001",
            decided_by="analista_teste",
            justification=None,
        )
        assert result["status"] == "REJECTED"

    def test_unknown_action_code_uses_default_response(self):
        from app.action_executor import execute_action
        result = execute_action(
            action_id="ACT-TEST04",
            action_code="acao_inexistente_xyz",
            case_id="CASE-001",
            customer_id="CLI-001",
            decided_by="analista_teste",
        )
        assert result["status"] in ("EXECUTED", "FAILED")
        assert result["execution_note"] is not None


class TestActionStorage:
    def test_save_and_list_action_results(self, tmp_path):
        from app import case_storage
        original = case_storage._CASES_DIR
        case_storage._CASES_DIR = tmp_path
        try:
            result = {
                "action_id": "ACT-001",
                "case_id": "CASE-001",
                "action_code": "bloquear_conta_temporariamente",
                "status": "EXECUTED",
                "decided_by": "analista_teste",
                "decided_at": "2024-01-01T10:00:00",
                "executed_at": "2024-01-01T10:00:01",
                "execution_note": "Conta bloqueada. Ref: BLQ-001.",
                "simulated": True,
            }
            case_storage.save_action_result("CASE-001", result)
            actions = case_storage.list_action_results("CASE-001")
            assert len(actions) == 1
            assert actions[0]["action_id"] == "ACT-001"
            assert actions[0]["status"] == "EXECUTED"
            assert "_recorded_at" in actions[0]
        finally:
            case_storage._CASES_DIR = original

    def test_list_actions_empty_when_none(self, tmp_path):
        from app import case_storage
        original = case_storage._CASES_DIR
        case_storage._CASES_DIR = tmp_path
        try:
            actions = case_storage.list_action_results("CASE-NAO-EXISTE")
            assert actions == []
        finally:
            case_storage._CASES_DIR = original

    def test_multiple_actions_appended(self, tmp_path):
        from app import case_storage
        original = case_storage._CASES_DIR
        case_storage._CASES_DIR = tmp_path
        try:
            for i in range(3):
                case_storage.save_action_result("CASE-MULTI", {
                    "action_id": f"ACT-{i:03d}",
                    "case_id": "CASE-MULTI",
                    "action_code": "monitorar",
                    "status": "EXECUTED",
                    "decided_by": "analista",
                    "decided_at": "2024-01-01T10:00:00",
                })
            actions = case_storage.list_action_results("CASE-MULTI")
            assert len(actions) == 3
        finally:
            case_storage._CASES_DIR = original

    def test_list_cases_ignores_action_files(self, tmp_path):
        from app import case_storage
        original = case_storage._CASES_DIR
        case_storage._CASES_DIR = tmp_path
        try:
            # Salva um caso e uma ação
            case_storage.save_case("CASE-X", {
                "case_id": "CASE-X",
                "trace_id": "trace-x",
                "transaction_id": "TX-X",
                "agent_4_master": {"processing_status": "COMPLETED", "final_risk_score": 30},
            })
            case_storage.save_action_result("CASE-X", {
                "action_id": "ACT-X",
                "case_id": "CASE-X",
                "action_code": "monitorar",
                "status": "EXECUTED",
                "decided_by": "analista",
                "decided_at": "2024-01-01T10:00:00",
            })
            cases = case_storage.list_cases()
            # Arquivo _actions.json não deve aparecer como caso
            assert all(c["case_id"] != "CASE-X_actions" for c in cases)
            assert len(cases) == 1
        finally:
            case_storage._CASES_DIR = original


class TestAgent4SuggestedActions:
    """Verifica que o Agente 4 gera suggested_actions estruturadas."""

    def _risk_result_with_recs(self):
        return {
            "transaction_id": "TEST-S01",
            "case_id": "CASE-001",
            "risk_score": 72,
            "risk_dimensions": {
                "severity_level": "alto",
                "severity_justification": "Múltiplos critérios.",
                "priority_level": "alta",
                "priority_justification": "Urgência alta.",
                "confidence_score": 0.78,
                "confidence_justification": "Dados suficientes.",
            },
            "recommendations": [
                {"action_code": "solicitar_2fa_e_revisar", "description": "Solicitar 2FA.", "proportional": True},
                {"action_code": "encaminhar_nivel2", "description": "Encaminhar Nível 2.", "proportional": True},
            ],
            "information_gaps": [],
            "score_is_fallback": False,
            "critical_evidence": [],
            "refutation_points": [],
        }

    def test_suggested_actions_present(self):
        from app.agents import agent_master
        with patch("app.agents.agent_master.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("LLM down")
            result = agent_master.run(
                TX_SUSPICIOUS, DETECTION_RESULT_SUSPICIOUS,
                INVESTIGATION_RESULT, self._risk_result_with_recs(),
                "CASE-001", "TRACE-001"
            )
        assert "suggested_actions" in result
        assert len(result["suggested_actions"]) >= 1

    def test_each_action_has_action_id(self):
        from app.agents import agent_master
        with patch("app.agents.agent_master.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("LLM down")
            result = agent_master.run(
                TX_SUSPICIOUS, DETECTION_RESULT_SUSPICIOUS,
                INVESTIGATION_RESULT, self._risk_result_with_recs(),
                "CASE-001", "TRACE-001"
            )
        for action in result["suggested_actions"]:
            assert "action_id" in action
            assert action["action_id"].startswith("ACT-")
            assert action["status"] == "PENDING"

    def test_fallback_generates_at_least_one_action(self):
        from app.agents import agent_master
        risk_no_recs = {**self._risk_result_with_recs(), "recommendations": []}
        with patch("app.agents.agent_master.gemini_client") as mock_gc:
            mock_gc.generate_json.side_effect = Exception("LLM down")
            result = agent_master.run(
                TX_SUSPICIOUS, DETECTION_RESULT_SUSPICIOUS,
                INVESTIGATION_RESULT, risk_no_recs,
                "CASE-001", "TRACE-001"
            )
        assert len(result["suggested_actions"]) >= 1
