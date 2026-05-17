# Stack

## Backend (`backend/`)
- **Runtime:** Python 3.12
- **Framework:** FastAPI 0.115.0 + Uvicorn 0.30.6 (`[standard]`)
- **Config:** pydantic-settings 2.5.2 (`Settings` em `app/core/config.py`)
- **HTTP client:** httpx 0.27.2
- **Auth/DB:** supabase 2.9.1 (clients `get_supabase_client` e `get_supabase_admin_client` em `app/clients/supabase.py`)
- **Tests:** pytest 8.3.3 (apenas conftest com fixture `client`; nenhum teste real)

## Frontend (`frontend/`)
- **Runtime / build:** Node + Vite 8.0.12 + `@vitejs/plugin-react` 6
- **Framework:** React 19.2.6 + React DOM 19.2.6
- **Roteamento:** react-router-dom 7.15.1
- **Styling:** Tailwind 3.4.19 + PostCSS 8.5.14 + autoprefixer 10.5
- **Charts:** recharts 3.8.1
- **Icons:** lucide-react 1.16
- **QR:** qrcode.react 4.2
- **Voice agent:** @elevenlabs/react 1.6 (agente "Marina" id `agent_8601krmch56bfbbv5wjya2jw0y3x`)
- **Lint:** eslint 10.3 + plugins React Hooks/Refresh

## Variáveis de ambiente (existentes em `backend/.env.example`)
- `SUPABASE_URL`
- `SUPABASE_KEY` (anon)
- `SUPABASE_SERVICE_ROLE_KEY`
- `DEBUG`
- `ALLOWED_ORIGINS` (lista JSON)

## A adicionar
- `LLM_PROVIDER` (`anthropic` | `openai`)
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`
- `WHATSAPP_SIDECAR_URL` (ex.: `http://localhost:3001`)
- `WHATSAPP_SIDECAR_TOKEN` (auth básica do sidecar)
- No sidecar Node: porta + diretório de sessões.

## Versionamento e tooling
- Git já versionado (branch `main`, 3 commits).
- `package-lock.json` na raiz (provavelmente artefato — ver CONCERNS).
- `frontend/package-lock.json` válido.
- Não há lockfile para o backend além de `requirements.txt`.
