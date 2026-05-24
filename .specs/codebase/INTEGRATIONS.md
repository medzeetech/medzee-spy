# Integrações externas

## Existentes

### Supabase (Auth + DB)
- Client: `supabase-py` (`backend/app/clients/supabase.py`).
- Variáveis: `SUPABASE_URL`, `SUPABASE_KEY` (anon), `SUPABASE_SERVICE_ROLE_KEY`.
- Auth: bearer token validado em `app/core/security.py` via `supabase.auth.get_user(jwt)`.
- Instância **compartilhada com projeto "News"** (D3) — convenção de prefixo `medzee_` nas tabelas.
- Frontend ainda não consome Supabase direto; em F2/F4 vai usar `@supabase/supabase-js` para `setSession` após signup. Vars `VITE_SUPABASE_URL` e `VITE_SUPABASE_ANON_KEY` já reservadas comentadas no `frontend/.env.example`.

### ElevenLabs (agente de voz)
- Frontend: `@elevenlabs/react` v1.6 em `AgentScreen.jsx`.
- Agent id: hoje hardcoded como `agent_8601krmch56bfbbv5wjya2jw0y3x` (Marina). Mover para `import.meta.env.VITE_ELEVENLABS_AGENT_ID` — variável já configurada em `frontend/.env`.
- `clientTools` exposto: `mostrarQRCode`, `mostrarRelatorio` — disparam a transição do fluxo.
- Conexão via WebSocket; permissão de microfone solicitada pelo navegador.
- Sem armazenamento de áudio; sem custo recorrente além do uso do agente.

## A criar (M1)

### uazapi.com (WhatsApp SaaS) — D1
Substitui a ideia descartada de sidecar Node + Baileys. Toda integração com WhatsApp Web fica encapsulada num adapter `app/clients/whatsapp/uazapi.py` que implementa o protocol `WhatsAppProvider`.

**Variáveis de ambiente:**
- `UAZAPI_BASE_URL` — subdomínio do tenant. Ex.: `https://naorpedroza.uazapi.com`.
- `UAZAPI_ADMIN_TOKEN` — token admin do tenant, usado para criar instâncias on-demand.

**Autenticação:**
- Operações de instância (connect, chat/find, message/find, disconnect): header `token: <instance_token>`.
- Operações admin (criar/listar/deletar instâncias, globalwebhook): header `admintoken: <admin_token>`.

**Endpoints usados na F1 (WhatsApp Ingestion):**

| Método | Path | Quando | Notas |
|---|---|---|---|
| `POST` | `/instance/create` | F1 — ao iniciar sessão | header `admintoken`; **body exige `name`** (L6 em STATE) — usamos `medzee-spy-<8hex>`; retorna `{ token, instance: {...} }` |
| `POST` | `/instance/connect` | F1 — após `create` | header `token` (instance_token); retorna `{ qrcode: base64_png, paircode? }`. **Free tier prefixa com `data:image/png;base64,`** — adapter strip antes de retornar |
| `GET`  | `/instance/status` | F1 — fallback / health-check | retorna `{ connected, loggedIn, jid }` |
| `POST` | `/webhook` | F1 — após `create` | registra URL + eventos por instância |
| `POST` | `/chat/find` | F1 — extração | lista chats. ⚠ Free tier devolve **500 logo após `connected`** (B3 em STATE) — aguardar history sync interno |
| `POST` | `/message/find` | F1 — extração | paginado por chat: `{ chatid, limit, offset }` → `{ messages, hasMore, nextOffset }` |
| `POST` | `/instance/disconnect` | F1 — cleanup | encerra a sessão no WhatsApp (mantém instância) |
| **`DELETE`** | **`/instance`** | F1 — cleanup completo | header `token` (instance_token), sem ID na URL. Disconnect + remove + libera slot. **`POST /instance/reset` NÃO faz isso** (L7 em STATE) |
| `GET`  | `/instance/wa_messages_limits` | F1 — opcional (telemetria) | mostra `provider_code: 463` se atingiu cap |
| `GET`  | `/instance/all` | F1 — orphan cleanup script | header `admintoken`. **Free tier: 401 "endpoint disabled"** — só funciona em paid tier |

**Webhook (callback da uazapi → nosso backend):** wire format real (capturado em smoke 2026-05-17):

```json
{
  "EventType": "connection",
  "instance": {
    "name": "medzee-spy-<8hex>",
    "status": "connected" | "disconnected",
    "lastDisconnect": "<iso8601>",                  // só em disconnected
    "lastDisconnectReason": "401: logged out…"      // só em disconnected
  },
  "instanceName": "medzee-spy-<8hex>",
  "owner": "5511XXXXXXXXX",                          // msisdn quando connected
  "token": "<36 chars>",
  "type": "LoggedOut"                                // só em desconexão por outro device
}
```

**Observações importantes (L4 em STATE):**
- O campo discriminador é `EventType` (camelCase, **não** `event` lowercase).
- O status fica em `instance.status` (nested), **não** em um `loggedIn` top-level.
- O JID está em `owner`, **não** em `data.user.id`.
- Não há `data` aninhado — o body é flat. O parser do service trata isso com fallbacks defensivos.
- URL registrada por sessão: `<API_BASE_URL>/api/whatsapp/webhook?session_id=<uuid>`.
- Backend responde 2xx em ≤ 5s sempre (delega processamento para task assíncrona).

**Política:**
- Sidecar/sessão **não persiste em nossa infra** — uazapi gerencia o auth state.
- Persistimos apenas `medzee_spy.whatsapp_sessions.uazapi_token` (vinculado ao usuário pós-signup) e metadados de status. Conteúdo de mensagem nunca é gravado (D4).
- Cleanup completo = `DELETE /instance` (libera slot). `POST /instance/disconnect` só desloga mas a entry continua no tenant.

**Trade-offs e mitigações:**
- **Vendor lock-in.** Mitigação: adapter `WhatsAppProvider` permite trocar provider sem reescrever rotas/serviços.
- **Dado sensível na infra de terceiro.** Blocker B1 em [STATE.md](.specs/project/STATE.md) — validar DPA/LGPD antes de produção.
- **Sem filtro nativo por data.** Mitigação: paginação manual em `message/find` com early-exit quando `timestamp < now - 30d`; paralelizar via `asyncio.gather` (5 concurrent inicialmente).
- **Rate limit.** Conferir `/instance/wa_messages_limits` se observarmos erro `provider_code: 463`.

### LLM provider — D2
- Default: Anthropic (`anthropic` SDK) — modelo `claude-sonnet-4-6`.
- Abstração: `app/clients/llm.py` com função `async def complete(messages, model, max_tokens) -> str`.
- Adapter alternativo para OpenAI/Gemini ficará atrás da mesma interface (não implementar em M1 a menos que necessário).
- Variáveis: `LLM_PROVIDER=anthropic`, `LLM_MODEL=claude-sonnet-4-6`, `ANTHROPIC_API_KEY=<…>`.

## Convenções para integrações futuras
- Toda integração externa fica em `app/clients/<nome>.py` (ou `app/clients/<nome>/__init__.py` quando virar pacote com adapters).
- Variáveis em `Settings` com default vazio e validação no startup quando crítica.
- Timeouts explícitos em todas as chamadas HTTP (`httpx.AsyncClient(timeout=...)`).
- Erros de integração → log estruturado (counts/tempos apenas, nunca payload sensível) + status `5xx` específico (não `500` genérico).
