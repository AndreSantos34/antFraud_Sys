"""Define variáveis de ambiente ANTES de importar o main.py (que chama get_settings() no import)."""
import os

os.environ.setdefault("WATSONX_API_KEY", "test-key")
os.environ.setdefault("WATSONX_PROJECT_ID", "test-project")
os.environ.setdefault("WATSONX_URL", "https://us-south.ml.cloud.ibm.com")
os.environ.setdefault("API_SECRET_KEY", "chave-de-teste-forte-e-longa-123456")
os.environ.setdefault("MONITOR_AUTOSTART", "false")
