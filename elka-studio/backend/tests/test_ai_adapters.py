from types import SimpleNamespace
import sys
import types
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.adapters.ai.base import HeuristicAIAdapter, get_ai_adapters
from app.utils.config import Config


class DummyModels:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def generate_content(self, model: str, contents: str) -> SimpleNamespace:
        self.calls.append((model, contents))
        return SimpleNamespace(text=f"{model}:{contents}")


class DummyClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.models = DummyModels()


def test_get_ai_adapters_returns_gemini_instances(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-key")
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("AI_VALIDATOR_MODEL", "gemini-2.5-pro")
    monkeypatch.setenv("AI_WRITER_MODEL", "gemini-2.5-flash")

    clients: list[DummyClient] = []

    def _client_factory(api_key: str) -> DummyClient:
        client = DummyClient(api_key)
        clients.append(client)
        return client

    google_module = types.ModuleType("google")
    google_module.genai = types.SimpleNamespace(Client=_client_factory)
    monkeypatch.setitem(sys.modules, "google", google_module)

    monkeypatch.setattr("app.adapters.ai.gemini.genai.Client", _client_factory)

    config = Config(data={})
    validator, writer = get_ai_adapters(config)

    assert validator.model == "gemini-2.5-pro"
    assert writer.model == "gemini-2.5-flash"

    validator.analyse("Test prompt", "format")
    writer.generate_markdown("Instruction", "Context")

    assert clients[0].api_key == "unit-test-key"
    assert clients[0].models.calls[-1][0] == "gemini-2.5-pro"
    assert clients[1].models.calls[-1][0] == "gemini-2.5-flash"
    assert "Context" in clients[1].models.calls[-1][1]


def test_get_ai_adapters_without_key_falls_back(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    config = Config(data={"ai": {"provider": "gemini"}})

    validator, writer = get_ai_adapters(config)

    assert validator is writer
    assert isinstance(validator, HeuristicAIAdapter)
