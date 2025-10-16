"""Story archival utilities executed inside Celery workers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List

from app.adapters.ai.base import BaseAIAdapter
from app.adapters.git.base import GitAdapter
from app.utils.config import Config


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


__all__ = ["ArchiveResult", "ArchivistEngine"]
