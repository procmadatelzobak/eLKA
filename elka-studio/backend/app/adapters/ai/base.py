"""AI adapter abstractions for lore validation and summarisation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from app.utils.config import Config


class BaseAIAdapter(ABC):
    """Minimal interface required by the Validator and Archivist engines."""

    def __init__(self, config: Config) -> None:
        self.config = config

    @abstractmethod
    def analyse(
        self,
        story_content: str,
        aspect: str,
        context: str | None = None,
    ) -> Dict[str, Any]:
        """Return a structured analysis of the story for the requested aspect."""

    @abstractmethod
    def summarise(self, story_content: str) -> str:
        """Return a compact summary suitable for commit messages or metadata."""

        raise NotImplementedError

    # Optional helpers -------------------------------------------------
    def generate_markdown(self, instruction: str, context: str | None = None) -> str:
        """Return Markdown content generated from the provided instruction."""

        raise NotImplementedError

    def generate_json(
        self, system: str, user: str
    ) -> Tuple[str, Optional[Dict[str, int]]]:
        """Return JSON text generated from a system/user prompt pair."""

        raise NotImplementedError

    def generate_text(
        self,
        prompt: str,
        model_key: str | None = None,
    ) -> Tuple[str, Optional[Dict[str, int]]]:
        """Return a free-form text response with optional token usage metadata."""

        raise NotImplementedError

    def count_tokens(self, text: str) -> int:
        """Best-effort token counting for adapters that support it."""

        if not text:
            return 0
        return len(text.split())


@dataclass(slots=True)
class HeuristicAIAdapter(BaseAIAdapter):
    """A lightweight adapter that performs deterministic heuristics."""

    config: Config

    def __post_init__(self) -> None:  # pragma: no cover - dataclass compatibility
        BaseAIAdapter.__init__(self, self.config)

    def analyse(
        self,
        story_content: str,
        aspect: str,
        context: str | None = None,
    ) -> Dict[str, Any]:
        # The heuristic adapter does not currently use the optional context but the
        # parameter is accepted to maintain API parity with provider-backed
        # adapters that rely on it for richer analysis.
        if context is not None:
            _ = context  # Preserve the argument for interface compatibility.

        cleaned = story_content.strip()
        word_count = len(cleaned.split())
        aspect_lower = aspect.lower()
        passed = bool(cleaned)
        messages: list[str] = []

        if not cleaned:
            messages.append("Story content is empty.")
            passed = False
        elif word_count < 50:
            messages.append(
                "Story is very short; consider expanding for richer detail."
            )
            if aspect_lower != "format":
                passed = False

        if aspect_lower == "format":
            max_line_length = max(
                (len(line) for line in cleaned.splitlines()), default=0
            )
            if max_line_length > 240:
                messages.append(
                    "Some lines exceed 240 characters which may impact readability."
                )
                passed = False
        elif aspect_lower == "continuity":
            paragraph_count = cleaned.count("\n\n") + 1 if cleaned else 0
            if paragraph_count < 2:
                messages.append(
                    "Continuity check suggests adding more than one paragraph."
                )
                passed = False
        elif aspect_lower == "tone":
            uppercase_ratio = sum(1 for ch in cleaned if ch.isupper()) / max(
                len(cleaned), 1
            )
            if uppercase_ratio > 0.3:
                messages.append("Tone analysis detected excessive uppercase usage.")
                passed = False
        else:
            messages.append(
                "No specific heuristics for this aspect; marking as informational only."
            )

        return {
            "aspect": aspect_lower,
            "passed": passed,
            "messages": messages,
            "word_count": word_count,
        }

    def summarise(self, story_content: str) -> str:
        cleaned = " ".join(story_content.strip().split())
        if not cleaned:
            return "Empty story"
        words = cleaned.split()
        summary = " ".join(words[:20])
        if len(words) > 20:
            summary += "…"
        return summary

    def generate_markdown(self, instruction: str, context: str | None = None) -> str:
        """Deterministically combine instruction and context into Markdown."""

        context_value = (context or "").strip()
        if not context_value:
            context_value = instruction.strip()

        title = "Generated Entry"
        if "entity" in instruction.lower():
            title = "Entity Update"
        elif "update" in instruction.lower():
            title = "Update"

        body = context_value
        if not body.endswith("\n"):
            body = f"{body}\n"

        if title.lower() == "update":
            return f"## Update\n{body}"
        return f"# {title}\n{body}"

    def generate_json(
        self, system: str, user: str
    ) -> Tuple[str, Optional[Dict[str, int]]]:
        """Return a deterministic JSON payload with system/user fields."""

        import json

        payload = {"system": system.strip(), "user": user.strip()}
        metadata = {
            "input": 0,
            "output": 0,
            "total": 0,
            "prompt_token_count": 0,
            "candidates_token_count": 0,
            "total_tokens": 0,
        }
        return json.dumps(payload), metadata

    def generate_text(
        self, prompt: str, model_key: str | None = None
    ) -> Tuple[str, Optional[Dict[str, int]]]:
        """Return a deterministic text response for the provided prompt."""

        cleaned = prompt.strip()
        metadata = {
            "input": 0,
            "output": 0,
            "total": 0,
            "prompt_token_count": 0,
            "candidates_token_count": 0,
            "total_tokens": 0,
        }
        return cleaned or "", metadata


def get_default_ai_adapter(config: Config) -> BaseAIAdapter:
    """Factory returning the default AI adapter used by workers."""

    return HeuristicAIAdapter(config=config)


def get_ai_adapters(config: Config) -> tuple[BaseAIAdapter, BaseAIAdapter]:
    """Return validator and writer adapters based on configuration."""

    provider = config.ai_provider()
    if provider == "gemini" and config.get_gemini_api_key():
        from app.adapters.ai.gemini import GeminiAdapter

        validator = GeminiAdapter(config=config, model=config.validator_model())
        writer = GeminiAdapter(config=config, model=config.writer_model())
        return validator, writer

    heuristic = HeuristicAIAdapter(config=config)
    return heuristic, heuristic


__all__ = [
    "BaseAIAdapter",
    "HeuristicAIAdapter",
    "get_ai_adapters",
    "get_default_ai_adapter",
]
