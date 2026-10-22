"""
Configurações centrais da aplicação lidas do arquivo .env
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── WatsonX ──────────────────────────────────────────────────────────────
    watsonx_api_key: str = ""
    watsonx_project_id: str = ""
    watsonx_url: str = "https://us-south.ml.cloud.ibm.com"

    # ── API ───────────────────────────────────────────────────────────────────
    app_port: int = 8000
    app_host: str = "0.0.0.0"
    debug: bool = True

    # ── Monitor background ────────────────────────────────────────────────────
    # Intervalo em segundos entre cada transação simulada
    monitor_interval_seconds: float = 2.0
    # Inicia o monitor automaticamente junto com a API
    monitor_autostart: bool = True

    # ── Segurança ─────────────────────────────────────────────────────────────
    # API Key para autenticar chamadas aos endpoints protegidos
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
