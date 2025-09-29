# Generator Engine

Autonomní generátor rozšiřuje schopnosti eLKA agenta o tvorbu nových příběhů bez nutnosti zásahu člověka.

## Pracovní postup

1. **Načtení kánonu** – stáhne aktuální stav hlavní větve a připraví vstup pro AI modely.
2. **Analýza mezer** – výkonný `generator` model navrhne pět možných námětů ve formátu JSON. Náhodně je vybrán jeden.
3. **Psaní příběhu** – stejný model vytvoří kompletní příběh včetně metadat, přičemž respektuje legendy a pravidla z adresáře `Pokyny/`.
4. **Validace** – vygenerovaný text projde stávající validační pipeline (formát, kontinuita, tón).
5. **Archivace** – ArchivistEngine připraví aktualizace databází a timeline.
6. **Commit & PR** – Git adaptér vytvoří novou větev `elka-generated/<slug>-<timestamp>`, nahraje změny, a založí Pull Request proti stabilní větvi.

## Spuštění

```bash
python -m elka.main generate --num-stories 3
```

Parametr `--num-stories` lze vynechat – výchozí hodnota je 1.

## Bezpečnostní pojistky

- Každý příběh musí projít validátorem; v případě selhání se cyklus přeskočí.
- Pokud Git adaptér nepodporuje tvorbu větví nebo PR, generátor chybu zaloguje a pokračuje až po nápravě prostředí.

## Využití pro redakci

Vytvořené Pull Requesty obsahují shrnutí námětu, odkaz na soubor s příběhem a seznam aktualizovaných databázových záznamů. Redakce tak může rychle posoudit příspěvek a rozhodnout o jeho začlenění do hlavní continuity.
