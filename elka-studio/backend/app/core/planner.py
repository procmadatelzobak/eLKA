"""Planner responsible for proposing deterministic repository changes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Tuple

from app.adapters.ai.base import BaseAIAdapter

from .extractor import _slugify
from .schemas import Changeset, ChangesetFile, FactEntity, FactEvent, FactGraph

TEMPLATE_TIMELINE = (
    Path(__file__).resolve().parent.parent / "templates" / "universe_scaffold" / "timeline.md"
)


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
    entity_updates = 0
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
                if "## Update" not in cleaned_existing:
                    base_body = cleaned_existing.split("\n", 1)[1] if "\n" in cleaned_existing else ""
                    if base_body.strip() == summary_text.strip():
                        new_content = cleaned_existing + "\n"
                        if old_content == new_content:
                            continue
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
        entity_updates += 1

    timeline_change = _plan_timeline_updates(incoming.events, repo_path, files)

    summary = (
        "No universe files require updates"
        if not files
        else (
            "Planned updates for "
            + ", ".join(
                filter(
                    None,
                    [
                        f"{entity_updates} entity file(s)" if entity_updates else "",
                        f"{timeline_change} timeline entry(ies)" if timeline_change else "",
                    ],
                )
            )
            + "."
        )
    )
    return Changeset(files=files, summary=summary)


def _plan_timeline_updates(
    events: Iterable[FactEvent],
    repo_path: Path,
    files: List[ChangesetFile],
) -> int:
    event_list = [event for event in events if event.title]
    if not event_list:
        return 0

    timeline_path, old_content, base_content = _load_timeline(repo_path)

    existing_lines = base_content.splitlines()
    header, existing_events, footer = _split_timeline(existing_lines)
    existing_line_set = {item["line"].strip() for item in existing_events}
    existing_keys = {
        _normalize_date_key(item["date"], _slugify(item["title"])) for item in existing_events
    }

    additions: list[dict[str, str | None]] = []
    for event in event_list:
        line = _format_event_line(event)
        stripped = line.strip()
        date = event.date or _extract_date_from_line(stripped)
        slug = _slugify(event.title)
        key = _normalize_date_key(date, slug)
        if stripped in existing_line_set or key in existing_keys:
            continue
        additions.append({"date": date, "title": event.title, "line": stripped})
        existing_keys.add(key)

    if not additions:
        return 0

    merged_events = existing_events + additions
    merged_events.sort(
        key=lambda item: _normalize_date_key(
            item.get("date"), _slugify(str(item.get("title", "")))
        )
    )

    rebuilt_lines: list[str] = []
    rebuilt_lines.extend(header)
    if header and header[-1].strip():
        rebuilt_lines.append("")
    rebuilt_lines.extend(item["line"] for item in merged_events)
    if footer:
        if rebuilt_lines and rebuilt_lines[-1].strip():
            rebuilt_lines.append("")
        rebuilt_lines.extend(footer)

    new_content = "\n".join(rebuilt_lines)
    if new_content and not new_content.endswith("\n"):
        new_content += "\n"

    files.append(
        ChangesetFile(
            path=str(timeline_path.relative_to(repo_path)),
            old=old_content,
            new=new_content,
        )
    )
    return len(additions)


def _load_timeline(repo_path: Path) -> tuple[Path, str | None, str]:
    for candidate in (repo_path / "timeline.md", repo_path / "timeline.txt"):
        if candidate.exists():
            text = candidate.read_text(encoding="utf-8")
            return candidate, text, text

    template_text = (
        TEMPLATE_TIMELINE.read_text(encoding="utf-8") if TEMPLATE_TIMELINE.is_file() else "# Timeline\n"
    )
    timeline_path = repo_path / "timeline.md"
    return timeline_path, None, template_text


def _split_timeline(lines: List[str]) -> tuple[List[str], List[dict[str, str | None]], List[str]]:
    header: list[str] = []
    events: list[dict[str, str | None]] = []
    footer: list[str] = []
    event_started = False
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            date = _extract_date_from_line(stripped)
            title = _extract_title_from_line(stripped)
            events.append({"date": date, "title": title, "line": stripped})
            event_started = True
        else:
            if not event_started:
                header.append(line)
            else:
                footer.append(line)
    return header, events, footer


def _format_event_line(event: FactEvent) -> str:
    parts = []
    if event.date:
        parts.append(event.date.strip())
    title = event.title.strip()
    parts.append(title)
    if event.location:
        parts.append(f"@ {event.location}")
    if event.description:
        parts.append(f"– {event.description.strip()}")
    return " ".join(parts)


def _extract_date_from_line(line: str) -> str | None:
    match = _TIMELINE_DATE_PATTERN.match(line)
    if match:
        return match.group("date").strip()
    return None


def _extract_title_from_line(line: str) -> str:
    match = _TIMELINE_DATE_PATTERN.match(line)
    if match:
        remainder = match.group("title").strip()
        return remainder or line
    return line


_TIMELINE_DATE_PATTERN = re.compile(
    r"^(?P<date>(?:\d{3,4}(?:[\-/]\d{1,2}){0,2}|(?:jaro|léto|leto|podzim|zima|spring|summer|autumn|fall|winter)\s+\d{3,4}))?\s*(?:[-–—:]\s*)?(?P<title>.+)$",
    flags=re.IGNORECASE,
)


def _normalize_date_key(raw: str | None, slug: str) -> Tuple[int, int, int, str]:
    slug = slug or ""
    if not raw:
        return (9999, 12, 31, slug)

    text = raw.strip().lower()
    season_map = {
        "zima": 1,
        "winter": 1,
        "jaro": 4,
        "spring": 4,
        "léto": 7,
        "leto": 7,
        "summer": 7,
        "podzim": 10,
        "autumn": 10,
        "fall": 10,
    }

    year = 9999
    month = 12
    day = 31

    match = re.search(r"(\d{3,4})", text)
    if match:
        year = int(match.group(1))

    if "-" in text or "/" in text:
        parts = re.split(r"[-/]", text)
        try:
            if len(parts) > 1 and parts[1].isdigit():
                month = int(parts[1])
            if len(parts) > 2 and parts[2].isdigit():
                day = int(parts[2])
        except ValueError:
            month = 12
            day = 31
    else:
        for season, value in season_map.items():
            if season in text:
                month = value
                day = 0
                break
    return (year, month, day, slug)


def _date_from_key(key: Tuple[int, int, int, str]) -> str | None:
    year, month, day, slug = key
    if year == 9999:
        return None
    if day == 31 and month == 12:
        return str(year)
    if day == 0:
        return str(year)
    return f"{year:04d}-{month:02d}-{day:02d}"


def _title_from_line(line: str) -> str:
    return _extract_title_from_line(line)


__all__ = ["plan_changes"]
