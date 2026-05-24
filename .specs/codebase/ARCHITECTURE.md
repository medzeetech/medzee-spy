# Arquitetura

## Visão geral (alvo M1)

```
┌─────────────────────┐                       ┌───────────────────────────────┐
│   Frontend (Vite)   │ ───── HTTPS/JSON ───▶ │   FastAPI (backend/)           │
│   React 19 + RR7    │                       │   /api/auth                    │
│                     │ ◀──── SSE ─────────── │   /api/whatsapp/*              │
│                     │       (status)        │   /api/reports                 │
└─────────────────────┘                       │   /api/whatsapp/webhook ◀──┐   │
                                              └───────────┬────────────────┼──┘
                                                          │ httpx          │
                                                          │ REST           │ webhook
                                                          ▼                │ (POST)
                                              ┌──────────────────────────────┐
                                              │         uazapi.com           │
                                              │  (WhatsApp SaaS — D1)        │
                                              │  base: <subdomain>.uazapi.com│
                                              └─────────────┬────────────────┘
                                                            │ WhatsApp Web
                                                            ▼
                                                       WhatsApp da clínica


            FastAPI ─► Supabase (Auth + DB — D3)        FastAPI ─► LLM (Anthropic — D2)
                       ├── auth.users
                       ├── medzee_users_profile
                       ├── medzee_whatsapp_sessions
                       └── medzee_reports
```

Pontos-chave:
- **Sem sidecar próprio.** uazapi (externa) substitui Baileys/Node — D1.
- **Stream backend → frontend = SSE** (D5).
- **Trigger de extração = webhook `connection`** da uazapi (D6).
- **Container alvo:** só FastAPI (D7). Frontend roda em host via `npm run dev`. uazapi é externa.

## Fluxo principal — geração do relatório

1. **`/spy` carrega.** Frontend chama `POST /api/whatsapp/sessions`. Backend:
   - `POST <uazapi>/instance/create` (`admintoken`) → recebe `{ token: instance_token, instance: {...} }`.
   - `POST <uazapi>/instance/connect` (`token=instance_token`) → recebe `{ qrcode: base64_png }`.
   - `POST <uazapi>/webhook` registrando `{ url: <our>/api/whatsapp/webhook?session_id=<uuid>, events: ['connection','messages'] }`.
   - Insere `medzee_whatsapp_sessions { id, uazapi_token=instance_token, status='pending', user_id=NULL }`.
   - Responde `{ sessionId, qr: base64_png, status: 'pending' }`.

2. **Frontend abre SSE** `GET /api/whatsapp/sessions/:id/events`. Recebe eventos `qr-updated`, `connected`, `extracting`, `extracted`, `failed`, `expired`. Backend mantém um per-session pub/sub em memória.

3. **Médico lê o QR.** uazapi detecta no servidor deles e dispara `POST <our>/api/whatsapp/webhook` com `event='connection'`, `data={ loggedIn: true, jid: '...' }`.

4. **Backend recebe webhook:**
   - Atualiza `medzee_whatsapp_sessions.status='connected'`.
   - Publica evento SSE `{ event: 'connected', phone: <msisdn mascarado> }`.
   - Dispara task async de **extração** (D6).

5. **Extração** (in-process, async):
   - `POST <uazapi>/chat/find` paginado (ordenar por última mensagem desc).
   - Para cada chat (até N paralelos via `asyncio.gather`), `POST <uazapi>/message/find` paginado, parando quando `timestamp < now - 30d` OU `hasMore=false`.
   - Agrega em memória: `{ messageCount, conversationCount, conversations: [{ wa_chatid, contactName, lastMessageAt, messages: [{ ts, fromMe, type, text }] }] }`.
   - Publica `extracting` com progresso periódico.
   - Persiste cache em memória (`session_cache[session_id] = payload, TTL=15min`) — **nunca em disco/DB**.
   - Atualiza `medzee_whatsapp_sessions.status='extracted'`, `message_count`, `extracted_at`. Publica `extracted`.

6. **Frontend mostra `LeadFormScreen`** → ao submeter, `POST /api/auth/signup` com `{ ...form, whatsappSessionId }`. Backend (F2):
   - Cria usuário no Supabase Auth (`sign_up`).
   - Insere `medzee_users_profile`.
   - Liga `medzee_whatsapp_sessions.user_id` ao usuário.
   - Lê o payload do cache em memória, dispara processamento LLM em background — front recebe `{ session, reportJobId }`.
   - Após sucesso, `POST <uazapi>/instance/disconnect` e marca `status='consumed'`.

7. **Frontend faz login** com a session retornada (`supabase.auth.setSession`) e poll/SSE `GET /api/reports/:id/status` até `ready`.

8. **`ReportScreen` busca `GET /api/reports/:id`** (autenticado) e renderiza com os componentes existentes em `components/report/*`.

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
uazapi_token    text not null                                     -- instance_token devolvido pelo /instance/create
status          text not null                                     -- pending | connected | extracted | consumed | failed
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
from app.modules.whatsapp.routes import router as whatsapp_router
api_router.include_router(whatsapp_router, prefix="/whatsapp", tags=["whatsapp"])
```

## Camada de provider WhatsApp

```
app/clients/whatsapp/
├── __init__.py          # exporta WhatsAppProvider (Protocol) + get_provider()
├── uazapi.py            # adapter atual (httpx + uazapi REST)
└── (futuro: baileys_sidecar.py, official_cloud_api.py)
```

`WhatsAppProvider` deve expor pelo menos:
- `async create_session() -> { session_token, qr_base64 }`
- `async register_webhook(session_token, callback_url) -> None`
- `async list_chats(session_token, limit, offset) -> list[Chat]`
- `async list_messages(session_token, chat_id, limit, offset) -> { messages, has_more }`
- `async disconnect(session_token) -> None`

Trocar de provider no futuro = implementar o protocol e mudar `get_provider()`.

## Fluxo de erro
- uazapi 5xx / timeout → backend retorna `503 uazapi_unavailable`; frontend mostra "tentar novamente".
- QR expirado (uazapi reemite a cada ~20s, mas com timeout final) → renovar via novo `/instance/connect`; SSE empurra `qr-updated`.
- Webhook não chega em N min → backend faz fallback `GET /instance/status` em poll a cada 5s por até 60s.
- Extração falha (timeout, número banido — `provider_code: 463`) → status `failed`; relatório não é criado; STATE.md ganha lição.
- LLM falha → relatório `failed` com `error` no payload; UI mostra fallback genérico.
