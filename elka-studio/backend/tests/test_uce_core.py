"""Unit tests for the Universe Consistency Engine helpers."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Iterable, List

import git
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.adapters.ai.base import BaseAIAdapter
from app.adapters.git.base import GitAdapter
from app.core.archivist import load_universe
from app.core.extractor import extract_fact_graph
from app.core.planner import plan_changes
from app.core.schemas import Changeset, ChangesetFile, FactEntity, FactEvent, FactGraph
from app.core.validator import validate_universe
from app.utils.config import Config


class DummyAIAdapter(BaseAIAdapter):
    """Test double returning predefined responses for analysis calls."""

    def __init__(self, response: object, json_responses: Iterable[str] | None = None) -> None:
        super().__init__(Config(data={}))
        self._response = response
        self._json_responses: List[str] = list(json_responses or ["{}"])
        self._json_calls = 0

    def analyse(self, story_content: str, aspect: str):  # type: ignore[override]
        return self._response

    def summarise(self, story_content: str) -> str:  # pragma: no cover - unused in tests
        return "summary"

    def generate_markdown(self, instruction: str, context: str | None = None) -> str:  # pragma: no cover - unused
        return (context or instruction).strip()

    def generate_json(self, system: str, user: str) -> str:  # type: ignore[override]
        index = min(self._json_calls, len(self._json_responses) - 1)
        self._json_calls += 1
        return self._json_responses[index]


class RetryingAIAdapter(BaseAIAdapter):
    """Adapter that fails once before returning valid JSON."""

    def __init__(self, responses: Iterable[str]) -> None:
        super().__init__(Config(data={}))
        self._responses = list(responses)
        self._calls = 0

    def analyse(self, story_content: str, aspect: str):  # pragma: no cover - unused
        return {}

    def summarise(self, story_content: str) -> str:  # pragma: no cover - unused
        return "summary"

    def generate_json(self, system: str, user: str) -> str:  # type: ignore[override]
        response = self._responses[self._calls]
        self._calls = min(self._calls + 1, len(self._responses) - 1)
        return response


class ValidationRetryAdapter(BaseAIAdapter):
    """Adapter capturing prompts and providing staged responses."""

    def __init__(self, responses: Iterable[str]) -> None:
        super().__init__(Config(data={}))
        self._responses = list(responses)
        self.prompts: list[str] = []
        self._index = 0

    def analyse(self, story_content: str, aspect: str):  # pragma: no cover - unused
        return {}

    def summarise(self, story_content: str) -> str:  # pragma: no cover - unused
        return "summary"

    def generate_json(self, system: str, user: str) -> str:  # type: ignore[override]
        self.prompts.append(user)
        response = self._responses[self._index]
        self._index = min(self._index + 1, len(self._responses) - 1)
        return response


class LegendAIAdapter(BaseAIAdapter):
    """Adapter returning deterministic legend breach findings."""

    def __init__(self, payload: object) -> None:
        super().__init__(Config(data={}))
        self._payload = payload

    def analyse(self, story_content: str, aspect: str):  # pragma: no cover - unused
        return {}

    def summarise(self, story_content: str) -> str:  # pragma: no cover - unused
        return "summary"

    def generate_json(self, system: str, user: str) -> str:  # type: ignore[override]
        return json.dumps(self._payload)


@pytest.fixture()
def universe_repo(tmp_path: Path) -> Path:
    (tmp_path / "Objekty").mkdir()
    (tmp_path / "Legendy").mkdir()
    (tmp_path / "Objekty" / "fortress.md").write_text(
        "---\nera: 1100-1300\n---\n# Ancient Fortress\n",
        encoding="utf-8",
    )
    (tmp_path / "Legendy" / "myth.md").write_text("# Forgotten Myth\n\n- Core truth\n", encoding="utf-8")
    (tmp_path / "timeline.txt").write_text("1200 Founding of the order\n", encoding="utf-8")
    return tmp_path


def test_extract_fact_graph_accepts_dict_and_slugifies() -> None:
    response = {
        "entities": [{"id": "Knight of Dawn", "type": "person"}],
        "events": [
            {
                "title": "Battle of Dawn",
                "participants": ["Knight of Dawn"],
                "location": "Ancient Fortress",
            }
        ],
    }
    adapter = DummyAIAdapter({}, json_responses=[json.dumps(response)])
    graph = extract_fact_graph("Story", adapter)
    assert [entity.id for entity in graph.entities] == ["knight_of_dawn"]
    assert graph.events[0].participants == ["knight_of_dawn"]
    assert graph.events[0].location == "ancient_fortress"


def test_extract_fact_graph_retry_on_invalid_json() -> None:
    responses = ["not-json", json.dumps({"entities": [], "events": [{"title": "Duel"}]})]
    adapter = RetryingAIAdapter(responses)
    graph = extract_fact_graph("Story", adapter)
    assert [event.title for event in graph.events] == ["Duel"]


def test_extract_fact_graph_retry_on_validation_error() -> None:
    invalid = json.dumps({
        "entities": [{"id": "hero", "type": "mystery"}],
        "events": [],
    })
    valid = json.dumps({
        "entities": [{"id": "hero", "type": "person"}],
        "events": [],
    })
    adapter = ValidationRetryAdapter([invalid, valid])
    graph = extract_fact_graph("Story", adapter)
    assert [entity.type for entity in graph.entities] == ["person"]
    assert len(adapter.prompts) == 2
    assert adapter.prompts[1].startswith("Return ONLY JSON.")


def test_extract_fact_graph_invalid_payload_raises() -> None:
    adapter = DummyAIAdapter("not-json", json_responses=["also-bad", "still-bad"])
    with pytest.raises(ValueError):
        extract_fact_graph("Story", adapter)


def test_load_universe_parses_entities_events_and_truths(universe_repo: Path) -> None:
    graph = load_universe(universe_repo)
    entity = next(entity for entity in graph.entities if entity.id == "fortress")
    assert entity.attributes.get("era") == "1100-1300"
    assert any(event.title.startswith("Founding") for event in graph.events)
    assert "Core truth" in graph.core_truths


def test_plan_changes_creates_new_files(universe_repo: Path) -> None:
    incoming = FactGraph(entities=[FactEntity(id="village", type="place", summary="Quiet village")])
    changeset = plan_changes(FactGraph(), incoming, universe_repo)
    file_paths = {file.path for file in changeset.files}
    assert "Objekty/village.md" in file_paths
    assert "# village" in next(file.new for file in changeset.files if file.path == "Objekty/village.md")


def test_plan_changes_adds_timeline_events(universe_repo: Path) -> None:
    incoming = FactGraph(
        events=[FactEvent(id="battle", title="Battle of Spring", date="1201", participants=[])],
    )
    changeset = plan_changes(FactGraph(), incoming, universe_repo)
    timeline_change = next(file for file in changeset.files if file.path.startswith("timeline"))
    assert "Battle of Spring" in timeline_change.new
    assert "1200 Founding of the order" in timeline_change.new


def test_plan_changes_timeline_duplicate_detection(universe_repo: Path) -> None:
    incoming = FactGraph(
        events=[
            FactEvent(
                id="battle", title="Battle of Dawn", date="Spring 1202", participants=[]
            )
        ]
    )
    initial = plan_changes(FactGraph(), incoming, universe_repo)
    timeline_file = next(file for file in initial.files if file.path.startswith("timeline"))
    (universe_repo / timeline_file.path).write_text(timeline_file.new, encoding="utf-8")

    refreshed = load_universe(universe_repo)
    repeat = plan_changes(refreshed, incoming, universe_repo)
    assert all(not file.path.startswith("timeline") for file in repeat.files)


def test_plan_changes_uses_writer_for_body(universe_repo: Path) -> None:
    class RecordingWriter(BaseAIAdapter):
        def __init__(self) -> None:
            super().__init__(Config(data={}))
            self.calls: list[tuple[str, str | None]] = []

        def analyse(self, story_content: str, aspect: str):  # type: ignore[override]
            return {}

        def summarise(self, story_content: str) -> str:  # pragma: no cover - unused
            return "summary"

        def generate_markdown(self, instruction: str, context: str | None = None) -> str:  # type: ignore[override]
            self.calls.append((instruction, context))
            return "Generated lore body"

        def generate_json(self, system: str, user: str) -> str:  # pragma: no cover - unused
            return "{}"

    writer = RecordingWriter()
    incoming = FactGraph(entities=[FactEntity(id="artifact", type="artifact", summary="Ancient key")])

    changeset = plan_changes(FactGraph(), incoming, universe_repo, writer)

    new_file = next(file for file in changeset.files if file.path == "Objekty/artifact.md")
    assert new_file.new == "# artifact\nGenerated lore body\n"
    assert writer.calls


def test_validate_universe_detects_conflicts() -> None:
    current = FactGraph(entities=[FactEntity(id="hero", type="person")])
    incoming = FactGraph(entities=[FactEntity(id="hero", type="artifact")])
    issues = validate_universe(current, incoming)
    assert any(issue.code == "entity_type_conflict" for issue in issues)


def test_validate_universe_missing_entity() -> None:
    incoming = FactGraph(events=[FactEvent(id="raid", title="Raid", participants=["ghost"])])
    issues = validate_universe(FactGraph(), incoming)
    assert any(issue.code == "missing_entity" and "ghost" in issue.refs for issue in issues)


def test_validate_universe_temporal_mismatch() -> None:
    entity = FactEntity(id="hero", type="person", attributes={"era": "1200-1250"})
    event = FactEvent(id="battle", title="Battle", date="1300", participants=["hero"])
    issues = validate_universe(FactGraph(entities=[entity]), FactGraph(events=[event]))
    assert any(issue.code == "temporal_mismatch" for issue in issues)


def test_validate_universe_legend_breach() -> None:
    current = FactGraph(core_truths=["The hero never falls."])
    incoming = FactGraph(events=[FactEvent(id="fall", title="Hero falls", participants=[])])
    ai = LegendAIAdapter([{"message": "Contradiction detected", "refs": ["fall"], "level": "error"}])
    issues = validate_universe(current, incoming, ai)
    assert any(issue.code == "legend_breach" for issue in issues)


def test_validate_universe_legend_skip_info() -> None:
    current = FactGraph(core_truths=["Magic is rare."])
    issues = validate_universe(current, FactGraph())
    assert any(issue.code == "legend_breach_check_skipped" for issue in issues)


def test_validate_universe_loads_template_truths() -> None:
    class RecordingAdapter(LegendAIAdapter):
        def __init__(self) -> None:
            super().__init__([{"message": "conflict", "refs": ["fall"], "level": "error"}])
            self.last_truths: list[str] = []

        def generate_json(self, system: str, user: str) -> str:  # type: ignore[override]
            payload = json.loads(user)
            self.last_truths = payload.get("truths", [])
            return super().generate_json(system, user)

    ai = RecordingAdapter()
    issues = validate_universe(FactGraph(), FactGraph(events=[FactEvent(id="fall", title="Hero falls")]), ai)
    assert ai.last_truths
    assert any(issue.code == "legend_breach" for issue in issues)


def test_git_adapter_branch_and_commit(tmp_path: Path) -> None:
    repo = git.Repo.init(tmp_path)
    (tmp_path / "README.md").write_text("initial", encoding="utf-8")
    repo.git.add(A=True)
    repo.index.commit("Initial commit")

    config = Config(data={"git": {"default_branch": "main"}})
    adapter = GitAdapter(project_path=tmp_path, config=config)

    adapter.create_branch("uce/test")
    assert repo.active_branch.name == "uce/test"

    changeset = Changeset(
        files=[
            ChangesetFile(
                path="Objekty/hero.md",
                old=None,
                new="# hero\nChampion\n",
            )
        ],
        summary="Add hero",
    )
    adapter.apply_changeset(changeset)
    sha = adapter.commit_all("Add hero")

    assert repo.head.commit.hexsha == sha
    assert (tmp_path / "Objekty" / "hero.md").read_text(encoding="utf-8") == "# hero\nChampion\n"


__all__ = [
    "DummyAIAdapter",
    "RetryingAIAdapter",
    "ValidationRetryAdapter",
    "LegendAIAdapter",
]
