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
    # ── Crítico (score 81–100) ─────────────────────────────────────────────────
    "congelar_conta_e_escalar_soc": {
        "success_note": "Sessão ativa encerrada e conta congelada preventivamente. "
                        "Caso escalado para SOC Nível 2 — Ticket: INC-{ref}. "
                        "Protocolo de resposta a incidente iniciado. Analista de plantão notificado.",
        "failure_note": "Falha ao congelar conta no core bancário (timeout). "
                        "Escalone manualmente para SOC Nível 2 e notifique o analista de plantão.",
    },
    # ── Alto (score 61–80) ────────────────────────────────────────────────────
    "forcar_reautenticacao_e_investigar": {
        "success_note": "Reautenticação MFA forçada — sessão atual invalidada. "
                        "Transações pendentes suspensas por 60 min. "
                        "Ticket de investigação aberto no SIEM: INV-{ref}.",
        "failure_note": "Falha ao forçar reautenticação. Invalide a sessão manualmente e abra ticket no SIEM.",
    },
    # ── Médio (score 41–60) ───────────────────────────────────────────────────
    "ativar_monitoramento_intensivo": {
        "success_note": "Perfil de monitoramento intensivo ativado por 72h. "
                        "Alertas em tempo real configurados para qualquer nova transação. "
                        "Ref: MON-{ref}. Correlação com eventos recentes iniciada no SIEM.",
        "failure_note": "Sistema de monitoramento indisponível. Registre manualmente e acione analista de plantão.",
    },
    # ── Baixo (score 21–40) ───────────────────────────────────────────────────
    "registrar_e_vigiar": {
        "success_note": "Evento registrado no log de auditoria do SIEM. "
                        "Cliente incluído em fila de vigilância preventiva por 24h. Ref: VIG-{ref}.",
        "failure_note": "Falha ao registrar no SIEM. Documente manualmente no sistema de auditoria.",
    },
    # ── Mínimo (score 1–20) ───────────────────────────────────────────────────
    "arquivar_sem_acao": {
        "success_note": "Evento arquivado no SIEM para análise estatística. "
                        "Nenhuma ação operacional necessária. Ref: AUD-{ref}.",
        "failure_note": "Falha ao arquivar no SIEM. Registre manualmente no log de auditoria.",
    },
    # ── Legado — mantidos para compatibilidade com casos já persistidos ────────
    "bloquear_conta_temporariamente": {
        "success_note": "Conta bloqueada preventivamente. Ref: BLQ-{ref}.",
        "failure_note": "Falha ao bloquear conta. Escalone manualmente.",
    },
    "encaminhar_nivel2_imediato": {
        "success_note": "Caso encaminhado para SOC Nível 2. Ticket: SOC-{ref}.",
        "failure_note": "Sistema de ticketing indisponível. Notifique o SOC manualmente.",
    },
    "solicitar_2fa_e_revisar": {
        "success_note": "Autenticação adicional solicitada ao cliente. Ref: 2FA-{ref}.",
        "failure_note": "Falha ao enviar 2FA. Verifique dados de contato do cliente.",
    },
    "monitorar_intensivamente": {
        "success_note": "Monitoramento intensivo ativado por 72h. Ref: MON-{ref}.",
        "failure_note": "Sistema de monitoramento indisponível.",
    },
    "registrar_e_arquivar": {
        "success_note": "Evento arquivado. Ref: AUD-{ref}.",
        "failure_note": "Falha ao arquivar. Registre manualmente.",
    },
    "revisao_humana": {
        "success_note": "Caso marcado para revisão. Ref: REV-{ref}.",
        "failure_note": "Falha ao criar registro. Notifique o analista diretamente.",
    },
}

_DEFAULT_RESPONSE = {
    "success_note": "Ação registrada no sistema. Ref: ACT-{ref}. Acompanhe pelo painel SOC.",
    "failure_note": "Falha ao executar ação. Registre e escalone manualmente.",
}

# Taxa de sucesso simulada por action_code.
# Ações críticas têm taxa 100% — em demo não faz sentido simular falha num congelamento.
# Ações de monitoramento/arquivo têm ~5% de falha (infra menos crítica).
_SUCCESS_RATE_BY_ACTION: dict[str, float] = {
    "congelar_conta_e_escalar_soc":       1.00,   # crítico — sempre executa
    "forcar_reautenticacao_e_investigar": 1.00,   # alto    — sempre executa
    "ativar_monitoramento_intensivo":     0.97,   # médio
    "registrar_e_vigiar":                 0.95,   # baixo
    "arquivar_sem_acao":                  0.95,   # mínimo
}
_DEFAULT_SUCCESS_RATE = 0.90   # fallback para códigos legados


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
    rate = _SUCCESS_RATE_BY_ACTION.get(action_code, _DEFAULT_SUCCESS_RATE)
    success = random.random() < rate

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
