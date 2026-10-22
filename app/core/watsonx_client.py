"""
Cliente IBM WatsonX — obtém token IAM e expõe método generate()
para chamadas à API de inferência do watsonx.ai.
"""
import time
import logging
import requests
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_IAM_TOKEN_URL = "https://iam.cloud.ibm.com/identity/token"
_GENERATE_ENDPOINT = "{watsonx_url}/ml/v1/text/generation?version=2023-05-29"


class WatsonXClient:
    """Gerencia autenticação IAM e chamadas ao endpoint de geração de texto."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._access_token: str | None = None
        self._token_expiry: float = 0.0

    # ── Autenticação IAM ──────────────────────────────────────────────────────

    def _refresh_token(self) -> None:
        """Obtém (ou renova) o token de acesso via IBM IAM."""
        response = requests.post(
            _IAM_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                "apikey": self._settings.watsonx_api_key,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        self._access_token = payload["access_token"]
        # Renova 5 minutos antes de expirar
        self._token_expiry = time.time() + payload.get("expires_in", 3600) - 300
        logger.debug("Token IAM renovado com sucesso.")

    def _get_token(self) -> str:
        if self._access_token is None or time.time() >= self._token_expiry:
            self._refresh_token()
        return self._access_token  # type: ignore[return-value]

    # ── Geração de texto ──────────────────────────────────────────────────────

    def generate(
        self,
        model_id: str,
        prompt: str,
        parameters: dict[str, Any] | None = None,
    ) -> str:
        """
        Chama o endpoint de geração de texto do watsonx.ai.

        Args:
            model_id: ID do modelo LLM (ex: "ibm/granite-13b-instruct-v2").
            prompt:   Texto de entrada para o modelo.
            parameters: Parâmetros de inferência (temperature, max_new_tokens, …).

        Returns:
            Texto gerado pelo modelo.
        """
        url = _GENERATE_ENDPOINT.format(watsonx_url=self._settings.watsonx_url)
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        body: dict[str, Any] = {
            "model_id": model_id,
            "input": prompt,
            "project_id": self._settings.watsonx_project_id,
            "parameters": parameters or {},
        }

        response = requests.post(url, headers=headers, json=body, timeout=60)
        response.raise_for_status()
        data = response.json()

        try:
            return data["results"][0]["generated_text"].strip()
        except (KeyError, IndexError) as exc:
            raise ValueError(f"Resposta inesperada do WatsonX: {data}") from exc


# Instância singleton compartilhada entre os agentes
watsonx_client = WatsonXClient()
