"""
Especificação executável das 6 regras de detecção (valores-limite e casos de borda).

Por padrão roda contra o ORÁCULO (oraculo_regras.py), provando que a especificação é coerente.
Para testar o código real, troque a linha `avaliar = oraculo.avaliar` por um adaptador
que chame sua função (ex.: a do Agente 1 / orquestrador) e retorne um set de nomes de regras.

Rodar:  pytest tests/test_regras_spec.py -v
"""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

import oraculo_regras as oraculo

avaliar = oraculo.avaliar  # <-- TROQUE pelo adaptador da implementação real

BASE = datetime(2024, 6, 10, 14, 0, 0)  # segunda, 14h: horário "normal"


def tx(amount="100.00", dt=BASE, loc="São Paulo, BR", device="disp_conhecido", cid="CLI-1", tid="T"):
    return dict(transaction_id=tid, customer_id=cid, amount=Decimal(amount), datetime=dt,
                location=loc, device=device, channel="internet_banking")


# ── 1. Valor elevado (limite estrito: > 5000) ──────────────────────────────────
@pytest.mark.parametrize("valor,esperado", [
    ("4999.99", False), ("5000.00", False),   # borda: exatamente 5000 NÃO dispara (README usa ">")
    ("5000.01", True), ("9800.00", True),
])
def test_valor_elevado(valor, esperado):
    assert ("valor_elevado" in avaliar(tx(valor))) is esperado


# ── 2. Horário incomum (22h–6h cruza a meia-noite) ─────────────────────────────
@pytest.mark.parametrize("hh,mm,esperado", [
    (21, 59, False), (22, 0, True), (23, 59, True),
    (0, 0, True), (2, 37, True), (5, 59, True),
    (6, 0, False), (14, 0, False),
])
def test_horario_incomum(hh, mm, esperado):
    dt = BASE.replace(hour=hh, minute=mm)
    assert ("horario_incomum" in avaliar(tx(dt=dt))) is esperado


# ── 3. Frequência (> 3 transações em 10 min) ───────────────────────────────────
def _rajada(n, espacamento_s=60):
    return [tx(dt=BASE + timedelta(seconds=i * espacamento_s), tid=f"H{i}") for i in range(n)]


@pytest.mark.parametrize("anteriores,esperado", [
    (2, False),   # atual = 3ª  -> não dispara
    (3, True),    # atual = 4ª  -> dispara (> 3)
    (5, True),
])
def test_frequencia_contagem(anteriores, esperado):
    hist = _rajada(anteriores)
    atual = tx(dt=BASE + timedelta(seconds=anteriores * 60), tid="ATUAL")
    assert ("frequencia_elevada" in avaliar(atual, hist)) is esperado


def test_frequencia_fora_da_janela_nao_conta():
    hist = _rajada(3, espacamento_s=0)                      # 3 tx em BASE
    atual = tx(dt=BASE + timedelta(minutes=10, seconds=1))  # 10min01s depois
    assert "frequencia_elevada" not in avaliar(atual, hist)


def test_frequencia_isola_por_cliente():
    hist = [tx(cid="OUTRO", dt=BASE, tid=f"O{i}") for i in range(5)]
    assert "frequencia_elevada" not in avaliar(tx(dt=BASE + timedelta(minutes=1)), hist)


# ── 4. Valores semelhantes  [DEFINIR tolerância e quantidade] ──────────────────
def test_valores_semelhantes_dispara():
    hist = [tx("1000.00", BASE - timedelta(hours=h), tid=f"S{h}") for h in (1, 2)]
    assert "valores_semelhantes" in avaliar(tx("1030.00"), hist)       # +3% e +3%


def test_valores_diferentes_nao_dispara():
    hist = [tx("1000.00", BASE - timedelta(hours=h), tid=f"S{h}") for h in (1, 2)]
    assert "valores_semelhantes" not in avaliar(tx("1200.00"), hist)


# ── 5. Mudança geográfica  [DEFINIR critério; hoje location é texto livre] ─────
def test_geo_cidade_diferente_em_30min_dispara():
    hist = [tx(loc="São Paulo, BR", dt=BASE - timedelta(minutes=30))]
    assert "mudanca_geografica" in avaliar(tx(loc="Miami, EUA"), hist)


def test_geo_mesma_cidade_nao_dispara():
    hist = [tx(loc="São Paulo, BR", dt=BASE - timedelta(minutes=30))]
    assert "mudanca_geografica" not in avaliar(tx(loc="São Paulo, BR"), hist)


def test_geo_viagem_plausivel_nao_dispara():
    hist = [tx(loc="São Paulo, BR", dt=BASE - timedelta(hours=10))]
    assert "mudanca_geografica" not in avaliar(tx(loc="Miami, EUA"), hist)


@pytest.mark.xfail(reason="Texto livre: 'Sao Paulo' x 'São Paulo, BR' gera falso positivo. Normalizar localização.")
def test_geo_normalizacao_de_texto():
    hist = [tx(loc="São Paulo, BR", dt=BASE - timedelta(minutes=30))]
    assert "mudanca_geografica" not in avaliar(tx(loc="Sao Paulo, Brasil"), hist)


# ── 6. Dispositivo ─────────────────────────────────────────────────────────────
def test_dispositivo_novo_dispara():
    hist = [tx(device="iphone_A", dt=BASE - timedelta(days=1))]
    assert "dispositivo_desconhecido" in avaliar(tx(device="android_Z"), hist)


def test_dispositivo_conhecido_nao_dispara():
    hist = [tx(device="iphone_A", dt=BASE - timedelta(days=1))]
    assert "dispositivo_desconhecido" not in avaliar(tx(device="iphone_A"), hist)


def test_rotulo_literal_dispositivo_desconhecido_dispara():
    assert "dispositivo_desconhecido" in avaliar(tx(device="dispositivo_desconhecido"))


# ── Caso do README (TXN-999) ───────────────────────────────────────────────────
def test_exemplo_do_readme():
    t = tx("9800.00", datetime(2024, 6, 10, 2, 37), "Miami, EUA", "dispositivo_desconhecido", "CLI-9999", "TXN-999")
    assert {"valor_elevado", "horario_incomum", "dispositivo_desconhecido"} <= avaliar(t)
