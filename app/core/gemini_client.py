"""
Cliente Google Gemini — autenticação por API Key e geração de texto com
resposta forçada em JSON via response_mime_type.

Vantagem sobre chamada raw: o Gemini garante JSON válido na saída,
eliminando erros de parsing nos agentes.
"""
import json
import logging
import requests
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiClient:
    """Gerencia chamadas à API Gemini com saída JSON garantida."""

    def __init__(self) -> None:
        self._settings = get_settings()

    def generate(
        self,
        model_id: str,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.2,
        max_output_tokens: int = 1024,
    ) -> str:
        """
        Chama a API Gemini e retorna o texto gerado.

        Args:
            model_id:          ID do modelo (ex: "gemini-1.5-flash").
            system_prompt:     Instrução de sistema (papel e regras do agente).
            user_message:      Mensagem com os dados a analisar.
            temperature:       Criatividade da resposta (0.0 = determinístico).
            max_output_tokens: Limite de tokens na saída.

        Returns:
            String com o JSON gerado pelo modelo.
        """
        api_key = self._settings.gemini_api_key
        url = _BASE_URL.format(model=model_id)

        body: dict[str, Any] = {
            "system_instruction": {
                "parts": [{"text": system_prompt}]
            },
            "contents": [
                {"role": "user", "parts": [{"text": user_message}]}
            ],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
                "responseMimeType": "application/json",  # garante JSON puro na saída
            },
        }

        response = requests.post(
            url,
            params={"key": api_key},
            headers={"Content-Type": "application/json"},
            json=body,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()

        try:
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError) as exc:
            raise ValueError(f"Resposta inesperada do Gemini: {data}") from exc

    def generate_json(
        self,
        model_id: str,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.2,
        max_output_tokens: int = 1024,
    ) -> dict:
        """
        Chama generate() e já desserializa o JSON retornado.

        Returns:
            Dicionário Python com o resultado do modelo.

        Raises:
            ValueError: se o modelo retornar JSON inválido.
        """
        raw = self.generate(model_id, system_prompt, user_message, temperature, max_output_tokens)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Gemini retornou JSON inválido: {raw[:300]}") from exc


# Instância singleton compartilhada entre os agentes
gemini_client = GeminiClient()
