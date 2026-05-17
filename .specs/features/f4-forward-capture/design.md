# F4 — Forward-Capture & On-Demand Reports · Design

> Blueprint técnico que mapeia [spec.md](spec.md) para código. Atomização em [tasks.md](tasks.md).

## 1. Visão geral

F4 inverte a polaridade de F1: em vez de **puxar histórico passado**, **escuta o futuro**. uazapi paid webhook entrega cada mensagem nova → backend persiste → user clica "Gerar relatório" → worker F3 (reusado) lê do DB e roda métricas + Claude.

```
  Primeira vez                Ongoing
  ─────────────               ──────────
  /spy → QR → form           [conexão persistente]
       ↓                            ↓
   signup OK                  msg nova chega
   webhook conecta            uazapi webhook
       ↓                            ↓
  /app/dashboard              insert captured_messages
   "Conectado,                      ↓
    aguardando msgs"          [acumula]
                                    ↓
                              user: "Gerar relatório (30d)"
                                    ↓
                              POST /api/reports/generate
                                    ↓
                              Worker: SELECT captured WHERE ts > now-30d
                                    ↓
                              ExtractedPayload (shape do F3) ── reuse total
                                    ↓
                              metrics + sample + Claude + compose ── reuse
                                    ↓
                              update reports row status=completed
```

**Diff arquitetural vs F3:**
- F3 produzia `ExtractedPayload` em memória via `extract_30d_pipeline` → consumia 1×
- F4 produz `ExtractedPayload` **virtualmente** lendo do DB → pode consumir N×

`generate_report_pipeline` (worker do F3) **não muda**. O que muda é **quem chama ele e com qual payload**.

## 2. Arquivos a criar/alterar

### Backend

```
backend/app/
├── modules/captured_messages/                   # NOVO módulo
│   ├── __init__.py
│   ├── schemas.py                                # CapturedMessage, CapturedMessageStats
│   ├── repository.py                             # CRUD + queries por janela
│   └── service.py                                # _build_extracted_payload, stats
│
├── modules/whatsapp/
│   ├── routes.py                                 # ALTERAR — webhook trata messages event
│   ├── service.py                                # ALTERAR — handle_webhook_event extends
│   └── status.py                                 # NOVO — GET /whatsapp/status endpoint
│
├── modules/reports/
│   └── routes.py                                 # ALTERAR — POST /reports/generate
│   └── service.py                                # ALTERAR — generate_for_user(period_days)
│
├── workers/
│   ├── ttl_cleanup.py                            # NOVO — TTL job de captured_messages
│   ├── extract.py                                # MANTER (dead code; reabilitável)
│   └── report.py                                 # SEM MUDANÇAS (input shape preservado)
│
└── main.py                                        # ALTERAR — start TTL loop no lifespan
```

### Frontend

```
frontend/src/
├── lib/
│   ├── whatsapp.js                               # NOVO — getStatus, disconnect, useWhatsappStatus
│   └── reports.js                                 # ALTERAR — generateReport(periodDays)
│
├── screens/dashboard/
│   ├── WhatsAppPage.jsx                          # ALTERAR — estado conectado/desconectado + counts
│   ├── ReportsListPage.jsx                       # ALTERAR — botão "Gerar relatório agora" + period_days
│   ├── GenerateReportModal.jsx                   # NOVO — dropdown 7/15/30/60
│   └── DashboardPage.jsx                         # ALTERAR — card status do WhatsApp
│
└── screens/
    └── (LeadFormScreen e demais inalterados)
```

### Migration

```
SQL via mcp__supabase__apply_migration name="f4_1_captured_messages"
```

## 3. Migration SQL

