# F1 — WhatsApp Ingestion · Design

> Blueprint técnico que mapeia [spec.md](spec.md) para código. Cada seção alimenta uma ou mais tasks em `tasks.md`.

## 1. Visão geral

Backend FastAPI orquestra três camadas:

1. **Provider layer** (`app/clients/whatsapp/`) — adapter REST contra uazapi.com, isolado atrás do protocol `WhatsAppProvider`.
2. **Module layer** (`app/modules/whatsapp/`) — routes (HTTP/SSE/webhook), service (regra de negócio), repository (Supabase) e state (in-memory store + pub/sub).
3. **Worker layer** (`app/workers/extract.py`) — task assíncrona disparada pelo webhook que executa o pipeline de extração de 30 dias.

Nada de fila externa (Redis/RQ/Celery) em M1 — `asyncio.create_task` + `SessionStore` em memória são suficientes para a escala alvo (< 100 sessões simultâneas, single-instance).

## 2. Arquivos a criar

```
backend/app/
├── clients/
│   └── whatsapp/
│       ├── __init__.py          # exporta WhatsAppProvider, get_provider()
│       ├── types.py             # tipos compartilhados (Chat, Message, ProviderSession)
│       ├── errors.py            # UazapiError, UazapiUnavailable, UazapiBanned, UazapiTimeout
│       └── uazapi.py            # adapter UazapiProvider (httpx)
├── modules/
│   └── whatsapp/
│       ├── __init__.py
│       ├── routes.py            # APIRouter: POST /sessions, GET /sessions/:id/events, POST /webhook, DELETE /sessions/:id
│       ├── service.py           # cria/encerra sessão, dispara extract
│       ├── repository.py        # persistência em medzee_whatsapp_sessions
│       ├── schemas.py           # pydantic: requests, responses, SSE events, webhook payload
│       ├── state.py             # SessionStore (in-memory) + pub/sub por sessão
│       └── mask.py              # masking helpers (msisdn → "+55 11 9****-1234")
├── workers/
│   └── extract.py               # extract_30d_pipeline(session_id)
└── tests/
    └── whatsapp/
        ├── __init__.py
        ├── conftest.py          # fixtures: client, mock_uazapi (via respx), mock_store
        ├── test_routes.py
        ├── test_service.py
        ├── test_extract.py
        ├── test_state.py
        └── test_uazapi_adapter.py

backend/migrations/
└── 0001_medzee_whatsapp_sessions.sql

backend/requirements.txt             # adicionar: respx, anyio (já vem com starlette)
```

Atualizações em arquivos existentes:
- `app/core/config.py` — adicionar settings `UAZAPI_BASE_URL`, `UAZAPI_ADMIN_TOKEN`, `LLM_PROVIDER`, `LLM_MODEL`, `ANTHROPIC_API_KEY`, `API_BASE_URL` (usado para construir a URL do webhook callback).
- `app/api/router.py` — `include_router(whatsapp_router, prefix="/whatsapp", tags=["whatsapp"])`.
- `app/main.py` — registrar startup/shutdown hooks no `lifespan` para o cleanup background task do `SessionStore`.

## 3. Configuração

```python
# app/core/config.py — diff conceitual
class Settings(BaseSettings):
    # ... existentes ...
    API_BASE_URL: str = "http://localhost:8000"  # usado p/ montar callback URL
    UAZAPI_BASE_URL: str = ""
    UAZAPI_ADMIN_TOKEN: str = ""
    LLM_PROVIDER: str = "anthropic"
    LLM_MODEL: str = "claude-sonnet-4-6"
    ANTHROPIC_API_KEY: str = ""

    # Tuning
    EXTRACT_DAYS_WINDOW: int = 30
    EXTRACT_PARALLELISM: int = 5            # chats concurrent
    EXTRACT_SOFT_TIMEOUT_S: int = 90        # alvo da spec
    EXTRACT_HARD_TIMEOUT_S: int = 120       # corte forçado (EC-03)
    SESSION_TTL_MINUTES: int = 15
    UAZAPI_HTTP_TIMEOUT_S: float = 8.0
```

