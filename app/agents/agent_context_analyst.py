"""
Agente 2 — Investigação de Ameaças (Threat Investigator)
──────────────────────────────────────────────────────────
Responsabilidade: coletar e estruturar dados do remetente e destinatário,
cruzar histórico e identificar padrões de comportamento anômalo.

Só é acionado quando o Agente 1 detectar >= 3 critérios.

Modelo: gemini-1.5-flash
Perfil: temperatura 0.4 — análise investigativa com raciocínio contextual.
"""
import json
import logging
from typing import Any

from app.core.gemini_client import gemini_client
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Você é um investigador especializado em ameaças financeiras.
Uma transação foi escalada para investigação porque atingiu 3 ou mais critérios de suspeita.

Sua tarefa é coletar e estruturar todos os dados disponíveis para montar o dossiê do caso:

1. PERFIL DO REMETENTE: analise o histórico de transações, padrão de valores, horários
   habituais, localizações frequentes e dispositivos utilizados.

2. PERFIL DO DESTINATÁRIO: identifique quem recebe a transação, se há padrão de
   recebimento suspeito, se o destinatário aparece em outras transações anômalas.

3. PADRÕES DE COMPORTAMENTO: compare a transação atual com o histórico para identificar
   desvios — mudanças abruptas de comportamento, valores fora do padrão, horários atípicos.

4. INDICADORES CRUZADOS: quais critérios se reforçam mutuamente.

Retorne um objeto JSON com exatamente esta estrutura:
{
  "transaction_id": "<id>",
  "sender_profile": {
    "customer_id": "<id do remetente>",
    "typical_transaction_range": "<faixa de valores habitual>",
    "typical_hours": "<horários habituais>",
    "typical_locations": ["<local1>"],
    "known_devices": ["<dispositivo1>"],
    "transaction_frequency": "<frequência habitual>",
    "behavioral_deviation_score": 0.85,
    "anomalies_found": ["<anomalia1>"]
  },
  "receiver_profile": {
    "receiver_id": "<id ou referência do destinatário>",
    "appears_in_other_suspicious": false,
    "receiver_notes": "<observações sobre o destinatário>"
  },
  "crossed_indicators": ["<indicador cruzado 1>"],
  "investigation_summary": "<resumo investigativo em 3-5 frases>",
  "data_collection_status": "completo",
  "missing_data": []
}"""


def run(
    transaction: dict[str, Any],
    risk_result: dict[str, Any],
    customer_history: list[dict] | None = None,
    all_transactions: list[dict] | None = None,
) -> dict:
    """
    Executa o Agente 2 — Investigação de Ameaças.

    Returns:
        Dicionário com perfil do remetente, destinatário, indicadores cruzados
        e resumo investigativo.
    """
    settings = get_settings()
    history = customer_history or []

    receiver_id = transaction.get("receiver_id", "não informado")
    receiver_txs: list[dict] = []
    if all_transactions:
        receiver_txs = [
            t for t in all_transactions
            if t.get("customer_id") == receiver_id or t.get("receiver_id") == receiver_id
        ]

    tx_json = json.dumps(transaction, ensure_ascii=False, indent=2)
    risk_json = json.dumps(risk_result, ensure_ascii=False, indent=2)
    hist_json = json.dumps(history, ensure_ascii=False, indent=2)
    recv_json = json.dumps(receiver_txs, ensure_ascii=False, indent=2)

    user_msg = (
        f"TRANSAÇÃO ESCALADA:\n{tx_json}\n\n"
        f"ANÁLISE DE RISCO (Agente 1):\n{risk_json}\n\n"
        f"HISTÓRICO DO REMETENTE:\n{hist_json}\n\n"
        f"TRANSAÇÕES RELACIONADAS AO DESTINATÁRIO:\n{recv_json}\n\n"
        f"Monte o dossiê completo do caso."
    )

    logger.info("[Agente2] Investigando ameaça em %s", transaction.get("transaction_id"))

    try:
        result = gemini_client.generate_json(
            model_id=settings.gemini_model_agent2,
            system_prompt=_SYSTEM_PROMPT,
            user_message=user_msg,
            temperature=0.4,
            max_output_tokens=1024,
        )
    except Exception as exc:
        logger.warning("[Agente2] Erro na chamada Gemini: %s", exc)
        result = {
            "transaction_id": transaction.get("transaction_id"),
            "sender_profile": {
                "customer_id": transaction.get("customer_id"),
                "behavioral_deviation_score": 0.8,
                "anomalies_found": [f"Erro de processamento: {exc}"],
            },
            "receiver_profile": {
                "receiver_id": receiver_id,
                "appears_in_other_suspicious": False,
                "receiver_notes": "Dados não processados.",
            },
            "crossed_indicators": [],
            "investigation_summary": f"Erro ao processar investigação: {exc}",
            "data_collection_status": "insuficiente",
            "missing_data": ["resposta_do_modelo_indisponível"],
        }

    return result
