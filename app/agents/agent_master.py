"""
Agente 4 — IA Mestre (Master Intelligence)
────────────────────────────────────────────
Responsabilidade: posição hierárquica superior aos Agentes 1, 2 e 3.
Recebe os resultados consolidados dos 3 agentes e:
  1. Calcula o Score de Risco final (0-100)
  2. Determina o nível de urgência
  3. Gera a mensagem de alerta formatada para envio imediato ao profissional
     de Cybersecurity

Modelo: ibm/granite-34b-code-instruct (instância separada, parâmetros diferentes)
Perfil: temperatura mais alta — linguagem clara, direta e urgente para
        comunicação com equipe de segurança em tempo real.
"""
import json
import logging
from datetime import datetime
from typing import Any

from app.core.watsonx_client import watsonx_client

logger = logging.getLogger(__name__)

MODEL_ID = "ibm/granite-34b-code-instruct"
PARAMETERS = {
    "decoding_method": "sample",
    "max_new_tokens": 800,
    "temperature": 0.55,         # balanceada: precisão no score + clareza na mensagem
    "top_p": 0.92,
    "top_k": 50,
    "repetition_penalty": 1.08,
}

_SYSTEM_PROMPT = """Você é a IA Mestre de um sistema de prevenção de fraudes financeiras.
Você está no topo da hierarquia e recebe os relatórios dos 3 agentes subordinados.

Sua tarefa é FINAL e CRÍTICA:
1. Calcular o SCORE DE RISCO (0 a 100) baseado em todos os dados consolidados
2. Definir o NÍVEL DE URGÊNCIA da resposta necessária
3. Gerar o ALERTA DE SEGURANÇA que será enviado IMEDIATAMENTE ao profissional de Cybersecurity

ESCALA DE SCORE:
  0-20:  Risco mínimo (não deveria chegar até aqui)
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
- Baixa qualidade/disponibilidade de dados (incerteza = risco maior)

FORMATO DO ALERTA: objetivo, urgente, sem jargão técnico excessivo.
Deve conter: quem, o quê, quando, onde, valor, por quê é suspeito e ação recomendada.

Retorne APENAS um JSON válido:
{{
  "transaction_id": "<id>",
  "case_id": "<case_id do Agente 3>",
  "risk_score": <0 a 100>,
  "risk_level": "minimo" | "baixo" | "medio" | "alto" | "critico",
  "urgency": "baixa" | "media" | "alta" | "maxima",
  "score_breakdown": {{
    "base_criteria_score": <pontos pelos critérios>,
    "behavioral_deviation_score": <pontos pelo desvio comportamental>,
    "evidence_quality_score": <pontos pela qualidade das evidências>,
    "crossed_indicators_score": <pontos pelos indicadores cruzados>,
    "confirmation_score": <pontos pela confirmação do Agente 3>
  }},
  "recommended_action": "monitorar" | "investigar" | "bloquear_preventivo" | "bloquear_imediato",
  "cybersecurity_alert": {{
    "subject": "⚠️ ALERTA DE FRAUDE — <nivel> — <transaction_id>",
    "priority": "BAIXA" | "MÉDIA" | "ALTA" | "CRÍTICA",
    "timestamp": "<ISO datetime>",
    "message": "<mensagem completa e urgente para o profissional de Cybersecurity, 3-5 parágrafos>",
    "immediate_actions": ["<ação imediata 1>", "<ação imediata 2>", ...],
    "case_summary": "<resumo do caso em 2-3 frases para o cabeçalho do alerta>"
  }},
  "disclaimer": "Sistema acadêmico de apoio à triagem. Decisão final sob responsabilidade humana."
}}"""


def _build_prompt(
    transaction: dict[str, Any],
    risk_result: dict[str, Any],
    investigation_result: dict[str, Any],
    evidence_result: dict[str, Any],
) -> str:
    tx_json = json.dumps(transaction, ensure_ascii=False, indent=2)
    risk_json = json.dumps(risk_result, ensure_ascii=False, indent=2)
    inv_json = json.dumps(investigation_result, ensure_ascii=False, indent=2)
    ev_json = json.dumps(evidence_result, ensure_ascii=False, indent=2)
    now = datetime.now().isoformat()
    return (
        f"{_SYSTEM_PROMPT}\n\n"
        f"TIMESTAMP ATUAL: {now}\n\n"
        f"TRANSAÇÃO:\n{tx_json}\n\n"
        f"AGENTE 1 — ANÁLISE DE RISCO:\n{risk_json}\n\n"
        f"AGENTE 2 — INVESTIGAÇÃO DE AMEAÇAS:\n{inv_json}\n\n"
        f"AGENTE 3 — EVIDÊNCIAS CONSOLIDADAS:\n{ev_json}\n\n"
        f"Calcule o score final e gere o alerta de Cybersecurity:"
    )


def run(
    transaction: dict[str, Any],
    risk_result: dict[str, Any],
    investigation_result: dict[str, Any],
    evidence_result: dict[str, Any],
) -> dict:
    """
    Executa o Agente 4 — IA Mestre.

    Args:
        transaction:          Dados da transação.
        risk_result:          Saída do Agente 1.
        investigation_result: Saída do Agente 2.
        evidence_result:      Saída do Agente 3.

    Returns:
        Dicionário com risk_score, risk_level, urgency, recommended_action
        e cybersecurity_alert pronto para envio.
    """
    prompt = _build_prompt(transaction, risk_result, investigation_result, evidence_result)

    logger.info("[Agente4-Mestre] Calculando score de risco para %s", transaction.get("transaction_id"))
    raw = watsonx_client.generate(MODEL_ID, prompt, PARAMETERS)

    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        result = json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning("[Agente4-Mestre] Falha ao parsear JSON: %s | raw: %s", exc, raw)
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
                    f"ATENÇÃO: Transação {tx_id} foi sinalizada como suspeita com alto risco. "
                    f"Houve erro no processamento do relatório completo. "
                    f"Revisão humana imediata necessária.\n\n"
                    f"Dados brutos: {str(transaction)[:300]}"
                ),
                "immediate_actions": [
                    "Revisar manualmente a transação",
                    "Verificar histórico do cliente",
                    "Acionar protocolo de segurança padrão",
                ],
                "case_summary": f"Erro de processamento na IA Mestre para {tx_id}. Revisão manual obrigatória.",
            },
            "disclaimer": "Sistema acadêmico de apoio à triagem. Decisão final sob responsabilidade humana.",
        }

    return result
