# Integrações externas

## Existentes

### Supabase (Auth + DB)
- Client: `supabase-py` (`backend/app/clients/supabase.py`).
- Variáveis: `SUPABASE_URL`, `SUPABASE_KEY` (anon), `SUPABASE_SERVICE_ROLE_KEY`.
- Auth: bearer token validado em `app/core/security.py` via `supabase.auth.get_user(jwt)`.
- Instância **compartilhada com projeto "News"** (D3) — convenção de prefixo `medzee_` nas tabelas.
- Frontend ainda não consome Supabase direto; em F4 vai usar `@supabase/supabase-js` para `setSession` após signup.

### ElevenLabs (agente de voz)
- Frontend: `@elevenlabs/react` v1.6 em `AgentScreen.jsx`.
- Agent id hardcoded: `agent_8601krmch56bfbbv5wjya2jw0y3x` (Marina).
- `clientTools` exposto: `mostrarQRCode`, `mostrarRelatorio` — disparam a transição do fluxo.
- Conexão via WebSocket; permissão de microfone solicitada pelo navegador.
- Sem armazenamento de áudio; sem custo recorrente além do uso do agente.

## A criar (M1)

### Baileys (WhatsApp Web)
- Serviço sidecar em Node.js (`whatsapp-sidecar/`).
- Lib: `@whiskeysockets/baileys` (fork ativo).
- Storage de auth state: filesystem local `sessions/<sessionId>/` (no `.gitignore`).
- Endpoints expostos para o FastAPI:
  - `POST /sessions` → cria sessão, retorna `{ sessionId, qr }`.
  - `GET /sessions/:id/events` (SSE ou WS) → stream de status (`qr-updated`, `connected`, `extracted`, `failed`).
  - `POST /sessions/:id/extract` → extrai mensagens dos últimos 30 dias.
  - `DELETE /sessions/:id` → encerra sessão e remove auth state.
- Auth interna: header `X-Sidecar-Token` validado contra `WHATSAPP_SIDECAR_TOKEN`.
- Política: sidecar nunca persiste conteúdo de mensagem em disco — só retorna no response do `/extract`.

### LLM provider
- Default: Anthropic (`anthropic` SDK) — `claude-sonnet-4-6`.
- Abstração: `app/clients/llm.py` com função `async def complete(messages, model, max_tokens) -> str`.
- Adapter alternativo para OpenAI ficará atrás da mesma interface (não implementar em M1 a menos que necessário).
- Variáveis: `LLM_PROVIDER`, `ANTHROPIC_API_KEY`.

## Convenções para integrações futuras
- Toda integração externa fica em `app/clients/<nome>.py` com factory function (não importar SDKs em modules diretamente).
- Variáveis em `Settings` com default vazio e validação no startup quando crítica.
- Timeouts explícitos em todas as chamadas HTTP (`httpx.AsyncClient(timeout=...)`).
- Erros de integração → log estruturado + status `5xx` específico (não `500` genérico).
