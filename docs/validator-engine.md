# Validator Engine

Tento dokument shrnuje, jak eLKA ověřuje nové příběhy před přijetím do kánonu.

## Přehled

ValidatorEngine je odpovědný za spuštění tří navazujících kontrol nad novým příběhem:

1. **Formát** – metadata příběhu jsou porovnána s pravidly uloženými v adresáři `Pokyny/`.
2. **Kontinuita** – příběh je porovnán s kompletním kánonem načteným z hlavní větve (`master`).
3. **Tón** – text je posouzen proti stylovým a tematickým zásadám univerza.

Každá kontrola využívá stejné AI rozhraní nakonfigurované jako `validator` model v konfiguraci.

## Průběh zpracování PR

Orchestrátor zajistí, že Pull Request obsahuje právě jeden nový soubor s příběhem, načte jeho obsah a připraví kontext kánonu.
Pokud některý krok selže, přidá se komentář přímo do PR s detailními chybami.

## Rozšíření

- Název hlavní větve lze přenastavit pomocí `core.main_branch` v souboru `config.yml`.
- Strukturu pravidel lze upravit v adresáři definovaném klíčem `core.rules_path`.
