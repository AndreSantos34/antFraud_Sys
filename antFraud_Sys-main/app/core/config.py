"""
Configurações centrais da aplicação lidas do arquivo .env
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Google Gemini ─────────────────────────────────────────────────────────
    gemini_api_key: str = ""
    # Aliases recomendados — compatíveis com a maioria das contas gratuitas.
    # Execute: GET https://generativelanguage.googleapis.com/v1beta/models?key=SUA_CHAVE
    # para ver os modelos disponíveis na sua conta.
    gemini_model_agent1: str = "gemini-flash-lite-latest"  # Agente 1: detecção (justificativa)
    gemini_model_agent2: str = "gemini-flash-lite-latest"  # Agente 2: investigação + correlação
    gemini_model_agent3: str = "gemini-flash-lite-latest"  # Agente 3: risco + recomendações
    gemini_model_agent4: str = "gemini-flash-lite-latest"  # Agente 4: relatório executivo

    # ── Retry do cliente Gemini ───────────────────────────────────────────────
    gemini_retry_attempts: int = 2       # tentativas extras em caso de erro transitório
    gemini_retry_delay_s:  float = 3.0   # espera entre tentativas (segundos)

    # ── API ───────────────────────────────────────────────────────────────────
    app_port: int = 8000
    app_host: str = "0.0.0.0"
    debug: bool = True

    # ── Monitor background ────────────────────────────────────────────────────
    monitor_interval_seconds: float = 2.0
    monitor_autostart: bool = True

    # ── Segurança ─────────────────────────────────────────────────────────────
    api_secret_key: str = "nuclea-dev-key-change-in-production"

    # ── Thresholds de detecção determinística ────────────────────────────────
    high_value_threshold: float = 5000.00
    unusual_hour_start:   int = 22
    unusual_hour_end:     int = 6
    high_freq_max_tx:     int = 3
    high_freq_window_min: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()
