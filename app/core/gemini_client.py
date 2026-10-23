"""
Cliente Google Gemini — autenticação por API Key e geração de texto com
resposta forçada em JSON via response_mime_type.

Vantagem sobre chamada raw: o Gemini garante JSON válido na saída,
eliminando erros de parsing nos agentes.
"""
import json
import logging
import time
import requests
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiAPIError(Exception):
    """Erro de chamada à API Gemini com detalhes do status HTTP."""
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}: {message}")


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

        Raises:
            GeminiAPIError: para erros HTTP com status e mensagem legíveis.
            ValueError: se a estrutura da resposta for inesperada.
        """
        api_key = self._settings.gemini_api_key

        if not api_key:
            raise GeminiAPIError(0, "GEMINI_API_KEY não configurada.")

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

        max_attempts = 1 + max(0, self._settings.gemini_retry_attempts)
        last_exc: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                response = requests.post(
                    url,
                    params={"key": api_key},
                    headers={"Content-Type": "application/json"},
                    json=body,
                    timeout=60,
                )
            except requests.Timeout:
                last_exc = GeminiAPIError(0, f"Timeout na chamada ao modelo '{model_id}' (>60s).")
                if attempt < max_attempts:
                    time.sleep(self._settings.gemini_retry_delay_s)
                    continue
                raise last_exc  # type: ignore[misc]
            except requests.ConnectionError as exc:
                last_exc = GeminiAPIError(0, f"Erro de conexão com a API Gemini: {exc}.")
                if attempt < max_attempts:
                    time.sleep(self._settings.gemini_retry_delay_s)
                    continue
                raise last_exc  # type: ignore[misc]

            # Trata erros HTTP com mensagens diagnósticas específicas
            if not response.ok:
                status = response.status_code
                try:
                    err_body = response.json()
                    err_msg = err_body.get("error", {}).get("message", response.text[:200])
                except Exception:
                    err_msg = response.text[:200]

                if status == 400:
                    # 400 é erro de configuração — não adianta tentar novamente
                    raise GeminiAPIError(status, f"Requisição inválida (modelo '{model_id}' pode não existir): {err_msg}")
                elif status in (401, 403):
                    raise GeminiAPIError(status, f"Autenticação inválida — verifique GEMINI_API_KEY: {err_msg}")
                elif status == 429:
                    logger.warning("[GeminiClient] Rate limit (429) — tentativa %d/%d", attempt, max_attempts)
                    last_exc = GeminiAPIError(status, f"Rate limit atingido: {err_msg}")
                    if attempt < max_attempts:
                        time.sleep(self._settings.gemini_retry_delay_s * attempt)
                        continue
                    raise last_exc  # type: ignore[misc]
                elif status >= 500:
                    logger.warning("[GeminiClient] Erro de servidor (%d) — tentativa %d/%d", status, attempt, max_attempts)
                    last_exc = GeminiAPIError(status, f"API Gemini indisponível (serviço em erro): {err_msg}")
                    if attempt < max_attempts:
                        time.sleep(self._settings.gemini_retry_delay_s)
                        continue
                    raise last_exc  # type: ignore[misc]
                else:
                    raise GeminiAPIError(status, err_msg)

            # Resposta OK — sai do loop de retry
            break

        data = response.json()

        try:
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError) as exc:
            # Verifica se o modelo retornou finish_reason bloqueio (safety filter)
            finish_reason = None
            try:
                finish_reason = data["candidates"][0].get("finishReason")
            except (KeyError, IndexError):
                pass
            if finish_reason and finish_reason != "STOP":
                raise ValueError(
                    f"Gemini bloqueou a resposta (finishReason={finish_reason}). "
                    f"Revise o conteúdo do prompt ou o modelo utilizado."
                )
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
            GeminiAPIError: para erros HTTP da API.
            ValueError: se o modelo retornar JSON inválido ou resposta bloqueada.
        """
        raw = self.generate(model_id, system_prompt, user_message, temperature, max_output_tokens)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Gemini retornou JSON inválido: {raw[:300]}") from exc


# Instância singleton compartilhada entre os agentes
gemini_client = GeminiClient()
