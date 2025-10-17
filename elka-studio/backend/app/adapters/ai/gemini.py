from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from google import genai

from app.adapters.ai.base import BaseAIAdapter
from app.utils.config import Config


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

    def analyse(self, prompt: str, aspect: str = "generic") -> Dict[str, Any] | str:  # type: ignore[override]
        """Call the configured Gemini model for analytical tasks."""

        response = self._client.models.generate_content(model=self.model, contents=prompt)
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
        response = self._client.models.generate_content(model=self.model, contents=contents)
        return getattr(response, "text", "")

    def generate_json(self, system: str, user: str) -> str:
        """Return JSON-formatted text by combining system and user prompts."""

        prompt = f"{system}\n\n{user}"
        response = self._client.models.generate_content(model=self.model, contents=prompt)
        return getattr(response, "text", "")


__all__ = ["GeminiAdapter"]
