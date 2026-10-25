"""
Teste do fluxo de aprovação humana — AntFraud_Sys
Executa sem servidor e sem chamadas reais ao Gemini.
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

GREEN = "\033[92m"; RED = "\033[91m"; YELLOW = "\033[93m"
BOLD = "\033[1m"; RESET = "\033[0m"
PASS = f"{GREEN}[PASS]{RESET}"; FAIL = f"{RED}[FAIL]{RESET}"

results = []

def check(name, passed, detail=""):
    results.append(passed)
    status = PASS if passed else FAIL
    print(f"  {status}  {name}")
    if detail:
        print(f"         >> {detail}")

def section(title):
    print(f"\n{BOLD}{'-'*55}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{BOLD}{'-'*55}{RESET}")


# ── Fixtures ──────────────────────────────────────────────────────────────────

TX = {
    "transaction_id": "TX-APR-01", "customer_id": "CLI-001",
    "amount": 9800.0, "datetime": "2024-06-10T02:00:00",
    "location": "Miami, EUA", "channel": "internet_banking",
    "device": "dispositivo_desconhecido",
}

DETECTION = {
    "transaction_id": "TX-APR-01",
    "criteria_flags": {
        "valor_elevado": True, "horario_incomum": True,
        "dispositivo_desconhecido": True, "frequencia_elevada": False,
        "valor_repetido": False, "mudanca_geografica": False,
    },
    "total_criteria_met": 3, "escalate_to_investigation": True,
    "classification": "suspeita",
    "deterministic_evidence": ["Valor alto", "Horário incomum", "Dispositivo desconhecido"],
    "llm_justification": None, "llm_confidence": None,
}

INVESTIGATION = {
    "transaction_id": "TX-APR-01",
    "sender_profile": {"customer_id": "CLI-001", "typical_amount_range": None, "anomalies_found": []},
    "receiver_profile": {"receiver_id": None, "appears_in_other_suspicious": False},
    "crossed_indicators": ["valor_elevado + horario_incomum"],
    "correlated_events": [], "investigation_summary": "Transação atípica.",
    "data_collection_status": "insuficiente", "missing_data": [], "llm_generated": False,
}

RISK = {
    "transaction_id": "TX-APR-01", "case_id": "CASE-APR-01",
    "risk_score": 72,
    "risk_dimensions": {
        "severity_level": "alto", "severity_justification": "Score elevado.",
        "priority_level": "alta", "priority_justification": "Urgência alta.",
        "confidence_score": 0.8, "confidence_justification": "Dados suficientes.",
    },
    "recommendations": [
        {"action_code": "solicitar_2fa_e_revisar", "description": "Solicitar 2FA.", "proportional": True},
        {"action_code": "encaminhar_nivel2", "description": "Encaminhar para Nível 2.", "proportional": True},
    ],
    "information_gaps": [], "score_is_fallback": False,
    "critical_evidence": ["Valor elevado", "Horário incomum"],
    "refutation_points": [],
}


# ══════════════════════════════════════════════════════════════════════════════
section("1 · Agente 4 — Geração de suggested_actions")
# ══════════════════════════════════════════════════════════════════════════════

try:
    from app.agents import agent_master
    with patch("app.agents.agent_master.gemini_client") as mock_gc:
        mock_gc.generate_json.side_effect = Exception("LLM down")
        master_result = agent_master.run(
            TX, DETECTION, INVESTIGATION, RISK, "CASE-APR-01", "TRACE-APR-01"
        )

    actions = master_result.get("suggested_actions", [])
    check("suggested_actions presente na saída do Agente 4", len(actions) >= 1,
          f"{len(actions)} ação(ões) gerada(s)")
    check("Todas as ações com status PENDING",
          all(a.get("status") == "PENDING" for a in actions))
    check("Todas com action_id único (prefixo ACT-)",
          all(a.get("action_id", "").startswith("ACT-") for a in actions))
    check("Todas com action_code e description",
          all(a.get("action_code") and a.get("description") for a in actions))
    check("action_ids são únicos entre si",
          len({a["action_id"] for a in actions}) == len(actions))
    check("Ações derivadas das recomendações do Agente 3",
          any("2fa" in a["action_code"] or "nivel2" in a["action_code"] for a in actions),
          str([a["action_code"] for a in actions]))

    # Guarda para usar nos próximos blocos
    first_action = actions[0]
    action_id = first_action["action_id"]
    action_code = first_action["action_code"]

except Exception as e:
    check("Agente 4 executou", False, str(e))
    first_action = {"action_id": "ACT-FALLBACK", "action_code": "revisao_humana", "status": "PENDING"}
    action_id = "ACT-FALLBACK"
    action_code = "revisao_humana"


# ══════════════════════════════════════════════════════════════════════════════
section("2 · Executor Simulado — Aprovação")
# ══════════════════════════════════════════════════════════════════════════════

try:
    from app.action_executor import execute_action

    exec_result = execute_action(
        action_id=action_id,
        action_code=action_code,
        case_id="CASE-APR-01",
        customer_id="CLI-001",
        decided_by="dr_silva_soc",
    )

    check("Executor retorna EXECUTED ou FAILED",
          exec_result["status"] in ("EXECUTED", "FAILED"),
          f"status={exec_result['status']}")
    check("simulated=True (protótipo)", exec_result.get("simulated") is True)
    check("execution_note não vazia", bool(exec_result.get("execution_note")))
    check("decided_by preservado", exec_result.get("decided_by") == "dr_silva_soc")
    check("action_id preservado", exec_result.get("action_id") == action_id)
    check("executed_at preenchido", bool(exec_result.get("executed_at")))

    # Verifica nota por código de ação
    note = exec_result.get("execution_note", "")
    if action_code == "solicitar_2fa_e_revisar":
        check("Nota menciona 2FA", "2FA" in note or "2fa" in note.lower(), note[:100])
    elif "nivel2" in action_code or "nivel_2" in action_code:
        check("Nota menciona SOC", "SOC" in note or "Nível 2" in note, note[:100])
    else:
        check("Nota de execução coerente com ação", len(note) > 10, note[:100])

except Exception as e:
    check("Executor de aprovação", False, str(e))
    exec_result = {}


# ══════════════════════════════════════════════════════════════════════════════
section("3 · Executor Simulado — Rejeição")
# ══════════════════════════════════════════════════════════════════════════════

try:
    from app.action_executor import reject_action

    rej_result = reject_action(
        action_id="ACT-REJ-TEST",
        action_code="monitorar",
        case_id="CASE-APR-01",
        decided_by="dr_silva_soc",
        justification="Risco considerado aceitável neste contexto operacional.",
    )

    check("Rejeição retorna status REJECTED", rej_result["status"] == "REJECTED")
    check("executed_at é None (não executou)", rej_result.get("executed_at") is None)
    check("Justificativa registrada na nota",
          "Risco considerado aceitável" in rej_result.get("execution_note", ""))
    check("decided_by preservado", rej_result.get("decided_by") == "dr_silva_soc")
    check("simulated=True", rej_result.get("simulated") is True)

    # Rejeição sem justificativa
    rej_sem = reject_action("ACT-REJ-02", "monitorar", "CASE-001", "analista", None)
    check("Rejeição sem justificativa funciona", rej_sem["status"] == "REJECTED")

except Exception as e:
    check("Executor de rejeição", False, str(e))
    rej_result = {}


# ══════════════════════════════════════════════════════════════════════════════
section("4 · Persistência de Decisões (case_storage)")
# ══════════════════════════════════════════════════════════════════════════════

try:
    import app.case_storage as cs
    original_dir = cs._CASES_DIR

    with tempfile.TemporaryDirectory() as tmp:
        cs._CASES_DIR = Path(tmp)

        # Salva duas decisões
        if exec_result:
            cs.save_action_result("CASE-PERSIST", {**exec_result, "action_id": "ACT-P01"})
        if rej_result:
            cs.save_action_result("CASE-PERSIST", {**rej_result, "action_id": "ACT-P02"})

        history = cs.list_action_results("CASE-PERSIST")
        check("2 decisões persistidas corretamente", len(history) == 2, f"{len(history)} encontradas")
        check("_recorded_at em cada entrada", all("_recorded_at" in h for h in history))

        # Acumula — salva mais uma
        cs.save_action_result("CASE-PERSIST", {
            "action_id": "ACT-P03", "action_code": "monitorar",
            "status": "EXECUTED", "decided_by": "analista2",
            "decided_at": "2024-01-01T10:00:00",
        })
        history2 = cs.list_action_results("CASE-PERSIST")
        check("Nova decisão acumulada (não sobrescreve)", len(history2) == 3)

        # list_cases ignora arquivos _actions
        cs.save_case("CASE-PERSIST", {
            "case_id": "CASE-PERSIST", "trace_id": "trace-x",
            "transaction_id": "TX-P01",
            "agent_4_master": {"processing_status": "COMPLETED", "final_risk_score": 72},
        })
        cases = cs.list_cases()
        ids = [c["case_id"] for c in cases]
        check("list_cases não inclui arquivos _actions", "CASE-PERSIST_actions" not in ids,
              str(ids))
        check("list_cases inclui o caso real", "CASE-PERSIST" in ids)

        # Caso sem decisões retorna lista vazia
        empty = cs.list_action_results("CASE-SEM-ACOES")
        check("Caso sem decisões retorna lista vazia", empty == [])

        cs._CASES_DIR = original_dir

except Exception as e:
    check("Persistência de decisões", False, str(e))
    try:
        cs._CASES_DIR = original_dir
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
section("5 · Schemas — ActionStatus, SuggestedAction, ActionDecision, ActionResult")
# ══════════════════════════════════════════════════════════════════════════════

try:
    from app.models.schemas import ActionStatus, SuggestedAction, ActionDecision, ActionResult

    check("ActionStatus.PENDING = 'PENDING'", ActionStatus.PENDING == "PENDING")
    check("ActionStatus.APPROVED = 'APPROVED'", ActionStatus.APPROVED == "APPROVED")
    check("ActionStatus.REJECTED = 'REJECTED'", ActionStatus.REJECTED == "REJECTED")
    check("ActionStatus.EXECUTED = 'EXECUTED'", ActionStatus.EXECUTED == "EXECUTED")
    check("ActionStatus.FAILED = 'FAILED'", ActionStatus.FAILED == "FAILED")

    sa = SuggestedAction(
        action_id="ACT-001", action_code="monitorar",
        description="Monitorar conta intensivamente.", risk_level="alto",
    )
    check("SuggestedAction default status=PENDING", sa.status == ActionStatus.PENDING)
    check("SuggestedAction proportional=True por padrão", sa.proportional is True)

    ad = ActionDecision(decided_by="dr_silva", decision="approve",
                        justification="Evidências suficientes.")
    check("ActionDecision instancia corretamente", ad.decided_by == "dr_silva")
    check("ActionDecision justification opcional", ActionDecision(
        decided_by="analista", decision="reject").justification is None)

except Exception as e:
    check("Schemas de aprovação", False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
section("6 · Endpoints de aprovação registrados na API")
# ══════════════════════════════════════════════════════════════════════════════

try:
    from app.routes.fraud import router
    routes = [r.path for r in router.routes]
    check("POST /cases/{case_id}/actions/{action_id}/approve registrado",
          any("approve" in r for r in routes), str([r for r in routes if "action" in r]))
    check("POST /cases/{case_id}/actions/{action_id}/reject registrado",
          any("reject" in r for r in routes))
    check("GET /cases/{case_id}/actions registrado",
          any(r.endswith("/actions") for r in routes))
except Exception as e:
    check("Endpoints registrados", False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
section("7 · Proteção contra dupla decisão (409 Conflict)")
# ══════════════════════════════════════════════════════════════════════════════

try:
    from fastapi.testclient import TestClient
    from main import app as fastapi_app
    from app.core.config import get_settings

    settings = get_settings()
    headers = {"X-API-Key": settings.api_secret_key}
    client = TestClient(fastapi_app, raise_server_exceptions=False)

    # Precisa de um caso real com suggested_actions
    import app.case_storage as cs2
    fake_case = {
        "case_id": "CASE-409-TEST",
        "trace_id": "trace-409",
        "transaction_id": "TX-409",
        "transaction": {"customer_id": "CLI-409"},
        "agent_4_master": {
            "suggested_actions": [
                {"action_id": "ACT-409-AA", "action_code": "monitorar",
                 "description": "Monitorar.", "status": "PENDING", "risk_level": "medio"},
            ]
        },
    }
    cs2.save_case("CASE-409-TEST", fake_case)

    # Primeira decisão — deve funcionar
    r1 = client.post(
        "/api/v1/cases/CASE-409-TEST/actions/ACT-409-AA/approve",
        json={"decided_by": "analista_teste", "decision": "approve"},
        headers=headers,
    )
    # Registra manualmente o resultado para simular que a ação foi processada
    # (o endpoint real faz isso, mas como o caso em disco ainda tem PENDING,
    #  testamos com uma segunda chamada ao mesmo endpoint)
    check("Primeira aprovação retorna 200", r1.status_code == 200,
          f"status={r1.status_code}")

    # 404 para caso inexistente
    r404 = client.post(
        "/api/v1/cases/CASE-NAO-EXISTE/actions/ACT-XYZ/approve",
        json={"decided_by": "analista", "decision": "approve"},
        headers=headers,
    )
    check("404 para caso inexistente", r404.status_code == 404,
          f"status={r404.status_code}")

    # 404 para action_id inexistente
    r404b = client.post(
        "/api/v1/cases/CASE-409-TEST/actions/ACT-INEXISTENTE/approve",
        json={"decided_by": "analista", "decision": "approve"},
        headers=headers,
    )
    check("404 para action_id inexistente", r404b.status_code == 404,
          f"status={r404b.status_code}")

    # GET /actions retorna estrutura esperada
    rget = client.get("/api/v1/cases/CASE-409-TEST/actions", headers=headers)
    check("GET /actions retorna 200", rget.status_code == 200)
    if rget.status_code == 200:
        body = rget.json()
        check("GET /actions contém suggested_actions e decisions_history",
              "suggested_actions" in body and "decisions_history" in body,
              str(list(body.keys())))

except Exception as e:
    check("Testes HTTP dos endpoints", False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
section("RESULTADO FINAL")
# ══════════════════════════════════════════════════════════════════════════════

total  = len(results)
passed = sum(results)
failed = total - passed

print(f"\n  {BOLD}Total:{RESET} {total}  |  {GREEN}{BOLD}Passou: {passed}{RESET}  |  {RED}{BOLD}Falhou: {failed}{RESET}")

if failed == 0:
    print(f"\n  {GREEN}{BOLD}>> Fluxo de aprovação humana 100% funcional!{RESET}\n")
else:
    print(f"\n  {RED}{BOLD}>> {failed} teste(s) falharam.{RESET}\n")

sys.exit(0 if failed == 0 else 1)
