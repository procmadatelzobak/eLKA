# eLKA – electronic Lore Keeping Agent

eLKA je modulární agent navržený pro správu komunitního kánonu a automatickou validaci příběhů v rámci pull requestů. Spojuje sílu jazykových modelů, kontrolních pravidel a archivace, aby udržoval lore konzistentní napříč univerzem.

## Instalace
```bash
git clone <URL_REPOZITARE>
cd eLKA
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

## Konfigurace
1. Upravte `config.yml` v kořenovém adresáři projektu tak, aby odpovídal vašemu prostředí.
2. Zkopírujte `.env.example` jako `.env` a doplňte potřebné API klíče a tokeny (například `GITHUB_API_TOKEN`, `GEMINI_API_KEY`).

## Použití
### Asistovaný režim (zpracování PR)
Tento režim je vhodný pro CI/CD pipeline, například GitHub Actions.
```bash
elka process --pr-id <ID_PULL_REQUESTU>
```

### Autonomní režim (generování příběhů)
```bash
elka generate --num-stories <POCET_PRIBEHU>
```

## Architektura
Projekt je rozdělen do dvou hlavních vrstev:
- **Jádro** (`elka/core`) obsahuje orchestrátor, validátor, archivář a generátor, které dohromady řídí tok dat a rozhodování agenta.
- **Adaptéry** (`elka/adapters`) propojují jádro s externími službami, jako jsou Git platformy nebo poskytovatelé AI. Adaptéry jsou implementovány pomocí továrních funkcí v `main.py`, takže je snadné přidat další poskytovatele.

Strategie větvení projektu vychází z toku `Server`/`Client` → `Dev` → `Master`, přičemž `Master` reprezentuje stabilní produkční větev.
