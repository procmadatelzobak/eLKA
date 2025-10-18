from __future__ import annotations
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict

from celery.exceptions import MaxRetriesExceededError, Retry
from google import genai
from google.api_core.exceptions import ResourceExhausted
from google.genai.errors import ClientError
from limits import RateLimitItemPerMinute
from limits.storage import MemoryStorage, RedisStorage
from limits.strategies import MovingWindowRateLimiter

from app.adapters.ai.base import BaseAIAdapter
from app.utils.config import Config


logger = logging.getLogger(__name__)
@dataclass(slots=True)
class GeminiAdapter(BaseAIAdapter):
    """Parametric adapter for Google Gemini models."""

    config: Config
    model: str

    def __post_init__(self) -> None:
        BaseAIAdapter.__init__(self, self.config)
        api_key = self.config.get_gemini_api_key()
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        self._client = genai.Client(api_key=api_key)
        self._model_aliases = self.config.get_ai_model_aliases()
        self._rate_limit_rpm = self.config.gemini_rate_limit_rpm()
        self._rate_limit_namespace = f"gemini:{self.model}"
        self._rate_limit_sleep = 0.0
        self._rate_limiter_disabled = False
        self._rate_limiter: MovingWindowRateLimiter | None = None
        self._rate_limit_item: RateLimitItemPerMinute | None = None

        if self._rate_limit_rpm > 0:
            self._rate_limit_sleep = max(60.0 / float(self._rate_limit_rpm), 1.0)
            redis_url = os.getenv("ELKA_RATE_LIMIT_REDIS_URL") or os.getenv(
                "CELERY_BROKER_URL", "redis://localhost:6379/0"
            )
            try:
                storage = RedisStorage(redis_url)
            except Exception as exc:  # pragma: no cover - depends on Redis availability
                if isinstance(exc, Retry):
                    raise
                logger.warning(
                    "Falling back to in-memory rate limiter for Gemini usage tracking: %s",
                    exc,
                )
                storage = MemoryStorage()

            self._rate_limiter = MovingWindowRateLimiter(storage)
            self._rate_limit_item = RateLimitItemPerMinute(self._rate_limit_rpm)

        # TODO: Implement more sophisticated usage tracking. Google does not
        # expose remaining quota details, so the moving window approximation is
        # best effort and based on successful requests recorded in Redis.

    def _wait_for_rate_limit(self) -> None:
        """Block until the proactive rate limiter grants a slot."""

        if (
            self._rate_limiter is None
            or self._rate_limit_item is None
            or self._rate_limiter_disabled
        ):
            return

        logged = False
        waited = False
        while True:
            try:
                allowed = self._rate_limiter.hit(
                    self._rate_limit_item, self._rate_limit_namespace
                )
            except Exception as exc:  # pragma: no cover - depends on Redis availability
                if isinstance(exc, Retry):
                    raise
                if not self._rate_limiter_disabled:
                    logger.warning(
                        "Disabling proactive Gemini rate limiter due to storage error: %s",
                        exc,
                    )
                self._rate_limiter_disabled = True
                break

            if allowed:
                break

            if not logged:
                logger.info(
                    "Approaching Gemini rate limit (%s RPM); waiting for an available slot.",
                    self._rate_limit_rpm,
                )
                logged = True

            time.sleep(self._rate_limit_sleep or 1.0)
            waited = True

        if waited:
            logger.info("Rate limit slot acquired after waiting.")

        # TODO: Consider surfacing estimated wait durations to task metadata so
        # long-running jobs can report ETA updates while throttled. Accuracy is
        # difficult because retries and external quota resets are opaque.

    def _resolve_model(self, model_key: str | None = None) -> str:
        if model_key:
            resolved = self._model_aliases.get(model_key)
            if resolved:
                return resolved
            return model_key
        return self.model

    def _extract_usage_metadata(self, response: object) -> dict | None:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return None
        prompt_tokens = getattr(usage, "prompt_token_count", None) or getattr(
            usage, "prompt_tokens", 0
        )
        candidate_tokens = getattr(
            usage, "candidates_token_count", None
        ) or getattr(usage, "candidates_tokens", 0)
        metadata = {
            "prompt_token_count": int(prompt_tokens or 0),
            "candidates_token_count": int(candidate_tokens or 0),
        }
        total = getattr(usage, "total_token_count", None) or getattr(
            usage, "total_tokens", None
        )
        if total is not None:
            metadata["total_tokens"] = int(total)
        else:
            metadata["total_tokens"] = metadata["prompt_token_count"] + metadata[
                "candidates_token_count"
            ]
        return metadata

    def generate_text(
        self, prompt: str, model_key: str | None = None
    ) -> tuple[str, dict | None]:
        model_name = self._resolve_model(model_key)
        self._wait_for_rate_limit()
        try:
            response = self._client.models.generate_content(
                model=model_name, contents=prompt
            )
        except (ResourceExhausted, ClientError) as exc:
            self._handle_rate_limit(exc, operation="text generation")
            return "", None
        except Exception as exc:
            # Allow Celery retry exceptions to propagate without logging.
            if isinstance(exc, Retry):
                raise exc
            logger.error(
                "Unexpected error during Gemini text generation: %s",
                exc,
                exc_info=True,
            )
            raise
        metadata = self._extract_usage_metadata(response)
        return getattr(response, "text", ""), metadata

    def analyse(
        self,
        story_content: str,
        aspect: str = "generic",
        context: str | None = None,
    ) -> Dict[str, object] | str:  # type: ignore[override]
        """Call the configured Gemini model for analytical tasks."""

        if context:
            prompt = (
                "You are evaluating a story for consistency with the provided universe context.\n"
                f"ASPECT: {aspect}\n"
                "--- BEGIN CONTEXT ---\n"
                f"{context}\n"
                "--- END CONTEXT ---\n"
                "--- BEGIN STORY ---\n"
                f"{story_content}\n"
                "--- END STORY ---"
            )
        else:
            prompt = story_content

        self._wait_for_rate_limit()
        try:
            response = self._client.models.generate_content(
                model=self._resolve_model(), contents=prompt
            )
        except (ResourceExhausted, ClientError) as exc:
            self._handle_rate_limit(exc, operation="analysis")
            return str(exc)
        except Exception as exc:
            # Allow Celery retry exceptions to propagate without logging.
            if isinstance(exc, Retry):
                raise exc
            logger.error(
                "Unexpected error during Gemini analysis: %s",
                exc,
                exc_info=True,
            )
            raise
        return getattr(response, "text", str(response))

    def summarise(self, story_content: str) -> str:  # type: ignore[override]
        """Summarise narrative content using the writer model."""

        instruction = (
            "Provide a concise summary (no more than 40 words) of the following story. "
            "Return plain text without bullet points."
        )
        summary = self.generate_markdown(instruction=instruction, context=story_content).strip()
        return summary or "Summary unavailable"

    def generate_markdown(self, instruction: str, context: str | None = None) -> str:
        """Generate Markdown content using the Gemini model."""

        contents = instruction if not context else f"{instruction}\n\nCONTEXT:\n{context}"
        text, _ = self.generate_text(contents)
        return text

    def generate_json(
        self, system: str, user: str, model_key: str | None = None
    ) -> tuple[str, dict | None]:
        """Return JSON-formatted text by combining system and user prompts."""

        prompt = f"{system}\n\n{user}"
        try:
            text, metadata = self.generate_text(prompt, model_key=model_key)
        except (ResourceExhausted, ClientError) as exc:
            self._handle_rate_limit(exc, operation="JSON generation")
            return "{}", None
        except Exception as exc:
            # Allow Celery retry exceptions to propagate without logging.
            if isinstance(exc, Retry):
                raise exc
            logger.error(
                "Unexpected error during Gemini JSON generation: %s",
                exc,
                exc_info=True,
            )
            raise
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            error_message = f"Failed to decode JSON from Gemini: {text}"
            logger.error(error_message)
            raise ValueError(error_message) from exc
        except Exception as exc:  # pragma: no cover - defensive logging
            if isinstance(exc, Retry):
                raise
            logger.error("Error processing Gemini JSON response: %s", exc)
            raise
        return text, metadata

    def _is_rate_limit_error(self, exc: Exception) -> bool:
        if isinstance(exc, ResourceExhausted):
            return True

        if isinstance(exc, ClientError):
            code = getattr(exc, "code", None)
            status = (getattr(exc, "status", "") or "").upper()
            message = (getattr(exc, "message", "") or str(exc)).upper()
            if code == 429:
                return True
            if "RESOURCE_EXHAUSTED" in status:
                return True
            if "QUOTA" in message or "RATE" in message:
                return True

        return False

    def _coerce_retry_seconds(self, value: object) -> int | None:
        if value is None:
            return None

        if isinstance(value, (int, float)):
            if value > 0:
                return max(int(value), 1)
            return None

        if isinstance(value, str):
            match = re.search(r"(\d+(?:\.\d+)?)", value)
            if match:
                seconds = float(match.group(1))
                if seconds > 0:
                    return max(int(seconds), 1)
            return None

        return None

    def _extract_retry_seconds(self, container: object) -> int | None:
        seconds = self._coerce_retry_seconds(container)
        if seconds is not None:
            return seconds

        if isinstance(container, dict):
            for key in ("retry_delay", "retryDelay", "retry-after", "retry_after"):
                if key in container:
                    seconds = self._coerce_retry_seconds(container[key])
                    if seconds is not None:
                        return seconds
            for value in container.values():
                seconds = self._extract_retry_seconds(value)
                if seconds is not None:
                    return seconds

        if isinstance(container, (list, tuple, set)):
            for item in container:
                seconds = self._extract_retry_seconds(item)
                if seconds is not None:
                    return seconds

        return None

    def _parse_retry_delay(self, exc: ResourceExhausted | ClientError) -> int:
        """Best-effort extraction of retry delay seconds from Gemini errors."""

        default_delay = max(int(self._rate_limit_sleep or 1.0), 5)

        retry_delay = getattr(exc, "retry_delay", None)
        if retry_delay is not None:
            total_seconds = getattr(retry_delay, "total_seconds", None)
            if callable(total_seconds):
                seconds = int(total_seconds())
                if seconds > 0:
                    return seconds
            try:
                seconds = int(retry_delay)
                if seconds > 0:
                    return seconds
            except (TypeError, ValueError):
                pass

        metadata_sources: list[Any] = []
        details = getattr(exc, "details", None)
        if details:
            metadata_sources.append(details)
            if isinstance(details, dict) and "error" in details:
                metadata_sources.append(details["error"])

        errors_attr = getattr(exc, "errors", None)
        if errors_attr:
            metadata_sources.append(errors_attr)

        for source in metadata_sources:
            seconds = self._extract_retry_seconds(source)
            if seconds is not None:
                return seconds

        message = str(exc)
        match = re.search(r"retry\s*(?:in|after)\s*(\d+(?:\.\d+)?)", message, re.IGNORECASE)
        if match:
            seconds = float(match.group(1))
            if seconds > 0:
                return max(int(seconds), 1)

        return default_delay

    def count_tokens(self, text: str) -> int:
        try:
            counting_model_name = self._resolve_model(self.config.validator_model())
            self._wait_for_rate_limit()
            response = self._client.models.count_tokens(
                model=counting_model_name,
                contents=text,
            )
            return int(getattr(response, "total_tokens", 0))
        except Exception as exc:  # pragma: no cover - depends on external service
            if isinstance(exc, Retry):
                raise
            logger.error("Failed to count tokens: %s", exc)
            return 0

    def _handle_rate_limit(
        self, exc: ResourceExhausted | ClientError, operation: str
    ) -> None:
        """Centralised handling for Gemini rate limit responses."""

        if not self._is_rate_limit_error(exc):
            raise exc

        logger.warning("Gemini rate limit hit during %s: %s", operation, exc)
        limit_type = "Token Count" if "token_count" in str(exc) else "Request Rate (RPM)"
        logger.warning(
            "Detected Limit Type: %s. Consider adjusting context size or RPM config.",
            limit_type,
        )

        delay_seconds = self._parse_retry_delay(exc)
        logger.info(
            "Rate limit triggered. Will request Celery task retry in %s seconds.",
            delay_seconds,
        )

        from celery import current_task

        if current_task:
            try:
                current_task.retry(
                    exc=exc,
                    countdown=delay_seconds,
                    max_retries=5,
                )
            except Retry:
                raise
            except MaxRetriesExceededError:
                logger.error("Max retries exceeded for rate limit. Task will fail.")
                raise exc
            except Exception as retry_exc:  # pragma: no cover - defensive logging
                if isinstance(retry_exc, Retry):
                    raise retry_exc
                logger.error("Error during Celery retry attempt: %s", retry_exc)
                raise exc
            return None
        else:
            logger.warning(
                "Not running within a Celery task context, re-raising ResourceExhausted."
            )
            raise exc


__all__ = ["GeminiAdapter"]
