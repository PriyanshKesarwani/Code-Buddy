# CodePilot Backend (FastAPI)

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env          # defaults to LLM_PROVIDER=mock (no key needed)
uvicorn app.main:app --reload
```
Swagger UI (share with frontend): http://localhost:8000/docs
Run tests: `pytest`

## Switch to the real model
Edit `.env`:
```
LLM_PROVIDER=google        # Gemma via Google AI Studio key, or "openai" for any OpenAI-compatible server
LLM_API_KEY=your-key
LLM_MODEL=<exact Gemma 4 model id from the docs>
LLM_BASE_URL=              # only for openai provider / custom host
```
All model calls live in `app/llm.py`. If the Gemma 4 API request format differs, that is the only file to change.

## Example calls
```bash
curl localhost:8000/api/v1/health
curl -X POST localhost:8000/api/v1/bugfix -H 'Content-Type: application/json' \
  -d '{"code":"def f(xs):\n  return sum(xs[:-1])","skill_level":"beginner"}'
curl -X POST localhost:8000/api/v1/cli -H 'Content-Type: application/json' \
  -d '{"query":"delete all node_modules folders","os":"linux","shell":"bash"}'
curl -N -X POST localhost:8000/api/v1/chat/stream -H 'Content-Type: application/json' \
  -d '{"message":"explain decorators"}'
```

## Deploy
- **Render / Railway / Heroku**: connect the repo, build `pip install -r requirements.txt`, start command from `Procfile`. Set the env vars from `.env.example` in the dashboard.
- **Docker**: `docker build -t codepilot . && docker run -p 8000:8000 --env-file .env codepilot`

Note: chat sessions are in memory, so they reset on restart. Run a single worker.

## Running code (Run button)
`POST /api/v1/run` with `{"language": "python", "code": "print(1)", "stdin": ""}` executes the code in a temp folder
(10s timeout, 64 KB output cap) and returns `stdout`, `stderr`, `exit_code`, `timed_out`, `duration_ms`.
`GET /api/v1/meta` lists `runnable_languages`, the ones whose runtime is installed on your machine.

| Language | Needs installed |
|---|---|
| python, sql | Python 3 (SQL runs on built-in SQLite) |
| javascript | `node` |
| typescript | `tsx`, `ts-node`, or Node 22.6+ |
| c / cpp | `gcc` / `g++` |
| java | JDK 11+ (`java`) |
| go / rust | `go` / `rustc` |
| bash | `bash` |

**Security:** this runs code on the server. Keep it for local use, or sandbox the container, or set `ENABLE_CODE_EXECUTION=false`.