Em prod via env do D7 (container): `API_BASE_URL` precisa apontar para a URL pública/túnel — uazapi precisa alcançar o backend para entregar webhook.

## 4. Provider layer

### 4.1 Tipos compartilhados

```python
# app/clients/whatsapp/types.py
from dataclasses import dataclass

@dataclass(frozen=True)
class ProviderSession:
    session_token: str   # = uazapi instance_token
    qr_base64: str       # PNG já em base64, sem prefixo "data:image/png;base64,"

@dataclass(frozen=True)
class Chat:
    wa_chatid: str
    contact_name: str
    is_group: bool
    last_message_at: int | None   # unix ts seconds

@dataclass(frozen=True)
class Message:
    ts: int                       # unix ts seconds
    from_me: bool
    type: str                     # "text" | "image" | ... — em M1 só interessa "text"
    text: str
```

### 4.2 Protocol e factory

```python
# app/clients/whatsapp/__init__.py
from typing import Protocol

class WhatsAppProvider(Protocol):
    async def create_session(self) -> ProviderSession: ...
    async def register_webhook(self, session_token: str, callback_url: str) -> None: ...
    async def refresh_qr(self, session_token: str) -> str: ...                     # retorna novo qr_base64
    async def get_status(self, session_token: str) -> dict: ...                    # health-check / fallback do webhook
    async def list_chats(
        self, session_token: str, limit: int = 100, offset: int = 0
    ) -> tuple[list[Chat], bool]: ...                                              # (chats, has_more)
    async def list_messages(
        self, session_token: str, chat_id: str, limit: int = 100, offset: int = 0
    ) -> tuple[list[Message], bool, int]: ...                                      # (messages, has_more, next_offset)
    async def disconnect(self, session_token: str) -> None: ...

def get_provider() -> WhatsAppProvider:
    from app.clients.whatsapp.uazapi import UazapiProvider
    return UazapiProvider()   # lê settings.UAZAPI_*
```

### 4.3 Adapter Uazapi

`UazapiProvider` encapsula um `httpx.AsyncClient` configurado com `timeout=UAZAPI_HTTP_TIMEOUT_S`. Headers padrão: `Content-Type: application/json`. Token muda por chamada (admin vs instance).

**Mapeamento endpoint → método:**

| Método do Protocol | Endpoint uazapi | Header de auth | Notas |
|---|---|---|---|
| `create_session` | `POST /instance/create` + `POST /instance/connect` | `admintoken` (1ª), `token` (2ª) | encadeia ambos; retorna QR já |
| `register_webhook` | `POST /webhook` | `token` | `{ url, events: ["connection","messages"], enabled: true }` |
| `refresh_qr` | `POST /instance/connect` | `token` | mesmo endpoint do connect inicial |
| `get_status` | `GET /instance/status` | `token` | usado em fallback se webhook não chega |
| `list_chats` | `POST /chat/find` | `token` | body: `{ limit, offset, sort: "last_message_desc" }` |
| `list_messages` | `POST /message/find` | `token` | body: `{ chatid, limit, offset }` |
| `disconnect` | `POST /instance/disconnect` | `token` | best-effort no failure |

**Parser de erro:**

```python
# app/clients/whatsapp/errors.py
class UazapiError(Exception):
    code: str

class UazapiUnavailable(UazapiError):    code = "uazapi_unavailable"   # 5xx / network
class UazapiTimeout(UazapiError):        code = "timeout"
class UazapiBanned(UazapiError):         code = "banned"               # provider_code 463
class UazapiQrExpired(UazapiError):      code = "qr_expired"           # response code específico
class UazapiUnknown(UazapiError):        code = "unknown"
```

Em cada chamada, o adapter:
1. Faz `client.post(...)`; em `httpx.TimeoutException` → `raise UazapiTimeout`.
2. Em `httpx.HTTPStatusError` 5xx → `raise UazapiUnavailable`.
3. Lê o body; se contém `provider_code: 463` → `raise UazapiBanned`.
4. Se 4xx por QR expirado → `raise UazapiQrExpired`.
5. Demais 4xx → `raise UazapiUnknown(response.text)`.

## 5. State manager

### 5.1 Estrutura

