"""
Simulador de Transações em Tempo Real
───────────────────────────────────────
Gera transações fictícias continuamente para simular o fluxo de um sistema
de pagamentos real (PIX, TED, cartão) integrado à infraestrutura da Núclea.

Em produção real, este módulo seria substituído por um consumidor de fila
(ex: Kafka, RabbitMQ) ou webhook do core bancário da Núclea.
"""
import random
import uuid
from datetime import datetime, timedelta
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

# ── Perfis de transação ────────────────────────────────────────────────────────

def _normal_transaction(seq: int) -> dict:
    """Gera uma transação de baixo risco — máximo 2 critérios."""
    now = datetime.now().replace(
        hour=random.randint(8, 20),
        minute=random.randint(0, 59),
    )
    return {
        "transaction_id": f"SIM-{seq:06d}",
        "customer_id": random.choice(_CUSTOMERS[:10]),
        "receiver_id": random.choice(_CUSTOMERS[5:]),
        "amount": round(random.uniform(50, 3000), 2),
        "datetime": now.isoformat(),
        "location": random.choice(_NORMAL_LOCATIONS),
        "channel": random.choice(_CHANNELS),
        "device": random.choice(_KNOWN_DEVICES),
        "simulated": True,
        "simulation_profile": "normal",
    }


def _suspicious_transaction(seq: int) -> dict:
    """Gera uma transação com 3 ou mais critérios de suspeita."""
    # Horário de madrugada
    now = datetime.now().replace(
        hour=random.choice([1, 2, 3, 4, 23]),
        minute=random.randint(0, 59),
    )
    # Escolhe aleatoriamente quais critérios disparar (sempre >= 3)
    profiles = [
        # Perfil 1: valor alto + madrugada + dispositivo desconhecido
        {
            "amount": round(random.uniform(6000, 15000), 2),
            "location": random.choice(_NORMAL_LOCATIONS),
            "device": random.choice(_UNKNOWN_DEVICES),
            "simulation_profile": "alto_valor_madrugada_dispositivo",
        },
        # Perfil 2: localização internacional + dispositivo desconhecido + madrugada
        {
            "amount": round(random.uniform(2000, 8000), 2),
            "location": random.choice(_SUSPICIOUS_LOCATIONS),
            "device": random.choice(_UNKNOWN_DEVICES),
            "simulation_profile": "geo_suspeita_dispositivo_madrugada",
        },
        # Perfil 3: valor alto + localização internacional + dispositivo desconhecido
        {
            "amount": round(random.uniform(8000, 20000), 2),
            "location": random.choice(_SUSPICIOUS_LOCATIONS),
            "device": random.choice(_UNKNOWN_DEVICES),
            "simulation_profile": "critico_multiplos_indicadores",
        },
    ]
    chosen = random.choice(profiles)
    return {
        "transaction_id": f"SIM-{seq:06d}",
        "customer_id": random.choice(_CUSTOMERS[10:]),
        "receiver_id": random.choice(_CUSTOMERS[:5]),
        "amount": chosen["amount"],
        "datetime": now.isoformat(),
        "location": chosen["location"],
        "channel": random.choice(_CHANNELS),
        "device": chosen["device"],
        "simulated": True,
        "simulation_profile": chosen["simulation_profile"],
    }


def _burst_transaction(seq: int, base_customer: str, base_amount: float) -> dict:
    """
    Gera transação de rafaga (frequência elevada + valor repetido).
    Representa tentativas de fracionamento de valor.
    """
    now = datetime.now().replace(
        hour=random.choice([2, 3, 14, 15]),
        minute=random.randint(0, 9),  # dentro de 10 minutos
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
    }


# ── Gerador principal ──────────────────────────────────────────────────────────

def generate_stream(
    total: int = 50,
    suspicious_ratio: float = 0.35,
    burst_ratio: float = 0.10,
) -> Generator[dict, None, None]:
    """
    Gera um stream de transações fictícias.

    Args:
        total:            Número total de transações a gerar.
        suspicious_ratio: Proporção de transações suspeitas (0.0 a 1.0).
        burst_ratio:      Proporção de transações em rajada (fracionamento).

    Yields:
        Dicionário de transação pronto para envio ao pipeline.
    """
    seq = 1
    burst_customer = random.choice(_CUSTOMERS[10:])
    burst_amount = round(random.uniform(400, 1200), 2)
    burst_count = 0
    max_burst = 4  # até 4 transações em rajada do mesmo cliente/valor

    for _ in range(total):
        roll = random.random()

        if roll < burst_ratio and burst_count < max_burst:
            tx = _burst_transaction(seq, burst_customer, burst_amount)
            burst_count += 1
        elif roll < burst_ratio + suspicious_ratio:
            tx = _suspicious_transaction(seq)
        else:
            tx = _normal_transaction(seq)

        seq += 1
        yield tx


def generate_single(force_suspicious: bool = False) -> dict:
    """Gera uma única transação aleatória."""
    seq = random.randint(100000, 999999)
    if force_suspicious:
        return _suspicious_transaction(seq)
    roll = random.random()
    if roll < 0.35:
        return _suspicious_transaction(seq)
    return _normal_transaction(seq)
