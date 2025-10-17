import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.utils.config import Config


def test_config_defaults_when_no_env(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    monkeypatch.delenv("AI_VALIDATOR_MODEL", raising=False)
    monkeypatch.delenv("AI_WRITER_MODEL", raising=False)

    config = Config(data={})

    assert config.get_gemini_api_key() is None
    assert config.ai_provider() == "heuristic"
    assert config.validator_model() == "gemini-2.5-pro"
    assert config.writer_model() == "gemini-2.5-flash"
    assert config.ai_model == "heuristic-v1"


def test_env_overrides_take_precedence(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-secret")
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("AI_VALIDATOR_MODEL", "validator-test")
    monkeypatch.setenv("AI_WRITER_MODEL", "writer-test")

    config = Config(data={"ai": {"provider": "heuristic", "model": "custom"}})

    assert config.get_gemini_api_key() == "env-secret"
    assert config.ai_provider() == "gemini"
    assert config.validator_model() == "validator-test"
    assert config.writer_model() == "writer-test"
    # ai_model falls back to writer model when provider is gemini
    assert config.ai_model == "writer-test"


def test_gemini_provider_without_key_falls_back(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    config = Config(data={"ai": {"provider": "gemini"}})
    assert config.ai_provider() == "heuristic"

    config_with_key = Config(data={"ai": {"gemini_api_key": "from-config"}})
    assert config_with_key.get_gemini_api_key() == "from-config"
