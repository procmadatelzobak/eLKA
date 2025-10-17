"""Planner responsible for proposing deterministic repository changes."""

from __future__ import annotations

from pathlib import Path

from .schemas import Changeset, ChangesetFile, FactGraph


def plan_changes(current: FactGraph, incoming: FactGraph, repo_path: Path) -> Changeset:
    """Generate a deterministic changeset for the provided fact graph."""

    files: list[ChangesetFile] = []
    for entity in incoming.entities:
        target = repo_path / "Objekty" / f"{entity.id}.md"
        old_content = target.read_text(encoding="utf-8") if target.exists() else None

        if old_content is None:
            body = (entity.summary or "").strip()
            new_content = f"# {entity.id}\n{body}\n"
        else:
            cleaned_existing = old_content.rstrip("\n")
            summary_text = (entity.summary or "").strip()
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
