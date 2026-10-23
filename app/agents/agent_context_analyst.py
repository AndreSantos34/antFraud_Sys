"""
Agente 2 — Investigação e Correlação
──────────────────────────────────────
Responsabilidade:
  1. Construir o perfil comportamental do remetente a partir do histórico real.
  2. Verificar se o destinatário aparece em outros eventos suspeitos.
  3. Cruzar eventos em busca de padrões: compartilhamento de dispositivo/localização,
     rajadas temporais, possíveis redes de contas suspeitas.
  4. Documentar explicitamente lacunas de informação (Zero Alucinação).

O LLM é usado para síntese narrativa e correlação contextual complexa.
Toda extração de dados do histórico é feita deterministicamente em Python.
"""
import json
import logging
from collections import Counter
from datetime import datetime
from typing import Any

from app.core.gemini_client import gemini_client
from app.core.config import get_settings

logger = logging.getLogger(__name__)

# ── Prompt do LLM ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """Você é um investigador especializado em ameaças financeiras.
Recebeu dados estruturados de uma transação suspeita e do perfil do remetente/destinatário.
TODOS os dados já foram extraídos deterministicamente — você NÃO deve inventar fatos.

Sua tarefa é:
1. Resumir a investigação em linguagem clara para o analista SOC.
2. Identificar quais indicadores cruzados se reforçam mutuamente.
3. Listar correlações suspeitas identificadas nos dados fornecidos.
4. Registrar lacunas de informação explicitamente como "Dado não disponível".

REGRAS OBRIGATÓRIAS:
- Use APENAS os dados fornecidos no contexto.
- NÃO invente transações, IPs, localizações ou contas.
- NÃO diga que a transação É fraude — diga que ela APRESENTA indicadores.
- NÃO recomende bloquear, cancelar ou executar operações financeiras.

