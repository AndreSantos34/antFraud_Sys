"""
Agente 4 — Explicabilidade, Relatório e Orquestração (Master)
───────────────────────────────────────────────────────────────
Responsabilidade:
  1. Receber os resultados dos Agentes 1, 2 e 3 já processados.
  2. Gerar o relatório executivo final para o analista SOC em PT-BR, com:
       - Fatos Observados (dados reais do payload e histórico)
       - Hipóteses da IA (inferências do LLM, marcadas como tal)
       - Limitações / Gaps (dados ausentes que afetam a análise)
       - Justificativa do Risco (raciocínio de síntese final)
  3. Produzir o alerta de cibersegurança com ações imediatas consultivas.
  4. Determinar o ProcessingStatus final do caso.

O Agente 4 NÃO recalcula scores — usa os dados dos agentes anteriores.
NÃO executa operações financeiras. Recomendações são estritamente consultivas.
"""
import json
import logging
import uuid
from datetime import datetime
from typing import Any

from app.core.gemini_client import gemini_client
from app.core.config import get_settings

logger = logging.getLogger(__name__)

# ── Prompt do LLM ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """Você é o analista-chefe de um sistema de prevenção de fraudes financeiras.
Todos os dados já foram processados pelos agentes anteriores. Sua missão é:

1. Escrever o RELATÓRIO EXECUTIVO completo para o analista SOC, separando:
   a) FATOS OBSERVADOS: apenas dados reais do payload e histórico
   b) HIPÓTESES DA IA: inferências e interpretações do modelo, sempre marcadas como hipóteses
   c) LIMITAÇÕES: dados ausentes, lacunas que afetam a análise
   d) JUSTIFICATIVA DO RISCO: raciocínio integrado de todos os agentes

2. Escrever a NARRATIVA COMPLETA (3-5 parágrafos em PT-BR) para o analista SOC.

3. Definir as AÇÕES IMEDIATAS consultivas — NUNCA operacionais.

REGRAS CRÍTICAS:
- Use APENAS dados já existentes nos resultados fornecidos.
- NUNCA invente transações, IPs, localizações, contas ou históricos.
- NUNCA recomende bloquear, cancelar, aprovar ou executar operações financeiras.
- Ações válidas: "Encaminhar para revisão humana de Nível 2",
  "Solicitar confirmação do cliente via canal seguro",
  "Acionar protocolo SOC de monitoramento intensivo", etc.
- Hipóteses devem ser identificadas com frases como "A IA infere que...",
  "É possível que...", "Os dados sugerem que..." — nunca como fatos.

