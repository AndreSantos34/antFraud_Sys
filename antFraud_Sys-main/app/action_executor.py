"""
Executor de Ações — AntFraud_Sys (Modo Simulado)
──────────────────────────────────────────────────
Responsável por executar as ações aprovadas pelo analista de cibersegurança.

Neste protótipo opera em MODO SIMULADO — simula chamadas ao core bancário
e retorna respostas realistas sem dependência de API externa.

Em produção: substituir _call_banking_api() por chamada HTTP real ao core
bancário da instituição, usando BANKING_API_URL e BANKING_API_TOKEN do .env.

IMPORTANTE: Este módulo nunca é chamado automaticamente. Só executa
            uma ação após aprovação explícita de um humano autorizado.
"""
import logging
import random
from datetime import datetime

logger = logging.getLogger(__name__)

# ── Respostas simuladas por código de ação ────────────────────────────────────
# Em produção, cada action_code mapearia para um endpoint específico do banco.

_SIMULATED_RESPONSES: dict[str, dict] = {
    "bloquear_conta_temporariamente": {
        "success_note": "Conta bloqueada preventivamente por 24h. Código de ocorrência: BLQ-{ref}. "
                        "Cliente notificado via SMS e e-mail cadastrado.",
        "failure_note": "Falha ao contatar core bancário (timeout). Bloqueio pendente — escalone manualmente.",
    },
    "encaminhar_nivel2_imediato": {
        "success_note": "Caso encaminhado à equipe SOC Nível 2. Ticket criado: SOC-{ref}. "
                        "Analista de plantão notificado.",
        "failure_note": "Sistema de ticketing indisponível. Notifique manualmente o responsável SOC.",
    },
    "encaminhar_nivel2": {
        "success_note": "Caso encaminhado à equipe SOC Nível 2. Ticket criado: SOC-{ref}. "
                        "Analista de plantão notificado.",
        "failure_note": "Sistema de ticketing indisponível. Notifique manualmente o responsável SOC.",
    },
    "solicitar_2fa_e_revisar": {
        "success_note": "Solicitação de autenticação adicional (2FA) enviada ao cliente. "
                        "Transação em espera por 30 minutos. Ref: 2FA-{ref}.",
        "failure_note": "Falha ao enviar solicitação 2FA. Verifique dados de contato do cliente.",
    },
    "solicitar_confirmacao_cliente": {
        "success_note": "Contato enviado ao cliente via canal seguro (app + SMS). "
                        "Aguardando resposta por até 2h. Ref: CONF-{ref}.",
        "failure_note": "Canal de contato indisponível. Acione equipe de atendimento manualmente.",
    },
    "monitorar_intensivamente": {
        "success_note": "Conta incluída no perfil de monitoramento intensivo por 72h. "
                        "Alertas automáticos ativados. Ref: MON-{ref}.",
        "failure_note": "Sistema de monitoramento indisponível. Registre acompanhamento manual.",
    },
    "monitorar": {
        "success_note": "Conta incluída em fila de monitoramento padrão. Ref: MON-{ref}.",
        "failure_note": "Sistema de monitoramento indisponível. Registre acompanhamento manual.",
    },
    "registrar_e_arquivar": {
        "success_note": "Evento registrado no log de auditoria. Arquivado para análise estatística. "
                        "Ref: AUD-{ref}.",
        "failure_note": "Falha ao registrar no sistema de auditoria. Registre manualmente.",
    },
    "revisao_humana": {
        "success_note": "Caso marcado para revisão humana prioritária. Ref: REV-{ref}. "
                        "Analista designado será notificado.",
        "failure_note": "Falha ao criar registro de revisão. Notifique o analista diretamente.",
    },
}

_DEFAULT_RESPONSE = {
    "success_note": "Ação registrada no sistema. Ref: ACT-{ref}. Acompanhe pelo painel SOC.",
    "failure_note": "Falha ao executar ação. Registre e escalone manualmente.",
}

# Simula ~90% de taxa de sucesso (realista para ambiente de produção)
_SIMULATED_SUCCESS_RATE = 0.90


def execute_action(
    action_id: str,
    action_code: str,
    case_id: str,
    customer_id: str,
    decided_by: str,
) -> dict:
    """
    Executa uma ação aprovada pelo analista — MODO SIMULADO.

    Simula a chamada ao core bancário e retorna o resultado.
    Em produção: substituir o corpo desta função por chamada HTTP real.

    Args:
        action_id:   ID único da ação (ex: "ACT-001")
        action_code: Código da ação (ex: "bloquear_conta_temporariamente")
        case_id:     ID do caso associado
        customer_id: ID do cliente alvo da ação
        decided_by:  Identificador do analista que aprovou

    Returns:
        Dicionário com status, nota de execução e metadados.
    """
    now = datetime.now().isoformat()
    ref = action_id[-6:].upper()  # referência curta para exibição

    logger.info(
        "[Executor] Executando ação simulada | action=%s | case=%s | cliente=%s | aprovado_por=%s",
        action_code, case_id, customer_id, decided_by,
    )

    templates = _SIMULATED_RESPONSES.get(action_code, _DEFAULT_RESPONSE)
    success = random.random() < _SIMULATED_SUCCESS_RATE

    if success:
        note = templates["success_note"].format(ref=ref)
        status = "EXECUTED"
        logger.info("[Executor] ✅ Ação %s executada com sucesso: %s", action_id, note)
    else:
        note = templates["failure_note"].format(ref=ref)
        status = "FAILED"
        logger.warning("[Executor] ⚠️  Ação %s falhou (simulado): %s", action_id, note)

    return {
        "action_id":      action_id,
        "case_id":        case_id,
        "action_code":    action_code,
        "description":    templates.get("success_note", note).split(".")[0] + ".",
        "status":         status,
        "decided_by":     decided_by,
        "decided_at":     now,
        "executed_at":    now,
        "execution_note": note,
        "simulated":      True,
        "customer_id":    customer_id,
    }


def reject_action(
    action_id: str,
    action_code: str,
    case_id: str,
    decided_by: str,
    justification: str | None,
) -> dict:
    """
    Registra a rejeição de uma ação pelo analista.
    Nenhuma chamada ao banco é feita.
    """
    now = datetime.now().isoformat()
    note = f"Ação rejeitada por {decided_by}."
    if justification:
        note += f" Justificativa: {justification}"

    logger.info(
        "[Executor] ❌ Ação %s rejeitada por %s | case=%s",
        action_id, decided_by, case_id,
    )

    return {
        "action_id":      action_id,
        "case_id":        case_id,
        "action_code":    action_code,
        "description":    f"Ação {action_code} rejeitada.",
        "status":         "REJECTED",
        "decided_by":     decided_by,
        "decided_at":     now,
        "executed_at":    None,
        "execution_note": note,
        "simulated":      True,
    }
