"""Implementace AI adaptéru pro Google Gemini."""

from __future__ import annotations

from typing import Any, Dict

import google.generativeai as genai

from .base import BaseAIAdapter


class GeminiAdapter(BaseAIAdapter):
    """Adaptér pro práci s Google Gemini API."""

    def __init__(self, provider_config: Dict[str, Any]):
        super().__init__(provider_config)
        api_key = provider_config.get("api_key")
        if not api_key:
            raise ValueError("Konfigurace Gemini adaptéru vyžaduje položku 'api_key'.")

        genai.configure(api_key=api_key)

    def prompt(self, model_name: str, system_prompt: str, user_prompt: str) -> str:
        try:
            model = genai.GenerativeModel(model_name, system_instruction=system_prompt)
            response = model.generate_content(user_prompt)
        except Exception as exc:  # pragma: no cover - závislé na externím API
            raise RuntimeError(f"Gemini API request failed: {exc}") from exc

        if not response or not getattr(response, "text", None):
            raise RuntimeError("Gemini API nevrátilo textovou odpověď.")

        return response.text

