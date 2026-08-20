# Logline

Logline is an agentic work-log and standup assistant. It pulls signal from tools you already use (GitHub, Slack,
Jira, Google Calendar, and your own computer activity) and helps you reconstruct what you did during the day —
showing an honest sense of how much to trust each piece of information (proven, estimated, or a gap it asks you
about).

The project has three parts, in separate folders:

- **`backend/`** — a Python (FastAPI) API server. Handles auth, talks to Postgres, fetches data from GitHub/Slack/
  Jira/Calendar, and uses an LLM to help write draft entries.
- **`frontend/`** — a React + TypeScript web app (built with Vite) that you use in the browser.
- **`tracker/`** — an optional macOS-only background app that records what you're working on locally (active app,
  window title) and syncs that activity to the backend. Not required to use Logline — see `tracker/README.md` for
  its own setup steps.

This README covers the backend and frontend, which is what most people need to get a working local copy of the app.

## 1. What you need installed first

- **Python 3.11 or newer** (the project is developed on 3.14, older 3.11+ versions should also work)
- **Node.js 18 or newer** and **npm**
- **Docker** (used to run the Postgres database — you don't need Postgres installed separately)
- **git**

Check what you have:

```sh
python3 --version
node --version
npm --version
docker --version
```

## 2. Get the code

```sh
git clone <this-repo-url>
cd logline
```

## 3. Set up the database (Postgres via Docker)

The backend expects a Postgres database running in Docker — do not install Postgres directly on your machine.

```sh
cd backend
docker-compose up -d
```

This starts a Postgres 16 container named `logline_postgres` with:

- user: `logline`
- password: `logline`
- database: `logline`
- port: `5432` (the standard Postgres port on your machine)

Leave this running in the background. You can check it's up with `docker ps`.

## 4. Set up the backend

All commands below assume you're inside the `backend/` folder.

### 4.1 Create a virtual environment and install dependencies

```sh
python3 -m venv .venv
source .venv/bin/activate        # on Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt   # only needed if you plan to run tests/lint
```

### 4.2 Create your `.env` file

Copy the example file:

```sh
cp .env.example .env
```

`.env` is your personal, private config file — it's already in `.gitignore`, so it will never be committed. Never
put real secrets into `.env.example`, only into `.env`.

The list below reflects what the code actually reads (`app/config.py`), which is the source of truth if it ever
disagrees with the comments in `.env.example`.

#### Required — the app refuses to start without these

- `DATABASE_URL` — connection string for the Postgres container you started in step 3. For the default Docker
  Compose settings above, use:
  ```
  DATABASE_URL=postgresql://logline:logline@localhost:5432/logline
  ```
- `JWT_SECRET_KEY` and `ITSDANGEROUS_SECRET_KEY` — random secrets used to sign login tokens and email links. Generate
  each one with:
  ```sh
  python -c "import secrets; print(secrets.token_hex(32))"
  ```
  Run it twice — these two must be **different** values from each other.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_ADDRESS` — used to send verification and
  password-reset emails. These are required even for local dev (the server raises an error on startup if any are
  missing) — point them at any SMTP provider you have test credentials for, e.g. a Gmail account with an
  [app password](https://myaccount.google.com/apppasswords), or a test inbox like Mailtrap.
- `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` — also required at startup, even if you don't plan to use Google
  sign-in yet. Create an OAuth 2.0 client in the [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
  (type "Web application") to get these.

#### Effectively required — the app starts, but these specific features break without them

- `GOOGLE_OAUTH_CREDENTIALS` — set to `gcp-oauth.keys.json` (a client-secret file you download from the same Google
  Cloud Console credential, kept at `backend/gcp-oauth.keys.json`, already git-ignored). Only used by the standalone
  Google Calendar MCP connectivity script (`scripts/manual_test_calendar_mcp.py`), not by the main app.
- `ANTHROPIC_API_KEY` and/or `OPENAI_API_KEY` — needed for the AI features (draft write-ups, reconciliation). Which
  one is actually required depends on `LLM_PROVIDER` below.
- `ENCRYPTION_KEY` — encrypts stored OAuth tokens at rest (field-level encryption). Generate with:
  ```sh
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```
  Any integration connect flow (GitHub/Slack/Jira/Calendar) will fail without this set.

#### Choose your LLM provider

- `LLM_PROVIDER` — `openai` (default) or `gemini`.
- `LLM_MODEL` — the model name for whichever provider you picked (e.g. `gpt-5-mini` for OpenAI, `gemini-2.5-flash`
  for Gemini).
- Set the matching key: `OPENAI_API_KEY` for `openai`, `GEMINI_API_KEY` (and optionally `GEMINI_MODEL`) for
  `gemini`. Any other value for `LLM_PROVIDER` fails at startup.

#### Optional — per-integration OAuth (only needed to test that specific integration)

- GitHub: `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` (from a [GitHub OAuth App](https://github.com/settings/developers)),
  `GITHUB_TEST_PAT` (a personal access token, only used by the manual GitHub MCP test script).
- Slack: `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET`, `SLACK_SIGNING_SECRET`, `SLACK_BOT_TOKEN` (from a Slack app you
  create). `SLACK_TEAM_ID` is only used by the standalone Slack MCP test script, not the main app.
- Jira: `JIRA_CLIENT_ID`, `JIRA_CLIENT_SECRET` (from an Atlassian OAuth 2.0 app).

Each provider's OAuth callback URL defaults to `<BACKEND_BASE_URL>/integrations/<source>/callback` automatically —
you only need to set `GITHUB_REDIRECT_URI`, `SLACK_REDIRECT_URI`, `JIRA_REDIRECT_URI`, `GOOGLE_REDIRECT_URI` (Google
sign-in), or `CALENDAR_REDIRECT_URI` (Google Calendar connect — note the name, **not** `GOOGLE_CALENDAR_REDIRECT_URI`)
if you need to override that default. `CALENDAR_REDIRECT_URI` and `GOOGLE_REDIRECT_URI` must be different URLs from
each other — the app checks this at startup because both flows share the same Google OAuth client.

#### Other settings

- `BACKEND_BASE_URL` / `FRONTEND_BASE_URL` — already default to `http://localhost:8000` / `http://localhost:5173`,
  which is correct for local dev; no need to set them yourself unless you're running on different ports.
- `CORS_ORIGINS` — comma-separated list of frontend origins allowed to call the API. The example file's default
  (`http://localhost:5173,http://127.0.0.1:5173`) is correct for local dev.
- `JWT_EXPIRE_MINUTES` — how long a login session lasts, in minutes. Defaults to `1440` (24 hours) if unset.

A few variable names show up in some `.env` files from older setups but are no longer read by any code —
`JWT_ALGORITHM` (the algorithm is fixed to `HS256` in code) and `SMTP_FROM_NAME`. Setting them is harmless but does
nothing; you can leave them out.

### 4.3 Run the database migrations

This creates all the tables the app needs, using Alembic:

```sh
alembic upgrade head
```

If this ever fails with an error about multiple "heads", run `alembic heads` to see the conflicting migrations and
`alembic merge` them — see `backend/CLAUDE.md` for more detail on this.

### 4.4 Start the backend server

```sh
uvicorn app.main:app --reload --port 8000
```

The API is now running at `http://localhost:8000`. FastAPI's interactive docs are available at
`http://localhost:8000/docs`.

## 5. Set up the frontend

Open a new terminal tab/window for this — leave the backend running in the other one.

```sh
cd frontend
npm install
```

The frontend doesn't need any environment variables for local development (it talks to the backend at
`http://localhost:8000` by default).