```sql
-- f4_1_captured_messages
-- F4 §F4-01..05: tabela de mensagens capturadas via webhook + período em reports.

-- 1. Tabela principal
create table if not exists medzee_spy.captured_messages (
  id                    uuid primary key default gen_random_uuid(),
  user_id               uuid not null references auth.users(id) on delete cascade,
  whatsapp_session_id   uuid not null references medzee_spy.whatsapp_sessions(id) on delete cascade,
  wa_chatid             text not null,
  contact_name          text,
  ts                    timestamptz not null,        -- timestamp da msg original
  is_from_me            boolean not null,
  message_type          text not null default 'text',
  text                  text,                         -- null em mídia
  raw_message_id        text,                         -- id da uazapi pra dedup
  created_at            timestamptz not null default now()
);

-- 2. Dedup (uazapi pode re-entregar mesmo evento)
create unique index if not exists ux_captured_messages_dedup
  on medzee_spy.captured_messages (whatsapp_session_id, raw_message_id)
  where raw_message_id is not null;

-- 3. Query principal (relatório de janela por user)
create index if not exists ix_captured_messages_user_ts
  on medzee_spy.captured_messages (user_id, ts desc);

-- 4. Query TTL (deletar por session)
create index if not exists ix_captured_messages_session
  on medzee_spy.captured_messages (whatsapp_session_id);

-- 5. RLS — só dono vê.
alter table medzee_spy.captured_messages enable row level security;

create policy "captured_owner_select"
  on medzee_spy.captured_messages
  for select to authenticated
  using (auth.uid() = user_id);

-- Service role (webhook + TTL job) bypassa RLS.
grant select, insert, delete on medzee_spy.captured_messages
  to authenticated, service_role;

comment on table medzee_spy.captured_messages is
  'WhatsApp messages captured via uazapi webhook. TTL: 30 days after the
   linked whatsapp_session disconnects (see workers/ttl_cleanup.py).';


-- 6. Adicionar period_days em reports (F4-06)
alter table medzee_spy.reports
  add column if not exists period_days int default 30
    check (period_days in (7, 15, 30, 60));

comment on column medzee_spy.reports.period_days is
  'F4: janela usada pra gerar este relatório (escolha do user).';
```

## 4. Pydantic schemas

`app/modules/captured_messages/schemas.py`:

```python
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field


class CapturedMessage(BaseModel):
    id: UUID
    user_id: UUID
    whatsapp_session_id: UUID
    wa_chatid: str
    contact_name: str | None = None
    ts: datetime
    is_from_me: bool
    message_type: str = "text"
    text: str | None = None
    raw_message_id: str | None = None
    created_at: datetime


class CapturedMessageInsert(BaseModel):
    """Payload normalizado que sai do webhook parser, vai pro repository."""
    user_id: UUID
    whatsapp_session_id: UUID
    wa_chatid: str
    contact_name: str | None = None
    ts: datetime
    is_from_me: bool
    message_type: Literal["text", "image", "audio", "video", "sticker", "document", "other"] = "text"
    text: str | None = None
    raw_message_id: str | None = None


class WhatsappStatusResponse(BaseModel):
    connected: bool
    session_id: UUID | None = None
    connected_since: datetime | None = None
    message_count: int = 0
    conversation_count: int = 0           # distinct wa_chatid
    last_message_at: datetime | None = None


class GenerateReportRequest(BaseModel):
    period_days: Literal[7, 15, 30, 60] = 30


class GenerateReportResponse(BaseModel):
    report_id: UUID
    status: Literal["generating"] = "generating"
```

## 5. Webhook handler extension

`app/modules/whatsapp/service.py::handle_webhook_event` hoje só trata `event=connection`. Vai aprender `event=messages`.

