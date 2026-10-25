"""
Simulador de Transações em Tempo Real
───────────────────────────────────────
Gera transações fictícias com 5 perfis de risco graduados (score 1–100),
distribuídos proporcionalmente para exercitar toda a escala do pipeline.

Perfis de risco:
  • minimo    (score  1–20): transações cotidianas normais
  • baixo     (score 21–40): 1 critério leve ativado
  • medio     (score 41–60): 2 critérios moderados
  • alto      (score 61–80): 3 critérios combinados
  • critico   (score 81–100): 4+ critérios ou combinação severa

Em produção real, este módulo seria substituído por um consumidor de fila
(ex: Kafka, RabbitMQ) ou webhook do core bancário da Núclea.
"""
import random
import uuid
from datetime import datetime
from typing import Generator

# ── Pools de dados fictícios ───────────────────────────────────────────────────

_CUSTOMERS = [
    "CLI-1001", "CLI-1002", "CLI-1003", "CLI-1004", "CLI-1005",
    "CLI-1006", "CLI-1007", "CLI-1008", "CLI-1009", "CLI-1010",
    "CLI-2001", "CLI-2002", "CLI-2003", "CLI-2004", "CLI-2005",
]

_KNOWN_DEVICES = [
    "smartphone_conhecido", "notebook_pessoal", "desktop_corporativo",
]

_UNKNOWN_DEVICES = [
    "dispositivo_desconhecido_A", "dispositivo_desconhecido_B",
    "smartphone_desconhecido", "terminal_nao_registrado",
]

_NORMAL_LOCATIONS = [
    "São Paulo, SP", "Rio de Janeiro, RJ", "Curitiba, PR",
    "Belo Horizonte, MG", "Porto Alegre, RS", "Salvador, BA",
    "Fortaleza, CE", "Recife, PE", "Brasília, DF", "Goiânia, GO",
]

_SUSPICIOUS_LOCATIONS = [
    "Miami, EUA", "Tóquio, Japão", "Lagos, Nigéria",
    "Moscou, Rússia", "Amsterdã, Holanda",
]

_CHANNELS = ["app_mobile", "internet_banking", "caixa_eletronico", "pix_automatico"]

# ── Perfis de transação por faixa de risco ────────────────────────────────────

def _profile_minimo(seq: int) -> dict:
    """
    Risco MÍNIMO — score esperado 1–20.
    Transação cotidiana: horário comercial, valor baixo, dispositivo conhecido,
    localização habitual. Zero critérios de suspeita.
    """
    now = datetime.now().replace(
        hour=random.randint(9, 18),
        minute=random.randint(0, 59),
    )
    return {
        "transaction_id": f"SIM-{seq:06d}",
        "customer_id": random.choice(_CUSTOMERS[:10]),
        "receiver_id": random.choice(_CUSTOMERS[5:]),
        "amount": round(random.uniform(20.0, 800.0), 2),
        "datetime": now.isoformat(),
        "location": random.choice(_NORMAL_LOCATIONS),
        "channel": random.choice(_CHANNELS),
        "device": random.choice(_KNOWN_DEVICES),
        "simulated": True,
        "simulation_profile": "minimo",
        "risk_hint": "score_esperado:1-20 | zero_criterios | operacao_rotineira",
    }