```python
# app/modules/whatsapp/state.py
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import asyncio
from uuid import UUID

class SessionStatus(str, Enum):
    PENDING = "pending"
    CONNECTED = "connected"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    CONSUMED = "consumed"
    FAILED = "failed"
    EXPIRED = "expired"

@dataclass
class SSEEvent:
    name: str                # qr-updated | connected | extracting | extracted | failed | expired
    data: dict

@dataclass
class SessionState:
    session_id: UUID
    uazapi_token: str
    status: SessionStatus = SessionStatus.PENDING
    qr_base64: str | None = None
    phone_masked: str | None = None
    payload: "ExtractedPayload | None" = None
    last_event: SSEEvent | None = None
    subscribers: list[asyncio.Queue[SSEEvent]] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    failed_code: str | None = None
    message_count: int = 0
```

### 5.2 SessionStore

```python
class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[UUID, SessionState] = {}
        self._lock = asyncio.Lock()

    async def create(self, session_id, uazapi_token, qr_base64) -> SessionState
    async def get(self, session_id) -> SessionState | None
    async def update(self, session_id, **fields) -> None                # atomically set + publish if status changed
    async def publish(self, session_id, event: SSEEvent) -> None        # writes to last_event + all subscribers' queues
    async def subscribe(self, session_id) -> AsyncIterator[SSEEvent]    # yields events; replay last_event first
    async def consume(self, session_id) -> "ExtractedPayload | None"    # called by F2 signup; marks as consumed + triggers disconnect
    async def expire_stale(self) -> None                                # background loop: TTL > 15min in non-terminal → mark expired + disconnect

# Singleton — instanciado uma vez em main.py via lifespan
```

**Subscribe semantics (per WPP-14 replay-last):**

```python
async def subscribe(self, session_id):
    state = self._sessions.get(session_id)
    if not state:
        return  # 404 path handled by route
    queue: asyncio.Queue[SSEEvent] = asyncio.Queue(maxsize=32)
    state.subscribers.append(queue)
    try:
        if state.last_event:
            yield state.last_event
            if state.status in {SessionStatus.EXTRACTED, SessionStatus.CONSUMED,
                                SessionStatus.FAILED, SessionStatus.EXPIRED}:
                return                          # terminal → close stream (WPP-15)
        while True:
            event = await queue.get()
            yield event
            if event.name in {"extracted", "failed", "expired"}:
                return
    finally:
        state.subscribers.remove(queue)
```

**Expire loop** (registrado no `lifespan`):

```python
async def _expire_loop(self):
    while True:
        await asyncio.sleep(60)
        now = datetime.now(timezone.utc)
        for sid, state in list(self._sessions.items()):
            age = (now - state.created_at).total_seconds() / 60
            if age > settings.SESSION_TTL_MINUTES and state.status not in {
                SessionStatus.CONSUMED, SessionStatus.FAILED, SessionStatus.EXPIRED
            }:
                try:
                    await get_provider().disconnect(state.uazapi_token)
                except Exception:
                    pass
                await self.publish(sid, SSEEvent("expired", {"reason": "ttl"}))
                state.status = SessionStatus.EXPIRED
```

## 6. Pipeline de extração

