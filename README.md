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

Copy the example file and fill in the values:

```sh
cp .env.example .env
```

Open `.env` and fill in at least the **required** section at the top of the file:

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
  password-reset emails. For local development you can point these at any SMTP provider you have test credentials
  for (e.g. Mailtrap, Gmail with an app password), or leave them blank if you don't need email-dependent features
  (signup verification and password reset will not work without them).
- `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` — needed for "Sign in with Google" and Google Calendar. Create these
  in the Google Cloud Console (OAuth 2.0 credentials) if you need this feature; otherwise you can leave them blank
  and skip Google sign-in.

Everything else in `.env.example` (GitHub, Slack, Jira integrations, Anthropic/OpenAI keys, field encryption key) is
optional for just getting the app running — fill those in later if you want to test those specific integrations.
The comments inside `.env.example` explain what each one is for and how to generate it.

The two base-URL settings already have sensible local defaults and don't need to change:

```
BACKEND_BASE_URL=http://localhost:8000
FRONTEND_BASE_URL=http://localhost:5173
```

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
