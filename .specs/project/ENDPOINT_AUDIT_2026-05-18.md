# Auditoria Endpoint-by-Endpoint — uazapi vs Nosso Código

> Estudo sistemático de cada endpoint da uazapi que tocamos.
> Testado live contra `https://naorpedroza.uazapi.com` em 2026-05-18.
> Spec OpenAPI bundle: `.agents/uazapi_spec.json` (132 endpoints, 11 schemas).

## TL;DR — descobertas críticas

| # | Bug | Fix necessário | Severidade |
|---|---|---|---|
| 1 | **Eventos do webhook errados** (`messages.upsert`, `messages.update`, `message.received` etc não existem) | Trocar pelos nomes reais do enum | **CRÍTICA** — webhook não recebe os eventos que esperamos |
| 2 | **`/message/find` não puxa histórico sozinho** | Chamar `/message/history-sync` ANTES — uazapi sincroniza sob demanda | **CRÍTICA** — destrava pull-history |
| 3 | **`chatid` retornado pode ser `@lid`** (locally-anchored id), não o `@s.whatsapp.net` que consultamos | Mapear LID → JID antes de salvar em `captured_messages` | **ALTA** — quebra joins entre chats/messages |
| 4 | `nextOffset` (camelCase) vs `next_offset` (snake) | Parser ignora silencioso, paginação cai pra heurística | **BAIXA** — funciona, mas ineficiente |
| 5 | Não usamos `/webhook/errors` pra debug | Adicionar diagnostic endpoint | **BAIXA** — quality of life |
| 6 | Não usamos `/chat/details` (foto, nome real, grupos em comum) | Útil pra enriquecer relatório | **BAIXA** — feature add |

---

## Endpoint-by-Endpoint

### E1. `POST /instance/create` ✅

**Spec:** body `{name}`, returns `{token, instance: {token, status, ...}, status, ...}`

**Live response:**
```json
{
  "token": "uuid-do-instance",
  "instance": { "token": "mesmo-uuid", "status": "disconnected", ... },
  "status": { "connected": false, "loggedIn": false }
}
```

**Nosso código (`_extract_instance_token`):** tenta `payload.token`, `payload.instance.token`, `payload.data.token` — **funciona** ✅

---

### E2. `POST /instance/connect` ⚠️

**Spec:** body `{}` (vazio é OK), retorna `{instance: {qrcode, ...}}`

**Live response (instância recém-criada):**
```
{"error": "..."}   ← às vezes!
```
Outras vezes retorna QR normal em `instance.qrcode` (~1838 chars base64).

**Nosso código (`_extract_qr`):** tenta `payload.qrcode`, `payload.instance.qrcode`, `payload.data.qrcode` — **funciona quando QR existe** ✅. **Bug latente**: se retornar `{error: ...}`, nosso código levanta `UazapiUnknown` e a sessão é abortada. Talvez precise retry no `instance/connect` (já temos no `_retry_5xx`? — não, só 5xx).

**Fix sugerido:** se POST /connect retornar 200 mas com `error` no body, retry 2-3× com delay curto antes de abortar.

---

### E3. `GET /instance/status` ✅

**Spec:** retorna `{instance: {status, owner, ...}, status: {...}}`

**Live response:**
```json
{
  "instance": {
    "status": "connected" | "connecting" | "disconnected",
    "owner": "5511965012680",   // JID do número pareado (só quando connected)
    "id": "r...",
    ...
  }
}
```

**Nosso código:** `_payload_says_connected` lê `instance.status` — **funciona** ✅

---

### E4. `POST /webhook` (registrar) ❌ → ✅ APÓS FIXES

**Spec (resumida):**
```json
{
  "url": "https://your-server.com/webhook",
  "enabled": true,
  "events": ["connection","history","messages","messages_update",...],
  "excludeMessages": ["fromMeYes"|"fromMeNo"|"wasSentByApi"|"isGroupYes"|...],
  "addUrlEvents": true,
  "addUrlTypesMessages": true
}
```

**Live response:** ARRAY com 1+ webhooks configurados:
```json
[{"id":"r...","url":"...","enabled":true,"events":[...],...}]
```

**BUG #1 — Eventos errados (já corrigido `excludeMessages: []`):**

| Nosso código manda | Realidade do enum |
|---|---|
| `connection` | ✅ existe |
| `messages` | ✅ existe |
| `messages.upsert` | ❌ não existe |
| `messages.update` | ❌ → use `messages_update` (underscore) |
| `message` | ❌ não existe |
| `message.upsert` | ❌ não existe |
| `message.received` | ❌ não existe |
| `messages.received` | ❌ não existe |
| `presence.update` | ❌ → use `presence` |
| `chats.upsert` | ❌ → use `chats` |
| `chats.update` | ❌ não tem variante de update |