```python
# app/workers/extract.py
async def extract_30d_pipeline(session_id: UUID) -> None:
    provider = get_provider()
    state = await session_store.get(session_id)
    if not state or state.status != SessionStatus.CONNECTED:
        return

    await session_store.update(session_id, status=SessionStatus.EXTRACTING)
    cutoff_ts = int((datetime.now(timezone.utc) - timedelta(days=settings.EXTRACT_DAYS_WINDOW)).timestamp())

    try:
        async with asyncio.timeout(settings.EXTRACT_HARD_TIMEOUT_S):
            # 1) Coletar TODOS os chats (paginar até has_more=false)
            chats: list[Chat] = []
            offset = 0
            while True:
                page, has_more = await provider.list_chats(
                    state.uazapi_token, limit=100, offset=offset
                )
                chats.extend(page)
                if not has_more:
                    break
                offset += 100

            await session_store.publish(session_id, SSEEvent(
                "extracting", {"collected": 0, "total_chats": len(chats)}
            ))

            # 2) Para cada chat, extrair mensagens (paralelo via semaphore)
            sem = asyncio.Semaphore(settings.EXTRACT_PARALLELISM)
            collected_chats = 0

            async def extract_chat(chat: Chat) -> ConversationPayload | None:
                nonlocal collected_chats
                async with sem:
                    msgs: list[Message] = []
                    msg_offset = 0
                    while True:
                        page, has_more, next_offset = await provider.list_messages(
                            state.uazapi_token, chat.wa_chatid, limit=100, offset=msg_offset
                        )
                        old_found = False
                        for m in page:
                            if m.ts < cutoff_ts:
                                old_found = True
                                break
                            if m.type == "text" and m.text:
                                msgs.append(m)
                        if old_found or not has_more:
                            break
                        msg_offset = next_offset
                    collected_chats += 1
                    if collected_chats % 5 == 0:
                        await session_store.publish(session_id, SSEEvent(
                            "extracting",
                            {"collected": collected_chats, "total_chats": len(chats)}
                        ))
                    if not msgs:
                        return None
                    return ConversationPayload(
                        wa_chatid=chat.wa_chatid,
                        contact_name=chat.contact_name,
                        is_group=chat.is_group,
                        last_message_at=chat.last_message_at,
                        messages=msgs,
                    )

            results = await asyncio.gather(*[extract_chat(c) for c in chats])
            conversations = [c for c in results if c is not None]

            # 3) Montar payload + cache
            payload = ExtractedPayload(
                message_count=sum(len(c.messages) for c in conversations),
                conversation_count=len(conversations),
                conversations=conversations,
            )
            await session_store.update(
                session_id,
                status=SessionStatus.EXTRACTED,
                payload=payload,
                message_count=payload.message_count,
            )
            await session_repo.mark_extracted(session_id, payload.message_count)  # DB
            await session_store.publish(session_id, SSEEvent(
                "extracted",
                {"message_count": payload.message_count,
                 "conversation_count": payload.conversation_count},
            ))

    except asyncio.TimeoutError:
        # corte duro (EC-03): salvar o que tem como "partial=true"
        await _finalize_partial(session_id)
    except UazapiBanned:
        await _fail(session_id, code="banned")
    except UazapiTimeout:
        await _fail(session_id, code="timeout")
    except UazapiUnavailable:
        await _fail(session_id, code="uazapi_unavailable")
    except Exception as exc:
        logger.exception("extract pipeline failed", extra={"session_id": str(session_id)})
        await _fail(session_id, code="extract_failed")
```

**Cuidados:**
- Acumulação de progresso a cada 5 chats (WPP-07/WPP-09) — evita inundar SSE.
- Filtro `m.type == "text" and m.text` descarta mídia/áudio/sticker explicitamente (WPP-08, CONCERNS R2).
- `cutoff_ts` é unix seconds para casar com o que uazapi devolve.
- O log estruturado **nunca** inclui `m.text` ou `wa_chatid` em texto bruto — só counts e elapsed_ms (WPP-10).

## 7. Endpoints HTTP

### 7.1 `POST /api/whatsapp/sessions`
Cria sessão na uazapi e retorna QR.

```python
@router.post("/sessions", response_model=SuccessResponse[CreateSessionResponse])
async def create_session(request: Request):
    # rate-limit por IP (WPP-16) — implementar com middleware simples + dict TTL
    service = WhatsAppService(get_provider(), session_store, session_repo)
    result = await service.create_session(client_ip=request.client.host)
    return SuccessResponse(data=result)
```

`service.create_session()` faz:
1. Chama `provider.create_session()` → `{ session_token, qr_base64 }`.
2. Gera `session_id = uuid4()`.
3. Monta `callback_url = f"{settings.API_BASE_URL}/api/whatsapp/webhook?session_id={session_id}"`.
4. Chama `provider.register_webhook(session_token, callback_url)`.
5. Chama `repo.create(session_id, uazapi_token=session_token, status="pending")`.
6. `store.create(session_id, ...)` em memória.
7. Retorna `CreateSessionResponse(session_id, qr=qr_base64, status="pending")`.

