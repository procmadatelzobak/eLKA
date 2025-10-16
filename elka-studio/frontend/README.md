# eLKA Studio – Frontend

Tato část repozitáře obsahuje Single Page Application (SPA) postavenou na Reactu a Vite. UI komunikuje s FastAPI backendem běžícím na `http://localhost:8000/api`.

## Požadavky

- Node.js 20+
- npm 10+

## Lokální vývoj

```bash
npm install
npm run dev
```

Aplikace se spustí na adrese [http://localhost:5173](http://localhost:5173). Backendová adresa je konfigurovatelná proměnnou prostředí `VITE_API_BASE_URL`.

## Struktura

```
src/
├── components/        # Sdílené UI komponenty (modaly, formuláře, ...)
├── layouts/           # Základní rozložení stránky (sidebar + obsah)
├── pages/             # Stránky routované pomocí React Routeru
├── services/          # Klient pro komunikaci s API (Axios)
└── main.jsx           # Vstupní bod aplikace
```

## Dostupné skripty

- `npm run dev` – spuštění vývojového serveru s HMR
- `npm run build` – produkční build
- `npm run preview` – náhled výsledného buildu
- `npm run lint` – statická analýza pomocí ESLintu

## API klient

Soubor `src/services/api.js` definuje instanci Axiosu s výchozí adresou `http://localhost:8000/api`. Pro změnu použijte `.env` soubor s proměnnou `VITE_API_BASE_URL`.
