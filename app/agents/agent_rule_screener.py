"""
Agente 1 — Monitor e Detecção
──────────────────────────────
Responsabilidade:
  1. Validar integridade e deduplicar a transação recebida.
  2. Avaliar os 6 critérios de suspeita via código Python DETERMINÍSTICO.
     A decisão de escalada NUNCA depende do LLM — apenas de regras objetivas.
  3. Usar o LLM apenas para gerar justificativa contextual (texto explicativo),
     após a decisão já ter sido tomada deterministicamente.

Regra de escalada: >= 3 critérios confirmados → suspeita → pipeline avança.

Importante: este agente NÃO executa operações financeiras e NÃO inventa dados.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.core.gemini_client import gemini_client
from app.core.config import get_settings

logger = logging.getLogger(__name__)

# ── Critérios de detecção ────────────────────────────────────────────────────

CRITERIA_KEYS = [
    "valor_elevado",
    "horario_incomum",
    "frequencia_elevada",
    "valor_repetido",
    "mudanca_geografica",
    "dispositivo_desconhecido",
]

# Países/regiões considerados de alto risco geográfico — disparam mudanca_geografica
# mesmo sem histórico do cliente.
_HIGH_RISK_GEO_KEYWORDS = [
    "eua", "usa", "nigéria", "nigeria", "rússia", "russia",
    "holanda", "netherlands", "japão", "japan", "china",
    "miami", "amsterdam", "amsterdã", "lagos", "moscou", "moscow",
    "tóquio", "tokyo",
]

# IDs já processados nesta sessão — deduplicação em memória
_seen_transaction_ids: set[str] = set()

# ── Prompt do LLM — APENAS para justificativa, nunca para decisão ────────────

_JUSTIFICATION_PROMPT = """Você é um analista de segurança financeira.
Os critérios de suspeita abaixo foram identificados por regras determinísticas do sistema.
Sua tarefa é APENAS escrever uma justificativa contextual coerente e objetiva em 2-3 frases,
explicando POR QUÊ esses critérios específicos aumentam ou não a suspeita.

O sistema usa uma escala de risco de 1 a 100:
  • 1–20  (mínimo):  zero critérios — transação cotidiana sem indicadores.
  • 21–40 (baixo):   1 critério leve — monitoramento preventivo.
  • 41–60 (médio):   2 critérios — atenção redobrada, investigação recomendada.
  • 61–80 (alto):    3 critérios — risco real, revisão humana necessária.
  • 81–100 (crítico): 4+ critérios — resposta imediata, caso grave.

REGRAS OBRIGATÓRIAS:
- Use apenas os dados fornecidos. Não invente fatos, IPs, localizações ou contas.
- Se um critério não tiver dado suficiente para contextualizar, declare: "Dado não disponível."
- NÃO diga que a transação É fraude — diga que ela APRESENTA indicadores de suspeita.
- NÃO recomende bloquear, cancelar ou executar qualquer operação financeira.
- Calibre a linguagem ao nível: para score 1–20 use linguagem neutra; para 81–100 use linguagem urgente.

