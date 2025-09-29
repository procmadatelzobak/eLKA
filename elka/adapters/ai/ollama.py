"""Implementace AI adaptéru pro lokální server Ollama."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Iterator

import requests

from .base import BaseAIAdapter


class OllamaAdapter(BaseAIAdapter):
    """Adaptér pro komunikaci s Ollama REST API."""

    def __init__(self, provider_config: Dict[str, Any]):
        super().__init__(provider_config)
        base_url = provider_config.get("base_url")
        if not base_url:
            raise ValueError("Konfigurace Ollama adaptéru vyžaduje položku 'base_url'.")

        self.base_url = base_url.rstrip("/")
        self.timeout = provider_config.get("timeout", 60)
        self._session = requests.Session()

    def prompt(self, model_name: str, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": model_name,
            "system": system_prompt,
            "prompt": user_prompt,
        }

        url = f"{self.base_url}/api/generate"

        try:
            response = self._session.post(url, json=payload, stream=True, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:  # pragma: no cover - závislé na externím API
            raise RuntimeError(f"Ollama request failed: {exc}") from exc

        output_parts = [chunk for chunk in self._parse_stream(response.iter_lines()) if chunk]

        if not output_parts:
            raise RuntimeError("Ollama API nevrátilo žádnou odpověď.")

        return "".join(output_parts)

    def _parse_stream(self, lines: Iterable[bytes]) -> Iterator[str]:
        for line in lines:
            if not line:
                continue
            try:
                payload = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError:
                continue

            text = payload.get("response")
            if text:
                yield text
            if payload.get("done"):
                break