```python
async def handle_webhook_event(self, session_id: UUID, payload: dict) -> None:
    event = (payload.get("event") or payload.get("EventType") or "").lower()
    if "connection" in event:
        await self._handle_connection_event(session_id, payload)
    elif event in ("messages", "messages.upsert", "message"):
        await self._handle_messages_event(session_id, payload)
    else:
        logger.debug("service.webhook.ignored event=%s", event)


async def _handle_messages_event(self, session_id: UUID, payload: dict) -> None:
    """Persiste cada msg nova em captured_messages.

    Shape provável (a confirmar via log na primeira chamada paid):
      {
        "EventType": "messages.upsert",
        "instance": {...},
        "messages": [{
          "key": {"id": "...", "remoteJid": "...@s.whatsapp.net", "fromMe": false},
          "messageTimestamp": 1735000000,
          "pushName": "Maria Silva",
          "message": {"conversation": "Olá, gostaria de marcar"}
        }, ...]
      }
    """
    state = await self._store.get(session_id)
    if state is None or state.user_id is None:
        logger.warning("captured.message.no_user_linked", extra={"session_id": str(session_id)})
        return

    raw_messages = payload.get("messages") or payload.get("data", {}).get("messages") or []
    if not isinstance(raw_messages, list):
        logger.warning("captured.message.unexpected_shape", extra={...})
        return

    inserts: list[CapturedMessageInsert] = []
    for raw in raw_messages:
        parsed = _parse_uazapi_message(raw, session_id=session_id, user_id=state.user_id)
        if parsed is not None:
            inserts.append(parsed)

    if inserts:
        await captured_repo.insert_many(inserts)


def _parse_uazapi_message(raw, *, session_id, user_id) -> CapturedMessageInsert | None:
    """Normalize uazapi's nested message shape → flat CapturedMessageInsert.

    Defensive: tolerates shape variations (free vs paid, version drift).
    Returns None pra mídia se não suportamos ainda (skip silenciosamente).
    """
    key = raw.get("key") or {}
    if not isinstance(key, dict):
        return None
    raw_message_id = key.get("id")
    wa_chatid = key.get("remoteJid") or raw.get("remoteJid")
    if not wa_chatid:
        return None

    is_from_me = bool(key.get("fromMe") or raw.get("fromMe"))
    ts_unix = raw.get("messageTimestamp") or raw.get("timestamp")
    if ts_unix is None:
        return None
    ts = datetime.fromtimestamp(int(ts_unix), tz=timezone.utc)

    # Tipo da msg + texto
    msg = raw.get("message") or {}
    if "conversation" in msg:
        text = msg["conversation"]
        message_type = "text"
    elif "extendedTextMessage" in msg:
        text = msg["extendedTextMessage"].get("text", "")
        message_type = "text"
    elif "imageMessage" in msg:
        text = msg["imageMessage"].get("caption")
        message_type = "image"
    elif "audioMessage" in msg:
        text = None
        message_type = "audio"
    else:
        text = None
        message_type = "other"

    contact_name = raw.get("pushName") or raw.get("notify")

    return CapturedMessageInsert(
        user_id=user_id,
        whatsapp_session_id=session_id,
        wa_chatid=wa_chatid,
        contact_name=contact_name,
        ts=ts,
        is_from_me=is_from_me,
        message_type=message_type,
        text=text,
        raw_message_id=raw_message_id,
    )
```

**Critical**: `state.user_id` precisa estar linkado **antes** das mensagens chegarem. Como F2 já roda `link_user` em `consume_extracted` e estamos abolindo o consume, vamos linkar de outra forma:

- Quando user faz signup vindo do `/spy`, `whatsapp_session_id` foi gerado lá. Backend `signup` agora chama `repository.link_user(session_id, user_id)` direto (sem `consume_extracted`).
- O `state.user_id` em memória precisa ser populado. Hoje `SessionStore` não tem campo `user_id`. Vamos **adicionar** essa propriedade.

## 6. Repository (`captured_messages/repository.py`)

```python
async def insert_many(items: list[CapturedMessageInsert]) -> int:
    """Bulk insert com ON CONFLICT DO NOTHING (dedup via unique index).
    Returns count of rows actually inserted (não duplicates)."""

async def query_window_for_user(
    user_id: UUID, *, since: datetime, until: datetime | None = None
) -> list[CapturedMessage]:
    """SELECT * WHERE user_id=? AND ts > since AND ts <= until ORDER BY ts ASC."""

async def stats_for_user(user_id: UUID) -> dict:
    """Returns: {message_count: int, conversation_count: int (distinct wa_chatid),
                 last_message_at: datetime|None}"""

async def stats_for_session(session_id: UUID) -> dict:
    """Idem mas filtrado por session_id (usado no /whatsapp/status)."""

async def delete_for_session(session_id: UUID) -> int:
    """DELETE WHERE whatsapp_session_id=?. Returns deleted count."""

async def delete_for_user(user_id: UUID) -> int:
    """Used by 'Apagar meus dados' (post-MVP)."""
```

