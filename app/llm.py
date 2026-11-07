"""Camada de provedor de LLM.

O restante da aplicação conversa só com `LLMClient`. Hoje há duas implementações:
- `OpenAIClient`: chat (JSON estruturado) e embeddings.
- `NullClient`: usado quando LLM_PROVIDER=none ou sem chave; a aplicação cai no modo determinístico.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.config import settings

log = logging.getLogger("aurora.llm")

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


class LLMError(RuntimeError):
    pass


class LLMClient:
    enabled: bool = False
    name: str = "none"

    def json_chat(self, system: str, user: str) -> dict[str, Any]:
        raise LLMError("LLM desabilitado")

    def text_chat(self, system: str, user: str) -> str:
        raise LLMError("LLM desabilitado")

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise LLMError("Embeddings desabilitados")

    @property
    def embedding_model(self) -> str | None:
        return None


class NullClient(LLMClient):
    pass


def _extract_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise LLMError(f"Resposta do modelo não contém JSON: {text[:200]}")
        return json.loads(match.group(0))


class OpenAIClient(LLMClient):
    enabled = True
    name = "openai"

    def __init__(self) -> None:
        from openai import OpenAI

        # base_url sempre explícito: com OPENAI_BASE_URL= vazio no .env, o SDK usaria "" como endereço da API
        self._client = OpenAI(api_key=settings.openai_api_key, timeout=settings.llm_timeout_s, max_retries=2,
                              base_url=settings.openai_base_url or DEFAULT_OPENAI_BASE_URL)
        self.model = settings.openai_model

    def _chat(self, system: str, user: str, json_mode: bool) -> str:
        params: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if json_mode:
            params["response_format"] = {"type": "json_object"}
        try:
            resp = self._client.chat.completions.create(**params)
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc
        content = resp.choices[0].message.content or ""
        return content.strip()

    def json_chat(self, system: str, user: str) -> dict[str, Any]:
        return _extract_json(self._chat(system, user, json_mode=True))

    def text_chat(self, system: str, user: str) -> str:
        return self._chat(system, user, json_mode=False)

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            resp = self._client.embeddings.create(model=settings.openai_embedding_model, input=texts)
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc
        return [item.embedding for item in resp.data]

    @property
    def embedding_model(self) -> str | None:
        return settings.openai_embedding_model


_client: LLMClient | None = None


def get_llm() -> LLMClient:
    global _client
    if _client is None:
        if settings.llm_enabled:
            _client = OpenAIClient()
            log.info("LLM habilitado: openai (%s)", settings.openai_model)
        else:
            _client = NullClient()
            log.warning("LLM desabilitado (LLM_PROVIDER=%s, chave %s). Modo determinístico.",
                        settings.llm_provider, "presente" if settings.openai_api_key else "ausente")
    return _client


def set_llm(client: LLMClient) -> None:
    """Permite injetar um cliente falso nos testes."""
    global _client
    _client = client