def _profile_baixo(seq: int) -> dict:
    """
    Risco BAIXO — score esperado 21–40.
    Um único critério leve ativado: valor ligeiramente acima do limiar OU
    horário incomum isolado. Não justifica escalada sozinho — monitoramento preventivo.
    """
    now = datetime.now().replace(
        hour=random.choice([7, 8, 21, 22]),   # horário limítrofe
        minute=random.randint(0, 59),
    )
    # Alterna entre dois sub-perfis de 1 critério
    if random.random() < 0.5:
        # Sub-perfil A: só valor elevado (acima de R$5k, mas modesto)
        amount = round(random.uniform(5_100.0, 7_500.0), 2)
        hour = random.randint(9, 18)
        now = now.replace(hour=hour)
        device = random.choice(_KNOWN_DEVICES)
        location = random.choice(_NORMAL_LOCATIONS)
        sub = "valor_elevado_isolado"
    else:
        # Sub-perfil B: só horário incomum (madrugada, valor baixo)
        amount = round(random.uniform(50.0, 800.0), 2)
        now = now.replace(hour=random.choice([23, 0, 1, 5, 6]))
        device = random.choice(_KNOWN_DEVICES)
        location = random.choice(_NORMAL_LOCATIONS)
        sub = "horario_incomum_isolado"
    return {
        "transaction_id": f"SIM-{seq:06d}",
        "customer_id": random.choice(_CUSTOMERS[:10]),
        "receiver_id": random.choice(_CUSTOMERS[5:]),
        "amount": amount,
        "datetime": now.isoformat(),
        "location": location,
        "channel": random.choice(_CHANNELS),
        "device": device,
        "simulated": True,
        "simulation_profile": f"baixo_{sub}",
        "risk_hint": f"score_esperado:21-40 | 1_criterio | {sub}",
    }


def _profile_medio(seq: int) -> dict:
    """
    Risco MÉDIO — score esperado 41–60.
    3 critérios: horario_incomum + dispositivo_desconhecido + (valor_elevado OU mudanca_geografica).
    Score base: 14+17+16=47 ou 14+17+19=50 → faixa médio (41-60).
    """
    now = datetime.now().replace(
        hour=random.choice([1, 2, 3, 4]),   # madrugada garantida
        minute=random.randint(0, 59),
    )
    profiles = [
        # 3 critérios: valor elevado + madrugada + dispositivo desconhecido
        {
            "amount": round(random.uniform(5_500.0, 12_000.0), 2),   # > R$5k
            "device": random.choice(_UNKNOWN_DEVICES),
            "location": random.choice(_NORMAL_LOCATIONS),             # sem geo suspeita
            "sub": "valor_madrugada_dispositivo",
        },
        # 3 critérios: geo suspeita + madrugada + dispositivo desconhecido (valor abaixo do limiar)
        {
            "amount": round(random.uniform(300.0, 4_500.0), 2),       # < R$5k (sem valor_elevado)
            "device": random.choice(_UNKNOWN_DEVICES),
            "location": random.choice(_SUSPICIOUS_LOCATIONS),
            "sub": "geo_madrugada_dispositivo",
        },
    ]
    chosen = random.choice(profiles)
    return {
        "transaction_id": f"SIM-{seq:06d}",
        "customer_id": random.choice(_CUSTOMERS[:12]),
        "receiver_id": random.choice(_CUSTOMERS[3:]),
        "amount": chosen["amount"],
        "datetime": now.isoformat(),
        "location": chosen["location"],
        "channel": random.choice(_CHANNELS),
        "device": chosen["device"],
        "simulated": True,
        "simulation_profile": f"medio_{chosen['sub']}",
        "risk_hint": f"score_esperado:41-60 | 3_criterios | {chosen['sub']}",
    }


def _profile_alto(seq: int) -> dict:
    """
    Risco ALTO — score esperado 61–80.
    4 critérios garantidos: valor_elevado + horario_incomum + mudanca_geografica + dispositivo_desconhecido
    Score base: 16+14+19+17 = 66 → faixa alto (61-80).
    Sem fracionamento — distingue do perfil crítico.
    """
    now = datetime.now().replace(
        hour=random.choice([1, 2, 3, 4]),   # madrugada garantida
        minute=random.randint(0, 59),
    )
    return {
        "transaction_id": f"SIM-{seq:06d}",
        "customer_id": random.choice(_CUSTOMERS[10:]),
        "receiver_id": random.choice(_CUSTOMERS[:5]),
        "amount": round(random.uniform(6_000.0, 18_000.0), 2),   # > R$5k → valor_elevado
        "datetime": now.isoformat(),
        "location": random.choice(_SUSPICIOUS_LOCATIONS),         # pais risco → mudanca_geografica
        "channel": random.choice(_CHANNELS),
        "device": random.choice(_UNKNOWN_DEVICES),                 # → dispositivo_desconhecido
        "simulated": True,
        "simulation_profile": "alto_4_criterios",
        "risk_hint": "score_esperado:61-80 | 4_criterios | valor+horario+geo+dispositivo (sem fracionamento)",
    }


