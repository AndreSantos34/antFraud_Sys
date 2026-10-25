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
#
# Calibração — mapeamento esperado de critérios para banda de risco:
#   3 critérios (limiar de escalada) → ~46–50  → médio   (41–60)
#   4 critérios                      → ~63–68  → alto    (61–80)
#   5 critérios                      → ~81–87  → crítico (81–100)
#   6 critérios                      → ~100    → crítico máximo
#
# Pesos escolhidos de forma que a combinação canônica de critérios por nível
# de risco caia na faixa correta, sem depender de bonuses para atingir "alto".
_CRITERIA_WEIGHTS = {
    "valor_elevado":            16,  # +16
    "horario_incomum":          14,  # +14  — madrugada aumenta risco real
    "frequencia_elevada":       20,  # +20  — maior peso: indica bot/automação
    "valor_repetido":           14,  # +14  — smurfing / structuring
    "mudanca_geografica":       19,  # +19  — mudança física quase impossível em minutos
    "dispositivo_desconhecido": 17,  # +17  — comprometimento de conta
}
# Soma máxima dos 6 critérios = 100 → cabo natural sem precisar de cap agressivo.

_RECEIVER_SUSPICIOUS_BONUS = 8   # destinatário em outros eventos suspeitos
_HIGH_DEVIATION_BONUS      = 6   # desvio comportamental calculado pelo Agente 2 > 0.7

# ── Bônus por magnitude do valor ─────────────────────────────────────────────
# Aplicado SOMENTE quando valor_elevado já foi ativado.
# Captura casos como TXN-016 (R$47k) e TXN-017 (R$38k) que precisam de pontos extras.
_VALUE_MAGNITUDE_TIERS = [
    (50_000.0,  8),  # > R$50k  → +8
    (20_000.0,  6),  # > R$20k  → +6
    (10_000.0,  3),  # > R$10k  → +3
    ( 5_000.0,  0),  # > limiar → +0 (peso base já contabilizado)
]

# ── Ajuste LLM (Agente 3) — contribuição contextual calibrada ─────────────────
# O LLM pode sugerir um ajuste de score após ver o contexto completo da investigação.
# Limites: -10 (mitigante forte) a +12 (agravante forte).
# Qualquer valor fora dessa faixa é descartado (proteção contra LLM alucinando scores altos).
_LLM_SCORE_ADJ_MIN = -10
_LLM_SCORE_ADJ_MAX = 12

# Ações proibidas por nível de risco — garante proporcionalidade.
# O LLM pode sugerir action_codes incorretos; esta lista barra os mais drásticos
# para níveis não compatíveis, evitando inconsistências na Auditoria.
_FORBIDDEN_ACTIONS_BY_LEVEL: dict[str, set[str]] = {
    "minimo": {"congelar_conta_e_escalar_soc", "forcar_reautenticacao_e_investigar",
               "ativar_monitoramento_intensivo"},
    "baixo":  {"congelar_conta_e_escalar_soc", "forcar_reautenticacao_e_investigar"},
    "medio":  {"congelar_conta_e_escalar_soc"},
    # alto e critico: sem restrições — ações drásticas são proporcionais
    "alto":   set(),
    "critico": set(),
}

# ── Mapeamento score → níveis ─────────────────────────────────────────────────

def _score_to_levels(score: int) -> tuple[str, str, str, str]:
    """
    Retorna (risk_level, urgency, action_code, priority_label).

    Escala 1–100 com 5 bandas — action_codes usam linguagem operacional SOC:
      81–100 → crítico  → congelar_conta_e_escalar_soc
      61–80  → alto     → forcar_reautenticacao_e_investigar
      41–60  → médio    → ativar_monitoramento_intensivo
      21–40  → baixo    → registrar_e_vigiar
       1–20  → mínimo   → arquivar_sem_acao
    """
    if score >= 81:
        return "critico", "maxima",  "congelar_conta_e_escalar_soc",        "CRÍTICA"
    if score >= 61:
        return "alto",    "alta",    "forcar_reautenticacao_e_investigar",   "ALTA"
    if score >= 41:
        return "medio",   "media",   "ativar_monitoramento_intensivo",       "MÉDIA"
    if score >= 21:
        return "baixo",   "baixa",   "registrar_e_vigiar",                   "BAIXA"
    return     "minimo",  "baixa",   "arquivar_sem_acao",                    "INFORMATIVA"


