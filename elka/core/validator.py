"""Validator engine responsible for verifying new stories against canon."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from elka.adapters.ai.base import BaseAIAdapter
from elka.utils.config import Config


ValidationResult = Dict[str, Any]


@dataclass
class _RulesData:
    """Container for separated validation rules."""

    format_rules: List[Tuple[str, str]]
    tone_rules: List[Tuple[str, str]]


class ValidatorEngine:
    """Core validator orchestrating different validation stages."""

    FORMAT_RULE_KEYWORDS = ("format", "metadata", "meta", "sablona")

    def __init__(self, ai_adapter: BaseAIAdapter, config: Config) -> None:
        self.ai_adapter = ai_adapter
        self.config = config
        self.logger = logging.getLogger(__name__)

        provider_name = (config.ai_provider or "").lower()
        providers_config = config.ai.get("providers", {})
        models_config = providers_config.get(provider_name, {}).get("models", {})
        self.model_name = models_config.get("validator")
        if not self.model_name:
            raise ValueError("Konfigurace neobsahuje AI model pro validátor.")

        rules_path = str(config.core.get("rules_path", "") or "").replace("\\", "/")
        self.rules_path = rules_path.strip("/")

    def validate(self, story_content: str, universe_files: Dict[str, str]) -> ValidationResult:
        """Run sequential validation checks on the provided story."""

        format_result = self._validate_format(story_content, universe_files)
        if not format_result.get("passed", False):
            return format_result

        continuity_result = self._validate_continuity(story_content, universe_files)
        if not continuity_result.get("passed", False):
            return continuity_result

        tone_result = self._validate_tone(story_content, universe_files)
        return tone_result

    # ------------------------------------------------------------------
    # Validation steps

    def _validate_format(self, story_content: str, universe_files: Dict[str, str]) -> ValidationResult:
        rules_data = self._extract_rules(universe_files)
        if not rules_data.format_rules:
            self.logger.error("V pravidlech nebyl nalezen žádný soubor popisující formát metadat.")
            return {
                "passed": False,
                "errors": ["V hlavní větvi nebyla nalezena pravidla pro formát metadat příběhu."],
            }

        format_rules_content = self._render_files(rules_data.format_rules)
        system_prompt = (
            "Jsi precizní validátor formátu pro fiktivní univerzum. Tvým úkolem je "
            "zkontrolovat, zda metadata v zadaném textu odpovídají požadované struktuře."
        )
        user_prompt = (
            "Zde je soubor s pravidly pro formát:\n"
            "--- PRAVIDLA ---\n"
            f"{format_rules_content}\n"
            "--- KONEC PRAVIDEL ---\n\n"
            "Zde je obsah nového příběhu:\n"
            "--- PŘÍBĚH ---\n"
            f"{story_content}\n"
            "--- KONEC PŘÍBĚHU ---\n\n"
            "Zkontroluj, zda metadata na začátku příběhu (část id:, nazev:, atd.) přesně odpovídají "
            "formátu popsanému v pravidlech. Odpověz POUZE ve formátu JSON. Pokud je vše v "
            "pořádku, odpověz: {\"passed\": true, \"errors\": []}. Pokud najdeš chyby, odpověz: "
            "{\"passed\": false, \"errors\": [\"Popis chyby 1\", \"Popis chyby 2\"]}."
        )

        return self._invoke_validator(system_prompt, user_prompt, stage="format")

    def _validate_continuity(self, story_content: str, universe_files: Dict[str, str]) -> ValidationResult:
        if not universe_files:
            self.logger.error("Kontinuitu nelze ověřit, protože chybí data kánonu.")
            return {
                "passed": False,
                "errors": ["Kontinuitu nelze ověřit – nepodařilo se načíst žádné kanonické soubory."],
            }

        canon_content = self._render_files(sorted(universe_files.items()))
        system_prompt = (
            "Jsi extremně detailní a pečlivý strážce kontinuity fiktivního univerza. Tvým úkolem je "
            "najít jakékoli faktické a chronologické rozpory mezi novým příběhem a zavedeným kánonem."
        )
        user_prompt = (
            "Zde je kompletní kánon univerza, soubor po souboru:\n"
            "--- KÁNON ---\n"
            f"{canon_content}\n"
            "--- KONEC KÁNONU ---\n\n"
            "Zde je nový příběh k validaci:\n"
            "--- PŘÍBĚH ---\n"
            f"{story_content}\n"
            "--- KONEC PŘÍBĚHU ---\n\n"
            "Pečlivě porovnej události, data, stavy postav a vlastnosti objektů v PŘÍBĚHU s "
            "informacemi v KÁNONU. Najdi VŠECHNY rozpory. Odpověz POUZE ve formátu JSON. Pokud "
            "je vše v pořádku, odpověz: {\"passed\": true, \"errors\": []}. Pokud najdeš rozpory, "
            "odpověz: {\"passed\": false, \"errors\": [\"Detailní popis rozporu 1 s citací a odkazem "
            "na zdrojový soubor v kánonu.\", \"Detailní popis rozporu 2...\"]}."
        )

        return self._invoke_validator(system_prompt, user_prompt, stage="continuity")

    def _validate_tone(self, story_content: str, universe_files: Dict[str, str]) -> ValidationResult:
        rules_data = self._extract_rules(universe_files)
        if not rules_data.tone_rules:
            self.logger.error("Nenalezena žádná pravidla popisující tón a základní pravdy univerza.")
            return {
                "passed": False,
                "errors": ["Chybí pravidla tónu – nelze zhodnotit atmosféru příběhu."],
            }

        tone_rules_content = self._render_files(rules_data.tone_rules)
        system_prompt = (
            "Jsi literární kritik a strážce stylu fiktivního univerza. Tvým úkolem je posoudit, "
            "zda nový příběh odpovídá zavedenému tónu, tématům a 'fyzikálním zákonům' světa."
        )
        user_prompt = (
            "Zde jsou soubory definující základní pravdy a tón univerza:\n"
            "--- PRAVIDLA TÓNU ---\n"
            f"{tone_rules_content}\n"
            "--- KONEC PRAVIDEL ---\n\n"
            "Zde je nový příběh k posouzení:\n"
            "--- PŘÍBĚH ---\n"
            f"{story_content}\n"
            "--- KONEC PŘÍBĚHU ---\n\n"
            "Posuď, zda se styl, témata a zavedené koncepty (technologie, magie atd.) v PŘÍBĚHU "
            "shodují s PRAVIDLY TÓNU. Hledej prvky, které působí cize nebo narušují atmosféru světa. "
            "Odpověz POUZE ve formátu JSON. Pokud je vše v pořádku, odpověz: {\"passed\": true, \"errors\": []}. "
            "Pokud najdeš problémy, odpověz: {\"passed\": false, \"errors\": [\"Popis tonálního "
            "problému 1 s doporučením na úpravu.\", \"Popis problému 2...\"]}."
        )

        return self._invoke_validator(system_prompt, user_prompt, stage="tone")

    # ------------------------------------------------------------------
    # Helpers

    def _invoke_validator(self, system_prompt: str, user_prompt: str, stage: str) -> ValidationResult:
        try:
            response_text = self.ai_adapter.prompt(self.model_name, system_prompt, user_prompt)
            return self._parse_response(response_text)
        except Exception as exc:  # pragma: no cover - ochrana před selháním API
            self.logger.exception("Validace %s selhala: %s", stage, exc)
            return {"passed": False, "errors": [f"Validace {stage} selhala: {exc}"]}

    def _parse_response(self, response_text: str) -> ValidationResult:
        text = response_text.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Odpověď validátoru není platný JSON: {text}") from exc

        if not isinstance(data, dict):
            raise ValueError("Odpověď validátoru musí být objekt JSON.")

        passed = bool(data.get("passed"))
        errors = data.get("errors", [])
        if not isinstance(errors, list):
            raise ValueError("Klíč 'errors' musí obsahovat seznam chyb.")

        normalized_errors = [str(err) for err in errors]
        return {"passed": passed, "errors": normalized_errors}

    def _extract_rules(self, universe_files: Dict[str, str]) -> _RulesData:
        format_rules: List[Tuple[str, str]] = []
        tone_rules: List[Tuple[str, str]] = []

        if not self.rules_path:
            return _RulesData(format_rules, tone_rules)

        normalized_prefix = self.rules_path + "/" if self.rules_path else ""
        for path, content in universe_files.items():
            normalized_path = self._normalize_path(path)
            if not normalized_path.startswith(normalized_prefix):
                continue

            lower = normalized_path.lower()
            if any(keyword in lower for keyword in self.FORMAT_RULE_KEYWORDS):
                format_rules.append((path, content))
            else:
                tone_rules.append((path, content))

        return _RulesData(format_rules, tone_rules)

    def _render_files(self, files: List[Tuple[str, str]]) -> str:
        rendered_parts = []
        for path, content in files:
            rendered_parts.append(
                f"### START FILE: {path} ###\n{content}\n### END FILE: {path} ###"
            )
        return "\n\n".join(rendered_parts)

    @staticmethod
    def _normalize_path(path: str) -> str:
        normalized = path.replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        return normalized