Erros: qualquer `UazapiError` no caminho → marcar sessão como `failed` (se já criada) e retornar `503` com `detail` mapeado.

### 7.2 `GET /api/whatsapp/sessions/{session_id}/events`
SSE stream.

```python
@router.get("/sessions/{session_id}/events")
async def session_events(session_id: UUID):
    if not await session_store.get(session_id):
        raise HTTPException(404, "session_not_found")

    async def gen():
        async for event in session_store.subscribe(session_id):
            yield f"event: {event.name}\ndata: {json.dumps(event.data)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # nginx / proxy hint
            "Connection": "keep-alive",
        },
    )
```

### 7.3 `POST /api/whatsapp/webhook?session_id={uuid}`
Callback da uazapi.

```python
@router.post("/webhook", status_code=200)
async def uazapi_webhook(
    session_id: UUID,
    payload: UazapiWebhookPayload,
    background: BackgroundTasks,
):
    state = await session_store.get(session_id)
    if not state:
        return {"status": "ignored"}     # sessão expirada/desconhecida — não vazar 404

    if payload.event == "connection":
        if payload.data.get("loggedIn") is True:
            phone = mask_phone(payload.data.get("jid", ""))
            await session_store.update(session_id, status=SessionStatus.CONNECTED,
                                        phone_masked=phone)
            await session_store.publish(session_id, SSEEvent("connected", {"phone": phone}))
            background.add_task(extract_30d_pipeline, session_id)
        elif payload.data.get("loggedIn") is False and state.status == SessionStatus.CONNECTED:
            # desconectou pós-connected → tratar como failed
            await session_store.publish(session_id, SSEEvent("failed", {"code": "disconnected"}))

    # eventos "messages" são ignorados em M1 — extração é via REST
    return {"status": "ok"}
```

Resposta 2xx sempre em ≤ 5s — `BackgroundTasks` garante que o `extract_30d_pipeline` rode após o response.

### 7.4 `DELETE /api/whatsapp/sessions/{session_id}`
Cancelamento manual (frontend pode chamar se usuário fechar o `/spy`).

```python
@router.delete("/sessions/{session_id}")
async def cancel_session(session_id: UUID):
    state = await session_store.get(session_id)
    if not state:
        raise HTTPException(404, "session_not_found")
    if state.status in {SessionStatus.CONSUMED, SessionStatus.FAILED, SessionStatus.EXPIRED}:
        return {"status": "already_terminal"}
    try:
        await get_provider().disconnect(state.uazapi_token)
    except UazapiError:
        pass
    await session_store.publish(session_id, SSEEvent("expired", {"reason": "cancelled"}))
    return {"status": "cancelled"}
```

## 8. Schemas pydantic

```python
# app/modules/whatsapp/schemas.py
from pydantic import BaseModel, Field
from typing import Literal
from uuid import UUID

class CreateSessionResponse(BaseModel):
    session_id: UUID
    qr: str                  # base64 PNG (sem prefixo data:)
    status: Literal["pending"]

class UazapiWebhookPayload(BaseModel):
    event: str
    instance: str
    data: dict = Field(default_factory=dict)

class ConversationPayload(BaseModel):
    wa_chatid: str
    contact_name: str
    is_group: bool
    last_message_at: int | None
    messages: list["MessagePayload"]

class MessagePayload(BaseModel):
    ts: int
    from_me: bool
    type: str
    text: str

class ExtractedPayload(BaseModel):
    message_count: int
    conversation_count: int
    conversations: list[ConversationPayload]
    partial: bool = False    # true se cortou por timeout
```

`ExtractedPayload` **não** é serializado em response público — só fica em memória até F2 consumir. Manter como pydantic facilita validação interna e futuro export em F3.

## 9. SSE — formato e ciclo de vida

**Wire format:**
```
event: qr-updated
data: {"qr":"<base64>"}

event: connected
data: {"phone":"+55 11 9****-1234"}

event: extracting
data: {"collected":12,"total_chats":47}

event: extracted
data: {"message_count":2841,"conversation_count":43}

event: failed
data: {"code":"banned","message":"WhatsApp signaled provider_code 463"}
```

