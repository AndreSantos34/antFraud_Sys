"""
Agente 1 — Análise de Risco (Risk Analyzer)
─────────────────────────────────────────────
Responsabilidade: analisar a transação recebida aplicando os 6 critérios de
suspeita. A transação só é escalada se atingir NO MÍNIMO 3 critérios completos.

Modelo: gemini-1.5-flash
Perfil: temperatura 0.1 — respostas determinísticas para triagem consistente.
"""
import json
import logging
from typing import Any

from app.core.gemini_client import gemini_client
from app.core.config import get_settings

logger = logging.getLogger(__name__)

CRITERIA = [
    "valor_elevado",
    "horario_incomum",
    "frequencia_elevada",
    "valor_repetido",
    "mudanca_geografica",
    "dispositivo_desconhecido",
]

_SYSTEM_PROMPT = """Você é um sistema especializado em triagem inicial de transações financeiras.
Analise a transação e verifique cada um dos 6 critérios abaixo de forma independente.
Um critério está COMPLETO quando há evidência clara e direta nos dados fornecidos.

CRITÉRIOS:
1. valor_elevado       → valor acima de R$ {threshold}
2. horario_incomum     → horário entre {hour_start}h e {hour_end}h (madrugada/noite)
3. frequencia_elevada  → histórico mostra mais de {freq_max} transações em {freq_min} minutos
4. valor_repetido      → mesmo valor exato em 2 ou mais transações recentes do cliente
5. mudanca_geografica  → localização incompatível com histórico (ex: outro país ou estado distante)
6. dispositivo_desconhecido → campo device contém "desconhecido"

REGRA DE ESCALADA: a transação só é SUSPEITA se 3 ou mais critérios estiverem completos.
Com menos de 3 critérios → classificação NORMAL (fluxo regular do banco).

Retorne um objeto JSON com exatamente esta estrutura:
{{
  "transaction_id": "<id>",
  "criteria_evaluation": {{
    "valor_elevado": true,
    "horario_incomum": false,
    "frequencia_elevada": false,
    "valor_repetido": false,
    "mudanca_geografica": false,
    "dispositivo_desconhecido": true
  }},
  "total_criteria_met": 2,
  "escalate_to_investigation": false,
  "classification": "normal",
  "confidence": 0.95,
  "justification": "Explicação objetiva dos critérios encontrados."
}}"""


def run(transaction: dict[str, Any], customer_history: list[dict] | None = None) -> dict:
    """
    Executa o Agente 1 — Análise de Risco.

    Returns:
        Dicionário com criteria_evaluation, total_criteria_met,
        escalate_to_investigation, classification, confidence e justification.
    """
    settings = get_settings()
    history = customer_history or []

    system = _SYSTEM_PROMPT.format(
        threshold=settings.high_value_threshold,
        hour_start=settings.unusual_hour_start,
        hour_end=settings.unusual_hour_end,
        freq_max=settings.high_freq_max_tx,
        freq_min=settings.high_freq_window_min,
    )

    tx_json = json.dumps(transaction, ensure_ascii=False, indent=2)
    hist_json = json.dumps(history[-5:], ensure_ascii=False, indent=2)
    user_msg = (
        f"TRANSAÇÃO:\n{tx_json}\n\n"
        f"HISTÓRICO RECENTE DO CLIENTE:\n{hist_json}\n\n"
        f"Avalie cada critério e retorne o JSON."
    )

    logger.info("[Agente1] Analisando risco de %s", transaction.get("transaction_id"))

    try:
        result = gemini_client.generate_json(
            model_id=settings.gemini_model_agent1,
            system_prompt=system,
            user_message=user_msg,
            temperature=0.1,
            max_output_tokens=512,
        )
    except Exception as exc:
        logger.warning("[Agente1] Erro na chamada Gemini: %s", exc)
        result = {
            "transaction_id": transaction.get("transaction_id"),
            "criteria_evaluation": {c: False for c in CRITERIA},
            "total_criteria_met": 0,
            "escalate_to_investigation": False,
            "classification": "normal",
            "confidence": 0.0,
            "justification": f"Erro ao processar: {exc}",
        }

    # Garante consistência: escala somente se >= 3 critérios
    total = result.get("total_criteria_met", 0)
    if isinstance(total, int):
        result["escalate_to_investigation"] = total >= 3
        result["classification"] = "suspeita" if total >= 3 else "normal"

    return result
