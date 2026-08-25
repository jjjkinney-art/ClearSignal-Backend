# AI Analyst Backend

FastAPI + multi-agent investment intelligence backend.

## Deployment

### Render

The `Procfile` configures the start command:

```
web: alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

**Important:** The start command must use `$PORT` (Render's injected environment variable).
Do **not** hardcode a port number — Render will report "No open ports detected" and the deploy will fail.
The Alembic upgrade runs before the web process starts so an existing database
receives reviewed additive schema changes before current ORM models query it.

Set the following environment variables in the Render service dashboard:
- `OPENAI_API_KEY` — your OpenAI key
- Any other keys listed in `.env.example`

## Local Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add your OPENAI_API_KEY
uvicorn app.main:app --reload --port 8000
```

## Tests

```bash
pytest -q
```
