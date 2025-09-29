"""Hlavní vstupní bod pro eLKA agenta."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Dict, Type

from elka.adapters.git.base import BaseGitAdapter
from elka.adapters.git.gitea import GiteaAdapter
from elka.adapters.git.github import GitHubAdapter
from elka.utils.config import Config


GIT_ADAPTERS: Dict[str, Type[BaseGitAdapter]] = {
    "github": GitHubAdapter,
    "gitea": GiteaAdapter,
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


def main() -> None:
    args = parse_args()
    config = Config(args.config)
    configure_logging(config)

    adapter = create_git_adapter(config)
    logger = logging.getLogger(__name__)
    logger.info("Inicializován adaptér: %s", adapter.__class__.__name__)

    if args.pr_id is not None:
        logger.info("Spuštěno pro PR ID: %s", args.pr_id)

    print(f"Inicializován adaptér: {adapter.__class__.__name__}")


if __name__ == "__main__":
    main()
