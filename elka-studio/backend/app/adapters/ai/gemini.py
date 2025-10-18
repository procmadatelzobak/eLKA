from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Dict

from google import genai

from app.adapters.ai.base import BaseAIAdapter
from app.utils.config import Config


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GeminiAdapter(BaseAIAdapter):
    """Parametric adapter for Google Gemini models."""

    config: Config
    model: str

    def __post_init__(self) -> None:
        BaseAIAdapter.__init__(self, self.config)
        api_key = self.config.get_gemini_api_key()
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        self._client = genai.Client(api_key=api_key)
        self._model_aliases = self.config.get_ai_model_aliases()

    def _resolve_model(self, model_key: str | None = None) -> str:
        if model_key:
            resolved = self._model_aliases.get(model_key)
            if resolved:
                return resolved
            return model_key
        return self.model

    def generate_text(self, prompt: str, model_key: str | None = None) -> str:
        model_name = self._resolve_model(model_key)
        response = self._client.models.generate_content(model=model_name, contents=prompt)
        return getattr(response, "text", "")

    def analyse(self, prompt: str, aspect: str = "generic") -> Dict[str, object] | str:  # type: ignore[override]
        """Call the configured Gemini model for analytical tasks."""

        response = self._client.models.generate_content(model=self._resolve_model(), contents=prompt)
        return getattr(response, "text", str(response))

    def summarise(self, story_content: str) -> str:  # type: ignore[override]
        """Summarise narrative content using the writer model."""

        instruction = (
            "Provide a concise summary (no more than 40 words) of the following story. "
            "Return plain text without bullet points."
        )
        summary = self.generate_markdown(instruction=instruction, context=story_content).strip()
        return summary or "Summary unavailable"

    def generate_markdown(self, instruction: str, context: str | None = None) -> str:
        """Generate Markdown content using the Gemini model."""

        contents = instruction if not context else f"{instruction}\n\nCONTEXT:\n{context}"
        return self.generate_text(contents)

    def generate_json(self, system: str, user: str, model_key: str | None = None) -> str:
        """Return JSON-formatted text by combining system and user prompts."""

        prompt = f"{system}\n\n{user}"
        text = self.generate_text(prompt, model_key=model_key)
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            error_message = f"Failed to decode JSON from Gemini: {text}"
            logger.error(error_message)
            raise ValueError(error_message) from exc
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Error processing Gemini JSON response: %s", exc)
            raise
        return text


__all__ = ["GeminiAdapter"]