Logs: `repo.captured.insert_many count=N`, `repo.captured.query_window count=N range=...`. NUNCA logar `text`.

## 7. Endpoints

### `GET /api/whatsapp/status` (F4-14)

```python
@router.get("/status", response_model=SuccessResponse[WhatsappStatusResponse])
async def whatsapp_status(
    user_id: UUID = Depends(get_current_user_id),
    repo: ... = Depends(...),
) -> SuccessResponse[WhatsappStatusResponse]:
    """Retorna status atual do WhatsApp do user."""
    session = await whatsapp_repo.get_active_for_user(user_id)
    if session is None:
        return SuccessResponse(data=WhatsappStatusResponse(connected=False))

    stats = await captured_repo.stats_for_session(session["id"])
    return SuccessResponse(data=WhatsappStatusResponse(
        connected=session["status"] == "connected",
        session_id=session["id"],
        connected_since=session["connected_at"],     # adicionar coluna se não existe
        message_count=stats["message_count"],
        conversation_count=stats["conversation_count"],
        last_message_at=stats["last_message_at"],
    ))
```

### `POST /api/reports/generate` (F4-11..13)

```python
@router.post("/generate", response_model=SuccessResponse[GenerateReportResponse])
async def generate_report(
    req: GenerateReportRequest,
    user_id: UUID = Depends(get_current_user_id),
    service: ReportService = Depends(get_report_service),
) -> SuccessResponse[GenerateReportResponse]:
    """Trigger relatório on-demand sobre janela escolhida.

    Rate limit: 1/min/user (F4-12).
    Pré-requisito: pelo menos 10 msgs capturadas (F4-13/EC-02).
    """
    # Rate limit
    _check_rate_limit(user_id)
    # Min volume
    stats = await captured_repo.stats_for_user(user_id)
    if stats["message_count"] < 10:
        raise HTTPException(422, detail="not_enough_data")
    # Cria report row + dispara worker
    report_id = await service.trigger_generate(user_id, period_days=req.period_days)
    return SuccessResponse(data=GenerateReportResponse(report_id=report_id))
```

## 8. Worker adapter

`generate_report_pipeline` (F3) hoje recebe `payload: ExtractedPayload` direto. Pra F4, criamos uma camada de tradução:

```python
# app/modules/reports/service.py

async def trigger_generate(self, user_id: UUID, *, period_days: int) -> UUID:
    """Cria row reports e dispara worker async."""
    report_id = await repository.create_generating(
        whatsapp_session_id=None,    # pode ser any of the user's sessions
        user_id=user_id,
        clinic_segment=await _resolve_clinic_segment(user_id),
    )
    # Atualiza period_days
    await repository.update_period_days(report_id, period_days)

    asyncio.create_task(
        _build_and_run(report_id, user_id, period_days),
        name=f"report-{report_id}",
    )
    return report_id


async def _build_and_run(report_id, user_id, period_days):
    """Builds ExtractedPayload from captured_messages, runs F3 pipeline."""
    from datetime import datetime, timedelta, timezone
    since = datetime.now(timezone.utc) - timedelta(days=period_days)

    captured = await captured_repo.query_window_for_user(user_id, since=since)
    payload = _build_extracted_payload(captured)
    # Importante: passa o report_id pra worker NÃO criar nova row.
    await generate_report_pipeline(
        session_id=captured[0].whatsapp_session_id if captured else uuid4(),
        payload=payload,
        user_id=user_id,
        report_id=report_id,        # NOVO param — pula create_generating
    )


def _build_extracted_payload(captured: list[CapturedMessage]) -> ExtractedPayload:
    """Agrupa msgs por wa_chatid → ConversationPayload list → ExtractedPayload."""
    by_chat: dict[str, list[MessagePayload]] = {}
    contact_names: dict[str, str | None] = {}

    for m in captured:
        msgs = by_chat.setdefault(m.wa_chatid, [])
        msgs.append(MessagePayload(
            ts=int(m.ts.timestamp()),
            from_me=m.is_from_me,
            type=m.message_type,
            text=m.text or "",
        ))
        if m.wa_chatid not in contact_names:
            contact_names[m.wa_chatid] = m.contact_name

    conversations = [
        ConversationPayload(
            wa_chatid=cid,
            contact_name=contact_names.get(cid) or "",
            is_group=cid.endswith("@g.us"),
            last_message_at=max(m.ts for m in msgs) if msgs else None,
            messages=sorted(msgs, key=lambda m: m.ts),
        )
        for cid, msgs in by_chat.items()
    ]

    return ExtractedPayload(
        message_count=sum(len(c.messages) for c in conversations),
        conversation_count=len(conversations),
        conversations=conversations,
        partial=False,
    )
```

