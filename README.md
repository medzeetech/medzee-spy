# Medzee Spy

> Diagnóstico comercial automatizado para clínicas: o usuário conecta o WhatsApp via QR Code, o sistema lê as conversas, e a IA devolve um relatório com funil de conversão, tempo de resposta, oportunidades perdidas e benchmark do setor.

**Status:** M1 funcional ponta-a-ponta (smoke 2026-05-19). Branch ativa: `feat/f4-forward-capture`.

---

## Stack

| Camada | Tecnologia |
|---|---|
| Frontend | React 19 + Vite 8 + Tailwind 3 + react-router 7 |
| Backend | FastAPI 0.115 + Python 3.12 |
| Auth + DB | Supabase (schema `medzee_spy.*` no projeto compartilhado) |
| WhatsApp | uazapi.com (REST + webhook) |
| LLM | Anthropic Claude (sonnet 4.6) — provider-agnostic |
| Deploy backend | Railway (Procfile + nixpacks) |
| Voice agent | ElevenLabs (Marina) |

---

## Setup local (primeira vez)

### Pré-requisitos

- **Python 3.12** (`pyenv install 3.12.13` recomendado)
- **Node.js 20+** (`nvm install 20`)
- **Conta Supabase** com schema `medzee_spy` aplicado (ver `Migrações` abaixo)
- **Conta uazapi** (admin token) — paid recomendado, free tem limites severos
- **Anthropic API key** (Claude)
- **ElevenLabs agent ID** (opcional pro frontend público)

### 1. Clone + configure env vars

```bash
git clone https://github.com/medzeetech/medzee-spy.git
cd medzee-spy

# Backend
cp backend/.env.example backend/.env
# Edite backend/.env com:
#   SUPABASE_URL, SUPABASE_KEY, SUPABASE_SERVICE_ROLE_KEY
#   UAZAPI_BASE_URL, UAZAPI_ADMIN_TOKEN
#   ANTHROPIC_API_KEY

# Frontend
cp frontend/.env.example frontend/.env
# Edite frontend/.env com:
#   VITE_API_BASE_URL=http://localhost:8000
#   VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY
#   VITE_ELEVENLABS_AGENT_ID
```

### 2. Backend (FastAPI)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload      # → http://localhost:8000
```

Health check: `curl http://localhost:8000/api/health` → `{"status":"ok"}`.

### 3. Frontend (Vite)

Em outro terminal:

```bash
cd frontend
npm install
npm run dev                        # → http://localhost:5173
```

### 4. (Opcional) Subir os dois em paralelo

Da raiz do repo:

```bash
npm install                        # instala concurrently (1 dep)
npm run dev                        # sobe backend + frontend simultâneos
```

---

## Migrações Supabase

Todas as migrations vivem em `supabase/migrations` (gerenciadas via Supabase MCP / Dashboard SQL). Ordem aplicada hoje em prod:

```
f1_1_medzee_schema_and_whatsapp_sessions
f1_2_harden_set_updated_at_search_path
f1_3_rename_schema_to_medzee_spy
f1_4_recreate_medzee_spy_with_full_grants
f1_5_recreate_empty_medzee_to_unblock_pgrst
f2_1_users_profile
f3_1_reports
f4_1_captured_messages
f5_1_top_n_messages_per_chat_rpc    # window function pra last-N por chat
```

Pra aplicar em ambiente novo: rode na ordem, em SQL Editor do Supabase Dashboard ou via `supabase db push` se usar CLI.

---

## Estrutura do projeto

```
medzee-spy/
├── backend/                       # FastAPI
│   ├── app/
│   │   ├── main.py                # entrypoint, lifespan, CORS, middleware
│   │   ├── api/router.py          # aggregator (/api/*)
│   │   ├── core/                  # config (pydantic-settings), security (JWT)
│   │   ├── clients/               # supabase, llm, whatsapp (uazapi adapter)
│   │   ├── contracts/             # SuccessResponse, ErrorResponse
│   │   ├── modules/
│   │   │   ├── auth/              # signup, login, me (Supabase Auth)
│   │   │   ├── whatsapp/          # sessions, SSE, webhook handler
│   │   │   ├── captured_messages/ # webhook persistence + queries
│   │   │   └── reports/           # CRUD + on-demand generate + LLM prompts
│   │   ├── workers/               # extract, report, ttl_cleanup
│   │   └── tests/                 # pytest suite
│   ├── Procfile                   # Railway entrypoint
│   ├── requirements.txt
│   └── runtime.txt                # python-3.12
│
├── frontend/                      # Vite + React
│   ├── src/
│   │   ├── App.jsx                # router
│   │   ├── screens/               # AgentScreen, QRScreen, GeneratingScreen, …
│   │   ├── screens/dashboard/     # área logada (/app/*)
│   │   ├── components/report/     # seções do relatório
│   │   ├── constants/             # COLORS, etc
│   │   ├── data/                  # reportData.js (mocks só pra /spy demo)
│   │   └── lib/                   # api, supabase, reports, whatsapp, me
│   ├── public/
│   ├── vite.config.js
│   └── tailwind.config.js
│
├── .specs/                        # spec/design/tasks por feature
│   ├── project/                   # PROJECT, ROADMAP, STATE, AUDITs
│   └── features/                  # f1.. f5 (cada com spec.md, design.md, tasks.md)
│
├── memory/                        # memória persistente entre sessões Claude
│   ├── MEMORY.md                  # índice
│   └── feedback_*, project_*      # entradas
│
├── package.json                   # script `dev` raiz (orquestrador)
└── README.md
```

