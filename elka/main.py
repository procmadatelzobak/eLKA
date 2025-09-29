"""Hlavní vstupní bod pro eLKA agenta."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Dict, Type

from elka.adapters.ai.base import BaseAIAdapter
from elka.adapters.ai.gemini import GeminiAdapter
from elka.adapters.ai.ollama import OllamaAdapter
from elka.adapters.git.base import BaseGitAdapter
from elka.adapters.git.gitea import GiteaAdapter
from elka.adapters.git.github import GitHubAdapter
from elka.core.generator import GeneratorEngine
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
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config,
        help="Cesta ke konfiguračnímu souboru",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    process_parser = subparsers.add_parser(
        "process", help="Zpracuje existující Pull Request"
    )
    process_parser.add_argument(
        "--pr-id",
        type=int,
        required=True,
        help="Identifikátor Pull Requestu",
    )

    generate_parser = subparsers.add_parser(
        "generate", help="Spustí autonomní generování příběhů"
    )
    generate_parser.add_argument(
        "--num-stories",
        type=int,
        default=1,
        help="Počet příběhů, které se mají vygenerovat",
    )

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


def main() -> None:
    args = parse_args()
    config = Config(args.config)
    configure_logging(config)

    git_adapter = create_git_adapter(config)
    ai_adapter = create_ai_adapter(config)

    logger = logging.getLogger(__name__)
    logger.info("Inicializován Git adaptér: %s", git_adapter.__class__.__name__)
    logger.info("Inicializován AI adaptér: %s", ai_adapter.__class__.__name__)

    if args.command == "process":
        orchestrator = Orchestrator(config, ai_adapter=ai_adapter, git_adapter=git_adapter)
        logger.info("Spuštěno pro PR ID: %s", args.pr_id)
        orchestrator.process_pull_request(args.pr_id)
    elif args.command == "generate":
        generator = GeneratorEngine(ai_adapter=ai_adapter, git_adapter=git_adapter, config=config)
        logger.info("Spuštěno autonomní generování pro %s příběh(ů)", args.num_stories)
        generator.run_cycle(num_stories=max(1, args.num_stories))


if __name__ == "__main__":
    main()

