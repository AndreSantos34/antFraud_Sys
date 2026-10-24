"""
Agente 3 — Avaliação de Risco e Recomendação
──────────────────────────────────────────────
Responsabilidade:
  1. Calcular o score de risco (0–100) via fórmula determinística Python.
  2. Classificar o risco em três dimensões separadas e obrigatórias:
       - Gravidade: impacto potencial caso seja fraude confirmada.
       - Prioridade: urgência de atenção humana agora.
       - Confiança: solidez das evidências que sustentam a conclusão.
  3. Classificar evidências por relevância: críticas, de suporte, fracas.
  4. Usar o LLM para gerar recomendações consultivas e justificativas em PT-BR.

Recomendações são ESTRITAMENTE consultivas — jamais operacionais.
O agente NÃO aprova, recusa, bloqueia ou executa operações financeiras.
"""
import json
import logging
from typing import Any

from app.core.gemini_client import gemini_client
from app.core.config import get_settings

logger = logging.getLogger(__name__)

# ── Tabela de pesos para o score determinístico ──────────────────────────────

_CRITERIA_WEIGHTS = {
    "valor_elevado":            15,
    "horario_incomum":          12,
    "frequencia_elevada":       18,  # maior peso — indica automação/bot
    "valor_repetido":           13,
    "mudanca_geografica":       17,  # alto peso — mudança física improvável
    "dispositivo_desconhecido": 15,
}

_RECEIVER_SUSPICIOUS_BONUS = 10
_HIGH_DEVIATION_BONUS      = 8   # desvio comportamental > 0.7

# ── Mapeamento score → níveis ─────────────────────────────────────────────────

def _score_to_levels(score: int) -> tuple[str, str, str, str]:
    """Retorna (risk_level, urgency, action_code, priority_label)."""
    if score >= 81:
        return "critico", "maxima",  "encaminhar_nivel2_imediato",  "CRÍTICA"
    if score >= 61:
        return "alto",    "alta",    "solicitar_2fa_e_revisar",     "ALTA"
    if score >= 41:
        return "medio",   "media",   "monitorar_intensivamente",    "MÉDIA"
    if score >= 21:
        return "baixo",   "baixa",   "monitorar",                   "BAIXA"
    return "minimo",   "baixa",   "registrar_e_arquivar",        "INFORMATIVA"


# ── Prompt do LLM ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """Você é um especialista em avaliação de risco financeiro.
Os scores e classificações JÁ FORAM calculados deterministicamente pelo sistema.
Sua tarefa é:
1. Justificar as três dimensões de risco (Gravidade, Prioridade, Confiança) com base nos dados.
2. Classificar as evidências: críticas, de suporte, fracas e pontos de refutação.
3. Gerar recomendações consultivas e proporcionais — NUNCA operacionais.

REGRAS OBRIGATÓRIAS:
- Use apenas os dados fornecidos. Não invente fatos.
- NUNCA recomende bloquear, cancelar, aprovar ou executar operações financeiras.
- Recomendações válidas: "Solicitar autenticação adicional (2FA)", "Encaminhar para análise Nível 2",
  "Manter em monitoramento intensivo", "Aguardar confirmação do cliente", etc.
- Sinalize "Dado não disponível" para ausência de informação.