def _profile_critico(seq: int) -> dict:
    """
    Risco CRÍTICO — score esperado 81–100.
    4+ critérios garantidos deterministicamente:
      - valor_elevado      → amount > R$15k (sempre acima do limiar de R$5k)
      - horario_incomum    → madrugada (1h–4h)
      - mudanca_geografica → localização em _SUSPICIOUS_LOCATIONS (país de alto risco)
      - dispositivo_desconhecido → device contém "desconhecido"
      Sub-perfil "fracionamento" acrescenta frequencia_elevada (5° critério) via
      simulation_profile, detectado deterministicamente pelo screener.
    """
    now = datetime.now().replace(
        hour=random.choice([1, 2, 3, 4]),
        minute=random.randint(0, 59),
    )
    # Todos os sub-perfis usam simulation_profile "fracionamento_suspeito" para garantir
    # que frequencia_elevada seja ativada como 5° critério (score 86-100).
    # 4 critérios base (valor+horario+geo+dispositivo) = 66 pts → alto, não crítico.
    # Com frequencia_elevada (+20) = 86 pts → crítico garantido.
    profiles = [
        # 5 critérios: valor alto + madrugada + geo + dispositivo + fracionamento
        {
            "amount": round(random.uniform(15_000.0, 50_000.0), 2),
            "location": random.choice(_SUSPICIOUS_LOCATIONS),
            "device": random.choice(_UNKNOWN_DEVICES),
            "channel": "internet_banking",
            "simulation_profile": "fracionamento_suspeito",
            "sub": "5_criterios_valor_geo_fracionamento",
        },
        # 5 critérios: valor moderado + madrugada + geo + dispositivo + fracionamento
        {
            "amount": round(random.uniform(5_500.0, 12_000.0), 2),
            "location": random.choice(_SUSPICIOUS_LOCATIONS),
            "device": random.choice(_UNKNOWN_DEVICES),
            "channel": "app_mobile",
            "simulation_profile": "fracionamento_suspeito",
            "sub": "5_criterios_fracionamento_geo",
        },
        # 5 critérios: valor extremo + madrugada + geo + dispositivo + fracionamento
        {
            "amount": round(random.uniform(30_000.0, 80_000.0), 2),
            "location": random.choice(_SUSPICIOUS_LOCATIONS),
            "device": random.choice(_UNKNOWN_DEVICES),
            "channel": "internet_banking",
            "simulation_profile": "fracionamento_suspeito",
            "sub": "5_criterios_valor_extremo_fracionamento",
        },
    ]
    chosen = random.choice(profiles)
    return {
        "transaction_id": f"SIM-{seq:06d}",
        "customer_id": random.choice(_CUSTOMERS[10:]),
        "receiver_id": random.choice(_CUSTOMERS[:3]),
        "amount": chosen["amount"],
        "datetime": now.isoformat(),
        "location": chosen["location"],
        "channel": chosen["channel"],
        "device": chosen["device"],
        "simulated": True,
        "simulation_profile": chosen["simulation_profile"],
        "risk_hint": f"score_esperado:81-100 | 4+_criterios | {chosen['sub']}",
    }


def _burst_transaction(seq: int, base_customer: str, base_amount: float) -> dict:
    """
    Risco CRÍTICO — fracionamento (structuring).
    Mesmo cliente, mesmo valor, em janela de 10 min → frequência elevada.
    Score esperado 75–95 por acumular frequencia_elevada + valor_repetido.
    """
    now = datetime.now().replace(
        hour=random.choice([2, 3, 14, 15]),
        minute=random.randint(0, 9),
    )
    return {
        "transaction_id": f"SIM-{seq:06d}",
        "customer_id": base_customer,
        "receiver_id": random.choice(_CUSTOMERS[:5]),
        "amount": base_amount,
        "datetime": now.isoformat(),
        "location": random.choice(_NORMAL_LOCATIONS),
        "channel": "app_mobile",
        "device": random.choice(_UNKNOWN_DEVICES),
        "simulated": True,
        "simulation_profile": "fracionamento_suspeito",
        "risk_hint": "score_esperado:75-95 | frequencia_elevada+valor_repetido | structuring",
    }


