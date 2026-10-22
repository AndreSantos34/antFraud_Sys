"""
Testes do main.py (ciclo de vida, CORS, rotas públicas).

Rodar:  pytest tests/test_main.py -v

Os testes marcados com BUG descrevem o comportamento DESEJADO e hoje FALHAM de propósito:
cada um documenta um achado do relatório de QA. Depois de corrigir, devem passar.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

import main


class FakeMonitor:
    """Substitui o monitor real: sem chamadas ao WatsonX."""

    def __init__(self, crash_after=None):
        self.crash_after = crash_after
        self.started = False
        self.stop_called = False

    async def start(self):
        self.started = True
        if self.crash_after is not None:
            await asyncio.sleep(self.crash_after)
            raise RuntimeError("falha simulada no monitor")
        while not self.stop_called:
            await asyncio.sleep(0.01)

    def stop(self):
        self.stop_called = True


@pytest.fixture
def fake_monitor(monkeypatch):
    fm = FakeMonitor()
    monkeypatch.setattr(main, "fraud_monitor", fm)
    return fm


# ───────────────────────── caminho feliz ─────────────────────────
def test_root_retorna_metadados():
    with TestClient(main.app) as c:
        r = c.get("/")
    assert r.status_code == 200
    assert r.json()["versao"] == main.app.version


def test_autostart_true_inicia_e_shutdown_chama_stop(monkeypatch, fake_monitor):
    monkeypatch.setattr(main.settings, "monitor_autostart", True)
    with TestClient(main.app):
        pass
    assert fake_monitor.started and fake_monitor.stop_called


def test_autostart_false_nao_inicia_monitor(monkeypatch, fake_monitor):
    monkeypatch.setattr(main.settings, "monitor_autostart", False)
    with TestClient(main.app):
        pass
    assert not fake_monitor.started


# ───────────────────────── BUGS documentados ─────────────────────────
def test_BUG_shutdown_nao_deve_quebrar_se_monitor_falhou(monkeypatch):
    """[MÉDIO] Exceção do monitor só aparece no shutdown e derruba o encerramento."""
    monkeypatch.setattr(main, "fraud_monitor", FakeMonitor(crash_after=0.02))
    monkeypatch.setattr(main.settings, "monitor_autostart", True)
    with TestClient(main.app) as c:
        import time; time.sleep(0.1)  # monitor já morreu; API segue "saudável"
        assert c.get("/").status_code == 200
    # chegou aqui sem exceção => OK


def test_BUG_cors_nao_pode_refletir_origem_arbitraria_com_credenciais():
    """[ALTO] allow_origins=['*'] + allow_credentials=True reflete QUALQUER origem."""
    with TestClient(main.app) as c:
        r = c.get("/", headers={"Origin": "https://site-malicioso.example", "Cookie": "s=1"})
    assert r.headers.get("access-control-allow-origin") != "https://site-malicioso.example"


def test_BUG_chave_padrao_com_debug_false_deve_impedir_a_subida(monkeypatch):
    """[CRÍTICO] A chave padrão do env.example é pública: com DEBUG=false a config deve recusar."""
    config = pytest.importorskip("app.core.config")
    monkeypatch.setenv("API_SECRET_KEY", "nuclea-dev-key-change-in-production")
    monkeypatch.setenv("DEBUG", "false")
    getter = config.get_settings
    if hasattr(getter, "cache_clear"):
        getter.cache_clear()
    try:
        with pytest.raises(Exception):
            getter()
    finally:
        if hasattr(getter, "cache_clear"):
            getter.cache_clear()