Retorne JSON com exatamente:
{
  "observed_facts": ["<fato real extraído dos dados>"],
  "ai_hypotheses": ["<hipótese do modelo, identificada como tal>"],
  "limitations": ["<limitação ou dado ausente>"],
  "risk_justification": "<raciocínio integrado em 2-3 frases>",
  "full_narrative": "<relatório completo em PT-BR, 3-5 parágrafos>",
  "alert_subject": "<assunto do alerta para cibersegurança>",
  "alert_message": "<mensagem urgente em 1-2 parágrafos>",
  "immediate_actions": ["<ação consultiva proporcional>"]
}"""


# ── Determinação do ProcessingStatus ─────────────────────────────────────────

def _determine_status(risk_level: str, score_is_fallback: bool, pipeline_errors: list[str]) -> str:
    """Determina o status final do processamento do caso."""
    if pipeline_errors and len(pipeline_errors) >= 2:
        return "REQUIRES_HUMAN_REVIEW"
    if score_is_fallback or pipeline_errors:
        return "REQUIRES_HUMAN_REVIEW"
    if risk_level in ("alto", "critico"):
        return "REQUIRES_HUMAN_REVIEW"
    return "COMPLETED"


# ── Interface principal do agente ─────────────────────────────────────────────

def run(
    transaction: dict[str, Any],
    detection_result: dict[str, Any],
    investigation_result: dict[str, Any],
    risk_result: dict[str, Any],
    case_id: str,
    trace_id: str,
    pipeline_errors: list[str] | None = None,
) -> dict:
    """
    Executa o Agente 4 — Explicabilidade, Relatório e Orquestração.

    Returns:
        Dicionário compatível com MasterResult do schemas.py.
    """
    settings = get_settings()
    tx_id = transaction.get("transaction_id", "UNKNOWN")
    errors = pipeline_errors or []
    now = datetime.now().isoformat()

    # Dados do Agente 3
    risk_score      = risk_result.get("risk_score", 0)
    risk_dims       = risk_result.get("risk_dimensions", {})
    risk_level      = risk_dims.get("severity_level", "baixo")
    urgency         = risk_dims.get("priority_level", "baixa")
    score_is_fallback = bool(risk_result.get("score_is_fallback", False))
    recommendations = risk_result.get("recommendations", [])
    primary_action  = recommendations[0]["action_code"] if recommendations else "revisao_humana"

    logger.info("[Agente4] Sintetizando caso %s | score=%d | nível=%s", tx_id, risk_score, risk_level)

    # ── LLM para relatório executivo ──────────────────────────────────────────
    observed_facts:    list[str] = []
    ai_hypotheses:     list[str] = []
    limitations:       list[str] = []
    risk_justification = f"Transação {tx_id} apresenta score {risk_score}/100 nível {risk_level}."
    full_narrative     = risk_justification
    alert_subject      = f"⚠️ ALERTA DE SUSPEITA — {risk_level.upper()} — {tx_id}"
    alert_message      = f"Transação {tx_id} apresenta indicadores de suspeita. Score: {risk_score}/100."
    immediate_actions: list[str] = [r["description"] for r in recommendations]
    llm_report_ok = True

    # Ações estruturadas com action_id — para o fluxo de aprovação humana
    # Geradas a partir das recomendações do Agente 3 (determinísticas)
    suggested_actions: list[dict] = [
        {
            "action_id":    f"ACT-{str(uuid.uuid4())[:8].upper()}",
            "action_code":  r.get("action_code", "revisao_humana"),
            "description":  r.get("description", "Revisão humana necessária."),
            "risk_level":   risk_level,
            "proportional": r.get("proportional", True),
            "status":       "PENDING",
        }
        for r in recommendations
    ]
    # Garante ao menos uma ação sugerida mesmo sem recomendações do Agente 3
    if not suggested_actions:
        suggested_actions = [{
            "action_id":    f"ACT-{str(uuid.uuid4())[:8].upper()}",
            "action_code":  primary_action,
            "description":  "Encaminhar caso para revisão humana de Nível 2.",
            "risk_level":   risk_level,
            "proportional": True,
            "status":       "PENDING",
        }]

    user_msg = (
        f"TIMESTAMP: {now}\n\n"
        f"TRANSAÇÃO:\n{json.dumps(transaction, ensure_ascii=False)}\n\n"
        f"DETECÇÃO (Agente 1):\n"
        f"  Critérios: {detection_result.get('total_criteria_met', 0)}/6 | "
        f"  Classificação: {detection_result.get('classification', '?')}\n"
        f"  Evidências: {detection_result.get('deterministic_evidence', [])}\n"
        f"  Justificativa LLM: {detection_result.get('llm_justification', 'Não disponível')}\n\n"
        f"INVESTIGAÇÃO (Agente 2):\n"
        f"  Resumo: {investigation_result.get('investigation_summary', '')}\n"
        f"  Indicadores cruzados: {investigation_result.get('crossed_indicators', [])}\n"
        f"  Correlações: {investigation_result.get('correlated_events', [])}\n"
        f"  Status coleta: {investigation_result.get('data_collection_status', '')}\n"
        f"  Dados ausentes: {investigation_result.get('missing_data', [])}\n\n"
        f"RISCO (Agente 3):\n"
        f"  Score: {risk_score}/100 | Nível: {risk_level} | Urgência: {urgency}\n"
        f"  Gravidade: {risk_dims.get('severity_justification', '')}\n"
        f"  Prioridade: {risk_dims.get('priority_justification', '')}\n"
        f"  Confiança: {risk_dims.get('confidence_score', 0):.0%} — {risk_dims.get('confidence_justification', '')}\n"
        f"  Evidências críticas: {risk_result.get('critical_evidence', [])}\n"
        f"  Refutações: {risk_result.get('refutation_points', [])}\n"
        f"  Recomendações: {[r['description'] for r in recommendations]}\n"
        f"  Gaps: {risk_result.get('information_gaps', [])}\n\n"
        f"ERROS NO PIPELINE: {errors}\n\n"
        "Gere o relatório executivo final."
    )

    try:
        resp = gemini_client.generate_json(
            model_id=settings.gemini_model_agent4,
            system_prompt=_SYSTEM_PROMPT,
            user_message=user_msg,
            temperature=0.3,
            max_output_tokens=1500,
        )
        observed_facts     = resp.get("observed_facts", [])
        ai_hypotheses      = resp.get("ai_hypotheses", [])
        limitations        = resp.get("limitations", [])
        risk_justification = resp.get("risk_justification", risk_justification)
        full_narrative     = resp.get("full_narrative", full_narrative)
        alert_subject      = resp.get("alert_subject", alert_subject)
        alert_message      = resp.get("alert_message", alert_message)
        llm_actions = resp.get("immediate_actions", [])
        if llm_actions:
            immediate_actions = llm_actions
            # Enriquece as descrições das ações estruturadas com o texto do LLM
            for i, action in enumerate(suggested_actions):
                if i < len(llm_actions):
                    action["description"] = llm_actions[i]
    except Exception as exc:
        logger.warning("[Agente4] LLM indisponível para relatório: %s", exc)
        llm_report_ok = False
        errors.append(f"Agente4-LLM: {exc}")
        # Fallback determinístico: compila fatos a partir dos dados existentes
        observed_facts = detection_result.get("deterministic_evidence", [])
        limitations = risk_result.get("information_gaps", [])
        if not llm_report_ok:
            limitations.append("LLM indisponível — relatório executivo gerado automaticamente.")
        full_narrative = (
            f"ATENÇÃO: Transação {tx_id} foi escalada com {detection_result.get('total_criteria_met', 0)} "
            f"critério(s) de suspeita. Score de risco calculado deterministicamente: {risk_score}/100 "
            f"({risk_level}). Relatório narrativo indisponível — LLM fora de serviço. "
            f"Revisão humana recomendada."
        )

    status = _determine_status(risk_level, score_is_fallback, errors)

    return {
        "transaction_id": tx_id,
        "case_id": case_id,
        "trace_id": trace_id,
        "processing_status": status,
        "final_risk_score": risk_score,
        "final_risk_level": risk_level,
        "urgency": urgency,
        "recommended_action": primary_action,
        "executive_report": {
            "observed_facts":    observed_facts,
            "ai_hypotheses":     ai_hypotheses,
            "limitations":       limitations,
            "risk_justification": risk_justification,
            "full_narrative":    full_narrative,
        },
        "alert_subject":     alert_subject,
        "alert_message":     alert_message,
        "immediate_actions": immediate_actions,
        # Lista estruturada de ações aguardando aprovação humana
        # Cada item tem action_id único para o frontend usar em approve/reject
        "suggested_actions": suggested_actions,
        "pipeline_stages_completed": _stages_completed(detection_result, investigation_result, risk_result),
        "pipeline_errors":  errors,
        "completed_at":     now,
        "disclaimer": (
            "Sistema acadêmico de apoio à triagem. "
            "Decisão final sob responsabilidade humana. "
            "Este sistema NÃO executa operações financeiras."
        ),
    }


def _stages_completed(detection: dict, investigation: dict, risk: dict) -> list[str]:
    stages = ["agent_1_detection"]
    if investigation:
        stages.append("agent_2_investigation")
    if risk:
        stages.append("agent_3_risk_assessment")
    return stages
