"""Factory helpers for resolving AI adapters at runtime."""

from __future__ import annotations

from typing import Dict, Tuple

from app.adapters.ai.base import BaseAIAdapter, HeuristicAIAdapter
from app.adapters.ai.gemini import GeminiAdapter
from app.utils.config import Config


class AIAdapterFactory:
    """Resolve AI adapters based on configuration and requested model."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._cache: Dict[Tuple[str, str], BaseAIAdapter] = {}

    def _cache_key(self, adapter_name: str, model_key: str | None) -> Tuple[str, str]:
        key = model_key or ""
        return adapter_name, key

    def get_adapter(self, adapter_name: str, model_key: str | None = None) -> BaseAIAdapter:
        """Return an adapter by name, optionally scoped to a model key."""

        if adapter_name == "heuristic":
            model_key = ""

        cache_key = self._cache_key(adapter_name, model_key)
        if cache_key in self._cache:
            return self._cache[cache_key]

        if adapter_name == "heuristic":
            adapter: BaseAIAdapter = HeuristicAIAdapter(config=self._config)
        elif adapter_name == "gemini":
            resolved_name = self._config.resolve_model_name(model_key or "")
            if not resolved_name or resolved_name == "heuristic":
                resolved_name = self._config.writer_model()
            adapter = GeminiAdapter(config=self._config, model=resolved_name)
        else:
            raise ValueError(f"Unknown AI adapter '{adapter_name}' requested")

        self._cache[cache_key] = adapter
        return adapter

    def get_adapter_for_model(self, model_key: str) -> BaseAIAdapter:
        """Return an adapter suitable for the provided model key."""

        if model_key == "heuristic":
            return self.get_adapter("heuristic")

        adapter_name = self._config.get_default_adapter()
        return self.get_adapter(adapter_name, model_key=model_key)


__all__ = ["AIAdapterFactory"]

