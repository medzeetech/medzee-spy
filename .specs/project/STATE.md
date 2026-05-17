# STATE — Memória persistente entre sessões

> Decisões, blockers, lições, todos e ideias adiadas. Atualizar ao final de cada sessão e ao registrar qualquer escolha relevante.

## Decisões

- **D1 (2026-05-17, revisada) — WhatsApp via uazapi.com (REST + webhook), abstraído em `WhatsAppProvider`.**
  Por quê: uazapi entrega QR como base64 PNG direto (`POST /instance/connect`), webhook nativo (`connection`, `messages`) para status em tempo real, gerencia o auth state internamente (eliminando a necessidade de sidecar Node, Baileys, Puppeteer ou storage próprio de sessões) e oferece `/chat/find` + `/message/find` para o histórico. Substitui a ideia anterior de sidecar Node + Baileys.
  Como aplicar: criar `app/clients/whatsapp/__init__.py` com protocol `WhatsAppProvider` e adapter `uazapi.py`. Backend usa `UAZAPI_BASE_URL` e `UAZAPI_ADMIN_TOKEN` (admin) para criar instâncias on-demand; cada sessão grava seu `uazapi_token` em `medzee_whatsapp_sessions`. **Não** versionar Baileys/Node sidecar.
  Trade-offs aceitos: vendor lock-in (mitigado pela camada de adapter), dado sensível trafega por terceiro (ver blocker B1), sem filtro nativo por data (paginação manual com corte por timestamp).

- **D2 (2026-05-17) — LLM provider-agnostic, default Anthropic Claude (`claude-sonnet-4-6`).**
  Por quê: prompt envolve análise textual extensa em PT-BR; Claude tem janela grande e bom desempenho. Mantém abstração para trocar provider sem reescrever pipeline.
  Como aplicar: `app/clients/llm.py` com interface `async def complete(messages, model, max_tokens) -> str` e adapter Anthropic em primeiro. Vars `LLM_PROVIDER`, `LLM_MODEL`, `ANTHROPIC_API_KEY` já estão no `.env`.

- **D3 (2026-05-17) — Reutilizar instância Supabase do projeto "News" com prefixo `medzee_` nas tabelas.**
  Por quê: pedido explícito do briefing.
  Como aplicar: migrations criam `medzee_users_profile`, `medzee_reports`, `medzee_whatsapp_sessions`. Supabase Auth é compartilhado (sem prefixo).

- **D4 (2026-05-17) — Nenhuma mensagem persistida no banco/log/disco.**
  Por quê: privacidade prometida na landing + risco LGPD para dados de saúde.
  Como aplicar: pipeline lê em memória → gera relatório → descarta mensagens. Persiste apenas o relatório estruturado em `medzee_reports.payload` (jsonb) e metadados agregados (counts, médias) em `medzee_whatsapp_sessions`. Logs registram só counts e tempos.

- **D5 (2026-05-17) — Stream backend ↔ frontend = SSE (Server-Sent Events).**
  Por quê: uso unidirecional (status → frontend); FastAPI suporta nativamente via `StreamingResponse`; `EventSource` no browser auto-reconecta; proxy/load balancer trivial. WebSocket adiciona complexidade que não é usada (cancelar = `DELETE` HTTP).
  Como aplicar: endpoint `GET /api/whatsapp/sessions/:id/events` retorna `StreamingResponse(generator, media_type="text/event-stream")`. Eventos: `qr-updated`, `connected`, `extracting`, `extracted`, `failed`, `expired`. Frontend usa `new EventSource(url)`.

- **D6 (2026-05-17) — Extração automática disparada pelo webhook `connection` da uazapi.**
  Por quê: minimiza o tempo total (não espera o signup); cache TTL 15min em memória cobre a janela até o usuário completar o cadastro; reduz fricção de UX.
  Como aplicar: callback `/api/whatsapp/webhook` (registrado em `POST /webhook` da uazapi com `events: ['connection','messages']`) recebe `connection` com `loggedIn=true`, marca sessão como `connected`, dispara task assíncrona de extração (paralelizando `chat/find` + `message/find` paginados).

- **D7 (2026-05-17) — Execução em container separado já no dev/staging.**
  Por quê: alinha com produção desde o início; isola dependências Python do host; facilita CI futura.
  Como aplicar: `backend/Dockerfile` + `docker-compose.yml` na raiz subindo apenas o serviço `api`. Frontend continua via `npm run dev` no host (Vite não precisa container em dev). uazapi é externa, então **não há sidecar** para conteinerizar — apenas o FastAPI.

## Decisões obsoletas

- **~~Storage do auth state do Baileys (Supabase Storage)~~** — N/A: uazapi gerencia o auth state nos servidores deles (D1). Pergunta inicial perdeu sentido.

## Blockers

- **B1 (aberto) — Validação LGPD/DPA para tráfego via uazapi.**
  Antes de produção precisamos: (a) confirmar política de retenção da uazapi (quanto tempo eles guardam mensagens em seus servidores antes de descartar); (b) localização do data center (deve ser BR se possível); (c) ter DPA/contrato adequado já que dados sensíveis de saúde passam pela infra deles. Não bloqueia desenvolvimento local; bloqueia deploy público.

## Lições

_(serão preenchidas durante a execução)_

## Todos (cross-sessão)

- [x] ~~Confirmar modelo LLM default~~ → D2 ratificada (Anthropic Claude).
- [x] ~~Confirmar storage de sessão Baileys~~ → D1 trocou para uazapi, ponto obsoleto.
- [ ] **Benchmark de extração**: rodar smoke test com instância uazapi real (free ou paga) medindo tempo de extrair 30d para ~50 chats. Alvo da spec: ≤ 90s. Se não bater, paralelizar mais ou aceitar SLA maior.
- [ ] **Validar política LGPD/DPA da uazapi** (B1).
- [ ] **Migration Supabase**: criar `medzee_users_profile`, `medzee_reports`, `medzee_whatsapp_sessions` (com coluna `uazapi_token`).
- [ ] Mover `AGENT_ID` da Marina (ElevenLabs) de hardcode para `import.meta.env.VITE_ELEVENLABS_AGENT_ID` em `AgentScreen.jsx` (CONCERNS R8) — env já está pronto.

## Ideias adiadas

- Cache do relatório entre re-execuções no mesmo período (evita refazer LLM).
- Score de "saúde comercial" persistente para evolução temporal real (hoje mockado em `/app/dashboard`).
- Detectar pico de demanda fora do expediente e sugerir agente de IA (gancho de upsell).
- Comparativo entre atendentes (requer identificação por número/handle).
- Webhook global da uazapi (`/globalwebhook` admin) compartilhado entre todas as sessões — simplifica registro mas exige roteamento por `instance` no payload. Avaliar quando passar de 100 sessões simultâneas.

## Preferences

_(será preenchido quando o usuário sinalizar preferências de modelo, estilo de commit, etc.)_