**Pequeno refactor do worker F3** (`workers/report.py`):
- Aceitar `report_id` opcional. Se passado, pula `create_generating` e reusa.

## 9. TTL job (`workers/ttl_cleanup.py`)

```python
import asyncio
from datetime import datetime, timedelta, timezone

_TTL_DAYS = int(os.environ.get("CAPTURED_MESSAGES_TTL_DAYS", "30"))
_RUN_INTERVAL_S = 24 * 3600   # 1× por dia


async def ttl_cleanup_loop():
    """Background loop que roda 1× por dia.

    Pseudocódigo:
      every 24h:
        cutoff = now - 30 days
        SELECT id FROM whatsapp_sessions
          WHERE status = 'disconnected' AND updated_at < cutoff
        FOR session_id in result:
          DELETE FROM captured_messages WHERE whatsapp_session_id = session_id
          LOG cleanup count
    """
    while True:
        try:
            await _run_once()
        except Exception:
            logger.exception("ttl_cleanup.unhandled")
        await asyncio.sleep(_RUN_INTERVAL_S)


async def _run_once():
    cutoff = datetime.now(timezone.utc) - timedelta(days=_TTL_DAYS)
    expired_sessions = await whatsapp_repo.find_disconnected_before(cutoff)
    total = 0
    for session_id in expired_sessions:
        deleted = await captured_repo.delete_for_session(session_id)
        total += deleted
        logger.info(
            "ttl_cleanup.session_cleared",
            extra={"session_id": str(session_id), "deleted": deleted},
        )
    logger.info("ttl_cleanup.cycle_complete", extra={"total_deleted": total})
```

`app/main.py` lifespan:
```python
ttl_task = asyncio.create_task(ttl_cleanup_loop(), name="ttl_cleanup")
try:
    yield
finally:
    ttl_task.cancel()
```

## 10. Frontend

### `lib/whatsapp.js`

```javascript
import { useEffect, useState } from 'react';
import { callApi } from './api';

const POLL_MS = 5000;   // status só polla a cada 5s (não é tempo real)

export function useWhatsappStatus() {
  const [state, setState] = useState({ loading: true, status: null });

  useEffect(() => {
    let alive = true;
    let timer;
    async function tick() {
      try {
        const status = await callApi('/api/whatsapp/status', { auth: true });
        if (!alive) return;
        setState({ loading: false, status });
      } catch (e) {
        if (alive) setState({ loading: false, status: null, error: e });
      }
      if (alive) timer = setTimeout(tick, POLL_MS);
    }
    tick();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, []);

  return state;
}

export async function disconnectWhatsapp() {
  return callApi('/api/whatsapp/sessions/disconnect', { method: 'POST', auth: true });
}
```

### `lib/reports.js` (extensão)

```javascript
export async function generateReport(periodDays) {
  return callApi('/api/reports/generate', {
    method: 'POST',
    auth: true,
    body: { period_days: periodDays },
  });
}
```

### `WhatsAppPage.jsx`

```jsx
import { useWhatsappStatus, disconnectWhatsapp } from '../../lib/whatsapp';

export default function WhatsAppPage() {
  const { loading, status } = useWhatsappStatus();
  if (loading) return <Skeleton />;
  if (!status?.connected) {
    return <ConnectFlow />;  // links pra /spy
  }
  return (
    <ConnectedCard
      since={status.connected_since}
      messageCount={status.message_count}
      conversationCount={status.conversation_count}
      lastMessageAt={status.last_message_at}
      onDisconnect={disconnectWhatsapp}
    />
  );
}
```

