# Archivist Engine

ArchivistEngine je partnerem validátoru. Převádí schválený příběh na konkrétní změny v kánonu.

## Přehled

1. **Extrakce entit** – pomocí modelu `archivist` je z příběhu vytažen seznam dotčených entit a událostí.
2. **Generování záznamů** – model `generator` vytváří nové soubory a aktualizuje existující záznamy.
3. **Aktualizace timeline** – nové události se chronologicky vloží do `timeline.txt`.

## Integrace

Orchestrátor po úspěšné validaci zavolá archivátora, sloučí vzniklé změny se souborem příběhu a odešle commit pomocí Git adaptéru. Současně přidá do PR informaci, že je připraven k revizi.