Cada bloco termina com `\n\n`. Não usamos `id:` por enquanto (auto-reconnect do EventSource cuida do replay via lógica nossa de `last_event`).

**Estados terminais que fecham o stream:** `extracted`, `failed`, `expired`, `consumed`. Subscriber recebe o terminal e o gerador retorna.

## 10. Mapping de erros

| Origem | Excessão | `code` no SSE | HTTP retornado em sync routes |
|---|---|---|---|
| Network timeout | `UazapiTimeout` | `timeout` | `504` |
| 5xx uazapi | `UazapiUnavailable` | `uazapi_unavailable` | `503` |
| `provider_code: 463` | `UazapiBanned` | `banned` | `502` |
| QR expirado / instância morta | `UazapiQrExpired` | `qr_expired` | `409` |
| Pipeline excede `EXTRACT_HARD_TIMEOUT_S` | (interno) | `extract_failed` (parcial salvo) | n/a (assíncrono) |
| Outro | `UazapiUnknown` / `Exception` | `unknown` | `500` |

## 11. Persistência Supabase

**Status: aplicada** em `itghmlcipjloirsyhare` via migrations `f1_1_medzee_schema_and_whatsapp_sessions` e `f1_2_harden_set_updated_at_search_path`. A decisão D3 foi revisada após inspecionar o schema do projeto News: **schema dedicado `medzee`** em vez de prefixo `medzee_*`. Tabela canônica = `medzee.whatsapp_sessions`.

```sql
-- Schema isolado (coexiste com public.* do News)
create schema if not exists medzee;
grant usage on schema medzee to authenticated, service_role;

create table if not exists medzee.whatsapp_sessions (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid references auth.users(id) on delete cascade,  -- null antes do signup (F2)
  uazapi_token    text not null,
  status          text not null check (status in (
                    'pending','connected','extracting','extracted',
                    'consumed','failed','expired'
                  )),
  message_count   integer not null default 0,
  phone_masked    text,
  failed_code     text,
  extracted_at    timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index whatsapp_sessions_user_id_idx
  on medzee.whatsapp_sessions (user_id);
create index whatsapp_sessions_status_idx
  on medzee.whatsapp_sessions (status);

alter table medzee.whatsapp_sessions enable row level security;

-- Apenas o owner lê via JWT; backend usa service_role e bypassa RLS.
create policy "session_owner_select"
  on medzee.whatsapp_sessions
  for select to authenticated
  using (auth.uid() = user_id);

grant select on medzee.whatsapp_sessions to authenticated;
-- insert/update/delete: apenas service_role (backend).
```

Repository (`app/modules/whatsapp/repository.py`) expõe:
- `create(id, uazapi_token, status='pending') -> None`
- `mark_status(id, status, **extra) -> None`
- `mark_extracted(id, message_count) -> None`
- `mark_failed(id, code) -> None`
- `mark_consumed(id) -> None`
- `link_user(id, user_id) -> None`   _(consumido em F2; deixar a função pronta)_

Todas usam `get_supabase_admin_client()` (service_role) já que pré-signup não temos JWT. Após F2, o linkar passa a respeitar RLS.

## 12. Estratégia de testes

```
backend/app/tests/whatsapp/
├── conftest.py
├── test_routes.py
├── test_service.py
├── test_extract.py
├── test_state.py
└── test_uazapi_adapter.py
```

**Tools:**
- `pytest` + `pytest-asyncio` (anyio_mode = "auto" via `pyproject.toml` ou `conftest`)
- `respx` para mockar `httpx` (uazapi)
- `TestClient` (síncrono) para rotas REST simples
- `httpx.AsyncClient(ASGITransport(app=app))` para SSE (precisa async)

**Fixtures principais:**