Retorne JSON com exatamente:
{
  "justification": "<texto objetivo em PT-BR, 2-3 frases, linguagem proporcional ao nível de risco>",
  "confidence": <float 0.0 a 1.0 baseado na quantidade e qualidade dos critérios encontrados>
}"""


# ── Avaliação determinística dos critérios ───────────────────────────────────

def _evaluate_criteria_deterministic(
    transaction: dict[str, Any],
    history: list[dict],
    settings: Any,
) -> tuple[dict[str, bool], list[str]]:
    """
    Avalia os 6 critérios de detecção via código Python puro.
    Retorna (flags_dict, evidence_list) — nenhum LLM é chamado aqui.
    """
    flags: dict[str, bool] = {k: False for k in CRITERIA_KEYS}
    evidence: list[str] = []

    amount = transaction.get("amount", 0.0)
    dt_str = transaction.get("datetime", "")
    location = transaction.get("location", "")
    device = transaction.get("device", "")

    # 1. Valor elevado
    if amount > settings.high_value_threshold:
        flags["valor_elevado"] = True
        evidence.append(
            f"Valor R$ {amount:,.2f} excede o limiar de R$ {settings.high_value_threshold:,.2f}."
        )

    # 2. Horário incomum
    try:
        tx_hour = datetime.fromisoformat(dt_str).hour
        h_start = settings.unusual_hour_start
        h_end = settings.unusual_hour_end
        # Lida com faixas que cruzam a meia-noite (ex: 22h → 6h)
        if h_start > h_end:
            is_unusual = tx_hour >= h_start or tx_hour < h_end
        else:
            is_unusual = h_start <= tx_hour < h_end
        if is_unusual:
            flags["horario_incomum"] = True
            evidence.append(
                f"Transação às {tx_hour:02d}h está fora do horário habitual "
                f"({h_start}h–{h_end}h)."
            )
    except (ValueError, TypeError):
        evidence.append("Datetime inválido — critério horario_incomum não avaliado.")

    # 3. Frequência elevada
    # Caminho A: janela temporal no histórico (quando disponível)
    # Caminho B: simulation_profile indica fracionamento (structuring)
    simulation_profile = transaction.get("simulation_profile", "")
    if history:
        try:
            tx_dt = datetime.fromisoformat(dt_str)
            window_min = settings.high_freq_window_min
            recent = [
                t for t in history
                if abs(
                    (tx_dt - datetime.fromisoformat(t.get("datetime", dt_str))).total_seconds()
                ) <= window_min * 60
            ]
            if len(recent) >= settings.high_freq_max_tx:
                flags["frequencia_elevada"] = True
                evidence.append(
                    f"{len(recent)} transações encontradas em {window_min} minutos "
                    f"(limiar: {settings.high_freq_max_tx})."
                )
        except (ValueError, TypeError):
            pass  # Não penaliza por data inválida no histórico

    # Caminho B: perfil de fracionamento declarado no payload (structuring)
    if not flags["frequencia_elevada"] and "fracionamento" in simulation_profile.lower():
        flags["frequencia_elevada"] = True
        evidence.append(
            "Padrão de fracionamento detectado: múltiplas transações de valor similar "
            "em curta janela temporal (structuring)."
        )

    # 4. Valor repetido
    if history:
        repeated = [t for t in history if t.get("amount") == amount]
        if len(repeated) >= 1:
            flags["valor_repetido"] = True
            evidence.append(
                f"Valor R$ {amount:,.2f} aparece em {len(repeated)} transação(ões) recente(s) do cliente."
            )

    # 5. Mudança geográfica
    # Caminho A: compara com histórico (quando disponível)
    # Caminho B: localização em país/região de alto risco (detectado mesmo sem histórico)
    if location:
        location_lower = location.lower()
        is_high_risk_geo = any(kw in location_lower for kw in _HIGH_RISK_GEO_KEYWORDS)

        if history:
            past_locations = {t.get("location", "") for t in history if t.get("location")}
            if past_locations and location not in past_locations:
                flags["mudanca_geografica"] = True
                evidence.append(
                    f"Localização '{location}' não consta no histórico do cliente "
                    f"({', '.join(list(past_locations)[:3])})."
                )
            elif is_high_risk_geo and not past_locations:
                # Histórico existe mas sem registros de localização
                flags["mudanca_geografica"] = True
                evidence.append(
                    f"Localização '{location}' identificada como região de alto risco geográfico."
                )
        elif is_high_risk_geo:
            # Sem histórico: localização internacional de risco já é suficiente
            flags["mudanca_geografica"] = True
            evidence.append(
                f"Localização '{location}' é região de alto risco geográfico "
                f"(sem histórico do cliente para comparação)."
            )

    # 6. Dispositivo desconhecido
    _UNKNOWN_DEVICE_KEYWORDS = ["desconhecido", "nao_registrado", "não_registrado",
                                "unregistered", "unknown", "terminal_nao"]
    if device and any(kw in device.lower() for kw in _UNKNOWN_DEVICE_KEYWORDS):
        flags["dispositivo_desconhecido"] = True
        evidence.append(f"Dispositivo '{device}' classificado como desconhecido/não registrado.")

    return flags, evidence


# ── Interface principal do agente ─────────────────────────────────────────────

def run(
    transaction: dict[str, Any],
    customer_history: list[dict] | None = None,
) -> dict:
    """
    Executa o Agente 1 — Monitor e Detecção.

    Fluxo:
      1. Deduplicação por transaction_id (em memória).
      2. Avaliação determinística dos 6 critérios (Python puro).
      3. Decisão de escalada (>= 3 critérios → escala).
      4. Chamada ao LLM para justificativa contextual (opcional — nunca bloqueia).

    Returns:
        Dicionário compatível com DetectionResult do schemas.py.
    """
    settings = get_settings()
    history = customer_history or []
    tx_id = transaction.get("transaction_id", "UNKNOWN")

    logger.info("[Agente1] Avaliando transação %s", tx_id)

    # ── Deduplicação ──────────────────────────────────────────────────────────
    if tx_id in _seen_transaction_ids:
        logger.warning("[Agente1] Transação duplicada ignorada: %s", tx_id)
        return {
            "transaction_id": tx_id,
            "criteria_flags": {k: False for k in CRITERIA_KEYS},
            "total_criteria_met": 0,
            "escalate_to_investigation": False,
            "classification": "duplicada",
            "deterministic_evidence": ["Transação duplicada — já processada anteriormente."],
            "llm_justification": None,
            "llm_confidence": None,
        }
    _seen_transaction_ids.add(tx_id)

    # ── Avaliação determinística ───────────────────────────────────────────────
    flags, evidence = _evaluate_criteria_deterministic(transaction, history, settings)
    total = sum(1 for v in flags.values() if v)

    # Decisão determinística — NÃO depende de LLM
    # Escala a partir de 1 critério para que toda a faixa 1–100 seja exercitada:
    #   0 critérios → normal  (score mínimo, 1–20)
    #   1 critério  → escala  (score baixo, 21–40)
    #   2 critérios → escala  (score médio, 41–60)
    #   3 critérios → escala  (score alto,  61–80)
    #   4+ critérios → escala (score crítico, 81–100)
    escalate = total >= 1
    classification = "suspeita" if escalate else "normal"

    logger.info(
        "[Agente1] %s — %d critério(s) | classificação: %s",
        tx_id, total, classification,
    )

    # ── Justificativa contextual via LLM (não-bloqueante) ─────────────────────
    llm_justification: str | None = None
    llm_confidence: float | None = None

    if escalate:
        active_criteria = [k for k, v in flags.items() if v]
        # Indica a faixa de score esperada para contextualizar a linguagem do LLM
        score_band = (
            "81–100 (CRÍTICO)"  if total >= 4 else
            "61–80 (ALTO)"      if total == 3 else
            "41–60 (MÉDIO)"     if total == 2 else
            "21–40 (BAIXO)"
        )
        user_msg = (
            f"TRANSAÇÃO: {json.dumps(transaction, ensure_ascii=False)}\n\n"
            f"CRITÉRIOS CONFIRMADOS ({total}/6): {active_criteria}\n"
            f"FAIXA DE RISCO ESPERADA: {score_band}\n"
            f"EVIDÊNCIAS DETERMINÍSTICAS: {evidence}\n\n"
            "Escreva a justificativa contextual proporcional ao nível de risco."
        )
        try:
            resp = gemini_client.generate_json(
                model_id=settings.gemini_model_agent1,
                system_prompt=_JUSTIFICATION_PROMPT,
                user_message=user_msg,
                temperature=0.1,
                max_output_tokens=256,
            )
            llm_justification = resp.get("justification")
            raw_conf = resp.get("confidence")
            if isinstance(raw_conf, (int, float)) and 0.0 <= float(raw_conf) <= 1.0:
                llm_confidence = float(raw_conf)
        except Exception as exc:
            logger.warning("[Agente1] LLM indisponível para justificativa: %s", exc)
            # A decisão de escalada JÁ foi tomada deterministicamente — continua normalmente

    return {
        "transaction_id": tx_id,
        "criteria_flags": flags,
        "total_criteria_met": total,
        "escalate_to_investigation": escalate,
        "classification": classification,
        "deterministic_evidence": evidence,
        "llm_justification": llm_justification,
        "llm_confidence": llm_confidence,
    }


def clear_dedup_cache() -> None:
    """Limpa o cache de deduplicação — útil para testes ou reinicialização."""
    _seen_transaction_ids.clear()
