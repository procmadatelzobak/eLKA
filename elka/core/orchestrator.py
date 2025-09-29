from __future__ import annotations

from typing import TYPE_CHECKING

from elka.adapters.ai.base import BaseAIAdapter

if TYPE_CHECKING:
    from elka.utils.config import Config


class Orchestrator:
    """Central orchestrator for coordinating agent components."""

    def __init__(self, config: "Config", ai_adapter: BaseAIAdapter) -> None:
        self.config = config
        self.ai_adapter = ai_adapter
        # TODO: Inicializace adaptérů a dalších komponent bude doplněna později.

    def process_pull_request(self, pr_id: int) -> None:
        """Process the pull request with the given identifier."""
        pass