**Enum oficial completo:**
```
["connection", "history", "messages", "messages_update",
 "newsletter_messages", "call", "contacts", "presence",
 "groups", "labels", "chats", "chat_labels", "blocks", "sender"]
```

**Fix:** lista nova deve ser apenas:
```python
events: ["connection", "messages", "messages_update", "history", "chats", "presence"]
```

(Mantemos só os que importam pro nosso uso. `history` é importante porque é o evento disparado quando `/message/history-sync` completa.)

**BUG já corrigido:** `excludeMessages: false` (boolean) → `[]` (array) — commit `29f3e0d`.

---

### E5. `GET /webhook` ✅

**Live response:** mesmo shape do POST — array de configs.

**Nosso código:** só usa pra log de verificação — **funciona** ✅

---

### E6. `POST /chat/find` ✅

**Spec:** body `{operator, sort, limit, offset, ...filtros}`. Retorna `{chats, pagination, totalChatsStats}`.

**Live response:** OK, formato esperado. Campos do chat:
```python
{
  "wa_chatid": "557597035806@s.whatsapp.net",  # JID padrão
  "wa_name": "Ru",                              # nome conforme contato salvo
  "wa_contactName": "Amor",                     # nome no nosso WhatsApp
  "wa_lastMsgTimestamp": 1779062951000,         # MILISSEGUNDOS unix
  "wa_unreadCount": 0,
  "wa_isGroup": true | false,
  "wa_isBlocked": false,
  "wa_isPinned": false,
  "wa_archived": false,
  "wa_lastMessageType": "stickerMessage",
  "wa_lastMessageSender": "...",
  "lead_fullName": "",                          # CRM uazapi
  "lead_name": "",
  "lead_tags": [],
  "owner": "5511965012680",                     # nosso número
  ...
}
```

**Nosso código (`_parse_chat`):**
- Lê `wa_chatid` ✅
- Lê `contact_name` em `("contact_name","name","pushName","push_name","subject")` ❌ — **NÃO TEM nenhum desses**, deveria ler `wa_contactName` ou `wa_name`!
- Lê `is_group` de `("is_group","isGroup","group")` + fallback `@g.us` — funciona via fallback, mas devia ler `wa_isGroup`
- Lê `last_message_at` de `("last_message_at","lastMessageAt","t","timestamp")` ❌ — **NÃO LÊ `wa_lastMsgTimestamp`**!

**BUG #6 — Parser de chat ignorando os campos reais:**

| Field real | Nosso parser lê? |
|---|---|
| `wa_chatid` | ✅ |
| `wa_contactName` | ❌ |
| `wa_name` | ❌ |
| `wa_isGroup` | ❌ (usa fallback de sufixo @g.us) |
| `wa_lastMsgTimestamp` | ❌ |

Resultado: chats vinham com `contact_name=""` (vazio) e `last_message_at=None`.

**Fix:** atualizar `_parse_chat` pra preferir os campos `wa_*`.

---

### E7. `POST /message/history-sync` ⭐ **NOVO — CRÍTICO**

**Spec:**
```json
{
  "number": "5511999999999@s.whatsapp.net",  // OBRIGATÓRIO, JID completo
  "mode": "history" | "exact",                // default "history"
  "messageid": "...",                          // optional, âncora
  "count": 100                                 // 1-100, default ?
}
```

**Live response:**
```json
{
  "success": true,
  "message": "History sync request sent. Messages will be received as history sync events.",
  "request_id": "...",
  "details": {
    "anchor_source": "message_oldest",
    "attempted_chats": [...],
    "fallback_mode": "exact",
    "mode": "history",
    "count": 50,
    ...
  }
}
```

**Como funciona:** chamar isso "puxa" mensagens do servidor WhatsApp pro cache do uazapi. Depois (~5-8s), `/message/find` no mesmo chat retorna mensagens reais.

**Sem isso, `/message/find` retorna sempre vazio em instâncias recém-conectadas.**

**Fix:** adicionar método `request_history_sync(token, chatid, count)` no `UazapiProvider` e chamar no `pull_history` antes de iterar `/message/find`.

---

### E8. `POST /message/find` ✅ (com history-sync prévio)

**Spec:** body `{chatid, limit, offset, ...}`, retorna `{messages, hasMore, nextOffset, returnedMessages, offset, limit}`

