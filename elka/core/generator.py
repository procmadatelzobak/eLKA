"""Autonomní generátor příběhů využívající existující orchestrátor."""

from __future__ import annotations

import json
import logging
import random
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Tuple

from elka.adapters.ai.base import BaseAIAdapter
from elka.adapters.git.base import BaseGitAdapter
from elka.core.archivist import ArchivistEngine
from elka.core.validator import ValidatorEngine
from elka.utils.config import Config


class GeneratorEngine:
    """Engine zajišťující autonomní generování nových příběhů."""

    STORY_DIRECTORY = "Stories"

    def __init__(
        self,
        ai_adapter: BaseAIAdapter,
        git_adapter: BaseGitAdapter,
        config: Config,
    ) -> None:
        self.ai_adapter = ai_adapter
        self.git_adapter = git_adapter
        self.config = config
        self.logger = logging.getLogger(__name__)

        self.validator = ValidatorEngine(ai_adapter=ai_adapter, config=config)
        self.archivist = ArchivistEngine(ai_adapter=ai_adapter, config=config)

        provider_name = (config.ai_provider or "").lower()
        providers_config = config.ai.get("providers", {})
        models_config = providers_config.get(provider_name, {}).get("models", {})
        self.generator_model = models_config.get("generator")
        if not self.generator_model:
            raise ValueError("Konfigurace neobsahuje AI model pro generátor.")

        core_config = config.core or {}
        self.main_branch = core_config.get("main_branch", "master")
        rules_path = str(core_config.get("rules_path", "") or "").replace("\\", "/")
        self.rules_prefix = rules_path.strip("/")
        self.repo_root = Path(__file__).resolve().parents[2]

    # ------------------------------------------------------------------
    # Public API

    def run_cycle(self, num_stories: int = 1) -> None:
        """Spusť jeden nebo více cyklů autonomního generování."""

        for index in range(1, num_stories + 1):
            self.logger.info("Spouštím autonomní generaci příběhu %s/%s", index, num_stories)

            try:
                universe_files = self._load_universe_files()
            except RuntimeError as exc:
                self.logger.exception("Načtení kánonu selhalo: %s", exc)
                break

            idea = self._generate_idea(universe_files)
            if not idea:
                self.logger.warning("Generátor nevrátil žádný validní námět, cyklus přeskočen.")
                continue

            try:
                story_content = self._write_story(idea, universe_files)
            except Exception as exc:  # pragma: no cover - závislé na AI
                self.logger.exception("Generování příběhu selhalo: %s", exc)
                continue

            validation_result = self.validator.validate(story_content, universe_files)
            if not validation_result.get("passed", False):
                errors = validation_result.get("errors", [])
                self.logger.warning(
                    "Validace generovaného příběhu selhala. Důvody: %s", "; ".join(errors)
                )
                continue

            try:
                archive_updates = self.archivist.archive(story_content, universe_files)
            except Exception as exc:  # pragma: no cover - závislé na AI
                self.logger.exception("Archivace generovaného příběhu selhala: %s", exc)
                continue

            files_to_commit = dict(archive_updates)
            story_path = self._determine_story_path(story_content)
            files_to_commit[story_path] = story_content

            story_title = self._extract_metadata_value(story_content, "nazev")
            if not story_title:
                story_title = "Neznámý příběh"

            branch_name = self._build_generated_branch_name(story_title)
            commit_message = f"eLKA: Autonomně vygenerován příběh '{story_title}'."

            try:
                self.git_adapter.create_branch_and_commit(
                    self.main_branch,
                    branch_name,
                    files_to_commit,
                    commit_message,
                )
            except NotImplementedError:
                self.logger.error("Git adaptér nepodporuje vytvoření nové větve. Cyklus končí.")
                break
            except Exception as exc:  # pragma: no cover - závislé na Git API
                self.logger.exception("Commit do větve %s selhal: %s", branch_name, exc)
                continue

            pr_title = f"eLKA: Nový příběh '{story_title}'"
            pr_body = self._build_pr_body(idea, story_path, archive_updates)

            try:
                pr_url = self.git_adapter.create_pull_request(
                    pr_title,
                    pr_body,
                    branch_name,
                    self.main_branch,
                )
                if pr_url:
                    self.logger.info("Autonomní PR vytvořeno: %s", pr_url)
            except NotImplementedError:
                self.logger.info("Git adaptér nepodporuje automatické PR – krok přeskočen.")
            except Exception as exc:  # pragma: no cover - závislé na Git API
                self.logger.exception("Vytvoření PR pro větev %s selhalo: %s", branch_name, exc)

    # ------------------------------------------------------------------
    # Generační kroky

    def _generate_idea(self, universe_files: Dict[str, str]) -> Dict[str, str]:
        canon_content = self._render_files(sorted(universe_files.items()))

        system_prompt = (
            "Jsi zkušený editor a tvůrce světů. Tvým úkolem je analyzovat existující "
            "univerzum a navrhnout zajímavé, konzistentní a logické náměty na další "
            "příběhy, které by ho obohatily."
        )

        user_prompt = (
            "Zde je kompletní kánon univerza:\n"
            "--- KÁNON ---\n"
            f"{canon_content}\n"
            "--- KONEC KÁNONU ---\n\n"
            "Analyzuj tento svět. Hledej nevyřešené otázky, zajímavé vedlejší postavy "
            "bez vlastního příběhu, neprozkoumaná místa, nejasnosti v historii nebo "
            "nevyužité artefakty. Na základě své analýzy navrhni PĚT různých námětů na "
            "další příběh. Každý námět by měl být stručný (2-3 věty) a měl by obsahovat "
            "název, éru a klíčové entity. Odpověz POUZE ve formátu JSON:\n"
            "{\n"
            "  \"ideas\": [\n"
            "    {\"title\": \"Název námětu 1\", \"era\": \"Druhý věk\", \"summary\": \"Stručný popis námětu 1.\"},\n"
            "    {\"title\": \"Název námětu 2\", \"era\": \"Čtvrtý věk\", \"summary\": \"...\"}\n"
            "  ]\n"
            "}"
        )

        try:
            response = self.ai_adapter.prompt(self.generator_model, system_prompt, user_prompt)
        except Exception as exc:  # pragma: no cover - závislé na AI
            self.logger.exception("Volání modelu pro generování námětů selhalo: %s", exc)
            return {}

        try:
            data = json.loads(response.strip())
        except json.JSONDecodeError as exc:
            self.logger.error("Návrhy námětů nejsou platný JSON: %s", exc)
            return {}

        ideas = data.get("ideas") if isinstance(data, dict) else None
        if not isinstance(ideas, list):
            self.logger.error("Odpověď generátoru neobsahuje klíč 'ideas'.")
            return {}

        valid_ideas = [idea for idea in ideas if isinstance(idea, dict)]
        if not valid_ideas:
            self.logger.warning("V JSON odpovědi se nenachází žádné validní náměty.")
            return {}

        selected = random.choice(valid_ideas)
        self.logger.info("Vybrán námět: %s", selected.get("title", "bez názvu"))
        return selected

    def _write_story(self, idea: Dict[str, str], universe_files: Dict[str, str]) -> str:
        canon_content = self._render_files(sorted(universe_files.items()))
        rules_content = self._collect_rules_content(universe_files)

        system_prompt = (
            "Jsi talentovaný vypravěč a spisovatel. Tón a styl tvého psaní je definován "
            "v souborech legend a pokynů tohoto univerza. Tvým úkolem je napsat poutavý "
            "a konzistentní příběh."
        )

        user_prompt = (
            "Zde je kompletní kánon univerza pro zachování kontinuity:\n"
            "--- KÁNON ---\n"
            f"{canon_content}\n"
            "--- KONEC KÁNONU ---\n\n"
            "Zde jsou pravidla pro styl a tón:\n"
            "--- PRAVIDLA ---\n"
            f"{rules_content}\n"
            "--- KONEC PRAVIDEL ---\n\n"
            "Napiš kompletní, ucelený příběh na základě tohoto námětu:\n"
            f"- Název: {idea.get('title', 'Neznámý')}\n"
            f"- Éra: {idea.get('era', 'Neznámá')}\n"
            f"- Shrnutí: {idea.get('summary', 'Bez shrnutí')}\n\n"
            "Tvůj příběh MUSÍ obsahovat správně formátovaná metadata (id, nazev, era, atd.) na "
            "začátku. ID souboru si vymysli na základě názvu."
        )

        response = self.ai_adapter.prompt(self.generator_model, system_prompt, user_prompt)
        return response.strip()

    # ------------------------------------------------------------------
    # Helpers

    def _load_universe_files(self) -> Dict[str, str]:
        file_paths = self._list_branch_files(self.main_branch)
        universe_files: Dict[str, str] = {}
        for path in file_paths:
            universe_files[path] = self.git_adapter.get_file_content(path, self.main_branch)
        return universe_files

    def _list_branch_files(self, branch: str) -> List[str]:
        try:
            result = subprocess.run(
                ["git", "ls-tree", "-r", branch, "--name-only"],
                check=True,
                capture_output=True,
                text=True,
                cwd=self.repo_root,
            )
        except subprocess.CalledProcessError as exc:  # pragma: no cover - závislé na git
            raise RuntimeError(f"git ls-tree selhalo: {exc}") from exc

        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def _render_files(self, files: List[Tuple[str, str]]) -> str:
        rendered_parts = []
        for path, content in files:
            rendered_parts.append(
                f"### START FILE: {path} ###\n{content}\n### END FILE: {path} ###"
            )
        return "\n\n".join(rendered_parts)

    def _collect_rules_content(self, universe_files: Dict[str, str]) -> str:
        if not self.rules_prefix:
            return ""

        rendered: List[Tuple[str, str]] = []
        normalized_prefix = self.rules_prefix + "/" if self.rules_prefix else ""
        for path, content in universe_files.items():
            normalized = path.replace("\\", "/")
            while normalized.startswith("./"):
                normalized = normalized[2:]
            if normalized.startswith(normalized_prefix):
                rendered.append((path, content))

        return self._render_files(sorted(rendered)) if rendered else ""

    def _determine_story_path(self, story_content: str) -> str:
        story_id = self._extract_metadata_value(story_content, "id")
        if story_id:
            slug = self._slugify(story_id)
        else:
            title = self._extract_metadata_value(story_content, "nazev")
            slug = self._slugify(title) if title else ""

        if not slug:
            slug = f"pribeh-{int(time.time())}"

        return f"{self.STORY_DIRECTORY}/{slug}.md"

    def _extract_metadata_value(self, story_content: str, key: str) -> str:
        search_key = key.strip().lower()
        for line in story_content.splitlines():
            if ":" not in line:
                continue
            raw_key, value = line.split(":", 1)
            if raw_key.strip().lower() == search_key:
                return value.strip()
        return ""

    def _build_generated_branch_name(self, story_title: str) -> str:
        slug = self._slugify(story_title)
        timestamp = int(time.time())
        if slug:
            return f"elka-generated/{slug}-{timestamp}"
        return f"elka-generated/pribeh-{timestamp}"

    def _slugify(self, value: str | None) -> str:
        if not value:
            return ""
        normalized = value.lower()
        normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
        return normalized.strip("-")

    def _build_pr_body(
        self,
        idea: Dict[str, str],
        story_path: str,
        archive_updates: Dict[str, str],
    ) -> str:
        summary = idea.get("summary", "")
        era = idea.get("era", "Neuvedeno")
        title = idea.get("title", "Bez názvu")

        updates_list = "".join(
            f"- `{path}`\n" for path in sorted(archive_updates.keys()) if path != story_path
        )
        if updates_list:
            updates_section = (
                "\n## Aktualizované kanonické soubory\n"
                f"{updates_list}"
            )
        else:
            updates_section = ""

        return (
            f"## Autonomně vygenerovaný příběh\n"
            f"- **Název:** {title}\n"
            f"- **Éra:** {era}\n"
            f"- **Soubor:** `{story_path}`\n"
            f"- **Shrnutí námětu:** {summary}\n"
            f"{updates_section}\n"
        )
