"""Planner responsible for proposing deterministic repository changes."""

from __future__ import annotations

from pathlib import Path

from app.adapters.ai.base import BaseAIAdapter

from .schemas import Changeset, ChangesetFile, FactEntity, FactGraph


def _strip_heading(markdown: str) -> str:
    """Remove leading Markdown headings to extract body text."""

    lines = [line for line in markdown.splitlines() if line.strip()]
    while lines and lines[0].lstrip().startswith("#"):
        lines.pop(0)
    return "\n".join(lines).strip()


def _render_entity_body(entity: FactEntity, writer: BaseAIAdapter | None) -> str:
    summary = (entity.summary or "").strip()
    if writer and summary:
        generated = writer.generate_markdown(
            instruction=(
                "Write a short Markdown paragraph (no heading) describing the entity "
                f"'{entity.id}'. Focus on lore-relevant context."
            ),
            context=summary,
        ).strip()
        if generated:
            summary = _strip_heading(generated) or summary
    return summary


def _render_update_body(entity: FactEntity, writer: BaseAIAdapter | None) -> str:
    update_text = (entity.summary or "").strip()
    if writer and update_text:
        generated = writer.generate_markdown(
            instruction=(
                "Summarise the following lore update as a short paragraph. Do not include headings; "
                "return Markdown suitable for an '## Update' section."
            ),
            context=update_text,
        ).strip()
        if generated:
            update_text = _strip_heading(generated) or update_text
    return update_text


def plan_changes(
    current: FactGraph,
    incoming: FactGraph,
    repo_path: Path,
    writer: BaseAIAdapter | None = None,
) -> Changeset:
    """Generate a deterministic changeset for the provided fact graph."""

    files: list[ChangesetFile] = []
    for entity in incoming.entities:
        target = repo_path / "Objekty" / f"{entity.id}.md"
        old_content = target.read_text(encoding="utf-8") if target.exists() else None

        if old_content is None:
            body = _render_entity_body(entity, writer)
            new_content = f"# {entity.id}\n{body}\n" if body else f"# {entity.id}\n\n"
        else:
            cleaned_existing = old_content.rstrip("\n")
            summary_text = _render_update_body(entity, writer)
            if not summary_text:
                # Empty updates should not modify the file.
                new_content = old_content if old_content.endswith("\n") else f"{old_content}\n"
            else:
                update_block = f"\n\n## Update\n{summary_text}\n"
                if cleaned_existing.endswith(update_block.strip("\n")):
                    # The last update already matches the incoming summary.
                    new_content = cleaned_existing + "\n"
                else:
                    new_content = f"{cleaned_existing}{update_block}"

        if old_content == new_content:
            continue

        if not new_content.endswith("\n"):
            new_content = f"{new_content}\n"
        files.append(
            ChangesetFile(
                path=str(target.relative_to(repo_path)),
                old=old_content,
                new=new_content,
            )
        )

    summary = (
        "No universe files require updates"
        if not files
        else f"Planned updates for {len(files)} universe file(s)."
    )
    return Changeset(files=files, summary=summary)


__all__ = ["plan_changes"]
