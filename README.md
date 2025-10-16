# eLKA Studio

eLKA Studio je webová aplikace pro lokální správu a procedurální generování lore pro fiktivní univerza. Tento repozitář nyní obsahuje počáteční strukturu projektu včetně backendu postaveného na FastAPI, šablon pro nové světy a skriptů pro snadnou instalaci.

## Struktura projektu

```
elka-studio/
├── backend/
│   └── app/
│       ├── api/
│       ├── core/
│       ├── db/
│       ├── models/
│       ├── services/
│       ├── templates/
│       └── main.py
├── frontend/
├── scripts/
└── requirements.txt
```

Podrobné informace k jednotlivým částem naleznete v komentářích zdrojových souborů. Backend je připraven pro spuštění pomocí `uvicorn` a při startu automaticky vytvoří databázové tabulky.

## Rychlý start

1. `cd elka-studio`
2. `make setup`
3. `make run-backend`

API poběží na adrese `http://127.0.0.1:8000`.

Pro plnohodnotný vývoj (včetně background úloh a websocketů) je nově
k dispozici příkaz `make run-dev`, který spustí FastAPI, worker Celery a
Redis (pokud je k dispozici Docker). Skript `scripts/run-dev.sh` se postará
o nastavení proměnné `PYTHONPATH` i o přehledné ukončení všech procesů.

Dokumentaci prosím udržujte aktuální i při dalších změnách.

## Git správa projektů

Backend nyní při vytváření projektu automaticky klonuje vzdálený Git repozitář
do lokální složky (výchozí cesta je `~/.elka/projects`, lze změnit proměnnou
`ELKA_PROJECTS_DIR`). Pokud je repozitář prázdný, inicializuje se základní
struktura „universe_scaffold“ a první commit se odešle zpět na vzdálený
repozitář.

Citlivé údaje, jako jsou přístupové tokeny ke Git službám, jsou ukládány pouze
šifrovaně. Před spuštěním backendu nastavte proměnnou prostředí `SECRET_KEY`
(např. v souboru `.env`). Pro synchronizaci již vytvořeného projektu použijte
endpoint `POST /projects/{project_id}/sync`.

## Background úlohy a real-time aktualizace

Do projektu byla integrována kombinace Celery + Redis pro spouštění
dlouhotrvajících úloh na pozadí. Stav úloh je ukládán v databázi a
publikován přes WebSocket endpoint `/ws/tasks/{project_id}`, takže
frontend může reagovat na změny v reálném čase. Konfiguraci připojení k
Redis brokeru lze upravit proměnnou prostředí `CELERY_BROKER_URL`
(viz `.env.example`).

### Generační a zpracovatelský pipeline pro příběhy

Celery worker nyní obsahuje kompletní dvojici úloh pro kreativní tvorbu
i následné zpracování. Úloha `generate_story` vezme zadané "seed"
a pomocí generátoru připraví plně strukturovaný příběh včetně
metadata bloku. Jakmile je text hotový, vytvoří navazující úlohu
`process_story`, která propojuje validátor a archivátora jádra eLKA.

Endpoint `POST /tasks/` přijímá typy `generate_story` (parametr
`seed`), `generate_saga` (parametry `theme` a `chapters`) a stále také
`process_story` (parametr `story_content`). První dva typy generují
nový obsah a automaticky zakládají navazující zpracovatelské úlohy,
takže není nutné volat validaci/archivaci ručně.

Po dohotovení jednotlivých kapitol nebo celých ság je výstup uložen do
projektu v adresáři `lore/stories/`, následně commitnut a odeslán na
odpovídající PR větev. Stav každé fáze je průběžně zapisován do logu
úlohy, takže frontend i websocket klienti mají okamžitý přehled o
postupu.

#### Řízení dlouhých generačních úloh

Pro dlouho běžící úlohy (např. generování ságy) jsou k dispozici nové
endpointy `POST /tasks/{task_id}/pause` a `POST /tasks/{task_id}/resume`.
Pauza nastaví stav úlohy na `PAUSED` a orchestrátor ságy před
spuštěním každé kapitoly kontroluje, zda není pozastaven. Pokud ano,
pravidelně čeká (30 s) a vyčkává na opětovné spuštění. Díky tomu lze
dlouhé generování bezpečně pozastavit a opět rozběhnout bez zásahu do
již rozpracovaných dat.
