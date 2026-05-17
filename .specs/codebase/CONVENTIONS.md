# Convenções observadas

## Frontend

### Estilo de componentes
- Componentes funcionais com hooks; default export por arquivo.
- **Inline styles dominantes** com referência a `COLORS.*` (de `src/constants/colors.js`). Classes Tailwind aparecem para layout (`flex`, `grid`, breakpoints `sm:` `md:` `lg:`).
- Sem CSS modules nem styled-components; o `index.css` só carrega Tailwind e keyframes globais (`anim-fadeup`, `anim-spin`, `anim-pulse-dot`, `anim-scan`, `anim-rotate-slow`).
- Fonte hardcoded `'Red Hat Display', sans-serif` em vários blocos — aceitável, mas viraria token se crescer.

### Nomes
- Arquivos `.jsx` em `PascalCase` para componentes/telas.
- Helpers locais (`maskPhone`, `formatBRL`, `heatStyle`) ficam no topo do arquivo que os usa.
- Hooks/callbacks com `useCallback`/`useMemo` quando passados para SDK externo (ex.: ElevenLabs).

### Dados mockados
- TODO dado fictício do relatório vive em `src/data/reportData.js` (FUNNEL, OBJECTIONS, FAQS, SENTIMENT, OPPORTUNITIES, BENCHMARKS, GEN_STEPS, SIDEBAR_LINKS, HEATMAP_*).
- Trocar mocks por API real significa importar de um `src/api/reports.js` (a criar) e manter a forma do payload retro-compatível.

### Roteamento
- `BrowserRouter` único em `App.jsx`.
- Fluxo público (`/`, `/spy`) usa state interno (`useState`) para transições entre telas.
- Área autenticada (`/app/*`) usa `Outlet` + `NavLink`.

## Backend

### Estrutura modular (a aplicar — hoje só boilerplate)
Cada feature em `app/modules/<feature>/`:
- `routes.py` exporta um `APIRouter` chamado `router`.
- `service.py` contém regra de negócio; recebe deps por argumento (não importa singletons).
- `repository.py` isola SQL/Supabase.
- `schemas.py` define os pydantic models.

### Envelopes de resposta
- Sucesso: `SuccessResponse[T]` com `data: T` e `message: str = "ok"`.
- Erro: `ErrorResponse` (`detail: str`, `errors: list | None`).
- Paginação: `PaginatedResponse[T]` (`data`, `total`, `page`, `page_size`).
- Endpoints devem **anotar** `response_model=SuccessResponse[X]` para gerar OpenAPI correto.

### Autenticação
- `Depends(get_current_user)` (em `app/core/security.py`) extrai o user do header `Authorization: Bearer <jwt>` e chama `supabase.auth.get_user`.
- Endpoints públicos (signup, healthcheck) não dependem dele.

### Clients
- `get_supabase_client()` é um singleton lazy (anon key) — uso geral leitura/escrita com RLS aplicada.
- `get_supabase_admin_client()` retorna nova instância com `SERVICE_ROLE_KEY` — usar com cuidado para bypassar RLS em endpoints de signup/relatório.

### Config
- `Settings` em `app/core/config.py` lê de `.env`. Novas variáveis adicionar lá com default seguro.
- `case_sensitive = True` — usar SCREAMING_SNAKE_CASE.

## Git
- Mensagens recentes seguem padrão "emoji shortcode + verbo + descrição":
  - `:sparkles: add: /spy e user logged`
  - `:sparkles: add: base structure`
- Manter convenção: `:sparkles: add:` para feature nova, `:bug: fix:` para bug, `:hammer: refactor:` para refactor, etc. (Gitmoji).

## Convenções de naming para novas tabelas Supabase
- Prefixo `medzee_` (decisão D3 em STATE.md).
- snake_case.
- Tipo `uuid` para PKs; `gen_random_uuid()` como default.
- Timestamps `created_at` / `updated_at` em `timestamptz default now()`.
