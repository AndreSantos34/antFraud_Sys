"""
Oráculo determinístico das 6 regras (implementação de REFERÊNCIA para testes).

Premissas assumidas a partir do README/env.example. As marcadas [DEFINIR] são lacunas
da especificação: o grupo precisa decidir e registrar no README.
"""
from datetime import datetime, timedelta
from decimal import Decimal

LIMITE_VALOR = Decimal("5000.00")        # README: "> R$ 5.000" (estrito)
HORA_INI, HORA_FIM = 22, 6                # janela que cruza a meia-noite
MAX_TX, JANELA_MIN = 3, 10                # README: "> 3 em 10 min"
TOLERANCIA_SIMILAR = Decimal("0.05")      # [DEFINIR] ±5%
MIN_SIMILARES = 2                         # [DEFINIR] >= 2 anteriores em 24h
JANELA_GEO_MIN = 60                       # [DEFINIR] cidade diferente em < 60 min


def avaliar(tx: dict, historico: list[dict] | None = None) -> set[str]:
    historico = [h for h in (historico or []) if h["customer_id"] == tx["customer_id"]]
    t = tx["datetime"]
    regras = set()

    if tx["amount"] > LIMITE_VALOR:
        regras.add("valor_elevado")

    if t.hour >= HORA_INI or t.hour < HORA_FIM:      # 22:00 incluso, 06:00 excluso
        regras.add("horario_incomum")

    na_janela = [h for h in historico if timedelta(0) <= t - h["datetime"] <= timedelta(minutes=JANELA_MIN)]
    if len(na_janela) + 1 > MAX_TX:                  # conta a transação atual
        regras.add("frequencia_elevada")

    similares = [
        h for h in historico
        if timedelta(0) < t - h["datetime"] <= timedelta(hours=24)
        and abs(h["amount"] - tx["amount"]) <= tx["amount"] * TOLERANCIA_SIMILAR
    ]
    if len(similares) >= MIN_SIMILARES:
        regras.add("valores_semelhantes")

    anteriores = sorted((h for h in historico if h["datetime"] < t), key=lambda h: h["datetime"])
    if anteriores:
        ult = anteriores[-1]
        if ult["location"] != tx["location"] and t - ult["datetime"] < timedelta(minutes=JANELA_GEO_MIN):
            regras.add("mudanca_geografica")

    conhecidos = {h["device"] for h in historico}
    if tx["device"] == "dispositivo_desconhecido" or (conhecidos and tx["device"] not in conhecidos):
        regras.add("dispositivo_desconhecido")

    return regras
