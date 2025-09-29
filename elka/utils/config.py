from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
import os

import yaml
from dotenv import load_dotenv


class Config:
    """Load configuration for the eLKA agent."""

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path)
        if not self.config_path.exists():
            raise FileNotFoundError(f"Konfigurační soubor {self.config_path} neexistuje.")

        env_path = self.config_path.parent / ".env"
        load_dotenv(env_path)

        with self.config_path.open("r", encoding="utf-8") as config_file:
            data: Dict[str, Any] = yaml.safe_load(config_file) or {}

        self.git: Dict[str, Any] = data.get("git", {})
        self.ai: Dict[str, Any] = data.get("ai", {})
        self.core: Dict[str, Any] = data.get("core", {})
        self.logging: Dict[str, Any] = data.get("logging", {})

        self.git_platform: Optional[str] = self.git.get("platform")
        self.git_api_token: Optional[str] = self._load_git_token()

        self.ai_provider: Optional[str] = self.ai.get("provider")
        self.ai_api_key: Optional[str] = self._load_ai_key()

    def _load_git_token(self) -> Optional[str]:
        if self.git_platform == "github":
            token_var = "GITHUB_API_TOKEN"
        elif self.git_platform == "gitea":
            token_var = "GITEA_API_TOKEN"
        else:
            raise ValueError(f"Nepodporovaná Git platforma: {self.git_platform}")

        token = os.getenv(token_var)
        if not token:
            raise ValueError(f"Proměnná prostředí {token_var} musí být nastavena.")
        return token

    def _load_ai_key(self) -> Optional[str]:
        if self.ai_provider == "gemini":
            key_var = "GEMINI_API_KEY"
            api_key = os.getenv(key_var)
            if not api_key:
                raise ValueError(f"Proměnná prostředí {key_var} musí být nastavena.")
            return api_key
        if self.ai_provider == "ollama":
            return None
        raise ValueError(f"Nepodporovaný AI poskytovatel: {self.ai_provider}")
