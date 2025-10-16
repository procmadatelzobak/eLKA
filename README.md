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

Dokumentaci prosím udržujte aktuální i při dalších změnách.
