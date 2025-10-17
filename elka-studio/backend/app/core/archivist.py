"""Story archival utilities executed inside Celery workers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List

from app.adapters.ai.base import BaseAIAdapter
from app.adapters.git.base import GitAdapter
from app.utils.config import Config

from .extractor import _slugify
from .schemas import FactEntity, FactEvent, FactGraph

TEMPLATES_ROOT = Path(__file__).resolve().parent.parent / "templates" / "universe_scaffold"


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


def _parse_front_matter(text: str) -> dict[str, str]:
    match = re.match(r"^---\n(?P<body>.+?)\n---\n", text, flags=re.DOTALL)
    if not match:
        return {}
    attributes: dict[str, str] = {}
    for line in match.group("body").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        attributes[key.strip().lower()] = value.strip().strip('"')
    return attributes


def _parse_attribute_block(text: str) -> dict[str, str]:
    attributes: dict[str, str] = {}
    attribute_section = re.search(
        r"(?im)^(?:##\s+)?(?:atributy|attributes)\s*:?.*$([\s\S]+)",
        text,
    )
    if not attribute_section:
        return attributes
    for line in attribute_section.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            attributes[key.strip().lower()] = value.strip()
    return attributes


def _extract_core_truths(paths: Iterable[Path]) -> list[str]:
    truths: list[str] = []
    bullet_pattern = re.compile(r"^[\s>*-]*[-*+]\s+(?P<truth>.+)$")
    for path in paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            match = bullet_pattern.match(line.strip())
            if match:
                truths.append(match.group("truth").strip())
    return truths


def _collect_truth_sources(repo_path: Path) -> list[Path]:
    sources: list[Path] = []
    core_truths_template = TEMPLATES_ROOT / "Legends" / "CORE_TRUTHS.md"
    sources.append(core_truths_template)
    legendy_dir = repo_path / "Legendy"
    if legendy_dir.is_dir():
        sources.extend(sorted(legendy_dir.glob("*.md")))
    return sources


def _timeline_candidates(repo_path: Path) -> list[Path]:
    return [repo_path / "timeline.md", repo_path / "timeline.txt"]


def _parse_timeline_events(text: str) -> list[FactEvent]:
    events: list[FactEvent] = []
    line_pattern = re.compile(
        r"^(?P<date>(?:\d{3,4}(?:[\-/]\d{1,2}){0,2}|(?:jaro|léto|leto|podzim|zima|spring|summer|autumn|fall|winter)\s+\d{3,4}))?\s*(?:[-–—:]\s*)?(?P<title>.+)$",
        flags=re.IGNORECASE,
    )
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = line_pattern.match(stripped)
        if not match:
            continue
        date = match.group("date")
        title = match.group("title").strip()
        events.append(
            FactEvent(
                id=_slugify(stripped),
                title=title or stripped,
                date=date.strip() if date else None,
            )
        )
    return events


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
            attributes = {**_parse_front_matter(text), **_parse_attribute_block(text)}
            entities.append(
                FactEntity(
                    id=_slugify(path.stem),
                    type=entity_type,
                    summary=titles[0] if titles else path.stem,
                    attributes=attributes,
                )
            )

    legendy_dir = repo_path / "Legendy"
    if legendy_dir.is_dir():
        for path in sorted(legendy_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            titles = re.findall(r"^#\s*(.+)", text, flags=re.MULTILINE)
            attributes = {**_parse_front_matter(text), **_parse_attribute_block(text)}
            entities.append(
                FactEntity(
                    id=_slugify(path.stem),
                    type="concept",
                    summary=titles[0] if titles else path.stem,
                    attributes=attributes,
                )
            )

    for timeline_path in _timeline_candidates(repo_path):
        if not timeline_path.is_file():
            continue
        text = timeline_path.read_text(encoding="utf-8")
        events.extend(_parse_timeline_events(text))

    core_truth_sources = _collect_truth_sources(repo_path)
    core_truths = _extract_core_truths(core_truth_sources)

    return FactGraph(entities=entities, events=events, core_truths=core_truths)


__all__ = ["ArchiveResult", "ArchivistEngine", "load_universe"]
