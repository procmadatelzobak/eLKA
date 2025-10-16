"""Story validation utilities executed inside Celery workers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

from app.adapters.ai.base import BaseAIAdapter
from app.utils.config import Config

from .schemas import ConsistencyIssue, FactGraph

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


def validate_universe(current: FactGraph, incoming: FactGraph) -> List[ConsistencyIssue]:
    """Compare two fact graphs and emit consistency issues."""

    issues: List[ConsistencyIssue] = []
    current_entities = {entity.id: entity for entity in current.entities}

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

    return issues


__all__ = ["ValidationStep", "ValidationReport", "ValidatorEngine", "validate_universe"]
