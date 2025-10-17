"""Integration tests for the Universe Consistency Engine workflow."""

from __future__ import annotations

import difflib
from datetime import datetime
from pathlib import Path
import sys

import git

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.adapters.git.base import GitAdapter
from app.core.archivist import load_universe
from app.core.extractor import _slugify
from app.core.planner import plan_changes
from app.core.schemas import FactEntity, FactEvent, FactGraph
from app.utils.config import Config


def _init_repo(path: Path) -> git.Repo:
    repo = git.Repo.init(path)
    (path / "Objekty").mkdir()
    (path / "timeline.md").write_text("# Timeline\n", encoding="utf-8")
    repo.git.add(A=True)
    repo.index.commit("Initial commit")
    return repo


def test_uce_pipeline_dry_run_apply_noop(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)

    story_entities = [FactEntity(id="hero", type="person", summary="A brave hero")]
    story_events = [
        FactEvent(
            id="battle",
            title="Battle of Dawn",
            date="1202",
            participants=["hero"],
            description="The hero wins the battle.",
        )
    ]

    current_graph = load_universe(tmp_path)
    incoming = FactGraph(entities=story_entities, events=story_events)

    changeset = plan_changes(current_graph, incoming, tmp_path)
    assert changeset.files
    hero_file = tmp_path / "Objekty" / "hero.md"
    assert not hero_file.exists()
    original_timeline = (tmp_path / "timeline.md").read_text(encoding="utf-8")

    dry_run_diff = []
    for file in changeset.files:
        diff = "".join(
            difflib.unified_diff(
                (file.old or "").splitlines(keepends=True),
                file.new.splitlines(keepends=True),
                fromfile=f"a/{file.path}",
                tofile=f"b/{file.path}",
                lineterm="",
            )
        )
        dry_run_diff.append(diff)
    assert any(block for block in dry_run_diff)

    adapter = GitAdapter(project_path=tmp_path, config=Config(data={"git": {"default_branch": "main"}}))
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M")
    branch_name = f"uce/{timestamp}-{_slugify('Battle of Dawn')}"
    adapter.create_branch(branch_name)
    adapter.apply_changeset(changeset)
    commit_sha = adapter.commit_all("Apply UCE changes")

    assert hero_file.exists()
    assert (tmp_path / "timeline.md").read_text(encoding="utf-8") != original_timeline
    assert repo.head.commit.hexsha == commit_sha
    assert repo.active_branch.name.startswith("uce/")

    refreshed = load_universe(tmp_path)
    repeat_changeset = plan_changes(refreshed, incoming, tmp_path)
    assert repeat_changeset.files == []