### `GenerateReportModal.jsx`

```jsx
const PERIODS = [7, 15, 30, 60];
export default function GenerateReportModal({ open, onClose, onSubmit }) {
  const [period, setPeriod] = useState(30);
  return (
    <Modal open={open} onClose={onClose}>
      <h2>Gerar análise</h2>
      <p>Janela das conversas:</p>
      <RadioGroup value={period} onChange={setPeriod}>
        {PERIODS.map(d => <Radio value={d} label={`Últimos ${d} dias`} />)}
      </RadioGroup>
      <Button onClick={() => onSubmit(period)}>Gerar agora</Button>
    </Modal>
  );
}
```

### `ReportsListPage.jsx` (alterar)

```jsx
// Botão "Gerar relatório" existente → abre GenerateReportModal
// onSubmit → generateReport(period) → navigate(`/app/reports/${id}`)
//
// Cada item da lista mostra "Análise de N dias · DATA · score X"
```

## 11. Mapping de erros

| Camada | Erro | HTTP | UI |
|---|---|---|---|
| `POST /reports/generate` body inválido | (pydantic 422) | 422 | toast "Período inválido" |
| `POST /reports/generate` < 10 msgs | `not_enough_data` | 422 | "Aguarde algumas conversas chegarem" |
| `POST /reports/generate` rate-limit | (custom) | 429 | "Aguarde 1 minuto entre relatórios" |
| Webhook insert falha | swallow + log | 200 | n/a |
| `GET /whatsapp/status` sem session | `connected: false` | 200 | mostra ConnectFlow |

## 12. Test strategy

```
backend/app/tests/captured_messages/
├── conftest.py
├── test_repository.py        # insert_many dedup, query window, stats, TTL delete
├── test_service.py           # _parse_uazapi_message (shape variations), _build_extracted_payload
├── test_webhook.py           # event=messages full flow → DB insert
└── test_generate_endpoint.py # POST /reports/generate happy + 422 + 429
backend/app/tests/whatsapp/
└── test_status_endpoint.py   # GET /whatsapp/status (connected, disconnected, no session)
backend/app/tests/workers/
└── test_ttl_cleanup.py       # _run_once com session expirada → delete count > 0
```

Alvo: ~25 testes novos. Suite agregada: 172 → ~197.

**Casos críticos:**
- `_parse_uazapi_message` com payload de **3 shapes** observados (conversation, extendedTextMessage, imageMessage com caption)
- `insert_many` rejeita duplicatas via unique index sem erro
- `query_window_for_user` ordena por `ts asc` (importante pro funnel determinístico)
- TTL não toca session ainda conectada nem relatórios

## 13. Observações abertas

1. **uazapi webhook shape paid pode diferir do free** — parser fallback genérico mas vale capturar 1× via log de debug na primeira chamada paid pra documentar.
2. **Webhook flooding**: clínica ativa pode mandar 100+ msgs/min. `insert_many` em batch resolve. Não precisa Redis queue no MVP.
3. **TTL não considera "soft-disconnect"**: se uazapi cair sozinha (sem user agir), `status` no DB pode ficar `connected` indefinido. Precisamos heartbeat (futuro) ou aceitar que TTL só dispara em desconexão explícita do user.
4. **Multiplos providers no futuro**: o `_parse_uazapi_message` é uazapi-specific. Se um dia migrarmos, criamos `_parse_evolution_message`. Protocol já abstrai create/connect — falta abstrair também o webhook parser.
5. **F1 extract worker fica dormindo** (`extract.py`). Não é chamado por ninguém. Mantido pra reabilitar futuro.

## 14. Pontes pra próximas features

- **Recurring reports (M2)**: trivial — substitui o `POST /generate` por cron que chama o mesmo `trigger_generate` periodicamente.
- **Multi-WhatsApp por clínica**: schema já comporta (`whatsapp_session_id` é FK; user_id pode ter N sessions). Frontend precisaria escolher qual.
- **PDF export**: `payload` jsonb tem tudo; renderer separado.
