# Arquitetura

## Visão geral (alvo M1)

```
┌─────────────────────┐     HTTPS/JSON      ┌──────────────────────────┐
│   Frontend (Vite)   │ ──────────────────▶ │   FastAPI (backend/)      │
│   React 19 + RR7    │ ◀────────────────── │   /api/auth, /api/reports │
└─────────────────────┘                     │   /api/whatsapp           │
        │  WS (qr status)                   └────────────┬─────────────┘
        │                                                │ httpx
        ▼                                                ▼
┌─────────────────────┐    REST + WS local    ┌──────────────────────────┐
│  WhatsApp Sidecar   │ ◀──────────────────── │  WhatsApp Sidecar         │
│  (Node + Baileys)   │  /session/:id/qr      │  efêmero por sessão       │
│  porta 3001         │  /session/:id/extract │                           │
└─────────────────────┘                       └──────────────────────────┘
        │
        ▼ websocket Baileys
   WhatsApp Web

┌─────────────────────────────────────────────────────────────┐
│                       Supabase                              │
│   Auth   │   medzee_users_profile   │   medzee_reports      │
│          │   medzee_whatsapp_sessions                       │
└─────────────────────────────────────────────────────────────┘
                              ▲
                              │  REST (anon + service_role)
                              │
                       FastAPI ↑

┌────────────────┐
│  LLM provider  │ ◀── FastAPI (httpx) — prompt + mensagens normalizadas
│  (Anthropic)   │
└────────────────┘
```

## Fluxo principal — geração do relatório

1. **`/spy` carrega.** Frontend chama `POST /api/whatsapp/sessions` → backend pede sidecar uma nova sessão → recebe `{ sessionId, qr }` → repassa para o frontend.
2. **Frontend exibe QR + abre WS** com `/api/whatsapp/sessions/:id/events` (proxy do WS do sidecar). Recebe eventos `qr-updated`, `connected`, `extracting`, `extracted`, `failed`.
3. **Usuário lê o QR.** Sidecar emite `connected`; o frontend navega para `GeneratingScreen`.
4. **Sidecar extrai mensagens** dos últimos 30 dias e devolve `extracted` (`{ messageCount, conversations: [...] }`). Backend guarda o payload em memória (cache TTL curto) associado ao `sessionId` — **nunca grava conteúdo em disco**.
5. **Frontend mostra `LeadFormScreen`** → ao submeter, `POST /api/auth/signup` com `{ ...form, whatsappSessionId }`. Backend:
   - Cria usuário no Supabase Auth (`sign_up`).
   - Insere `medzee_users_profile`.
   - Liga `medzee_whatsapp_sessions.user_id` ao usuário.
   - Dispara processamento LLM em background (`workers/`) — o front recebe `{ session, reportJobId }`.
6. **Frontend faz login** com a session retornada (`supabase.auth.setSession`) e poll/WS `GET /api/reports/:id/status` até `ready`.
7. **`ReportScreen` busca `GET /api/reports/:id`** (autenticado) e renderiza com os componentes existentes em `components/report/*`.

## Modelo de dados (Supabase)

```sql
-- medzee_users_profile
id              uuid pk references auth.users(id) on delete cascade
name            text not null
email           text not null
phone           text not null
ticket_medio    numeric
clinic_segment  text         -- inferido (saúde, odonto, outro)
created_at      timestamptz default now()

-- medzee_whatsapp_sessions
id              uuid pk default gen_random_uuid()
user_id         uuid references auth.users(id) on delete cascade  -- null antes do signup
sidecar_session text not null      -- id da sessão Baileys (opaco)
status          text not null      -- pending | connected | extracted | consumed | failed
message_count   int
extracted_at    timestamptz
created_at      timestamptz default now()

-- medzee_reports
id              uuid pk default gen_random_uuid()
user_id         uuid not null references auth.users(id) on delete cascade
session_id      uuid references medzee_whatsapp_sessions(id) on delete set null
status          text not null      -- pending | processing | ready | failed
payload         jsonb              -- estrutura igual ao reportData.js, populada pelo LLM
prompt_version  text
model           text
created_at      timestamptz default now()
ready_at        timestamptz

-- RLS: cada user vê só os próprios reports/profile/sessions
```

## Padrões a seguir nos módulos (a criar)

Cada módulo em `app/modules/<feature>/` segue:

```
routes.py      # APIRouter + endpoints, usa SuccessResponse
service.py     # regra de negócio, orquestra repository + clients
repository.py  # acesso ao Supabase
schemas.py     # pydantic models (input/output)
```

Registro em `app/api/router.py`:

```python
from app.modules.auth.routes import router as auth_router
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
```

## Fluxo de erro
- Sidecar offline → backend retorna `503 sidecar_unavailable`; frontend mostra "tentar novamente".
- QR expirado (Baileys emite novo) → sidecar empurra `qr-updated`; frontend re-renderiza.
- Extração falha (timeout, número banido) → status `failed`; relatório não é criado; STATE.md ganha blocker.
- LLM falha → relatório fica `failed` com `error` no payload; UI mostra fallback genérico.