**Live response (mensagem real):**
```json
{
  "messages": [{
    "chatid": "163406912995344@lid",          // ⚠️ pode vir como @lid (não @s.whatsapp.net que enviei!)
    "messageid": "3A6D0A289C505C757353",
    "messageTimestamp": 1779060176000,         // MILISSEGUNDOS
    "fromMe": true | false,
    "sender": "163406912995344@lid",
    "senderName": "...",                        // nome do remetente
    "text": "esse é o plano",                  // pra mensagens de texto
    "content": {"URL": "..."},                 // pra mídia (DICT, não string!)
    "messageType": "StickerMessage" | "ImageMessage" | "AudioMessage" | "conversation" | "extendedTextMessage" | ...,
    "isGroup": false,
    "edited": false,
    "reaction": "",
    "quoted": {},                               // mensagem citada (reply)
    "fileURL": "",
    "owner": "5511965012680",
    "status": "delivered" | "read" | ...,
    "pinned": false
  }],
  "hasMore": true,
  "limit": 5,
  "offset": 0,
  "nextOffset": 0,                              // ⚠️ camelCase, nosso código procura snake_case
  "returnedMessages": 5
}
```

**Nosso código (`_parse_message`):**
- `ts` em `("ts", "t", "timestamp", "messageTimestamp")` ✅ — `_first_ts` faz divisão por 1000 se >10^10 (ms→s) ✅
- `fromMe` ✅
- `messageType` ✅
- `text` em `("text","body","content","message","caption")` ⚠️ — `content` é DICT no /message/find (não string), nosso `_first_str` rejeita corretamente. Mas perdemos contexto pra captions de imagem que vêm via webhook (lá `content` pode ser string).

**BUG #4 — `nextOffset` camelCase:**
```python
next_offset_raw = _maybe_int(payload.get("next_offset"))   # snake — uazapi NÃO usa
# Fallback: offset + len(messages)
```
Funciona via fallback, mas vale corrigir.

**BUG #3 — `chatid` retorna como `@lid` em alguns chats:**

Quando WhatsApp Business / contato sem perfil aberto, `messages[].chatid` vem como `163406912995344@lid` em vez do `557597035806@s.whatsapp.net` que enviamos. Mas o chat continua sendo o mesmo na lista de `/chat/find`.

Se a gente persiste `wa_chatid` da MENSAGEM em `captured_messages`, mensagens do mesmo contato vão ficar dispersas em 2 IDs diferentes (LID + JID).

**Fix:** ao parsear mensagem do webhook OU do /message/find, se `chatid` termina em `@lid`, usar o `chatid` do REQUEST (que sabemos ser JID) — ou consultar `/chat/details` pra mapear.

Mais simples: gravar o `chatid` do request em vez do retornado pela uazapi (porque o request veio do `/chat/find` que dá JID).

---

### E9. `GET /instance/all` (admin) ✅

**Live response:** array direto de instâncias (não wrap em `{data: [...]}`).

**Nosso código:** suporta ambos shapes — **funciona** ✅

---

### E10. `POST /instance/disconnect` ✅

**Live response:** `{response: "Already disconnected"}` quando já está disconnected; struct completa de instance quando estava connected.

**Nosso código:** usa só pra side effect (não lê response) — **funciona** ✅

---

### E11. `DELETE /instance` ✅

**Live response:**
```json
{"info": "...successfully disconnected and deleted...", "response": "Instance Deleted"}
```

**Nosso código:** só checa 2xx — **funciona** ✅

---

### E12. `POST /chat/details` ⭐ **NOVO — opcional**

**Body:** `{number: "557597035806"}` (sem @s.whatsapp.net — só dígitos)

**Live response:**
```json
{
  "name": "Amor",                              // contact name (nosso)
  "wa_name": "Ru",                             // WhatsApp profile name (deles)
  "wa_contactName": "Amor",
  "phone": "+55 75 9703-5806",                 // formatado
  "wa_chatid": "557597035806@s.whatsapp.net",
  "wa_chatlid": "163406912995344@lid",         // ⭐ MAPEAMENTO LID↔JID!
  "image": "https://pps.whatsapp.net/...",    // foto perfil
  "imagePreview": "...",
  "wa_common_groups": "Grupo 1 (chatid), Grupo 2 (chatid), ...",
  "wa_fastid": "...",
  "wa_label": "",
  "lead_*": {}  // CRM fields
}
```

