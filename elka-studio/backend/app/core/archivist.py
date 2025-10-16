"""Story archival utilities executed inside Celery workers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from app.adapters.ai.base import BaseAIAdapter
from app.adapters.git.base import GitAdapter
from app.utils.config import Config

from .extractor import _slugify
from .schemas import FactEntity, FactEvent, FactGraph


@dataclass(slots=True)
class ArchiveResult:
    """Result returned by the archivist when persisting a story."""

    success: bool
    files: Dict[str, str]
    metadata: Dict[str, str]
    log_messages: List[str]


class ArchivistEngine:
    """Persist validated stories into the lore repository."""

    def __init__(self, git_adapter: GitAdapter, ai_adapter: BaseAIAdapter, config: Config) -> None:
        self.git_adapter = git_adapter
        self.ai_adapter = ai_adapter
        self.config = config

    def archive(
        self,
        story_content: str,
        universe_files: dict[str, str] | None = None,
    ) -> ArchiveResult:
        """Return the files to be committed and relevant metadata.

        The ``universe_files`` argument is accepted to support future
        contextual archival strategies.  The current implementation focuses on
        the generated story alone, but Celery tasks can already provide the
        additional information.
        """

        summary = self.ai_adapter.summarise(story_content)
        slug = self._slugify(summary) or "story"
        filename = self.config.story_filename(prefix=slug)
        relative_path = str(self.config.story_directory / filename)
        # Ensure the directory exists prior to returning the files
        self.config.ensure_story_directory(self.git_adapter.project_path)
        document = self._build_document(story_content, summary)

        files = {relative_path: document}
        metadata = {
            "summary": summary,
            "filename": filename,
            "relative_path": relative_path,
            "timestamp": datetime.utcnow().isoformat(),
        }
        log_messages = [f"Story archived to {relative_path}"]

        return ArchiveResult(success=True, files=files, metadata=metadata, log_messages=log_messages)

    @staticmethod
    def _slugify(value: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9\s-]", "", value).strip().lower()
        cleaned = re.sub(r"[-\s]+", "-", cleaned)
        return cleaned[:40]

    @staticmethod
    def _build_document(story_content: str, summary: str) -> str:
        header = "---\n"
        header += f"summary: \"{summary.replace('\\', '\\\\').replace('"', '\\"')}\"\n"
        header += f"generated_at: {datetime.utcnow().isoformat()}\n"
        header += "---\n\n"
        return f"{header}{story_content.strip()}\n"


def load_universe(repo_path: Path) -> FactGraph:
    """Parse the existing universe files into a :class:`FactGraph`."""

    entities: list[FactEntity] = []
    events: list[FactEvent] = []

    objekty_dir = repo_path / "Objekty"
    if objekty_dir.is_dir():
        for path in sorted(objekty_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            titles = re.findall(r"^#\s*(.+)", text, flags=re.MULTILINE)
            entity_type = "place" if "place" in path.stem.lower() else "other"
            entities.append(
                FactEntity(
                    id=_slugify(path.stem),
                    type=entity_type,
                    summary=titles[0] if titles else path.stem,
                )
            )

    legendy_dir = repo_path / "Legendy"
    if legendy_dir.is_dir():
        for path in sorted(legendy_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            titles = re.findall(r"^#\s*(.+)", text, flags=re.MULTILINE)
            entities.append(
                FactEntity(
                    id=_slugify(path.stem),
                    type="concept",
                    summary=titles[0] if titles else path.stem,
                )
            )

    for timeline in sorted(repo_path.glob("timeline.*")):
        text = timeline.read_text(encoding="utf-8")
        for line in text.splitlines():
            if re.match(r"^\d", line.strip()):
                events.append(
                    FactEvent(
                        id=_slugify(line),
                        title=line.strip(),
                    )
                )

    return FactGraph(entities=entities, events=events)


__all__ = ["ArchiveResult", "ArchivistEngine", "load_universe"]
