"""
conftest.py — configura variáveis de ambiente antes dos testes.

Injeta DATABASE_URL e outras variáveis obrigatórias para que pydantic-settings
consiga construir o objeto Settings sem depender do arquivo .env.

Ordem de prioridade:
  1. Variável já definida no ambiente (permite override externo)
  2. Valor padrão definido aqui (para CI / execução local sem .env)
"""
import os

# Só define se ainda não estiver no ambiente (não sobrescreve .env existente)
_DEFAULTS = {
    "DATABASE_URL": "mysql+pymysql://root:Password@localhost:3306/antfraud_db",
    "API_SECRET_KEY": "nuclea-dev-key-change-in-production",
    "MONITOR_AUTOSTART": "true",
    "MONITOR_INTERVAL_SECONDS": "2.0",
    "DEBUG": "true",
    "APP_PORT": "8000",
    "APP_HOST": "0.0.0.0",
    "WATSONX_API_KEY": "",
    "WATSONX_PROJECT_ID": "",
    "WATSONX_URL": "https://us-south.ml.cloud.ibm.com",
    "HIGH_VALUE_THRESHOLD": "5000.00",
    "UNUSUAL_HOUR_START": "22",
    "UNUSUAL_HOUR_END": "6",
    "HIGH_FREQ_MAX_TX": "3",
    "HIGH_FREQ_WINDOW_MIN": "10",
}

for key, value in _DEFAULTS.items():
    os.environ.setdefault(key, value)