# ── Gerador principal ──────────────────────────────────────────────────────────

# Distribuição de perfis para cobrir toda a escala 1–100
# Total: 100 transações com distribuição realista
_PROFILE_DISTRIBUTION = [
    ("minimo",  0.30),   # 30% → score  1–20
    ("baixo",   0.20),   # 20% → score 21–40
    ("medio",   0.20),   # 20% → score 41–60
    ("alto",    0.15),   # 15% → score 61–80
    ("critico", 0.10),   # 10% → score 81–100
    ("burst",   0.05),   #  5% → fracionamento (score 75–95)
]


def generate_stream(
    total: int = 100,
    suspicious_ratio: float = 0.35,
    burst_ratio: float = 0.05,
) -> Generator[dict, None, None]:
    """
    Gera um stream de até 100 transações com distribuição graduada de risco (1–100).

    A distribuição cobre todos os 5 níveis de risco, permitindo que os agentes
    LLM exercitem toda a escala de score e justificativas proporcionais.

    Args:
        total:            Número total de transações (máximo recomendado: 100).
        suspicious_ratio: Parâmetro legado — mantido para compatibilidade de chamadas.
        burst_ratio:      Proporção de transações em rajada (fracionamento).

    Yields:
        Dicionário de transação com campo `risk_hint` indicando o score esperado.
    """
    total = min(total, 100)   # nunca excede 100

    seq = 1
    burst_customer = random.choice(_CUSTOMERS[10:])
    burst_amount = round(random.uniform(400, 1_200), 2)
    burst_count = 0
    max_burst = 5

    _profile_fns = {
        "minimo":  _profile_minimo,
        "baixo":   _profile_baixo,
        "medio":   _profile_medio,
        "alto":    _profile_alto,
        "critico": _profile_critico,
    }

    # Monta lista de perfis baseada nas proporções (garante distribuição determinística)
    profile_slots: list[str] = []
    for name, ratio in _PROFILE_DISTRIBUTION:
        count = max(1, round(total * ratio))
        profile_slots.extend([name] * count)

    # Ajusta para bater exatamente em `total`
    while len(profile_slots) < total:
        profile_slots.append("minimo")
    profile_slots = profile_slots[:total]
    random.shuffle(profile_slots)

    for slot in profile_slots:
        if slot == "burst" and burst_count < max_burst:
            tx = _burst_transaction(seq, burst_customer, burst_amount)
            burst_count += 1
        elif slot == "burst":
            # burst esgotado — degrada para alto
            tx = _profile_alto(seq)
        else:
            tx = _profile_fns[slot](seq)

        seq += 1
        yield tx


def generate_single(force_suspicious: bool = False) -> dict:
    """
    Gera uma única transação aleatória com perfil de risco graduado.

    Distribuição: 30% mínimo, 20% baixo, 20% médio, 15% alto, 10% crítico, 5% burst.
    """
    seq = random.randint(100_000, 999_999)

    if force_suspicious:
        return random.choice([_profile_alto, _profile_critico])(seq)

    roll = random.random()
    if roll < 0.30:
        return _profile_minimo(seq)
    if roll < 0.50:
        return _profile_baixo(seq)
    if roll < 0.70:
        return _profile_medio(seq)
    if roll < 0.85:
        return _profile_alto(seq)
    if roll < 0.95:
        return _profile_critico(seq)
    # 5%: burst isolado
    burst_customer = random.choice(_CUSTOMERS[10:])
    burst_amount = round(random.uniform(400, 1_200), 2)
    return _burst_transaction(seq, burst_customer, burst_amount)
