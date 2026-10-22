"""
Agente 2 — Investigação de Ameaças (Threat Investigator)
──────────────────────────────────────────────────────────
Responsabilidade: coletar e estruturar todos os dados disponíveis tanto da
conta remetente quanto da conta destinatária, cruzar com o histórico de
transações e identificar padrões de comportamento anômalo.

Só é acionado quando o Agente 1 detectar >= 3 critérios (escalate_to_investigation=True).

Modelo: ibm/granite-20b-multilingual
Perfil: temperatura média — análise investigativa que combina objetividade
        com capacidade de raciocínio sobre padrões de comportamento.
"""
import json
import logging
from typing import Any

from app.core.watsonx_client import watsonx_client

logger = logging.getLogger(__name__)

MODEL_ID = "ibm/granite-20b-multilingual"
PARAMETERS = {
    "decoding_method": "sample",
    "max_new_tokens": 600,
    "temperature": 0.4,
    "top_p": 0.9,
    "repetition_penalty": 1.05,
}

_SYSTEM_PROMPT = """Você é um investigador especializado em ameaças financeiras.
Uma transação foi escalada para investigação porque atingiu 3 ou mais critérios de suspeita.

Sua tarefa é coletar e estruturar todos os dados disponíveis para montar o dossiê do caso:

1. PERFIL DO REMETENTE: analise o histórico de transações, padrão de valores, horários
   habituais, localizações frequentes e dispositivos utilizados.

2. PERFIL DO DESTINATÁRIO: identifique quem recebe a transação, se há padrão de
   recebimento suspeito, se o destinatário aparece em outras transações anômalas.

3. PADRÕES DE COMPORTAMENTO: compare a transação atual com o histórico para identificar
   desvios — mudanças abruptas de comportamento, valores fora do padrão, horários atípicos.

4. INDICADORES CRUZADOS: quais critérios se reforçam mutuamente (ex: dispositivo
   desconhecido + horário de madrugada + localização internacional = padrão crítico).

Retorne APENAS um JSON válido:
{{
  "transaction_id": "<id>",
  "sender_profile": {{
    "customer_id": "<id do remetente>",
    "typical_transaction_range": "<faixa de valores habitual>",
    "typical_hours": "<horários habituais>",
    "typical_locations": ["<local1>", ...],
    "known_devices": ["<dispositivo1>", ...],
    "transaction_frequency": "<frequência habitual>",
    "behavioral_deviation_score": <0.0 a 1.0>,
    "anomalies_found": ["<anomalia1>", ...]
  }},
  "receiver_profile": {{
    "receiver_id": "<id ou referência do destinatário se disponível>",
    "appears_in_other_suspicious": true | false,
    "receiver_notes": "<observações sobre o destinatário>"
  }},
  "crossed_indicators": ["<indicador cruzado 1>", ...],
  "investigation_summary": "<resumo investigativo em 3-5 frases>",
  "data_collection_status": "completo" | "parcial" | "insuficiente",
  "missing_data": ["<dado ausente 1>", ...]
}}"""


def _build_prompt(
    transaction: dict[str, Any],
    risk_result: dict[str, Any],
    customer_history: list[dict],
    all_transactions: list[dict] | None = None,
) -> str:
    tx_json = json.dumps(transaction, ensure_ascii=False, indent=2)
    risk_json = json.dumps(risk_result, ensure_ascii=False, indent=2)
    hist_json = json.dumps(customer_history, ensure_ascii=False, indent=2)

    # Transações do destinatário (se disponíveis no dataset)
    receiver_id = transaction.get("receiver_id", "não informado")
    receiver_txs: list[dict] = []
    if all_transactions:
        receiver_txs = [
            t for t in all_transactions
            if t.get("customer_id") == receiver_id or t.get("receiver_id") == receiver_id
        ]
    receiver_json = json.dumps(receiver_txs, ensure_ascii=False, indent=2)

    return (
        f"{_SYSTEM_PROMPT}\n\n"
        f"TRANSAÇÃO ESCALADA:\n{tx_json}\n\n"
        f"ANÁLISE DE RISCO (Agente 1):\n{risk_json}\n\n"
        f"HISTÓRICO DO REMETENTE (todas as transações disponíveis):\n{hist_json}\n\n"
        f"TRANSAÇÕES RELACIONADAS AO DESTINATÁRIO:\n{receiver_json}\n\n"
        f"Monte o dossiê completo do caso:"
    )


def run(
    transaction: dict[str, Any],
    risk_result: dict[str, Any],
    customer_history: list[dict] | None = None,
    all_transactions: list[dict] | None = None,
) -> dict:
    """
    Executa o Agente 2 — Investigação de Ameaças.

    Args:
        transaction:       Dados da transação escalada.
        risk_result:       Saída do Agente 1.
        customer_history:  Histórico do remetente.
        all_transactions:  Dataset completo para cruzar com destinatário.

    Returns:
        Dicionário com perfil do remetente, destinatário, indicadores cruzados
        e resumo investigativo.
    """
    history = customer_history or []
    prompt = _build_prompt(transaction, risk_result, history, all_transactions)

    logger.info("[Agente2] Investigando ameaça em %s", transaction.get("transaction_id"))
    raw = watsonx_client.generate(MODEL_ID, prompt, PARAMETERS)

    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        result = json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning("[Agente2] Falha ao parsear JSON: %s | raw: %s", exc, raw)
        result = {
            "transaction_id": transaction.get("transaction_id"),
            "sender_profile": {
                "customer_id": transaction.get("customer_id"),
                "behavioral_deviation_score": 0.8,
                "anomalies_found": ["parse_error"],
            },
            "receiver_profile": {
                "receiver_id": transaction.get("receiver_id", "desconhecido"),
                "appears_in_other_suspicious": False,
                "receiver_notes": "Dados insuficientes para análise.",
            },
            "crossed_indicators": [],
            "investigation_summary": f"Erro ao processar investigação: {raw[:200]}",
            "data_collection_status": "insuficiente",
            "missing_data": ["resposta_do_modelo_inválida"],
        }

    return result