```python
# tests/whatsapp/conftest.py
@pytest.fixture
def mock_uazapi(respx_mock):
    respx_mock.post(f"{base}/instance/create").mock(
        return_value=httpx.Response(200, json={"token":"tok","instance":{"id":"x"}})
    )
    respx_mock.post(f"{base}/instance/connect").mock(
        return_value=httpx.Response(200, json={
            "connected":False,"loggedIn":False,
            "instance":{"qrcode":"<base64>","paircode":None}
        })
    )
    respx_mock.post(f"{base}/webhook").mock(return_value=httpx.Response(200))
    respx_mock.post(f"{base}/chat/find").mock(...)        # parametrizado por teste
    respx_mock.post(f"{base}/message/find").mock(...)
    respx_mock.post(f"{base}/instance/disconnect").mock(return_value=httpx.Response(200))
    return respx_mock

@pytest.fixture
def fresh_store():
    """SessionStore vazio + cleanup do estado in-memory global."""
```

**Casos prioritários:**

| Arquivo | Caso | Verifica |
|---|---|---|
| `test_routes.py` | `POST /sessions` happy path | 200, QR no payload, registro em store + repo |
| | `POST /sessions` quando uazapi 5xx | 503, sessão marcada failed |
| | `GET /sessions/:id/events` replay-last | 1º evento é o `last_event` da store |
| | `GET /sessions/:id/events` 404 | sessão inexistente |
| | `POST /webhook` event=connection loggedIn=true | publica `connected` + agenda extract task |
| | `DELETE /sessions/:id` | publica `expired`, chama disconnect |
| `test_service.py` | rate-limit por IP > 3 em 5min | 429 |
| `test_extract.py` | corte por timestamp 30d | só msgs no janela são incluídas |
| | filtro `type='text'` | mídia/áudio descartadas |
| | hard-timeout | termina com `partial=true` |
| | uazapi banned (463) | publica failed code=banned |
| | clínica sem mensagens (EC-02) | extracted com count=0 |
| `test_state.py` | TTL expira sessão | publish `expired` + remove |
| | subscribe replay-last terminal | fecha stream imediatamente |
| | multi-subscriber | ambos recebem mesmo evento |
| `test_uazapi_adapter.py` | parser de `provider_code: 463` | levanta UazapiBanned |
| | parser de timeout `httpx` | levanta UazapiTimeout |
| | mascaramento de phone via `mask_phone()` | "5511987651234@c.us" → "+55 11 9****-1234" |

**Cobertura alvo M1:** > 70% nos arquivos novos. Não obrigatório CI ainda (CONCERNS R7 ataca depois).

## 13. Observações abertas (entram em tasks ou no próximo design)

1. **`API_BASE_URL` em dev** — exigir cloudflared/ngrok rodando para o webhook funcionar. Adicionar item no README e validar no startup (warn se `API_BASE_URL` for localhost).
2. **Cleanup de instâncias órfãs** — sessões `consumed`/`failed` deixam a instância na uazapi em estado morto. Criar cron diário (fora do escopo M1, deixar tarefa em STATE) que lista instâncias via admin e deleta as > 24h sem uso.
3. **`fetch_message_history` da uazapi** — endpoint não listado na SKILL inicial; se `message/find` não trouxer histórico além de uns dias por chat, talvez precise sincronizar mais. Validar no smoke test antes de finalizar tasks.md.
4. **Idempotência do webhook** — uazapi pode reenviar callback. Hoje a lógica `if state.status != CONNECTED: skip` cobre duplicação de `connection`, mas vale registrar `webhook_received_at` no state e ignorar se < 2s atrás (debounce simples).
5. **Telemetria estruturada** — logs JSON com `session_id`, `event`, `elapsed_ms`. Em M1 basta `logging.getLogger(__name__).info(..., extra={...})`; estrutura mais formal (OpenTelemetry, etc.) fica adiada.

## 14. Pontes para próximas features

- **F2 (Auth)** vai chamar `session_store.consume(session_id)` para puxar o `ExtractedPayload`, gravar `user_id` em `medzee_whatsapp_sessions` (`repo.link_user`), e chamar `provider.disconnect()` ao final.
- **F3 (Report)** recebe o `ExtractedPayload` do service de auth, normaliza, manda para LLM, persiste em `medzee_reports`. Não precisa tocar nada do que F1 cria.
- **F4 (Frontend)** consome `POST /sessions`, abre `EventSource` no `/events`, manda `DELETE /sessions/:id` se o usuário fechar — toda a interface do contract pública já está espelhada nesta spec/design.