---

## Fluxos principais

### Público (lead novo)
1. `/` (AgentScreen) — voice agent Marina apresenta o produto
2. → `/spy` (QRScreen) — gera QR via uazapi, frontend escuta SSE
3. → `GeneratingScreen` (placeholder visual ~6s)
4. → `LeadFormScreen` — cadastra (nome, email, senha, ticket médio)
5. → backend cria user via Supabase Auth + perfil em `users_profile`
6. → `/app/reports/latest` (logado automaticamente)

### Logado (`/app/*`)
- `/app/dashboard` — métricas agregadas + LiveStatsRow (conversas/msgs reais)
- `/app/reports` — lista paginada de relatórios + botão "Gerar agora"
- `/app/reports/:id` — relatório completo com 9 seções
- `/app/whatsapp` — status da conexão + reconectar/desconectar
- `/app/connect` — fluxo de reconexão pra user já autenticado

### Geração de relatório (F5)
- User clica "Gerar agora" no modal → escolhe 10/20/30/50 msgs por conversa
- `POST /api/reports/generate` cria row `generating` e dispara worker async
- Service tenta `query_last_n_per_chat` (local, via RPC `top_n_messages_per_chat`)
- Se vazio, fallback `pull_last_n_per_chat` no uazapi
- Worker computa métricas determinísticas + sampling + chama Claude
- Persiste payload + score
- Frontend (poll 5s) detecta `status='completed'` e renderiza

---

## Comandos úteis

```bash
# Backend
cd backend
pytest                                  # roda suite (~250 testes)
pytest app/tests/whatsapp/ -v           # módulo específico
uvicorn app.main:app --reload --log-level debug

# Frontend
cd frontend
npm run dev                             # vite dev server
npm run build                           # bundle production
npm run lint                            # eslint
npm run preview                         # serve bundle local

# Raiz
npm run dev                             # backend + frontend em paralelo
```

---

## Deploy

### Backend (Railway)
- Auto-deploy ativo na branch `feat/f4-forward-capture`
- `Procfile`: `web: uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Runtime: nixpacks detecta Python 3.12 via `runtime.txt`
- Env vars: configurar no Railway Dashboard → Settings → Variables (mesma lista do `backend/.env.example`)
- **Cuidado** (vide STATE.md L5): Railway env vars com aspas literais quebram silenciosamente. Usar Raw Editor ou colar sem aspas.

### Frontend
- Não há deploy automático configurado ainda
- Build local: `npm run build` gera `dist/` pronto pra qualquer static host (Vercel, Netlify, Cloudflare Pages)

---

## Onde olhar quando algo quebra

| Sintoma | Onde investigar |
|---|---|
| Webhook não chega no backend | Railway logs filtrando por `route.webhook.enter`; `/webhook/errors` no uazapi |
| Relatório nunca termina | `worker.report.*` no log; conferir `error_code` em `medzee_spy.reports` |
| Captured_messages vazia | Conferir `repo.captured.insert_many` no log; se aparecer `42P10`, é regressão do fix Bug 1 |
| QR não aparece | `/instance/connect` no log da uazapi; possível 401 (token rotacionado) |
| Token uazapi morre | Provider deletou a instância — ver `_fail` em `extract.py` não pode chamar `delete_instance` exceto em `code='banned'` (L14) |

---

## Documentação detalhada

- **`.specs/project/PROJECT.md`** — visão, escopo, constraints
- **`.specs/project/ROADMAP.md`** — status por feature + commits-chave
- **`.specs/project/STATE.md`** — decisões (D1..D10), blockers (B1..B3), lições (L1..L14), todos cross-sessão
- **`.specs/features/<feature>/`** — spec.md, design.md, tasks.md por feature
- **`.specs/project/AUDIT_2026-05-18.md`** + **`ENDPOINT_AUDIT_2026-05-18.md`** — auditoria honesta uazapi
- **`memory/`** — feedback explicitamente salvo pelo Claude (lições recorrentes)

---

## Contato

Repositório privado da Medzee. Issues e PRs no GitHub `medzeetech/medzee-spy`.
