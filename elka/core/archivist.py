"""Archivist engine responsible for translating stories into canon updates."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from ..adapters.ai.base import BaseAIAdapter
from ..utils.config import Config


logger = logging.getLogger(__name__)


@dataclass
class _EntityExtraction:
    """Container for structured data extracted from a story."""

    entities_to_update: List[Dict[str, str]]
    entities_to_create: List[Dict[str, str]]
    timeline_entries: List[Dict[str, str]]


class ArchivistEngine:
    """Translate validated stories into structured canon updates."""

    TIMELINE_PATH = "timeline.txt"

    def __init__(self, ai_adapter: BaseAIAdapter, config: Config) -> None:
        self.ai_adapter = ai_adapter
        self.config = config

        provider_name = (config.ai_provider or "").lower()
        providers_config = config.ai.get("providers", {})
        models_config = providers_config.get(provider_name, {}).get("models", {})

        self.archivist_model = models_config.get("archivist")
        if not self.archivist_model:
            raise ValueError("Konfigurace neobsahuje AI model pro archivátora.")

        self.generator_model = models_config.get("generator", self.archivist_model)

    # ------------------------------------------------------------------
    # Public API

    def archive(self, story_content: str, universe_files: Dict[str, str]) -> Dict[str, str]:
        """Generate canon updates based on a validated story."""

        extraction = self._extract_entities(story_content, universe_files)

        files_to_update = self._process_entities(
            extraction, universe_files, story_content
        )

        timeline_content = self._update_timeline(
            extraction.timeline_entries, universe_files.get(self.TIMELINE_PATH)
        )
        if timeline_content is not None:
            files_to_update[self.TIMELINE_PATH] = timeline_content

        return files_to_update

    # ------------------------------------------------------------------
    # Extraction

    def _extract_entities(
        self, story_content: str, universe_files: Dict[str, str]
    ) -> _EntityExtraction:
        canon_render = self._render_canon(universe_files.items())

        system_prompt = (
            "Jsi specializovaný analytik dat pro fiktivní univerzum. Tvým úkolem je z "
            "literárního textu extrahovat všechny klíčové entity a události a převést je do "
            "strukturovaného formátu JSON."
        )
        user_prompt = (
            "Zde je kánon univerza pro kontext, abys rozpoznal existující entity:\n"
            "--- KÁNON ---\n"
            f"{canon_render}\n"
            "--- KONEC KÁNONU ---\n\n"
            "Zde je nový příběh k analýze:\n"
            "--- PŘÍBĚH ---\n"
            f"{story_content}\n"
            "--- KONEC PŘÍBĚHU ---\n\n"
            "Projdi PŘÍBĚH a identifikuj VŠECHNY zmíněné entity (postavy, místa, předměty, "
            "koncepty) a klíčové události. Pro každou entitu urči, zda je nová, nebo již "
            "existuje v KÁNONU. Pro každou existující entitu popiš, jak ji příběh mění. "
            "Vytvoř seznam událostí pro timeline. Odpověz POUZE ve formátu JSON s "
            "následující strukturou:\n"
            "{\n"
            "  \"entities_to_update\": [\n"
            "    {\"name\": \"Jméno existující entity 1\", \"summary_of_changes\": \"Stručný popis, co se s entitou v příběhu stalo.\"},\n"
            "    {\"name\": \"Jméno existující entity 2\", \"summary_of_changes\": \"...\"}\n"
            "  ],\n"
            "  \"entities_to_create\": [\n"
            "    {\"name\": \"Jméno nové entity 1\", \"category\": \"kategorie (beings/places/things/concepts)\", \"description\": \"Detailní popis entity na základě příběhu.\"},\n"
            "    {\"name\": \"Jméno nové entity 2\", \"category\": \"...\", \"description\": \"...\"}\n"
            "  ],\n"
            "  \"timeline_entries\": [\n"
            "    {\"date\": \"Datace události 1\", \"description\": \"Stručný popis události 1 s odkazem na klíčové entity.\"},\n"
            "    {\"date\": \"Datace události 2\", \"description\": \"...\"}\n"
            "  ]\n"
            "}"
        )

        response = self.ai_adapter.prompt(self.archivist_model, system_prompt, user_prompt)
        data = self._parse_extraction_response(response)
        return data

    def _render_canon(self, files: Iterable[tuple[str, str]]) -> str:
        rendered = []
        for path, content in sorted(files, key=lambda item: item[0]):
            rendered.append(
                f"### START FILE: {path} ###\n{content}\n### END FILE: {path} ###"
            )
        return "\n\n".join(rendered)

    def _parse_extraction_response(self, response_text: str) -> _EntityExtraction:
        text = response_text.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Odpověď archivátoru není platný JSON: {text}") from exc

        if not isinstance(data, dict):
            raise ValueError("Odpověď archivátoru musí být objekt JSON.")

        entities_to_update = self._ensure_list_of_dicts(data.get("entities_to_update", []))
        entities_to_create = self._ensure_list_of_dicts(data.get("entities_to_create", []))
        timeline_entries = self._ensure_list_of_dicts(data.get("timeline_entries", []))

        return _EntityExtraction(entities_to_update, entities_to_create, timeline_entries)

    @staticmethod
    def _ensure_list_of_dicts(value: object) -> List[Dict[str, str]]:
        if not value:
            return []
        if not isinstance(value, list):
            raise ValueError("Očekáván seznam objektů JSON.")
        normalized: List[Dict[str, str]] = []
        for item in value:
            if isinstance(item, dict):
                normalized.append({k: str(v) for k, v in item.items()})
        return normalized

    # ------------------------------------------------------------------
    # Processing entities

    def _process_entities(
        self,
        extraction: _EntityExtraction,
        universe_files: Dict[str, str],
        story_content: str,
    ) -> Dict[str, str]:
        updates: Dict[str, str] = {}

        story_title = self._extract_story_title(story_content)
        introduction_date = self._infer_introduction_date(extraction.timeline_entries)

        for entity in extraction.entities_to_create:
            name = entity.get("name", "").strip()
            if not name:
                continue

            category = entity.get("category", "concepts").strip().lower() or "concepts"
            description = entity.get("description", "").strip()

            path = self._build_entity_path(name, category)
            prompt = (
                f"Vytvoř obsah databázového souboru pro novou entitu '{name}'. "
                f"Kategorie: '{category}'. Popis z příběhu: '{description}'. "
                "Použij formát definovaný vPokyny/KONVENCE-SOUBORU.txt. Přidej první záznam do "
                "Dějin s datací '{introduction_date}' a textem 'Zavedeno v příběhu: "
                f"{story_title}'."
            )
            system_prompt = (
                "Jsi pečlivý kronikář fiktivního univerza. Tvoříš nové kanonické záznamy přesně "
                "podle stanovené šablony."
            )
            content = self.ai_adapter.prompt(
                self.generator_model, system_prompt, prompt
            ).strip()
            updates[path] = content

        for entity in extraction.entities_to_update:
            name = entity.get("name", "").strip()
            summary = entity.get("summary_of_changes", "").strip()
            if not name or not summary:
                continue

            path = self._find_entity_file(name, universe_files)
            if not path:
                logger.warning("Nebyl nalezen soubor pro aktualizaci entity '%s'.", name)
                continue

            current_content = universe_files.get(path)
            if current_content is None:
                logger.warning(
                    "Obsah souboru %s nebyl nalezen v kánonu, přeskočeno.", path
                )
                continue

            system_prompt = (
                "Jsi kronikář, který aktualizuje existující záznamy univerza. Dodržuj přesně "
                "strukturu souboru a doplň nové informace na správná místa."
            )
            user_prompt = (
                f"Zde je obsah existujícího souboru pro entitu '{name}':\n---\n"
                f"{current_content}\n---\n"
                f"Na základě této události: '{summary}', přidej nový, správně datovaný záznam do "
                "sekce Dějiny. Pokud je to nutné, aktualizuj pole 'stav'. Vrať kompletní, "
                "aktualizovaný obsah souboru."
            )
            updated_content = self.ai_adapter.prompt(
                self.generator_model, system_prompt, user_prompt
            ).strip()
            updates[path] = updated_content

        return updates

    @staticmethod
    def _extract_story_title(story_content: str) -> str:
        match = re.search(r"^\s*nazev\s*:\s*(.+)$", story_content, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).strip()
        return "Neznámý příběh"

    @staticmethod
    def _infer_introduction_date(timeline_entries: List[Dict[str, str]]) -> str:
        for entry in timeline_entries:
            date = entry.get("date")
            if date:
                return str(date)
        return "Neznámé datum"

    def _build_entity_path(self, name: str, category: str) -> str:
        slug = self._slugify(name)
        sanitized_category = self._slugify(category)
        if sanitized_category not in {"beings", "places", "things", "concepts"}:
            sanitized_category = "concepts"
        return str(Path("Objekty") / sanitized_category / f"{slug}.txt")

    def _find_entity_file(
        self, entity_name: str, universe_files: Dict[str, str]
    ) -> Optional[str]:
        slug = self._slugify(entity_name)
        for path in universe_files:
            file_stem = Path(path).stem.lower()
            if file_stem == slug:
                return path

        entity_lower = entity_name.lower()
        for path, content in universe_files.items():
            if entity_lower in content.lower():
                return path

        return None

    @staticmethod
    def _slugify(value: str) -> str:
        normalized = re.sub(r"[^\w\-]+", "-", value.lower()).strip("-")
        normalized = re.sub(r"-+", "-", normalized)
        return normalized or "entity"

    # ------------------------------------------------------------------
    # Timeline handling

    def _update_timeline(
        self, entries: List[Dict[str, str]], existing_content: Optional[str]
    ) -> Optional[str]:
        if not entries:
            return existing_content if existing_content is not None else None

        combined_entries = []

        if existing_content:
            for line in existing_content.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                date, description = self._split_timeline_line(stripped)
                combined_entries.append((date, description))

        for entry in entries:
            date = str(entry.get("date", "")).strip()
            description = str(entry.get("description", "")).strip()
            if not description:
                continue
            combined_entries.append((date, description))

        combined_entries = list({(d, desc) for d, desc in combined_entries})
        combined_entries.sort(key=lambda item: (item[0] or "", item[1]))

        lines = [self._format_timeline_line(date, description) for date, description in combined_entries]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _split_timeline_line(line: str) -> tuple[str, str]:
        if " - " in line:
            date, description = line.split(" - ", 1)
            return date.strip(), description.strip()
        return "", line.strip()

    @staticmethod
    def _format_timeline_line(date: str, description: str) -> str:
        if date:
            return f"{date} - {description}"
        return description

