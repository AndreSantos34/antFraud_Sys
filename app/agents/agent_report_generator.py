"""
Agente 3 — Base de Dados e Evidências (Evidence Consolidator)
───────────────────────────────────────────────────────────────
Responsabilidade: confirmar ou refutar a suspeita com base nas evidências
coletadas pelo Agente 2, organizar e estruturar todos os dados do caso de
forma que a IA Mestre (Agente 4) possa gerar o score de risco com precisão.
Os dados do caso são persistidos em arquivo JSON local.

Modelo: ibm/granite-34b-code-instruct
Perfil: temperatura moderada — síntese estruturada de evidências com
        organização rigorosa dos dados para consumo pela IA Mestre.
"""
import json
import logging
from typing import Any

from app.core.watsonx_client import watsonx_client

logger = logging.getLogger(__name__)

MODEL_ID = "ibm/granite-34b-code-instruct"
PARAMETERS = {
    "decoding_method": "sample",
    "max_new_tokens": 700,
    "temperature": 0.35,         # moderada-baixa: consolidação precisa de evidências
    "top_p": 0.9,
    "repetition_penalty": 1.1,
}

_SYSTEM_PROMPT = """Você é um especialista em consolidação de evidências para casos de fraude financeira.
Recebeu a análise de risco inicial e a investigação completa de uma transação suspeita.

Sua tarefa é:
1. CONFIRMAR ou REFUTAR a suspeita com base nas evidências disponíveis
2. ORGANIZAR todos os dados em um dossiê estruturado e completo
3. CLASSIFICAR as evidências por nível de relevância
4. IDENTIFICAR lacunas de informação que podem impactar a análise
5. PREPARAR os dados consolidados para que a IA Mestre possa calcular o score de risco

IMPORTANTE: Suspeita não é confirmação de fraude. Avalie as evidências de forma
imparcial, considerando a possibilidade de falso positivo.

Retorne APENAS um JSON válido:
{{
  "transaction_id": "<id>",
  "case_id": "<transaction_id>_CASE",
  "suspicion_confirmed": true | false,
  "confirmation_confidence": <0.0 a 1.0>,
  "refutation_arguments": ["<argumento que enfraquece a suspeita>", ...],
  "confirmation_arguments": ["<argumento que fortalece a suspeita>", ...],
  "evidence_summary": {{
    "critical_evidence": ["<evidência crítica 1>", ...],
    "supporting_evidence": ["<evidência de suporte 1>", ...],
    "weak_evidence": ["<evidência fraca 1>", ...]
  }},
  "consolidated_case": {{
    "transaction": "<resumo da transação>",
    "sender_summary": "<resumo do perfil do remetente>",
    "receiver_summary": "<resumo do destinatário>",
    "timeline": "<linha do tempo dos eventos>",
    "total_criteria_met": <número>,
    "criteria_list": ["<critério1>", ...]
  }},
  "data_quality": "alta" | "media" | "baixa",
  "information_gaps": ["<lacuna 1>", ...],
  "recommendation_to_master": "<instrução objetiva para a IA Mestre calcular o score>"
}}"""


def _build_prompt(
    transaction: dict[str, Any],
    risk_result: dict[str, Any],
    investigation_result: dict[str, Any],
) -> str:
    tx_json = json.dumps(transaction, ensure_ascii=False, indent=2)
    risk_json = json.dumps(risk_result, ensure_ascii=False, indent=2)
    inv_json = json.dumps(investigation_result, ensure_ascii=False, indent=2)
    return (
        f"{_SYSTEM_PROMPT}\n\n"
        f"TRANSAÇÃO:\n{tx_json}\n\n"
        f"ANÁLISE DE RISCO (Agente 1):\n{risk_json}\n\n"
        f"INVESTIGAÇÃO DE AMEAÇAS (Agente 2):\n{inv_json}\n\n"
        f"Consolide as evidências e prepare o dossiê:"
    )


def run(
    transaction: dict[str, Any],
    risk_result: dict[str, Any],
    investigation_result: dict[str, Any],
) -> dict:
    """
    Executa o Agente 3 — Base de Dados e Evidências.

    Args:
        transaction:          Dados da transação.
        risk_result:          Saída do Agente 1.
        investigation_result: Saída do Agente 2.

    Returns:
        Dossiê consolidado com evidências organizadas e dados prontos
        para o cálculo do score pelo Agente 4.
    """
    prompt = _build_prompt(transaction, risk_result, investigation_result)

    logger.info("[Agente3] Consolidando evidências de %s", transaction.get("transaction_id"))
    raw = watsonx_client.generate(MODEL_ID, prompt, PARAMETERS)

    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        result = json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning("[Agente3] Falha ao parsear JSON: %s | raw: %s", exc, raw)
        tx_id = transaction.get("transaction_id", "UNKNOWN")
        result = {
            "transaction_id": tx_id,
            "case_id": f"{tx_id}_CASE",
            "suspicion_confirmed": True,
            "confirmation_confidence": 0.5,
            "refutation_arguments": [],
            "confirmation_arguments": ["Erro de processamento — revisão humana necessária"],
            "evidence_summary": {
                "critical_evidence": [],
                "supporting_evidence": [],
                "weak_evidence": [],
            },
            "consolidated_case": {
                "transaction": str(transaction),
                "sender_summary": "Dados não processados",
                "receiver_summary": "Dados não processados",
                "timeline": "Não disponível",
                "total_criteria_met": risk_result.get("total_criteria_met", 0),
                "criteria_list": [],
            },
            "data_quality": "baixa",
            "information_gaps": ["resposta_do_modelo_inválida"],
            "recommendation_to_master": f"Erro ao processar: {raw[:200]}",
        }

    return result
