"""
Agente 1 — Análise de Risco (Risk Analyzer)
─────────────────────────────────────────────
Responsabilidade: analisar a transação recebida aplicando os 6 critérios de
suspeita definidos no documento. A transação só é escalada para investigação
aprofundada se atingir NO MÍNIMO 3 critérios completos simultaneamente.
Com menos de 3 critérios → fluxo normal de autorização do banco.

Modelo: ibm/granite-13b-instruct-v2
Perfil: temperatura baixa para máxima consistência e determinismo na triagem.
"""
import json
import logging
from typing import Any

from app.core.watsonx_client import watsonx_client
from app.core.config import get_settings

logger = logging.getLogger(__name__)

MODEL_ID = "ibm/granite-13b-instruct-v2"
PARAMETERS = {
    "decoding_method": "greedy",
    "max_new_tokens": 400,
    "temperature": 0.1,
    "repetition_penalty": 1.1,
}

# Critérios disponíveis para avaliação
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

Responda APENAS com JSON válido:
{{
  "transaction_id": "<id>",
  "criteria_evaluation": {{
    "valor_elevado": true | false,
    "horario_incomum": true | false,
    "frequencia_elevada": true | false,
    "valor_repetido": true | false,
    "mudanca_geografica": true | false,
    "dispositivo_desconhecido": true | false
  }},
  "total_criteria_met": <número 0-6>,
  "escalate_to_investigation": true | false,
  "classification": "normal" | "suspeita",
  "confidence": <0.0 a 1.0>,
  "justification": "<explicação objetiva dos critérios encontrados>"
}}"""


def _build_prompt(transaction: dict[str, Any], customer_history: list[dict]) -> str:
    settings = get_settings()
    system = _SYSTEM_PROMPT.format(
        threshold=settings.high_value_threshold,
        hour_start=settings.unusual_hour_start,
        hour_end=settings.unusual_hour_end,
        freq_max=settings.high_freq_max_tx,
        freq_min=settings.high_freq_window_min,
    )
    tx_json = json.dumps(transaction, ensure_ascii=False, indent=2)
    hist_json = json.dumps(customer_history[-5:], ensure_ascii=False, indent=2)
    return (
        f"{system}\n\n"
        f"TRANSAÇÃO:\n{tx_json}\n\n"
        f"HISTÓRICO RECENTE DO CLIENTE:\n{hist_json}\n\n"
        f"Avalie cada critério e responda com o JSON:"
    )


def run(transaction: dict[str, Any], customer_history: list[dict] | None = None) -> dict:
    """
    Executa o Agente 1 — Análise de Risco.

    Returns:
        Dicionário com criteria_evaluation, total_criteria_met,
        escalate_to_investigation, classification, confidence e justification.
    """
    history = customer_history or []
    prompt = _build_prompt(transaction, history)

    logger.info("[Agente1] Analisando risco de %s", transaction.get("transaction_id"))
    raw = watsonx_client.generate(MODEL_ID, prompt, PARAMETERS)

    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        result = json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning("[Agente1] Falha ao parsear JSON: %s | raw: %s", exc, raw)
        result = {
            "transaction_id": transaction.get("transaction_id"),
            "criteria_evaluation": {c: False for c in CRITERIA},
            "total_criteria_met": 0,
            "escalate_to_investigation": False,
            "classification": "normal",
            "confidence": 0.0,
            "justification": f"Erro ao processar resposta do modelo: {raw[:200]}",
        }

    # Garante consistência: escala somente se >= 3 critérios
    total = result.get("total_criteria_met", 0)
    if isinstance(total, int):
        result["escalate_to_investigation"] = total >= 3
        result["classification"] = "suspeita" if total >= 3 else "normal"

    return result
