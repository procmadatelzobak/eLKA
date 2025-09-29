"""Hlavní vstupní bod pro eLKA agenta."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Dict, Tuple, Type

from elka.adapters.ai.base import BaseAIAdapter
from elka.adapters.ai.gemini import GeminiAdapter
from elka.adapters.ai.ollama import OllamaAdapter
from elka.adapters.git.base import BaseGitAdapter
from elka.adapters.git.gitea import GiteaAdapter
from elka.adapters.git.github import GitHubAdapter
from elka.core.orchestrator import Orchestrator
from elka.utils.config import Config


GIT_ADAPTERS: Dict[str, Type[BaseGitAdapter]] = {
    "github": GitHubAdapter,
    "gitea": GiteaAdapter,
}

AI_ADAPTERS: Dict[str, Type[BaseAIAdapter]] = {
    "gemini": GeminiAdapter,
    "ollama": OllamaAdapter,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Spuštění eLKA agenta")
    default_config = Path(__file__).resolve().parent / "config.yml"
    parser.add_argument("--config", type=Path, default=default_config, help="Cesta ke konfiguračnímu souboru")
    parser.add_argument("--pr-id", type=int, required=False, help="Identifikátor Pull Requestu")
    return parser.parse_args()


def configure_logging(config: Config) -> None:
    logging_config = config.logging
    level_name = str(logging_config.get("level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)

    log_kwargs = {
        "level": level,
        "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    }

    log_file = logging_config.get("file")
    if log_file:
        log_kwargs["filename"] = log_file

    logging.basicConfig(**log_kwargs)


def create_git_adapter(config: Config) -> BaseGitAdapter:
    platform = (config.git_platform or "").lower()
    adapter_cls = GIT_ADAPTERS.get(platform)
    if adapter_cls is None:
        raise ValueError(f"Nepodporovaná Git platforma: {platform}")

    repo_url = config.git.get("repo_url")
    if not repo_url:
        raise ValueError("V konfiguraci musí být nastavena položka git.repo_url.")

    token = config.git_api_token
    if not token:
        raise ValueError("Git API token musí být k dispozici v konfiguraci nebo prostředí.")

    return adapter_cls(repo_url, token)


def create_ai_adapter(config: Config) -> BaseAIAdapter:
    provider = (config.ai_provider or "").lower()
    adapter_cls = AI_ADAPTERS.get(provider)
    if adapter_cls is None:
        raise ValueError(f"Nepodporovaný AI poskytovatel: {provider}")

    providers_config = config.ai.get("providers", {})
    provider_config = dict(providers_config.get(provider, {}))

    if provider == "gemini":
        api_key = config.ai_api_key
        if not api_key:
            raise ValueError("GEMINI API klíč musí být k dispozici v konfiguraci nebo prostředí.")
        provider_config.setdefault("api_key", api_key)
    elif provider == "ollama":
        if "base_url" not in provider_config:
            raise ValueError("Konfigurace Ollama poskytovatele vyžaduje položku base_url.")

    return adapter_cls(provider_config)


def main() -> Tuple[Config, BaseAIAdapter]:
    args = parse_args()
    config = Config(args.config)
    configure_logging(config)

    git_adapter = create_git_adapter(config)
    ai_adapter = create_ai_adapter(config)
    orchestrator = Orchestrator(config, ai_adapter=ai_adapter, git_adapter=git_adapter)

    logger = logging.getLogger(__name__)
    logger.info("Inicializován Git adaptér: %s", git_adapter.__class__.__name__)
    logger.info("Inicializován AI adaptér: %s", ai_adapter.__class__.__name__)

    print(f"Inicializován Git adaptér: {git_adapter.__class__.__name__}")
    print(f"Inicializován AI adaptér: {ai_adapter.__class__.__name__}")

    if args.pr_id is not None:
        logger.info("Spuštěno pro PR ID: %s", args.pr_id)
        orchestrator.process_pull_request(args.pr_id)

    return config, ai_adapter


if __name__ == "__main__":
    config, ai_adapter = main()

    print("Testuji AI adaptér...")
    try:
        provider_name = (config.ai_provider or "").lower()
        providers_config = config.ai.get("providers", {})
        models_config = providers_config.get(provider_name, {}).get("models", {})
        test_model_name = models_config.get("validator")
        if not test_model_name:
            raise ValueError("V konfiguraci chybí testovací model pro AI adaptér.")

        system_instruction = "Jsi užitečný asistent."
        user_question = "Kolik je 2 + 2?"

        response = ai_adapter.prompt(test_model_name, system_instruction, user_question)
        print(f"Odpověď od AI: {response}")
    except Exception as exc:  # pragma: no cover - může selhat bez externích služeb
        print(f"Test AI adaptéru selhal: {exc}")

