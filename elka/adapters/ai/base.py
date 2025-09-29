"""Základní rozhraní pro AI adaptéry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseAIAdapter(ABC):
    """Abstraktní základ pro AI adaptéry."""

    def __init__(self, provider_config: Dict[str, Any]):
        """Inicializuj adaptér konfiguračními parametry poskytovatele."""

        self.config = provider_config

    @abstractmethod
    def prompt(self, model_name: str, system_prompt: str, user_prompt: str) -> str:
        """Odešli dotaz na jazykový model a vrať jeho odpověď jako text."""

