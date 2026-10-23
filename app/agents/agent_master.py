"""
Agente 4 — IA Mestre (Master Intelligence)
────────────────────────────────────────────
Responsabilidade: posição hierárquica superior aos Agentes 1, 2 e 3.
Calcula o Score de Risco final (0-100), determina a urgência e gera
o alerta formatado para o profissional de Cybersecurity.

Modelo: gemini-1.5-pro
Perfil: temperatura 0.4 — modelo mais capaz para síntese final e
        geração de relatório claro e acionável em PT-BR.
"""
import json
import logging
from datetime import datetime
from typing import Any

from app.core.gemini_client import gemini_client
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Você é a IA Mestre de um sistema de prevenção de fraudes financeiras da Núclea.
Você está no topo da hierarquia e recebe os relatórios dos 3 agentes subordinados.

Sua tarefa é FINAL e CRÍTICA:
1. Calcular o SCORE DE RISCO (0 a 100) baseado em todos os dados consolidados
2. Definir o NÍVEL DE URGÊNCIA da resposta necessária
3. Gerar o ALERTA DE SEGURANÇA que será enviado IMEDIATAMENTE ao profissional de Cybersecurity

ESCALA DE SCORE:
  0-20:  Risco mínimo
  21-40: Risco baixo — monitorar
  41-60: Risco médio — investigação adicional recomendada
  61-80: Risco alto — ação preventiva imediata
  81-100: Risco crítico — bloqueio imediato + alerta máximo

FATORES QUE AUMENTAM O SCORE:
- Número de critérios confirmados (cada um soma pontos)
- Confirmação da suspeita pelo Agente 3
- Indicadores cruzados (combinação de sinais)
- Desvio comportamental elevado do remetente
- Destinatário envolvido em outros casos suspeitos
- Baixa qualidade de dados (incerteza = risco maior)

O ALERTA deve ser objetivo, urgente e em português do Brasil.
Deve conter: quem, o quê, quando, onde, valor, por quê é suspeito e ação recomendada.

Retorne um objeto JSON com exatamente esta estrutura:
{
  "transaction_id": "<id>",
  "case_id": "<case_id>",
  "risk_score": 87,
  "risk_level": "critico",
  "urgency": "maxima",
  "score_breakdown": {
    "base_criteria_score": 30,
    "behavioral_deviation_score": 20,
    "evidence_quality_score": 15,
    "crossed_indicators_score": 12,
    "confirmation_score": 10
  },
  "recommended_action": "bloquear_imediato",
  "cybersecurity_alert": {
    "subject": "⚠️ ALERTA DE FRAUDE — CRÍTICO — TXN-013",
    "priority": "CRÍTICA",
    "timestamp": "2024-06-10T02:37:00",
    "message": "<mensagem completa e urgente para o profissional de Cybersecurity, 3-5 parágrafos em PT-BR>",
    "immediate_actions": ["Bloquear transação imediatamente", "Contatar cliente via canal seguro"],
    "case_summary": "<resumo do caso em 2-3 frases>"
  },
  "disclaimer": "Sistema acadêmico de apoio à triagem. Decisão final sob responsabilidade humana."
}"""


def run(
    transaction: dict[str, Any],
    risk_result: dict[str, Any],
    investigation_result: dict[str, Any],
    evidence_result: dict[str, Any],
) -> dict:
    """
    Executa o Agente 4 — IA Mestre.

    Returns:
        Dicionário com risk_score, risk_level, urgency, recommended_action
        e cybersecurity_alert pronto para envio.
    """
    settings = get_settings()

    tx_json = json.dumps(transaction, ensure_ascii=False, indent=2)
    risk_json = json.dumps(risk_result, ensure_ascii=False, indent=2)
    inv_json = json.dumps(investigation_result, ensure_ascii=False, indent=2)
    ev_json = json.dumps(evidence_result, ensure_ascii=False, indent=2)
    now = datetime.now().isoformat()

    user_msg = (
        f"TIMESTAMP ATUAL: {now}\n\n"
        f"TRANSAÇÃO:\n{tx_json}\n\n"
        f"AGENTE 1 — ANÁLISE DE RISCO:\n{risk_json}\n\n"
        f"AGENTE 2 — INVESTIGAÇÃO DE AMEAÇAS:\n{inv_json}\n\n"
        f"AGENTE 3 — EVIDÊNCIAS CONSOLIDADAS:\n{ev_json}\n\n"
        f"Calcule o score final e gere o alerta de Cybersecurity."
    )

    logger.info("[Agente4-Mestre] Calculando score para %s", transaction.get("transaction_id"))

    try:
        result = gemini_client.generate_json(
            model_id=settings.gemini_model_agent4,
            system_prompt=_SYSTEM_PROMPT,
            user_message=user_msg,
            temperature=0.4,
            max_output_tokens=1500,
        )
    except Exception as exc:
        logger.warning("[Agente4-Mestre] Erro na chamada Gemini: %s", exc)
        tx_id = transaction.get("transaction_id", "UNKNOWN")
        result = {
            "transaction_id": tx_id,
            "case_id": evidence_result.get("case_id", f"{tx_id}_CASE"),
            "risk_score": 80,
            "risk_level": "alto",
            "urgency": "alta",
            "score_breakdown": {
                "base_criteria_score": 0,
                "behavioral_deviation_score": 0,
                "evidence_quality_score": 0,
                "crossed_indicators_score": 0,
                "confirmation_score": 0,
            },
            "recommended_action": "bloquear_preventivo",
            "cybersecurity_alert": {
                "subject": f"⚠️ ALERTA DE FRAUDE — ALTO — {tx_id}",
                "priority": "ALTA",
                "timestamp": datetime.now().isoformat(),
                "message": (
                    f"ATENÇÃO: Transação {tx_id} sinalizada com alto risco. "
                    f"Erro no processamento do relatório completo. "
                    f"Revisão humana imediata necessária."
                ),
                "immediate_actions": [
                    "Revisar manualmente a transação",
                    "Verificar histórico do cliente",
                    "Acionar protocolo de segurança padrão",
                ],
                "case_summary": f"Erro de processamento para {tx_id}. Revisão manual obrigatória.",
            },
            "disclaimer": "Sistema acadêmico de apoio à triagem. Decisão final sob responsabilidade humana.",
        }

    return result
