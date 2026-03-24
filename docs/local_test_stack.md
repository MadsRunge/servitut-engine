# Local test stack

Brug denne rækkefølge når du vil teste OCR, extraction og frontend lokalt.

## 1. Start backend-basics

```bash
cd /Users/madsrunge/Developer/servitut/servitut-engine
source .venv/bin/activate
docker compose up -d postgres
alembic upgrade head
```

## 2. Start Redis

Hvis du bruger Homebrew:

```bash
brew services start redis
redis-cli ping
```

Du skal få:

```bash
PONG
```

Hvis du kører Redis manuelt:

```bash
redis-server
```

## 3. Start backend API

```bash
cd /Users/madsrunge/Developer/servitut/servitut-engine
source .venv/bin/activate
uvicorn app.api.main:app --reload
```

## 4. Start Celery worker

I en ny terminal:

```bash
cd /Users/madsrunge/Developer/servitut/servitut-engine
source .venv/bin/activate
./scripts/run_worker.sh
```

## 5. Start frontend

I en ny terminal:

```bash
cd /Users/madsrunge/Developer/servitut/servitut-frontend
pnpm dev
```

## Minimum der skal køre

For at UI'et faktisk kan teste OCR/extraction-flowet skal disse være oppe:

- PostgreSQL
- Redis
- FastAPI backend
- Celery worker
- Next frontend

Hvis Redis eller worker mangler, vil frontend bare polle jobstatus uden at OCR/extraction bliver behandlet.

## Hurtig sanity check

- Backend health: `http://127.0.0.1:8000/health`
- Frontend: `http://localhost:3000`
- Redis: `redis-cli ping`

## Når du tester Aalborg igen

Hvis du vil teste extraction fra en ren state i UI'et:

- brug knappen `Genkør extraction fra bunden`
- den rydder eksisterende servitutter, redegørelser, erklæringer og attest-cache før nyt extraction-job starter