Retorne JSON com exatamente esta estrutura:
{
  "crossed_indicators": ["<indicador que se reforça com outro>"],
  "correlated_events": ["<descrição de correlação encontrada nos dados>"],
  "investigation_summary": "<resumo investigativo objetivo em 3-4 frases, PT-BR>",
  "missing_data": ["<dado ausente que limitou a análise>"]
}"""


# ── Extração determinística do perfil ────────────────────────────────────────

def _build_sender_profile_deterministic(
    customer_id: str,
    history: list[dict],
) -> dict:
    """Constrói o perfil do remetente a partir do histórico real. Zero invenção."""
    if not history:
        return {
            "customer_id": customer_id,
            "typical_amount_range": None,
            "typical_hours": None,
            "typical_locations": [],
            "known_devices": [],
            "behavioral_deviation_score": None,
            "anomalies_found": [],
        }

    amounts = [t.get("amount", 0) for t in history if t.get("amount")]
    locations = [t.get("location", "") for t in history if t.get("location")]
    devices = [t.get("device", "") for t in history if t.get("device")]

    hours: list[int] = []
    for t in history:
        try:
            hours.append(datetime.fromisoformat(t["datetime"]).hour)
        except (KeyError, ValueError):
            pass

    profile: dict[str, Any] = {
        "customer_id": customer_id,
        "typical_amount_range": None,
        "typical_hours": None,
        "typical_locations": [],
        "known_devices": [],
        "behavioral_deviation_score": None,
        "anomalies_found": [],
    }

    if amounts:
        profile["typical_amount_range"] = (
            f"R$ {min(amounts):,.2f} – R$ {max(amounts):,.2f} "
            f"(média: R$ {sum(amounts)/len(amounts):,.2f})"
        )

    if hours:
        h_counter = Counter(hours)
        common_hours = sorted(h_counter, key=h_counter.get, reverse=True)[:3]  # type: ignore[arg-type]
        profile["typical_hours"] = f"{common_hours[0]:02d}h–{common_hours[-1]:02d}h (horas mais frequentes)"

    if locations:
        profile["typical_locations"] = list(dict.fromkeys(locations))[:5]  # únicos, ordem de aparição

    if devices:
        profile["known_devices"] = list(dict.fromkeys(devices))[:5]

    return profile


def _detect_device_sharing(
    customer_id: str,
    device: str,
    all_transactions: list[dict],
) -> list[str]:
    """Verifica se o mesmo dispositivo foi usado por outros clientes."""
    if not device or not all_transactions or "desconhecido" not in device.lower():
        return []

    others = [
        t.get("customer_id")
        for t in all_transactions
        if t.get("device") == device and t.get("customer_id") != customer_id
    ]
    if others:
        unique_others = list(set(others))
        return [
            f"Dispositivo '{device}' também usado por: {', '.join(unique_others[:5])}."
        ]
    return []


def _detect_receiver_suspicion(
    receiver_id: str | None,
    all_transactions: list[dict],
    detection_result: dict,
) -> dict:
    """Verifica se o destinatário aparece em outros eventos suspeitos."""
    profile: dict[str, Any] = {
        "receiver_id": receiver_id or "Dado não disponível",
        "appears_in_other_suspicious": False,
        "receiver_notes": None,
    }

    if not receiver_id or not all_transactions:
        profile["receiver_notes"] = "Dado não disponível — receiver_id ausente."
        return profile

    # Transações onde o receiver aparece como destinatário ou remetente
    related = [
        t for t in all_transactions
        if t.get("receiver_id") == receiver_id or t.get("customer_id") == receiver_id
    ]

    # Considera suspeitos os que têm device desconhecido ou horário incomum
    suspicious_related = [
        t for t in related
        if "desconhecido" in str(t.get("device", "")).lower()
        or t.get("label") == "suspeita"
    ]

    if suspicious_related:
        profile["appears_in_other_suspicious"] = True
        profile["receiver_notes"] = (
            f"Destinatário encontrado em {len(suspicious_related)} evento(s) com indicadores suspeitos."
        )
    elif related:
        profile["receiver_notes"] = (
            f"Destinatário encontrado em {len(related)} transação(ões) sem indicadores adicionais."
        )
    else:
        profile["receiver_notes"] = "Destinatário não encontrado em outros eventos do dataset."

    return profile


def _compute_behavioral_deviation(
    transaction: dict,
    history: list[dict],
    criteria_flags: dict,
) -> float:
    """Score de desvio comportamental [0.0–1.0] calculado deterministicamente."""
    if not history:
        return 0.5  # sem histórico: incerteza moderada

    score = 0.0
    weights = {
        "valor_elevado": 0.20,
        "horario_incomum": 0.15,
        "frequencia_elevada": 0.25,
        "valor_repetido": 0.15,
        "mudanca_geografica": 0.15,
        "dispositivo_desconhecido": 0.10,
    }
    for criterion, weight in weights.items():
        if criteria_flags.get(criterion):
            score += weight

    return round(min(score, 1.0), 3)


# ── Interface principal do agente ─────────────────────────────────────────────

def run(
    transaction: dict[str, Any],
    detection_result: dict[str, Any],
    customer_history: list[dict] | None = None,
    all_transactions: list[dict] | None = None,
) -> dict:
    """
    Executa o Agente 2 — Investigação e Correlação.

    Returns:
        Dicionário compatível com InvestigationResult do schemas.py.
    """
    settings = get_settings()
    history = customer_history or []
    all_txs = all_transactions or []
    tx_id = transaction.get("transaction_id", "UNKNOWN")
    customer_id = transaction.get("customer_id", "UNKNOWN")
    receiver_id = transaction.get("receiver_id")
    device = transaction.get("device", "")
    criteria_flags = detection_result.get("criteria_flags", {})

    logger.info("[Agente2] Investigando %s", tx_id)

    # ── Extração determinística ───────────────────────────────────────────────
    sender_profile = _build_sender_profile_deterministic(customer_id, history)
    receiver_profile = _detect_receiver_suspicion(receiver_id, all_txs, detection_result)

    # Score de desvio comportamental (determinístico)
    dev_score = _compute_behavioral_deviation(transaction, history, criteria_flags)
    sender_profile["behavioral_deviation_score"] = dev_score

    # Anomalias óbvias do histórico
    anomalies: list[str] = []
    device_sharing = _detect_device_sharing(customer_id, device, all_txs)
    anomalies.extend(device_sharing)
    det_evidence = detection_result.get("deterministic_evidence", [])
    if det_evidence:
        anomalies.extend(det_evidence)
    sender_profile["anomalies_found"] = anomalies

    # ── Síntese via LLM ───────────────────────────────────────────────────────
    crossed_indicators: list[str] = []
    correlated_events: list[str] = []
    investigation_summary = "Investigação concluída com base nos dados disponíveis."
    missing_data: list[str] = []
    llm_generated = True

    context = {
        "transaction": transaction,
        "criteria_flags": criteria_flags,
        "sender_profile": sender_profile,
        "receiver_profile": receiver_profile,
        "history_count": len(history),
        "dataset_count": len(all_txs),
    }

    user_msg = (
        f"TRANSAÇÃO SUSPEITA:\n{json.dumps(transaction, ensure_ascii=False)}\n\n"
        f"CRITÉRIOS CONFIRMADOS: {[k for k, v in criteria_flags.items() if v]}\n\n"
        f"PERFIL DO REMETENTE:\n{json.dumps(sender_profile, ensure_ascii=False)}\n\n"
        f"PERFIL DO DESTINATÁRIO:\n{json.dumps(receiver_profile, ensure_ascii=False)}\n\n"
        f"HISTÓRICO DO REMETENTE ({len(history)} transações disponíveis): "
        f"{json.dumps(history[-5:], ensure_ascii=False) if history else '[]'}\n\n"
        "Produza a síntese investigativa."
    )

    try:
        resp = gemini_client.generate_json(
            model_id=settings.gemini_model_agent2,
            system_prompt=_SYSTEM_PROMPT,
            user_message=user_msg,
            temperature=0.3,
            max_output_tokens=768,
        )
        crossed_indicators = resp.get("crossed_indicators", [])
        correlated_events = resp.get("correlated_events", [])
        investigation_summary = resp.get("investigation_summary", investigation_summary)
        missing_data = resp.get("missing_data", [])
    except Exception as exc:
        logger.warning("[Agente2] LLM indisponível: %s", exc)
        llm_generated = False
        # Fallback determinístico — não inventa, apenas relata o que foi encontrado
        crossed_indicators = [
            f"{k} confirmado" for k, v in criteria_flags.items() if v
        ]
        investigation_summary = (
            f"Análise automática: {len(crossed_indicators)} critério(s) confirmado(s) "
            f"deterministicamente. Score de desvio: {dev_score:.2f}. "
            f"LLM indisponível — síntese narrativa não gerada."
        )
        if not receiver_id:
            missing_data.append("receiver_id ausente no payload.")
        if not history:
            missing_data.append("Histórico do cliente indisponível.")

    return {
        "transaction_id": tx_id,
        "sender_profile": sender_profile,
        "receiver_profile": receiver_profile,
        "crossed_indicators": crossed_indicators,
        "correlated_events": correlated_events,
        "investigation_summary": investigation_summary,
        "data_collection_status": "completo" if history and receiver_id else "parcial",
        "missing_data": missing_data,
        "llm_generated": llm_generated,
    }