**Uso potencial:**
1. **Resolver LID → JID** — se uma mensagem chegou com `chatid=@lid`, podemos consultar `/chat/details` pra obter o `@s.whatsapp.net` correto.
2. **Enriquecer relatório** — foto do contato, grupos em comum, etc.
3. **Validar contato** — confirma se o número existe no WhatsApp.

---

### E13. `GET /webhook/errors` ⭐ **NOVO — debug**

**Live response:** `[]` (array vazio quando sem erros).

**Uso:** quando webhook não tá disparando, podemos polar isso pra ver se uazapi tentou e errou. Ótimo pra debug em prod.

---

## Plano de implementação (ordem de prioridade)

### Fase 1 — Fixes de criticidade ALTA (~1h)

**1.1 Corrigir lista de events em `register_webhook`** (`uazapi.py`)
- Trocar nossos nomes inventados pelos valores reais do enum
- Mantemos: `connection`, `messages`, `messages_update`, `history`, `chats`, `presence`
- Removemos: `messages.upsert`, `messages.update`, `message`, `message.upsert`, `message.received`, `messages.received`, `presence.update`, `chats.upsert`, `chats.update`

**1.2 Adicionar método `request_history_sync`** (`uazapi.py`)
```python
async def request_history_sync(self, token, chatid, count=100):
    return await self._request("POST", "/message/history-sync", token=token,
        json_body={"number": chatid, "mode": "history", "count": min(count, 100)})
```

**1.3 Integrar history-sync em `pull_history`** (`extract.py`)
- Antes do loop de `/message/find` por chat, disparar `history-sync` em paralelo
- Aguardar 5-8s globalmente OU por chat
- Depois listar mensagens normalmente

**1.4 Corrigir parser `_parse_chat`** (`uazapi.py`)
- Adicionar `wa_contactName`, `wa_name` na lista de fallbacks de contact_name
- Adicionar `wa_isGroup` na lista de fallbacks de is_group  
- Adicionar `wa_lastMsgTimestamp` na lista de fallbacks de last_message_at

### Fase 2 — Fixes de robustez (~30min)

**2.1 Tratar LID em mensagens** (`captured_messages` parser)
- Se `chatid` retornado termina com `@lid`, usar o chatid do REQUEST (que sabemos ser JID)
- Alternativa: consultar `/chat/details` na primeira vez pra fazer o mapeamento e cachear

**2.2 Adicionar `nextOffset` (camelCase) ao parser**
- Trivial: `_first_int(raw, ("next_offset", "nextOffset"))`

**2.3 Retry em `/instance/connect`** quando retorna `{error: ...}`
- 2-3 tentativas com delay curto (3s) antes de abortar

### Fase 3 — Melhorias (~30min)

**3.1 Adicionar `request_chat_details`** (`uazapi.py`)
- Opcionalmente enriquecer captured_messages com nome do contato
- Útil pro relatório (foto, telefone formatado, grupos comuns)

**3.2 Adicionar `get_webhook_errors`** (`uazapi.py`)
- Endpoint de diagnóstico — log quando webhook não tá disparando

**3.3 Documentar event names** num constants module
- Pra evitar regressão futura

### Fase 4 — Testes E2E (~30min)

**4.1 Smoke test do fluxo completo:**
1. Connect WhatsApp
2. Confirmar webhook registra com events corretos
3. Mandar mensagem → ver chegar no Railway log
4. Inserção em captured_messages
5. Gerar relatório de 7 dias → usa captured_messages (rápido)
6. Conferir relatório real com dados

**4.2 Smoke test do pull_history (F1 reativado):**
1. Connect WhatsApp
2. F1 auto-extract dispara
3. history-sync por chat
4. /message/find retorna msgs reais
5. Relatório auto gerado com histórico de 30d

---

## Total de mudanças esperadas

- ~60-100 linhas de código backend (uazapi.py + extract.py + service.py)
- ~5 linhas de doc (STATE.md)
- Zero migrações de DB
- Zero mudança de frontend

## Impacto esperado

| Antes | Depois |
|---|---|
| Webhook registra mas só `connection`/`messages` chegam (de 11 que pedíamos, 9 eram inválidos) | Webhook registra com nomes corretos, eventos esperados disparam |
| `/message/find` retorna sempre 0 em instância nova | `/message/find` retorna msgs reais após `history-sync` |
| Chats vinham com `contact_name=""` e `last_message_at=None` | Chats trazem nome real ("Amor", "Mãe") + timestamp da última msg |
| Mensagens com `chatid=@lid` ficavam dispersas no DB | Todas as msgs do mesmo contato consolidadas pelo JID |
