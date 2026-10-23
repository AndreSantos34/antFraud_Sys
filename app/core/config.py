"""
Configurações centrais da aplicação lidas do arquivo .env
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── Google Gemini ─────────────────────────────────────────────────────────
    gemini_api_key: str = ""
    # Modelos por agente — podem ser sobrescritos no .env
    gemini_model_agent1: str = "gemini-3.8-flash"   # triagem rápida e determinística
    gemini_model_agent2: str = "gemini-3.8-flash"   # investigação contextual
    gemini_model_agent3: str = "gemini-3.8-flash"   # consolidação de evidências
    gemini_model_agent4: str = "gemini-3.5-flash"   # IA Mestre — maior capacidade

    # ── API ───────────────────────────────────────────────────────────────────
    app_port: int = 8000
    app_host: str = "0.0.0.0"
    debug: bool = True

    # ── Monitor background ────────────────────────────────────────────────────
    monitor_interval_seconds: float = 2.0
    monitor_autostart: bool = True

    # ── Segurança ─────────────────────────────────────────────────────────────
    api_secret_key: str = "nuclea-dev-key-change-in-production"

    # ── Thresholds de detecção ────────────────────────────────────────────────
    high_value_threshold: float = 5000.00
    unusual_hour_start: int = 22
    unusual_hour_end: int = 6
    high_freq_max_tx: int = 3
    high_freq_window_min: int = 10

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