# ── Prompt do LLM ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """Você é um especialista em avaliação de risco financeiro.
Os scores BASE foram calculados deterministicamente pelo sistema em uma escala de 1 a 100.
Sua missão é enriquecer essa avaliação com contexto qualitativo e propor um ajuste de score.

ESCALA DE RISCO (1–100):
  • Score  1–20  → nível MÍNIMO:   zero critérios confirmados; transação rotineira sem indicadores.
                   Ação: registrar e arquivar. Sem necessidade de intervenção.
  • Score 21–40  → nível BAIXO:    1 critério leve ativado; possível anomalia isolada.
                   Ação: monitoramento preventivo; sem urgência operacional.
  • Score 41–60  → nível MÉDIO:    2 critérios combinados; atenção redobrada.
                   Ação: investigação recomendada; monitoramento intensivo.
  • Score 61–80  → nível ALTO:     3 critérios confirmados; risco real de fraude.
                   Ação: solicitar 2FA e encaminhar para revisão humana.
  • Score 81–100 → nível CRÍTICO:  4+ critérios; padrão grave de comprometimento.
                   Ação: encaminhamento imediato para analista de Nível 2.

Suas tarefas:
1. Justificar as três dimensões de risco (Gravidade, Prioridade, Confiança) com linguagem
   PROPORCIONAL ao nível: neutra para scores 1–40, escalando para urgente em 81–100.
2. Classificar as evidências: críticas, de suporte, fracas e pontos de refutação.
3. Sugerir um ajuste de score contextual (`score_adjustment`): inteiro de -10 a +12.
   - Use valores POSITIVOS apenas para agravantes reais: múltiplos critérios críticos,
     padrão de comprometimento de conta, histórico suspeito, valor muito acima do limiar.
   - Use valores NEGATIVOS para mitigantes: contexto explica comportamento, histórico limpo.
   - Use 0 se o contexto não acrescenta nem subtrai risco.
   - NUNCA sugira ajuste > +12 ou < -10 — valores fora desse intervalo serão ignorados.
4. Gerar recomendações operacionais PROPORCIONAIS ao nível de risco, usando os action_codes abaixo.

ACTION_CODES VÁLIDOS (use EXATAMENTE estes valores):
  • "congelar_conta_e_escalar_soc"       → score 81–100: congelar sessão e conta; escalar para SOC Nível 2
  • "forcar_reautenticacao_e_investigar" → score 61–80:  forçar MFA; abrir investigação no SIEM
  • "ativar_monitoramento_intensivo"     → score 41–60:  monitoramento 72h; correlacionar no SIEM
  • "registrar_e_vigiar"                 → score 21–40:  log de auditoria; fila de vigilância 24h
  • "arquivar_sem_acao"                  → score 1–20:   arquivar para estatística; sem ação operacional

REGRAS OBRIGATÓRIAS:
- Use apenas os dados fornecidos. Não invente fatos.
- Use SOMENTE os action_codes da lista acima — nunca invente novos códigos.
- Calibre a urgência da linguagem ao score: scores 1–40 = tom informativo; 81–100 = tom urgente.
- Sinalize "Dado não disponível" para ausência de informação.

