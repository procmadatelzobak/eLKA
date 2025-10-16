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

> 💡 **Tip:** V kořenovém adresáři projektu lze použít `make run-dev`, který kromě backendu automaticky spustí i tento Vite server (s parametrem `--host 0.0.0.0`). Pokud potřebujete jen API, použijte `make run-backend`.

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

## Projektový dashboard

Stránka `ProjectDashboardPage` slouží jako hlavní pracovní prostředí pro konkrétní projekt. Umožňuje odesílat nové úlohy agentovi eLKA (zpracování příběhu, generování z seed hodnoty nebo vytvoření ságy) a v reálném čase sledovat jejich stav prostřednictvím WebSocketu.

- Ovládací panel se stará o validaci a odeslání požadavků pomocí funkce `createTask` z modulu `src/services/api.js`.
- Fronta úloh využívá službu `TaskSocket` (`src/services/websocket.js`) pro připojení na endpoint `/ws/tasks/{projectId}` a zobrazuje průběh včetně logů.
- Akce pozastavení a opětovného spuštění úlohy lze volat funkcemi `pauseTask` a `resumeTask`.

### Konfigurace WebSocketu

Výchozí adresa pro WebSocket se odvozuje od `VITE_API_BASE_URL`. Pokud backend běží na jiné adrese nebo portu, je možné jej přepsat proměnnou prostředí `VITE_WS_BASE_URL` (např. `ws://localhost:8000`).
