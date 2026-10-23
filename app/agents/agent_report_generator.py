"""
Agente 3 — Base de Dados e Evidências (Evidence Consolidator)
───────────────────────────────────────────────────────────────
Responsabilidade: confirmar ou refutar a suspeita, organizar evidências
e preparar o dossiê para a IA Mestre calcular o score de risco.

Modelo: gemini-1.5-flash
Perfil: temperatura 0.2 — consolidação precisa e estruturada de evidências.
"""
import json
import logging
from typing import Any

from app.core.gemini_client import gemini_client
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Você é um especialista em consolidação de evidências para casos de fraude financeira.
Recebeu a análise de risco inicial e a investigação completa de uma transação suspeita.

Sua tarefa é:
1. CONFIRMAR ou REFUTAR a suspeita com base nas evidências disponíveis
2. ORGANIZAR todos os dados em um dossiê estruturado e completo
3. CLASSIFICAR as evidências por nível de relevância: críticas, de suporte e fracas
4. IDENTIFICAR lacunas de informação que podem impactar a análise
5. PREPARAR os dados consolidados para que a IA Mestre calcule o score de risco

IMPORTANTE: Suspeita não é confirmação de fraude. Avalie as evidências de forma
imparcial, considerando a possibilidade de falso positivo.

Retorne um objeto JSON com exatamente esta estrutura:
{
  "transaction_id": "<id>",
  "case_id": "<transaction_id>_CASE",
  "suspicion_confirmed": true,
  "confirmation_confidence": 0.87,
  "refutation_arguments": ["<argumento que enfraquece a suspeita>"],
  "confirmation_arguments": ["<argumento que fortalece a suspeita>"],
  "evidence_summary": {
    "critical_evidence": ["<evidência crítica 1>"],
    "supporting_evidence": ["<evidência de suporte 1>"],
    "weak_evidence": ["<evidência fraca 1>"]
  },
  "consolidated_case": {
    "transaction": "<resumo da transação>",
    "sender_summary": "<resumo do perfil do remetente>",
    "receiver_summary": "<resumo do destinatário>",
    "timeline": "<linha do tempo dos eventos>",
    "total_criteria_met": 4,
    "criteria_list": ["valor_elevado", "horario_incomum"]
  },
  "data_quality": "alta",
  "information_gaps": [],
  "recommendation_to_master": "<instrução objetiva para a IA Mestre calcular o score>"
}"""


def run(
    transaction: dict[str, Any],
    risk_result: dict[str, Any],
    investigation_result: dict[str, Any],
) -> dict:
    """
    Executa o Agente 3 — Base de Dados e Evidências.

    Returns:
        Dossiê consolidado com evidências organizadas e dados prontos
        para o cálculo do score pelo Agente 4.
    """
    settings = get_settings()

    tx_json = json.dumps(transaction, ensure_ascii=False, indent=2)
    risk_json = json.dumps(risk_result, ensure_ascii=False, indent=2)
    inv_json = json.dumps(investigation_result, ensure_ascii=False, indent=2)

    user_msg = (
        f"TRANSAÇÃO:\n{tx_json}\n\n"
        f"ANÁLISE DE RISCO (Agente 1):\n{risk_json}\n\n"
        f"INVESTIGAÇÃO DE AMEAÇAS (Agente 2):\n{inv_json}\n\n"
        f"Consolide as evidências e prepare o dossiê."
    )

    logger.info("[Agente3] Consolidando evidências de %s", transaction.get("transaction_id"))

    try:
        result = gemini_client.generate_json(
            model_id=settings.gemini_model_agent3,
            system_prompt=_SYSTEM_PROMPT,
            user_message=user_msg,
            temperature=0.2,
            max_output_tokens=1024,
        )
    except Exception as exc:
        logger.warning("[Agente3] Erro na chamada Gemini: %s", exc)
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
            "information_gaps": ["resposta_do_modelo_indisponível"],
            "recommendation_to_master": f"Erro ao processar: {exc}",
        }

    return result
