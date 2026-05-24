---
name: project-stack
description: Stack técnica e organização de pastas do medzee-spy
metadata:
  type: project
---

**Frontend** (`frontend/`):
- React 19.2 + Vite 8 + Tailwind 3.4 (cores customizadas em `tailwind.config.js` e duplicadas em `src/constants/colors.js`).
- Router: react-router-dom 7.
- Bibliotecas-chave: `@elevenlabs/react` (voice agent Marina), `qrcode.react`, `recharts` (charts dashboard), `lucide-react` (ícones).
- Fonte: Red Hat Display (Google Fonts).
- Estrutura: `screens/` (telas top-level), `screens/dashboard/` (área logada), `components/report/` (seções do relatório), `data/reportData.js` (dados mockados — só usado em `ReportScreen` público), `assets/` (audios + svgs), `lib/` (api, supabase, reports, whatsapp, me).
- Hooks-chave: `useWhatsappStatus` (snapshot DB + captured_messages stats), `useUazapiStats` (chat_count ao vivo via uazapi /chat/find), `useReportPolling` (polling /api/reports/:id), `useMe` (perfil autenticado), `useAnimatedCount` (interpolação 0→target com ease-out, em ReportGeneratingState).

**Backend** (`backend/`):
- FastAPI 0.115 + Python 3.12 + Supabase 2.9 + Anthropic SDK (Claude sonnet-4-6).
- Módulos implementados em `app/modules/`: `auth`, `whatsapp`, `captured_messages`, `reports`.
- Workers em `app/workers/`: `extract` (legacy F1 + F5 `pull_last_n_per_chat`), `report` (F3 pipeline), `ttl_cleanup` (background 24h).
- Endpoints vivos: `/api/auth/{signup,login,me}`, `/api/whatsapp/{sessions,sessions/:id/events,webhook,webhook/:id,status,uazapi-stats}`, `/api/reports/{,/:id,/latest,/generate}`.
- Deploy: Railway (Procfile + nixpacks); frontend `npm run dev` local apontando pra Railway via `VITE_API_BASE_URL`.

**WhatsApp / uazapi**:
- Provider: `naorpedroza.uazapi.com` (paid tier; admin token em env).
- Estratégia atual (F5): coleta via webhook `messages` → `captured_messages`; relatório usa `top_n_messages_per_chat(user_id, n)` RPC SQL (window function) pra pegar últimas N msgs de cada conversa, sem janela temporal. `pull_last_n_per_chat` no extract worker é fallback se captured local está vazio.
- **NUNCA** filtre histórico uazapi por `cutoff_ts` no paid tier — provider não devolve histórico antigo (vide [[feedback-uazapi-last-n-per-chat]]).

**Supabase / DB**:
- Schema `medzee_spy.*` no projeto News (`itghmlcipjloirsyhare`). Tabelas: `whatsapp_sessions`, `users_profile`, `reports`, `captured_messages`. Auth compartilhada via `auth.users`.
- RPC: `medzee_spy.top_n_messages_per_chat(user_uuid, n_per_chat int)` SECURITY INVOKER (migration `f5_1_top_n_messages_per_chat_rpc`).
- Gotchas (vide STATE.md L11/L12): PostgREST `upsert(on_conflict=...)` exige índice unique normal (partial não casa, 42P10); todo `.select()` tem default Range 0-999 — usa `count="exact"` quando precisar do total real.

**Rodar localmente**:
- Backend: `cd backend && cp .env.example .env && pip install -r requirements.txt && uvicorn app.main:app --reload`. Prefixo: `/api`.
- Frontend: `cd frontend && npm install && npm run dev`. Aponta pro backend via `VITE_API_BASE_URL`.

**Convenções de novo módulo**: criar `app/modules/<feature>/` com `routes.py`, `service.py`, `repository.py`, `schemas.py`; registrar no `api/router.py`.
