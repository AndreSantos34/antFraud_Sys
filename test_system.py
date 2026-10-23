"""
Teste isolado do sistema Núclea/IBM — Prevenção de Fraudes
──────────────────────────────────────────────────────────
Valida todos os componentes sem precisar subir o servidor FastAPI.

Execução:
    python test_system.py
"""
import json
import sys
import time
import traceback
from pathlib import Path

# ── Cores para output no terminal ─────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

PASS = f"{GREEN}[PASS]{RESET}"
FAIL = f"{RED}[FAIL]{RESET}"
SKIP = f"{YELLOW}[SKIP]{RESET}"
INFO = f"{BLUE}[i]{RESET}"

results = []

def section(title: str) -> None:
    print(f"\n{BOLD}{'-'*55}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{BOLD}{'-'*55}{RESET}")

def check(name: str, passed: bool, detail: str = "") -> None:
    status = PASS if passed else FAIL
    print(f"  {status}  {name}")
    if detail:
        print(f"         {INFO} {detail}")
    results.append((name, passed))

def skip(name: str, reason: str) -> None:
    print(f"  {SKIP}  {name}")
    print(f"         {INFO} {reason}")
    results.append((name, None))


# ══════════════════════════════════════════════════════════════════════════════
# BLOCO 1 — Configuração e variáveis de ambiente
# ══════════════════════════════════════════════════════════════════════════════
section("1 · Configuração e Variáveis de Ambiente")

try:
    from app.core.config import get_settings
    settings = get_settings()
    check("Settings carregado com sucesso", True)
    check("GEMINI_API_KEY presente", bool(settings.gemini_api_key),
          f"{'Chave encontrada (' + str(len(settings.gemini_api_key)) + ' chars)' if settings.gemini_api_key else 'FALTANDO — configure no .env'}")
    check("API_SECRET_KEY configurada", bool(settings.api_secret_key))
    check("Threshold de valor configurado", settings.high_value_threshold > 0,
          f"R$ {settings.high_value_threshold:.2f}")
    check("Horário incomum configurado", True,
          f"{settings.unusual_hour_start}h–{settings.unusual_hour_end}h")
    check("Modelos Gemini configurados", all([
        settings.gemini_model_agent1,
        settings.gemini_model_agent2,
        settings.gemini_model_agent3,
        settings.gemini_model_agent4,
    ]), f"Ag1={settings.gemini_model_agent1} | Ag2={settings.gemini_model_agent2} | Ag3={settings.gemini_model_agent3} | Ag4={settings.gemini_model_agent4}")
