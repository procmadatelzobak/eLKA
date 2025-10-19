"""Tests for the ValidatorEngine normalising heterogeneous AI responses."""

from __future__ import annotations

import json
from typing import Iterable, List

import pytest

from app.adapters.ai.base import BaseAIAdapter
from app.core.validator import ValidatorEngine
from app.utils.config import Config


class DummyAdapter(BaseAIAdapter):
    """Adapter returning pre-seeded responses for each analyse call."""

    def __init__(self, responses: Iterable[object]) -> None:
        super().__init__(Config(data={}))
        self._responses: List[object] = list(responses)
        if not self._responses:
            self._responses = [""]
        self._index = 0

    def analyse(
        self,
        story_content: str,
        aspect: str,
        context: str | None = None,
    ):  # type: ignore[override]
        index = min(self._index, len(self._responses) - 1)
        self._index += 1
        return self._responses[index]

    def summarise(self, story_content: str) -> str:  # pragma: no cover - unused
        return "summary"


@pytest.mark.parametrize(
    "response, expected",
    [
        ("Format validation passed with no issues.", True),
        ("Format validation failed due to missing section.", False),
    ],
)
def test_validator_engine_interprets_textual_analysis(
    response: str, expected: bool
) -> None:
    adapter = DummyAdapter([response, response, response])
    engine = ValidatorEngine(adapter, Config(data={}))

    report = engine.validate("Example story text.")

    assert report.steps[0].passed is expected
    assert report.steps[0].messages == [response]


def test_validator_engine_parses_json_strings() -> None:
    payload = json.dumps({"passed": True, "messages": ["All good."]})
    adapter = DummyAdapter([payload, payload, payload])
    engine = ValidatorEngine(adapter, Config(data={}))

    report = engine.validate("Example story text.")

    assert all(step.passed for step in report.steps)
    assert report.steps[0].messages == ["All good."]
