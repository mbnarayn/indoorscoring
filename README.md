# Indoor Cricket Scorer

A mobile-first, offline-capable Progressive Web App for live ball-by-ball indoor cricket scoring.
It's built with FastAPI on Python 3.14 and stores matches as JSON, either in local files or in Azure Blob Storage.

## Features

- **Fast scoring.** Most deliveries take one tap. Large run buttons (0–6), additional runs (+1…+6, which can be stacked), wides, no balls, byes and leg byes.
- **Dismissals.** Bowled, caught, run out (striker or non-striker), hit wicket, other and retired. After a dismissal the app asks for the incoming batsman.
- **Retirements.** A retired batsman is not out, is tracked separately and shown as retired on the scorecard. They can come back in later.
- **Live dashboard.** Shows score, wickets, overs and run rate, plus both batsmen (R, B, SR), the current bowler (O-R-W, economy), the partnership and the current over. In the final innings it also shows target, runs required, balls remaining and required run rate.
- **Undo last ball.** Restores every statistic exactly (see *Architecture*).
- **Match management.** Create, resume, list completed, delete, export JSON and import JSON.
- **Match details.** Edit the match name, date and venue, rename teams, and add, rename or remove players at any point. Players who have already batted or bowled can't be removed. You can also change the number of overs mid-match; the change applies from that point on, including the current innings, and isn't reversed by undo.
- **Scorecards.** Batting and bowling cards, extras breakdown, fall of wickets, did-not-bat list, and a match summary with winner, margin, top batsman and top bowler.
- **Auto save.** Every action is saved before the response is returned.
- **PWA.** Installable on Android and iOS, with a service worker, app-shell caching and offline scoring through an on-device outbox.
- **Display options.** Dark, light and high-contrast themes, laid out for one-handed use in portrait.

## Project structure

```
app/
  main.py                 FastAPI app factory, static/PWA routes, security headers
  config.py               Environment-driven settings
  api/
    routes.py             REST endpoints (API layer)
    schemas.py            Pydantic request / document validation
  services/               Service layer (no I/O)
    engine.py             Match engine: cricket rules, event replay
    stats.py              Statistics engine: scorecards, summary, live state
    undo.py               Undo engine
    match_service.py      Orchestrates engine + storage, auto-save, idempotency
  storage/                Storage layer
    base.py               StorageProvider abstraction
    local.py              LocalJsonStorageProvider  (data/matches/<id>.json)
    azure_blob.py         AzureBlobStorageProvider  (<container>/<id>.json)
    factory.py            Selects provider from STORAGE_PROVIDER
  static/                 UI layer (HTML/CSS/JS, manifest, service worker, icons)
.github/workflows/        CI/CD: test, then deploy to App Service
scripts/generate_icons.py Regenerates PWA icons / splash (no dependencies)
tests/                    Unit tests (engine, undo, stats) and API tests
```

## Architecture

- **Event sourcing.** A match document holds its setup plus an ordered list of events: `innings_start`, `bowler`, `ball`, `new_batsman`, `retire` and `end_innings`. The engine rebuilds the full state by replaying those events. This means:
  - **Auto-save** only has to append an event and persist the document. The new list is replayed and validated before it's saved, so an invalid event is never stored.
  - **Undo** removes the last `ball` event and any selections made after it, then replays. Score, wickets, overs, batting and bowling figures, partnerships, retirements and dismissals all come back exactly as they were.
  - **Import** replays the imported events, so a tampered or inconsistent file is rejected.
- **Business rules live only in the Python service layer.** The frontend just sends user intents and renders the state the server returns.
- **Offline.** The service worker caches the app shell and the last API responses. Actions taken while offline go into an on-device outbox in `localStorage`. Each action has a unique `op_id`, and the outbox replays in order when the connection returns. The server ignores duplicate `op_id`s, so retries are safe. While offline, the screen shows the last synced statistics plus the pending deliveries. Because no cricket rules run in the browser, you pick the next bowler or incoming batsman offline with the **Bowler** and **Batsman in** buttons.

### Scoring rules implemented

| Delivery | Team runs | Batsman | Bowler | Counts as a ball |
|---|---|---|---|---|
| Runs (+ additional) | runs + additional | runs + additional, ball faced | charged | yes |
| Wide | penalty + runs | ball faced (except last over) | charged | yes, **re-bowled in the last over** |
| No ball | penalty + runs | runs, ball faced | charged | yes, **re-bowled in the last over** |
| Bye / Leg bye | runs | ball faced | not charged | yes |

- Wide / no-ball penalty is 2 runs, or 1 run in the last over of the innings (all configurable per match).
- The scorer is prompted to pick the striking batsman before every ball.
- **Pairing overs** (optional, set in New Match or Match Setup): during the first N overs of each innings a dismissed batsman stays in. The wicket still counts for the team and the bowler, and every dismissal is listed against the batsman.
- Bowled, caught and hit wicket are credited to the bowler. Run out and other are not. Retired isn't a wicket.
- Strike changes on an odd number of completed runs and at the end of each over. The scorer can still tap either batsman to set who faces the next ball.
- An innings ends when the overs are complete, the side is all out (no batsman left to come in), the target is reached, or the scorer taps **End innings**.

## Local development

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
python -m uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000. API docs are at http://localhost:8000/docs.

To test on a phone on the same Wi-Fi, run with `--host 0.0.0.0`. Service workers and installation need HTTPS, except on `localhost`, so use the Azure deployment or a tunnel to test the PWA on a phone.