Start the dev server:

```sh
npm run dev
```

The app is now running at `http://localhost:5173`. Open that in your browser.

## 6. Everyday commands

From the `backend/` folder (with the virtual environment activated):

| Command | What it does |
| --- | --- |
| `uvicorn app.main:app --reload --port 8000` | Run the API server, restarts automatically on code changes |
| `pytest -q` | Run backend tests |
| `alembic upgrade head` | Apply any new database migrations |
| `alembic revision -m "description"` | Create a new migration file |

From the `frontend/` folder:

| Command | What it does |
| --- | --- |
| `npm run dev` | Run the web app in development mode |
| `npm run build` | Type-check and build for production |
| `npm test` | Run frontend tests |
| `npm run lint` | Check code style |

From the repo root, `make check` runs the full set of static checks (import order, lint, type-checking, and
security scanning) across both backend and frontend in one go — see the `Makefile` for details on each step.

## 7. Stopping everything

- Stop the backend/frontend dev servers with `Ctrl+C` in their terminals.
- Stop the database container with:
  ```sh
  cd backend
  docker-compose down
  ```
  Your database data is kept in a Docker volume, so it will still be there next time you run `docker-compose up -d`.

## 8. Troubleshooting

- **Backend won't start / complains about missing env vars** — double check every value under the "Required" section
  of `backend/.env` is filled in.
- **Backend can't connect to the database** — make sure `docker-compose up -d` is running (`docker ps` should show
  `logline_postgres`), and that `DATABASE_URL` in `.env` matches the credentials in `backend/docker-compose.yml`.
- **`alembic upgrade head` fails with a "multiple heads" error** — run `alembic heads` to see the conflicting
  migrations, then resolve with `alembic merge`.
- **Frontend shows network/CORS errors** — make sure the backend is running on port 8000 and that `CORS_ORIGINS` in
  `backend/.env` includes `http://localhost:5173`.

## Learn more

- `backend/CLAUDE.md` — backend architecture, data model, and design decisions in depth.
- `tracker/README.md` — setup for the optional local activity tracker.
- `CLAUDE.md` (this folder) — git branch/commit conventions used on this project.
