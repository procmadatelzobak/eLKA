"""Unit tests for the Universe Consistency Engine helpers."""

from __future__ import annotations

import json
from pathlib import Path
import sys

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
from app.core.schemas import Changeset, ChangesetFile, FactEntity, FactGraph
from app.core.validator import validate_universe
from app.utils.config import Config


class DummyAIAdapter(BaseAIAdapter):
    """Test double returning a predefined response."""

    def __init__(self, response) -> None:
        super().__init__(Config(data={}))
        self._response = response

    def analyse(self, story_content: str, aspect: str):  # type: ignore[override]
        return self._response

    def summarise(self, story_content: str) -> str:  # pragma: no cover - unused in tests
        return "summary"


@pytest.fixture()
def universe_repo(tmp_path: Path) -> Path:
    (tmp_path / "Objekty").mkdir()
    (tmp_path / "Legendy").mkdir()
    (tmp_path / "Objekty" / "fortress.md").write_text("# Ancient Fortress\n", encoding="utf-8")
    (tmp_path / "Legendy" / "myth.md").write_text("# Forgotten Myth\n", encoding="utf-8")
    (tmp_path / "timeline.txt").write_text("1200 Founding of the order\n", encoding="utf-8")
    return tmp_path


def test_extract_fact_graph_accepts_dict() -> None:
    response = {"entities": [{"id": "hero", "type": "person"}], "events": []}
    adapter = DummyAIAdapter(response)
    graph = extract_fact_graph("Story", adapter)
    assert [entity.id for entity in graph.entities] == ["hero"]


def test_extract_fact_graph_accepts_json_string() -> None:
    payload = json.dumps({"entities": [], "events": [{"id": "battle", "title": "Battle"}]})
    adapter = DummyAIAdapter(payload)
    graph = extract_fact_graph("Story", adapter)
    assert [event.id for event in graph.events] == ["battle"]


def test_extract_fact_graph_invalid_payload_raises() -> None:
    adapter = DummyAIAdapter("not-json")
    with pytest.raises(ValueError):
        extract_fact_graph("Story", adapter)


def test_load_universe_parses_entities_and_events(universe_repo: Path) -> None:
    graph = load_universe(universe_repo)
    entity_ids = {entity.id for entity in graph.entities}
    event_titles = {event.title for event in graph.events}
    assert "fortress" in entity_ids
    assert "myth" in entity_ids
    assert "1200 Founding of the order" in event_titles


def test_plan_changes_creates_new_files(universe_repo: Path) -> None:
    incoming = FactGraph(entities=[FactEntity(id="village", type="place", summary="Quiet village")])
    changeset = plan_changes(FactGraph(), incoming, universe_repo)
    assert len(changeset.files) == 1
    file_change = changeset.files[0]
    assert file_change.path == "Objekty/village.md"
    assert "# village" in file_change.new


def test_plan_changes_skips_duplicate_updates(universe_repo: Path) -> None:
    target = universe_repo / "Objekty" / "fortress.md"
    target.write_text("# Ancient Fortress\n\n## Update\nQuiet village\n", encoding="utf-8")
    incoming = FactGraph(
        entities=[FactEntity(id="fortress", type="place", summary="Quiet village")]
    )
    current = FactGraph(entities=[FactEntity(id="fortress", type="place")])
    changeset = plan_changes(current, incoming, universe_repo)
    assert changeset.files == []
    assert changeset.summary == "No universe files require updates"


def test_plan_changes_appends_new_update(universe_repo: Path) -> None:
    target = universe_repo / "Objekty" / "fortress.md"
    target.write_text("# Ancient Fortress\n", encoding="utf-8")
    incoming = FactGraph(
        entities=[FactEntity(id="fortress", type="place", summary="New discovery revealed")]
    )
    current = FactGraph(entities=[FactEntity(id="fortress", type="place")])

    changeset = plan_changes(current, incoming, universe_repo)

    assert len(changeset.files) == 1
    file_change = changeset.files[0]
    assert file_change.old == "# Ancient Fortress\n"
    assert file_change.new == "# Ancient Fortress\n\n## Update\nNew discovery revealed\n"
    assert changeset.summary == "Planned updates for 1 universe file(s)."


def test_validate_universe_detects_conflicts() -> None:
    current = FactGraph(entities=[FactEntity(id="hero", type="person")])
    incoming = FactGraph(entities=[FactEntity(id="hero", type="artifact")])
    issues = validate_universe(current, incoming)
    assert any(issue.code == "entity_type_conflict" for issue in issues)


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