Retorne JSON com exatamente:
{
  "score_adjustment": <inteiro -10 a +12>,
  "score_adjustment_reason": "<1 frase explicando o ajuste, PT-BR>",
  "severity_justification": "<por que o impacto potencial é X no nível atual, PT-BR>",
  "priority_justification": "<por que a urgência operacional é X no nível atual, PT-BR>",
  "confidence_justification": "<por que a confiança nas evidências é X, PT-BR>",
  "critical_evidence": ["<evidência de alta relevância>"],
  "supporting_evidence": ["<evidência de suporte>"],
  "weak_evidence": ["<evidência fraca>"],
  "refutation_points": ["<argumento que enfraquece a suspeita>"],
  "recommendations": [
    {"action_code": "<um dos 5 códigos acima>", "description": "<descrição operacional concisa em PT-BR>", "proportional": true}
  ],
  "information_gaps": ["<lacuna de dado que limita a análise>"]
}"""


# ── Score determinístico ──────────────────────────────────────────────────────

def _compute_risk_score(
    criteria_flags: dict[str, bool],
    investigation_result: dict,
    transaction: dict,
) -> tuple[int, list[str]]:
    """
    Calcula o score de risco base (0–100) deterministicamente.
    Retorna (score_base, score_breakdown_notes).

    O score FINAL (com ajuste LLM) é calculado em run() após a chamada ao Gemini.
    """
    score = 0
    notes: list[str] = []

    for criterion, weight in _CRITERIA_WEIGHTS.items():
        if criteria_flags.get(criterion):
            score += weight
            notes.append(f"+{weight} {criterion}")

    # Bônus por magnitude do valor (aplicado somente quando valor_elevado ativo)
    if criteria_flags.get("valor_elevado"):
        amount = transaction.get("amount", 0.0)
        for threshold, bonus in _VALUE_MAGNITUDE_TIERS:
            if amount > threshold and bonus > 0:
                score += bonus
                notes.append(f"+{bonus} magnitude_valor (R${amount:,.0f} > R${threshold:,.0f})")
                break  # aplica apenas o tier mais alto

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

    Score final = score_base (determinístico) + llm_adjustment (contextual, -10 a +12).
    O LLM participa da calibração final, mas não pode alterar o score sozinho.

    Returns:
        Dicionário compatível com RiskAssessmentResult do schemas.py.
    """
    settings = get_settings()
    tx_id = transaction.get("transaction_id", "UNKNOWN")
    criteria_flags = detection_result.get("criteria_flags", {})

    logger.info("[Agente3] Avaliando risco de %s", tx_id)

    # ── Score base determinístico ─────────────────────────────────────────────
    risk_score_base, score_notes = _compute_risk_score(criteria_flags, investigation_result, transaction)
    total_criteria = detection_result.get("total_criteria_met", 0)

    logger.info("[Agente3] %s — score_base: %d | critérios: %d/6", tx_id, risk_score_base, total_criteria)

    # Confiança determinística baseada na qualidade dos dados disponíveis
    has_history = bool(investigation_result.get("sender_profile", {}).get("typical_amount_range"))
    data_status = investigation_result.get("data_collection_status", "insuficiente")
    base_confidence = total_criteria / 6.0
    if data_status == "completo":
        base_confidence = min(base_confidence + 0.15, 1.0)
    elif data_status == "insuficiente":
        base_confidence = max(base_confidence - 0.15, 0.0)
    confidence_score = round(base_confidence, 2)

    # ── LLM para ajuste contextual + justificativas + recomendações ──────────
    llm_adjustment = 0
    llm_adjustment_reason: str | None = None
    severity_just = (
        f"Score base {risk_score_base}/100 com {total_criteria} critério(s) confirmado(s). "
        f"Impacto potencial calculado deterministicamente."
    )
    priority_just = ""
    confidence_just = (
        f"Confiança de {confidence_score:.0%} baseada em {total_criteria} critério(s) "
        f"e qualidade dos dados ({data_status})."
    )
    critical_ev: list[str] = []
    supporting_ev: list[str] = []
    weak_ev: list[str] = []
    refutation: list[str] = []
    recommendations: list[dict] = []
    information_gaps: list[str] = []
    score_is_fallback = False

    user_msg = (
        f"TRANSAÇÃO: {json.dumps(transaction, ensure_ascii=False)}\n\n"
        f"SCORE BASE (determinístico): {risk_score_base}/100\n"
        f"DETALHAMENTO: {score_notes}\n"
        f"TOTAL DE CRITÉRIOS: {total_criteria}/6\n"
        f"CRITÉRIOS CONFIRMADOS: {[k for k, v in criteria_flags.items() if v]}\n\n"
        f"INVESTIGAÇÃO (Agente 2):\n{json.dumps(investigation_result, ensure_ascii=False)}\n\n"
        "Avalie o contexto completo, sugira o ajuste de score e justifique as dimensões de risco."
    )

    try:
        resp = gemini_client.generate_json(
            model_id=settings.gemini_model_agent3,
            system_prompt=_SYSTEM_PROMPT,
            user_message=user_msg,
            temperature=0.2,
            max_output_tokens=1200,
        )

        # ── Ajuste de score contextual do LLM ────────────────────────────────
        raw_adj = resp.get("score_adjustment", 0)
        if isinstance(raw_adj, (int, float)):
            llm_adjustment = int(max(_LLM_SCORE_ADJ_MIN, min(_LLM_SCORE_ADJ_MAX, raw_adj)))
            llm_adjustment_reason = resp.get("score_adjustment_reason")
            if llm_adjustment != 0:
                logger.info(
                    "[Agente3] LLM sugeriu ajuste de score: %+d ('%s')",
                    llm_adjustment, llm_adjustment_reason,
                )
                score_notes.append(
                    f"{llm_adjustment:+d} ajuste_contextual_LLM "
                    f"({llm_adjustment_reason or 'sem razão fornecida'})"
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
        # Calcular nível preliminar para validar action_codes antes de ter o score final
        prelim_score = max(0, min(100, risk_score_base + llm_adjustment))
        prelim_level, prelim_urgency, prelim_action, _ = _score_to_levels(prelim_score)
        forbidden = _FORBIDDEN_ACTIONS_BY_LEVEL.get(prelim_level, set())
        recommendations = []
        for r in raw_recs:
            if not isinstance(r, dict):
                continue
            code = r.get("action_code", prelim_action)
            if code in forbidden:
                logger.warning(
                    "[Agente3] LLM sugeriu action_code proibido '%s' para nível '%s' — substituído por '%s'",
                    code, prelim_level, prelim_action,
                )
                code = prelim_action
            recommendations.append({
                "action_code":  code,
                "description":  r.get("description", "Revisão humana recomendada."),
                "proportional": bool(r.get("proportional", True)),
            })

    except Exception as exc:
        logger.warning("[Agente3] LLM indisponível: %s", exc)
        score_is_fallback = True

    # ── Score final = base + ajuste LLM (clampado 0–100) ─────────────────────
    risk_score = max(0, min(100, risk_score_base + llm_adjustment))
    risk_level, urgency, action_code, priority_label = _score_to_levels(risk_score)

    if not priority_just:
        priority_just = f"Urgência definida como '{urgency}' com base no score final {risk_score}/100."

    logger.info(
        "[Agente3] %s — score_final: %d (base=%d, adj=%+d) | nível: %s",
        tx_id, risk_score, risk_score_base, llm_adjustment, risk_level,
    )

    if score_is_fallback:
        # Fallback determinístico para recomendações
        recommendations = [{
            "action_code": action_code,
            "description": _default_recommendation(risk_level),
            "proportional": True,
        }]
        information_gaps = ["LLM indisponível — justificativas e ajuste gerados automaticamente."]
        if not has_history:
            information_gaps.append("Histórico do cliente não disponível para comparação.")

    return {
        "transaction_id": tx_id,
        "case_id": case_id,
        "risk_score": risk_score,
        "risk_score_base": risk_score_base,
        "risk_score_llm_adjustment": llm_adjustment,
        "risk_score_llm_adjustment_reason": llm_adjustment_reason,
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
    """Recomendação padrão operacional proporcional ao nível de risco."""
    mapping = {
        "critico": "Congelar sessão ativa e conta do cliente; escalar imediatamente para SOC Nível 2; iniciar protocolo de resposta a incidente.",
        "alto":    "Forçar reautenticação completa (MFA); suspender transações pendentes; abrir investigação formal no SIEM.",
        "medio":   "Ativar monitoramento intensivo por 72h; correlacionar com eventos recentes no SIEM; alertar analista de plantão.",
        "baixo":   "Registrar evento no log de auditoria; incluir cliente em fila de vigilância preventiva por 24h.",
        "minimo":  "Arquivar para análise estatística — nenhuma ação operacional necessária.",
    }
    return mapping.get(risk_level, "Escalar para análise SOC.")
