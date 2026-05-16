# billing

FastAPI backend boilerplate with Supabase integration.

## Stack

- **Framework**: FastAPI
- **Auth / DB**: Supabase
- **Runtime**: Python 3.12

## Structure

```
app/
├── main.py           # App entrypoint, lifespan, middleware
├── core/             # Config, security, dependencies
├── api/              # Top-level router aggregation
├── modules/          # Feature modules (routes, schemas, service, repository)
├── clients/          # External service clients (Supabase, etc.)
├── contracts/        # Shared request/response models
├── workers/          # Background tasks
└── tests/            # Test suite
```

## Running locally

```bash
cp .env.example .env
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Conventions

- Each module under `modules/` is self-contained: routes → service → repository.
- Shared response envelopes live in `contracts/responses/`.
- External clients are instantiated once in `clients/` and injected via FastAPI dependencies.
