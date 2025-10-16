"""AI adapter abstractions for lore validation and summarisation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict

from app.utils.config import Config


class BaseAIAdapter(ABC):
    """Minimal interface required by the Validator and Archivist engines."""

    def __init__(self, config: Config) -> None:
        self.config = config

    @abstractmethod
    def analyse(self, story_content: str, aspect: str) -> Dict[str, Any]:
        """Return a structured analysis of the story for the requested aspect."""

    @abstractmethod
    def summarise(self, story_content: str) -> str:
        """Return a compact summary suitable for commit messages or metadata."""


@dataclass(slots=True)
class HeuristicAIAdapter(BaseAIAdapter):
    """A lightweight adapter that performs deterministic heuristics."""

    config: Config

    def __post_init__(self) -> None:  # pragma: no cover - dataclass compatibility
        BaseAIAdapter.__init__(self, self.config)

    def analyse(self, story_content: str, aspect: str) -> Dict[str, Any]:
        cleaned = story_content.strip()
        word_count = len(cleaned.split())
        aspect_lower = aspect.lower()
        passed = bool(cleaned)
        messages: list[str] = []

        if not cleaned:
            messages.append("Story content is empty.")
            passed = False
        elif word_count < 50:
            messages.append("Story is very short; consider expanding for richer detail.")
            if aspect_lower != "format":
                passed = False

        if aspect_lower == "format":
            max_line_length = max((len(line) for line in cleaned.splitlines()), default=0)
            if max_line_length > 240:
                messages.append("Some lines exceed 240 characters which may impact readability.")
                passed = False
        elif aspect_lower == "continuity":
            paragraph_count = cleaned.count("\n\n") + 1 if cleaned else 0
            if paragraph_count < 2:
                messages.append("Continuity check suggests adding more than one paragraph.")
                passed = False
        elif aspect_lower == "tone":
            uppercase_ratio = sum(1 for ch in cleaned if ch.isupper()) / max(len(cleaned), 1)
            if uppercase_ratio > 0.3:
                messages.append("Tone analysis detected excessive uppercase usage.")
                passed = False
        else:
            messages.append("No specific heuristics for this aspect; marking as informational only.")

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


def get_default_ai_adapter(config: Config) -> BaseAIAdapter:
    """Factory returning the default AI adapter used by workers."""

    return HeuristicAIAdapter(config=config)


__all__ = ["BaseAIAdapter", "HeuristicAIAdapter", "get_default_ai_adapter"]
