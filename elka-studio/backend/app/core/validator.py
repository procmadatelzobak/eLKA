"""Story validation utilities executed inside Celery workers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Set

from app.adapters.ai.base import BaseAIAdapter
from app.utils.config import Config

from .schemas import ConsistencyIssue, FactEntity, FactEvent, FactGraph

@dataclass(slots=True)
class ValidationStep:
    """Represents a single validation step outcome."""

    name: str
    passed: bool
    messages: List[str]

    def summary(self) -> str:
        status = "passed" if self.passed else "failed"
        details = "; ".join(self.messages) if self.messages else "ok"
        return f"{self.name.title()} validation {status}: {details}"


@dataclass(slots=True)
class ValidationReport:
    """Aggregate report for all validation steps."""

    passed: bool
    steps: List[ValidationStep]

    def failed_messages(self) -> List[str]:
        return ["; ".join(step.messages) for step in self.steps if not step.passed]


class ValidatorEngine:
    """High-level orchestrator responsible for validating generated stories."""

    def __init__(self, ai_adapter: BaseAIAdapter, config: Config) -> None:
        self.ai_adapter = ai_adapter
        self.config = config
        self._steps: tuple[str, ...] = ("format", "continuity", "tone")

    def validate(
        self,
        story_content: str,
        universe_files: dict[str, str] | None = None,
    ) -> ValidationReport:
        """Run all validation steps and return a structured report.

        ``universe_files`` is accepted for future contextual validation
        strategies. The current heuristic adapter does not require it, but we
        keep the signature so workers can provide additional context without
        altering their call sites later.
        """

        steps: List[ValidationStep] = []
        for step_name in self._steps:
            analysis = self.ai_adapter.analyse(story_content, step_name)
            passed = bool(analysis.get("passed", False))
            messages = self._normalise_messages(analysis.get("messages", []))
            steps.append(ValidationStep(name=step_name, passed=passed, messages=messages))
        overall_passed = all(step.passed for step in steps)
        return ValidationReport(passed=overall_passed, steps=steps)

    @staticmethod
    def _normalise_messages(messages: Iterable[str]) -> List[str]:
        normalised = [str(message).strip() for message in messages if str(message).strip()]
        return normalised or ["No issues detected."]


def validate_universe(
    current: FactGraph,
    incoming: FactGraph,
    ai: Optional[BaseAIAdapter] = None,
) -> List[ConsistencyIssue]:
    """Compare two fact graphs and emit consistency issues."""

    issues: List[ConsistencyIssue] = []
    current_entities = {entity.id: entity for entity in current.entities}
    incoming_entities = {entity.id: entity for entity in incoming.entities}

    for entity in incoming.entities:
        existing = current_entities.get(entity.id)
        if existing and entity.type != existing.type:
            issues.append(
                ConsistencyIssue(
                    level="error",
                    code="entity_type_conflict",
                    message=(
                        f"Entity {entity.id} type mismatch: incoming={entity.type} "
                        f"current={existing.type}"
                    ),
                    refs=[entity.id],
                )
            )
        elif not existing:
            issues.append(
                ConsistencyIssue(
                    level="info",
                    code="new_entity",
                    message=f"Entity {entity.id} is new to the universe.",
                    refs=[entity.id],
                )
            )

    known_entities: Set[str] = set(current_entities) | set(incoming_entities)

    issues.extend(_validate_missing_entities(incoming.events, known_entities))
    issues.extend(
        _validate_temporal_alignment(
            incoming.events,
            {**current_entities, **incoming_entities},
        )
    )

    issues.extend(
        _validate_legend_breaches(
            current.core_truths,
            incoming.entities,
            incoming.events,
            ai,
        )
    )

    issues.sort(key=lambda issue: (issue.code, "|".join(issue.refs), issue.message))
    return issues


def _validate_missing_entities(events: Iterable[FactEvent], known: Set[str]) -> List[ConsistencyIssue]:
    issues: List[ConsistencyIssue] = []
    for event in events:
        for participant in event.participants:
            if participant not in known:
                issues.append(
                    ConsistencyIssue(
                        level="error",
                        code="missing_entity",
                        message=(
                            f"Event '{event.title}' references unknown participant '{participant}'."
                        ),
                        refs=[event.id, participant],
                    )
                )
        if event.location and event.location not in known:
            issues.append(
                ConsistencyIssue(
                    level="error",
                    code="missing_entity",
                    message=(
                        f"Event '{event.title}' references unknown location '{event.location}'."
                    ),
                    refs=[event.id, event.location],
                )
            )
    return issues


def _validate_temporal_alignment(
    events: Iterable[FactEvent],
    entities: dict[str, FactEntity],
) -> List[ConsistencyIssue]:
    issues: List[ConsistencyIssue] = []
    for event in events:
        event_year = _extract_year(event.date)
        if event_year is None:
            continue
        participants = list(event.participants)
        if event.location:
            participants.append(event.location)
        for entity_id in participants:
            entity = entities.get(entity_id)
            if not entity:
                continue
            era = _parse_era(entity.attributes.get("era"))
            if not era:
                continue
            start, end = era
            if event_year < start or event_year > end:
                issues.append(
                    ConsistencyIssue(
                        level="warning",
                        code="temporal_mismatch",
                        message=(
                            f"Event '{event.title}' ({event_year}) conflicts with {entity.id} era {start}-{end}."
                        ),
                        refs=[event.id, entity.id],
                    )
                )
    return issues


def _validate_legend_breaches(
    truths: Iterable[str],
    entities: Iterable[FactEntity],
    events: Iterable[FactEvent],
    ai: Optional[BaseAIAdapter],
) -> List[ConsistencyIssue]:
    canonical_truths = [truth.strip() for truth in truths if truth.strip()]
    if not canonical_truths:
        return []

    if ai is None or not hasattr(ai, "generate_json"):
        return [
            ConsistencyIssue(
                level="info",
                code="legend_breach_check_skipped",
                message="Legend breach analysis skipped: validator adapter unavailable.",
                refs=[],
            )
        ]

    system_prompt = (
        "You are a canon auditor. Identify contradictions between canonical truths and "
        "the provided entities/events. Respond with JSON list of objects containing "
        "'message', optional 'refs', and optional 'level'. Return [] if none."
    )

    payload = {
        "truths": canonical_truths,
        "entities": [entity.dict() for entity in entities],
        "events": [event.dict() for event in events],
    }

    try:
        response = ai.generate_json(system_prompt, json.dumps(payload, ensure_ascii=False))  # type: ignore[arg-type]
        findings = json.loads(response) if isinstance(response, str) else response
    except Exception as exc:  # pragma: no cover - adapter specific
        return [
            ConsistencyIssue(
                level="info",
                code="legend_breach_check_failed",
                message=f"Legend breach analysis failed: {exc}",
                refs=[],
            )
        ]

    if not findings:
        return []

    issues: List[ConsistencyIssue] = []
    for finding in findings:
        if isinstance(finding, str):
            message = finding.strip()
            refs: List[str] = []
            level = "error"
        elif isinstance(finding, dict):
            message = str(finding.get("message") or finding.get("issue") or "Legend breach detected.").strip()
            refs = [str(ref) for ref in finding.get("refs", []) if str(ref).strip()]
            level = str(finding.get("level", "error"))
        else:
            continue
        if not message:
            continue
        issues.append(
            ConsistencyIssue(
                level="error" if level not in {"error", "warning", "info"} else level,  # type: ignore[arg-type]
                code="legend_breach",
                message=message,
                refs=refs,
            )
        )
    return issues


def _extract_year(date_text: Optional[str]) -> Optional[int]:
    if not date_text:
        return None
    match = re.search(r"(\d{3,4})", date_text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _parse_era(value: Optional[str]) -> Optional[tuple[int, int]]:
    if not value:
        return None
    numbers = [int(num) for num in re.findall(r"\d{3,4}", value)]
    if not numbers:
        return None
    if len(numbers) == 1:
        year = numbers[0]
        return year, year
    start, end = numbers[0], numbers[1]
    if start > end:
        start, end = end, start
    return start, end


__all__ = ["ValidationStep", "ValidationReport", "ValidatorEngine", "validate_universe"]