except Exception as e:
    check("Settings carregado com sucesso", False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# BLOCO 2 — Dataset de transações
# ══════════════════════════════════════════════════════════════════════════════
section("2 · Dataset de Transações")

try:
    from app.orchestrator import get_all_transactions
    txs = get_all_transactions()
    total = len(txs)
    normais = sum(1 for t in txs if t.get("label") == "normal")
    suspeitas = sum(1 for t in txs if t.get("label") == "suspeita")
    check("Dataset carregado", total > 0, f"{total} transações encontradas")
    check("Transações normais presentes", normais >= 10, f"{normais} transações normais")
    check("Transações suspeitas presentes", suspeitas >= 5, f"{suspeitas} transações suspeitas")
    campos = ["transaction_id","customer_id","amount","datetime","location","channel","device"]
    todos_campos = all(all(c in t for c in campos) for t in txs)
    check("Todos os campos obrigatórios presentes", todos_campos, str(campos))
except Exception as e:
    check("Dataset carregado", False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# BLOCO 3 — Cliente Gemini (conexão real)
# ══════════════════════════════════════════════════════════════════════════════
section("3 · Cliente Gemini (conexão real com a API)")

gemini_ok = False
try:
    from app.core.gemini_client import gemini_client
    from app.core.config import get_settings as _gs
    _s = _gs()
    if not _s.gemini_api_key:
        skip("Chamada à API Gemini", "GEMINI_API_KEY não configurada no .env")
    else:
        result = gemini_client.generate_json(
            model_id=_s.gemini_model_agent1,
            system_prompt='Responda apenas com JSON válido: {"status": "ok", "msg": "teste"}',
            user_message="Ping de teste do sistema Núclea.",
            temperature=0.1,
            max_output_tokens=50,
        )
        gemini_ok = isinstance(result, dict)
        check("Conexão com Gemini estabelecida", gemini_ok, f"Resposta: {result}")
except Exception as e:
    check("Conexão com Gemini estabelecida", False, f"{type(e).__name__}: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# BLOCO 4 — Simulador de transações
# ══════════════════════════════════════════════════════════════════════════════
section("4 · Simulador de Transações")

try:
    from app.simulator import generate_single, generate_stream
    tx_normal = generate_single(force_suspicious=False)
    tx_suspeit = generate_single(force_suspicious=True)
    check("Geração de transação normal", "transaction_id" in tx_normal,
          f"ID={tx_normal.get('transaction_id')} | R${tx_normal.get('amount')}")
    check("Geração de transação suspeita", "transaction_id" in tx_suspeit,
          f"ID={tx_suspeit.get('transaction_id')} | R${tx_suspeit.get('amount')} | {tx_suspeit.get('device')}")
    stream = list(generate_stream(total=5))
    check("Geração de stream de 5 transações", len(stream) == 5, f"{len(stream)} transações geradas")
    check("Campos obrigatórios no simulador", all(
        "transaction_id" in t and "amount" in t and "device" in t for t in stream
    ))
except Exception as e:
    check("Simulador de transações", False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# BLOCO 5 — Agente 1: Análise de Risco
# ══════════════════════════════════════════════════════════════════════════════
section("5 · Agente 1 — Análise de Risco")

ag1_result = None
if not gemini_ok:
    skip("Agente 1 — transação normal", "Gemini não disponível")
    skip("Agente 1 — transação suspeita (3+ critérios)", "Gemini não disponível")
else:
    try:
        from app.agents import agent_rule_screener

        # Transação normal (deve retornar < 3 critérios)
        tx_norm = {
            "transaction_id": "TEST-N01",
            "customer_id": "CLI-TEST",
            "amount": 200.00,
            "datetime": "2024-06-10T10:00:00",
            "location": "São Paulo, SP",
            "channel": "app_mobile",
            "device": "smartphone_conhecido",
        }
        r_norm = agent_rule_screener.run(tx_norm)
        check("Agente 1 — transação normal classificada",
              r_norm.get("classification") == "normal",
              f"classification={r_norm.get('classification')} | critérios={r_norm.get('total_criteria_met')}")
        check("Agente 1 — não escala transação normal",
              r_norm.get("escalate_to_investigation") == False)

        # Transação suspeita (deve atingir >= 3 critérios)
        tx_susp = {
            "transaction_id": "TEST-S01",
            "customer_id": "CLI-TEST2",
            "amount": 9800.00,         # valor_elevado ✓
            "datetime": "2024-06-10T02:37:00",  # horario_incomum ✓
            "location": "Miami, EUA",  # mudanca_geografica ✓
            "channel": "internet_banking",
            "device": "dispositivo_desconhecido",  # dispositivo_desconhecido ✓
        }
        r_susp = agent_rule_screener.run(tx_susp)
        ag1_result = r_susp
        total_met = r_susp.get("total_criteria_met", 0)
        check("Agente 1 — transação suspeita detectada",
              r_susp.get("classification") == "suspeita",
              f"classification={r_susp.get('classification')} | critérios={total_met}")
        check("Agente 1 — escala com >= 3 critérios",
              r_susp.get("escalate_to_investigation") == True,
              f"total_criteria_met={total_met}")
        check("Agente 1 — retorna criteria_evaluation",
              "criteria_evaluation" in r_susp)
        check("Agente 1 — retorna confidence",
              "confidence" in r_susp and 0 <= r_susp["confidence"] <= 1)
    except Exception as e:
        check("Agente 1 — execução", False, traceback.format_exc()[-200:])


# ══════════════════════════════════════════════════════════════════════════════
# BLOCO 6 — Pipeline completo (Agentes 2, 3 e 4)
# ══════════════════════════════════════════════════════════════════════════════
section("6 · Pipeline Completo (Agentes 2, 3 e 4 — IA Mestre)")

pipeline_result = None
if not gemini_ok or ag1_result is None:
    skip("Pipeline completo 4 agentes", "Gemini não disponível ou Agente 1 falhou")
else:
    try:
        from app.orchestrator import analyze_transaction
        tx_susp_full = {
            "transaction_id": "TEST-PIPE-01",
            "customer_id": "CLI-PIPE",
            "receiver_id": "CLI-RECV",
            "amount": 9800.00,
            "datetime": "2024-06-10T02:37:00",
            "location": "Miami, EUA",
            "channel": "internet_banking",
            "device": "dispositivo_desconhecido",
        }
        pipeline_result = analyze_transaction(tx_susp_full)

        check("Pipeline — Agente 1 executou",
              pipeline_result.get("agent_1_risk") is not None)
        check("Pipeline — transação escalada",
              pipeline_result.get("escalated") == True,
              f"total_criteria_met={pipeline_result.get('total_criteria_met')}")
        check("Pipeline — Agente 2 executou",
              pipeline_result.get("agent_2_investigation") is not None)
        check("Pipeline — Agente 3 executou",
              pipeline_result.get("agent_3_evidence") is not None)
        check("Pipeline — Agente 4 (IA Mestre) executou",
              pipeline_result.get("agent_4_master") is not None)

        master = pipeline_result.get("agent_4_master", {})
        score = master.get("risk_score", -1)
        check("IA Mestre — Score de risco gerado (0-100)",
              0 <= score <= 100, f"score={score}")
        check("IA Mestre — Nível de risco definido",
              master.get("risk_level") in ["minimo","baixo","medio","alto","critico"],
              f"risk_level={master.get('risk_level')}")
        check("IA Mestre — Alerta Cybersecurity gerado",
              bool(master.get("cybersecurity_alert", {}).get("message")))
        check("IA Mestre — Ações imediatas definidas",
              len(master.get("cybersecurity_alert", {}).get("immediate_actions", [])) > 0)
        check("Pipeline — Caso persistido em disco",
              pipeline_result.get("case_persisted") == True)
    except Exception as e:
        check("Pipeline completo", False, traceback.format_exc()[-300:])


# ══════════════════════════════════════════════════════════════════════════════
# BLOCO 7 — Persistência de casos
# ══════════════════════════════════════════════════════════════════════════════
section("7 · Persistência de Casos")

try:
    from app import case_storage
    cases = case_storage.list_cases()
    check("Listagem de casos funciona", isinstance(cases, list),
          f"{len(cases)} caso(s) persistido(s)")
    if cases:
        case_id = cases[0]["case_id"]
        loaded = case_storage.load_case(case_id)
        check("Carregamento de caso por ID", loaded is not None,
              f"case_id={case_id}")
    else:
        skip("Carregamento de caso por ID", "Nenhum caso persistido ainda")
except Exception as e:
    check("Persistência de casos", False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# RESULTADO FINAL
# ══════════════════════════════════════════════════════════════════════════════
section("RESULTADO FINAL")

total_tests = sum(1 for _, r in results if r is not None)
passed      = sum(1 for _, r in results if r is True)
failed      = sum(1 for _, r in results if r is False)
skipped     = sum(1 for _, r in results if r is None)

print(f"\n  {BOLD}Total executados:{RESET}  {total_tests}")
print(f"  {GREEN}{BOLD}Passou:{RESET}           {passed}")
print(f"  {RED}{BOLD}Falhou:{RESET}           {failed}")
print(f"  {YELLOW}{BOLD}Pulados:{RESET}          {skipped}")

if failed == 0 and passed > 0:
    print(f"\n  {GREEN}{BOLD}>> Sistema funcionando corretamente!{RESET}")
elif failed > 0:
    print(f"\n  {RED}{BOLD}>> {failed} teste(s) falharam. Verifique os itens acima.{RESET}")
    print(f"\n  Testes que falharam:")
    for name, result in results:
        if result is False:
            print(f"    {RED}*{RESET} {name}")

print()
sys.exit(0 if failed == 0 else 1)