Run the tests:

```powershell
python -m pytest -q
```

### Configuration (environment variables)

| Variable | Default | Description |
|---|---|---|
| `STORAGE_PROVIDER` | `local` | `local` or `azure_blob` |
| `DATA_DIR` | `data` | Root folder for local JSON (`<DATA_DIR>/matches/*.json`) |
| `AZURE_STORAGE_ACCOUNT_URL` | – | e.g. `https://myacct.blob.core.windows.net`, authenticated with Managed Identity / `DefaultAzureCredential` (recommended) |
| `AZURE_STORAGE_CONNECTION_STRING` | – | Alternative to the account URL. Store it as an App Service setting or in Key Vault, never in source control. |
| `AZURE_STORAGE_CONTAINER` | `matches` | Blob container (created if missing) |
| `MAX_IMPORT_BYTES` | `2097152` | Maximum size of an imported match file |
| `DELETE_PASSWORD` | `miltonkeynes600028` | Password the app asks for before deleting a match. Set your own value in production. |

You switch storage providers through these variables alone. Both providers store the same JSON document.

To try Blob Storage locally, sign in with `az login`, give your account the **Storage Blob Data Contributor** role on the storage account, and then run:

```powershell
$env:STORAGE_PROVIDER="azure_blob"; $env:AZURE_STORAGE_ACCOUNT_URL="https://<account>.blob.core.windows.net"
python -m uvicorn app.main:app --port 8000
```

## Deploy to Azure App Service (Linux)

Create the Azure resources yourself, then deploy the code with one of the options below.

### Required App Service configuration

- **Web app:** Linux, runtime `PYTHON|3.14`, B1 or higher (Always On), HTTPS only.
- **Startup command:** `bash startup.sh` ([startup.sh](startup.sh) installs `requirements.txt` into `/home/site/deps` if the platform build didn't, then starts uvicorn on `0.0.0.0:8000`)
- **Health check path:** `/api/health`
- **App settings:**
  - `SCM_DO_BUILD_DURING_DEPLOYMENT=true` (Oryx installs `requirements.txt`)
  - `STORAGE_PROVIDER=local` with `DATA_DIR=/home/data` (persists across restarts), or `STORAGE_PROVIDER=azure_blob` with `AZURE_STORAGE_ACCOUNT_URL` and `AZURE_STORAGE_CONTAINER`
  - `DELETE_PASSWORD` set to your own value
- **For `azure_blob`:** enable the web app's system-assigned managed identity and give it the **Storage Blob Data Contributor** role on the storage account.

### Option A – Zip deploy with Azure CLI

```powershell
Compress-Archive -Path app, requirements.txt, pyproject.toml, startup.sh -DestinationPath app.zip -Force
az webapp deploy -g <resource-group> -n <app-name> --src-path app.zip --type zip
```

### Option B – Quick deploy with `az webapp up`

```powershell
az webapp up --runtime "PYTHON:3.14" --sku B1 -n <unique-app-name> -g rg-indoorscore
az webapp config set -g rg-indoorscore -n <unique-app-name> --startup-file "bash startup.sh"
az webapp config appsettings set -g rg-indoorscore -n <unique-app-name> --settings STORAGE_PROVIDER=local DATA_DIR=/home/data
```

### Option C – GitHub Actions

[.github/workflows/azure-webapp.yml](.github/workflows/azure-webapp.yml) runs the tests and then deploys on every push to `main`. It uses OpenID Connect, so no publish profile is needed. Before it can run:

1. Create an Entra app registration or user-assigned identity with a federated credential for this repository. Give it the **Website Contributor** role on the web app.
2. Add the repository secrets `AZURE_CLIENT_ID`, `AZURE_TENANT_ID` and `AZURE_SUBSCRIPTION_ID`, and the repository variable `AZURE_WEBAPP_NAME`.

### Scaling note

Writes are serialised inside a single process, so run **one instance with one worker**. That's plenty for live scoring. If you scale out, use `azure_blob` and keep each match scored from a single device.

## API summary

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Health probe |
| GET | `/api/matches?status=in_progress\|completed` | List matches |
| POST | `/api/matches` | Create match (setup) |
| GET | `/api/matches/{id}` | Match + live state |
| DELETE | `/api/matches/{id}` | Delete match |
| POST | `/api/matches/{id}/events` | Record an event `{ "op_id": "...", "event": {...} }` |
| POST | `/api/matches/{id}/undo` | Undo last ball |
| GET | `/api/matches/{id}/scorecard` | Innings scorecards + match summary |
| GET | `/api/matches/{id}/export` | Download match JSON |
| POST | `/api/matches/import` | Import match JSON |

Example ball event, a 2 with 1 additional run (3 runs in total):

```json
{ "op_id": "c0ffee", "event": { "type": "ball", "runs": 2, "additional": [1] } }
```

## Security notes

- **No authentication.** The MVP has none, as specified. Put it behind App Service Authentication (Easy Auth) or restrict access if it's exposed publicly.
- **Input validation.** All input is validated with Pydantic. Match ids are restricted to `[A-Za-z0-9_-]`, which prevents path traversal.
- **Response headers.** A strict Content-Security-Policy is applied (no inline scripts), plus `nosniff`, `no-referrer` and `frame-ancestors 'none'`.
- **Safe rendering.** User-supplied names are HTML-escaped before they're rendered.