Retorne JSON com exatamente:
{
  "severity_justification": "<por que o impacto potencial é X, PT-BR>",
  "priority_justification": "<por que a urgência operacional é X, PT-BR>",
  "confidence_justification": "<por que a confiança nas evidências é X, PT-BR>",
  "critical_evidence": ["<evidência de alta relevância>"],
  "supporting_evidence": ["<evidência de suporte>"],
  "weak_evidence": ["<evidência fraca>"],
  "refutation_points": ["<argumento que enfraquece a suspeita>"],
  "recommendations": [
    {"action_code": "<código>", "description": "<texto consultivo em PT-BR>", "proportional": true}
  ],
  "information_gaps": ["<lacuna de dado que limita a análise>"]
}"""


# ── Score determinístico ──────────────────────────────────────────────────────

def _compute_risk_score(
    criteria_flags: dict[str, bool],
    investigation_result: dict,
) -> tuple[int, list[str]]:
    """
    Calcula o score de risco (0–100) deterministicamente.
    Retorna (score, score_breakdown_notes).
    """
    score = 0
    notes: list[str] = []

    for criterion, weight in _CRITERIA_WEIGHTS.items():
        if criteria_flags.get(criterion):
            score += weight
            notes.append(f"+{weight} {criterion}")

    # Bônus por destinatário suspeito
    receiver_profile = investigation_result.get("receiver_profile", {})
    if receiver_profile.get("appears_in_other_suspicious"):
        score += _RECEIVER_SUSPICIOUS_BONUS
        notes.append(f"+{_RECEIVER_SUSPICIOUS_BONUS} destinatário_em_outros_suspeitos")

    # Bônus por desvio comportamental elevado
    sender_profile = investigation_result.get("sender_profile", {})
    dev_score = sender_profile.get("behavioral_deviation_score") or 0
    if dev_score > 0.7:
        score += _HIGH_DEVIATION_BONUS
        notes.append(f"+{_HIGH_DEVIATION_BONUS} desvio_comportamental_elevado ({dev_score:.2f})")

    return min(score, 100), notes


# ── Interface principal do agente ─────────────────────────────────────────────

def run(
    transaction: dict[str, Any],
    detection_result: dict[str, Any],
    investigation_result: dict[str, Any],
    case_id: str,
) -> dict:
    """
    Executa o Agente 3 — Avaliação de Risco e Recomendação.

    Returns:
        Dicionário compatível com RiskAssessmentResult do schemas.py.
    """
    settings = get_settings()
    tx_id = transaction.get("transaction_id", "UNKNOWN")
    criteria_flags = detection_result.get("criteria_flags", {})

    logger.info("[Agente3] Avaliando risco de %s", tx_id)

    # ── Score determinístico ──────────────────────────────────────────────────
    risk_score, score_notes = _compute_risk_score(criteria_flags, investigation_result)
    total_criteria = detection_result.get("total_criteria_met", 0)
    risk_level, urgency, action_code, priority_label = _score_to_levels(risk_score)

    logger.info("[Agente3] %s — score: %d | nível: %s", tx_id, risk_score, risk_level)

    # Confiança determinística baseada na qualidade dos dados disponíveis
    has_history = bool(investigation_result.get("sender_profile", {}).get("typical_amount_range"))
    data_status = investigation_result.get("data_collection_status", "insuficiente")
    base_confidence = total_criteria / 6.0
    if data_status == "completo":
        base_confidence = min(base_confidence + 0.15, 1.0)
    elif data_status == "insuficiente":
        base_confidence = max(base_confidence - 0.15, 0.0)
    confidence_score = round(base_confidence, 2)

    # ── LLM para justificativas e recomendações ───────────────────────────────
    # Valores padrão (fallback caso LLM falhe)
    severity_just = (
        f"Score {risk_score}/100 com {total_criteria} critério(s) confirmado(s). "
        f"Impacto potencial calculado deterministicamente."
    )
    priority_just = f"Urgência definida como '{urgency}' com base no score."
    confidence_just = f"Confiança de {confidence_score:.0%} baseada em {total_criteria} critério(s) e qualidade dos dados ({data_status})."
    critical_ev: list[str] = []
    supporting_ev: list[str] = []
    weak_ev: list[str] = []
    refutation: list[str] = []
    recommendations: list[dict] = []
    information_gaps: list[str] = []
    score_is_fallback = False

    user_msg = (
        f"TRANSAÇÃO: {json.dumps(transaction, ensure_ascii=False)}\n\n"
        f"SCORE DE RISCO: {risk_score}/100 (calculado deterministicamente)\n"
        f"NÍVEL: {risk_level} | URGÊNCIA: {urgency}\n"
        f"TOTAL DE CRITÉRIOS: {total_criteria}/6\n"
        f"CRITÉRIOS CONFIRMADOS: {[k for k, v in criteria_flags.items() if v]}\n"
        f"DETALHAMENTO DO SCORE: {score_notes}\n\n"
        f"INVESTIGAÇÃO (Agente 2):\n{json.dumps(investigation_result, ensure_ascii=False)}\n\n"
        "Justifique as dimensões de risco e forneça recomendações consultivas."
    )

    try:
        resp = gemini_client.generate_json(
            model_id=settings.gemini_model_agent3,
            system_prompt=_SYSTEM_PROMPT,
            user_message=user_msg,
            temperature=0.2,
            max_output_tokens=1024,
        )
        severity_just   = resp.get("severity_justification", severity_just)
        priority_just   = resp.get("priority_justification", priority_just)
        confidence_just = resp.get("confidence_justification", confidence_just)
        critical_ev     = resp.get("critical_evidence", [])
        supporting_ev   = resp.get("supporting_evidence", [])
        weak_ev         = resp.get("weak_evidence", [])
        refutation      = resp.get("refutation_points", [])
        information_gaps = resp.get("information_gaps", [])

        raw_recs = resp.get("recommendations", [])
        recommendations = [
            {
                "action_code":  r.get("action_code", action_code),
                "description":  r.get("description", "Revisão humana recomendada."),
                "proportional": bool(r.get("proportional", True)),
            }
            for r in raw_recs
            if isinstance(r, dict)
        ]
    except Exception as exc:
        logger.warning("[Agente3] LLM indisponível: %s", exc)
        score_is_fallback = True
        # Fallback determinístico para recomendações
        recommendations = [
            {
                "action_code": action_code,
                "description": _default_recommendation(risk_level),
                "proportional": True,
            }
        ]
        information_gaps = ["LLM indisponível — justificativas geradas automaticamente."]
        if not has_history:
            information_gaps.append("Histórico do cliente não disponível para comparação.")

    return {
        "transaction_id": tx_id,
        "case_id": case_id,
        "risk_score": risk_score,
        "risk_dimensions": {
            "severity_level": risk_level,
            "severity_justification": severity_just,
            "priority_level": urgency,
            "priority_justification": priority_just,
            "confidence_score": confidence_score,
            "confidence_justification": confidence_just,
        },
        "critical_evidence": critical_ev,
        "supporting_evidence": supporting_ev,
        "weak_evidence": weak_ev,
        "refutation_points": refutation,
        "recommendations": recommendations,
        "information_gaps": information_gaps,
        "score_is_fallback": score_is_fallback,
        "score_notes": score_notes,
    }


def _default_recommendation(risk_level: str) -> str:
    """Recomendação padrão proporcional ao nível de risco."""
    mapping = {
        "critico": "Encaminhar imediatamente para análise humana de Nível 2.",
        "alto":    "Solicitar autenticação adicional (2FA) e revisar manualmente.",
        "medio":   "Manter em monitoramento intensivo e verificar histórico do cliente.",
        "baixo":   "Monitorar e registrar o evento para análise futura.",
        "minimo":  "Registrar e arquivar — nenhuma ação imediata necessária.",
    }
    return mapping.get(risk_level, "Revisão humana recomendada.")
