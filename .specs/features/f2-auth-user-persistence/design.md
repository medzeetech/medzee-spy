# F2 — Auth & User Persistence · Design

> Blueprint técnico que mapeia [spec.md](spec.md) para código. Cada seção alimenta uma ou mais tasks em `tasks.md`.

## 1. Visão geral

F2 adiciona **uma camada de identidade durável** sobre a fundação F1. Atalho mental:

```
   QR (F1)        Form (LeadFormScreen)       /app/* (autenticado)
     ↓                  ↓                              ↑
  uazapi          POST /api/auth/signup ──────────────┘
                  (Supabase Auth + users_profile +
                   consume_extracted F1 + delete_instance)

  Voltando dias depois:
  LoginScreen ──→ POST /api/auth/login ──→ /app/*
```

Backend: novo módulo `app/modules/auth/` com mesma estrutura dos outros (`routes.py`, `service.py`, `repository.py`, `schemas.py`). Reusa `app/core/security.py` pra extrair `current_user` de JWT.

Frontend: novo `LoginScreen.jsx`, rota `/login` no `App.jsx`, cliente `@supabase/supabase-js` em `src/lib/supabase.js`, e wire do `LeadFormScreen` que hoje só faz `onSubmit?.(payload)` mockado.

## 2. Arquivos a criar/alterar

### Backend
```
backend/app/
├── modules/auth/
│   ├── __init__.py             # marker
│   ├── routes.py               # APIRouter: signup, login, get_me, patch_me
│   ├── service.py              # AuthService (signup/login/get_me/update_me + rollback)
│   ├── repository.py           # CRUD users_profile (asyncio.to_thread)
│   └── schemas.py              # SignupRequest, LoginRequest, *Response, AppMetadata
├── core/
│   └── security.py             # ALTERAR — atualmente só decoda JWT; adicionar `get_current_user_id` helper
└── tests/auth/
    ├── __init__.py
    ├── conftest.py             # fixtures: fake_supabase_auth, fake_admin_supabase (reusar F1)
    ├── test_auth_routes.py     # endpoint tests (signup, login, me, patch_me)
    ├── test_auth_service.py    # business logic (rollback, app_metadata merge, project guard)
    └── test_auth_repository.py # supabase calls
```

Atualizações:
- `app/api/router.py` — incluir `auth_router` em `/auth`
- `app/clients/whatsapp/...` — sem mudanças (F1 já está completo)
- `app/modules/whatsapp/service.py::consume_extracted` — sem mudanças, já recebe `(session_id, user_id)`

### Frontend
```
frontend/src/
├── lib/
│   ├── supabase.js             # singleton createClient com VITE_SUPABASE_*
│   └── api.js                  # helper httpClient (Authorization header se logado)
├── screens/
│   ├── LoginScreen.jsx         # form email+password
│   └── LeadFormScreen.jsx      # ALTERAR — onSubmit chama API real, propaga state error
└── App.jsx                     # ALTERAR — rota /login, MainFlow passa whatsappSessionId
```

### Migration
```
SQL via mcp__supabase__apply_migration name="f2_1_users_profile"
```

## 3. Migration SQL

```sql
-- f2_1_users_profile
-- F2 §AUTH-07/08: perfil do médico, linkado a auth.users por PK, RLS owner-only.
create table if not exists medzee_spy.users_profile (
  user_id          uuid primary key references auth.users(id) on delete cascade,
  name             text not null,
  email            text not null,
  phone            text not null,
  ticket_medio     numeric,
  clinic_segment   text,                       -- F3 preenche depois ('saude'|'odonto'|'outro')
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create index users_profile_email_idx
  on medzee_spy.users_profile (email);

-- RLS — só dono lê/atualiza o próprio perfil.
alter table medzee_spy.users_profile enable row level security;

create policy "profile_owner_select"
  on medzee_spy.users_profile
  for select to authenticated
  using (auth.uid() = user_id);

create policy "profile_owner_update"
  on medzee_spy.users_profile
  for update to authenticated
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- Service role precisa criar (pré-JWT, durante signup) — INSERT bypassa RLS.
grant select, insert, update on medzee_spy.users_profile
  to authenticated, service_role;

-- updated_at via trigger (reusa a function de medzee_spy)
drop trigger if exists trg_users_profile_set_updated_at on medzee_spy.users_profile;
create trigger trg_users_profile_set_updated_at
  before update on medzee_spy.users_profile
  for each row execute function medzee_spy.set_updated_at();

comment on table medzee_spy.users_profile is
  'Profile of clinic owners signed up via Medzee Spy. user_id == auth.users.id; one-to-one.';
```

## 4. Pydantic schemas (`app/modules/auth/schemas.py`)

```python
from __future__ import annotations
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field, field_validator


# ─── Requests ───────────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str = Field(min_length=10, max_length=20)          # digits + symbols ok; service strips
    password: str = Field(min_length=6, max_length=128)
    ticket_medio: float | None = Field(default=None, ge=0)
    whatsapp_session_id: UUID | None = None                    # None se /spy não foi feito

    @field_validator("name", "phone")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)        # validação fraca: deixa Supabase julgar


class UpdateMeRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = Field(default=None, min_length=10, max_length=20)
    ticket_medio: float | None = Field(default=None, ge=0)
    clinic_segment: Literal["saude", "odonto", "outro"] | None = None


# ─── Responses ──────────────────────────────────────────────────────────

class SessionPayload(BaseModel):
    """Envelopa os tokens do Supabase que o frontend usa em setSession."""
    access_token: str
    refresh_token: str
    expires_in: int                                            # segundos
    token_type: Literal["bearer"] = "bearer"


class UserPayload(BaseModel):
    id: UUID
    email: EmailStr


class SignupResponse(BaseModel):
    user: UserPayload
    session: SessionPayload
    report_pending: bool = False                                # True se whatsapp_session_id linkou ok
    session_warning: str | None = None                          # "whatsapp_session_unavailable" etc


class LoginResponse(BaseModel):
    user: UserPayload
    session: SessionPayload


class MeResponse(BaseModel):
    user_id: UUID
    name: str
    email: EmailStr
    phone: str
    ticket_medio: float | None
    clinic_segment: str | None
```

## 5. Repository (`app/modules/auth/repository.py`)

Mesma forma do F1 (`asyncio.to_thread` envolvendo supabase-py síncrono, log estruturado sem secrets):

```python
async def create_profile(
    user_id: UUID, *, name: str, email: str, phone: str,
    ticket_medio: float | None,
) -> None: ...

async def get_profile(user_id: UUID) -> dict | None: ...

async def update_profile(user_id: UUID, **fields: Any) -> None: ...

async def delete_profile(user_id: UUID) -> None:
    # usado no rollback se auth.users.delete falhar — pouco provável mas defensivo
    ...
```

Logs: `repo.auth.create_profile`, `repo.auth.get_profile`, etc. Email é PII parcial — logamos só `email_domain` (parte após `@`).

## 6. Service (`app/modules/auth/service.py`)

```python
class AuthService:
    def __init__(self, supabase: Client | None = None) -> None:
        self._supabase = supabase or get_supabase_admin_client()

    # ─── Signup ─────────────────────────────────────────────────────────

    async def signup(self, req: SignupRequest) -> SignupResponse:
        """
        Sequence (AUTH-01..AUTH-10):
        1. Normalize email (strip + lower).
        2. supabase.auth.admin.create_user(email, password, email_confirm=true)
           — admin path evita verification email; user já entra "confirmed".
        3. Set app_metadata.projects = merge(existing, ['spy']).
        4. repository.create_profile(user_id, ...).  ── rollback se falhar (delete auth user)
        5. If whatsapp_session_id: try service.whatsapp.consume_extracted.
           ── log warning + session_warning se falhar; não bloqueia.
        6. Sign in to get session tokens (supabase.auth.sign_in_with_password).
           ── alternativa: admin generate_link 'magiclink' e parse… mais complexo.
           Sign-in com a senha que acabamos de setar é determinístico.
        7. Return SignupResponse(user, session, report_pending, session_warning).
        """

    # ─── Login ──────────────────────────────────────────────────────────

    async def login(self, req: LoginRequest) -> LoginResponse:
        """
        Sequence (AUTH-11..AUTH-13):
        1. supabase.auth.sign_in_with_password(email, password).
        2. Catch AuthError 'invalid credentials' → raise InvalidCredentials.
        3. Check user.app_metadata.projects contains 'spy';
           senão → raise UserNotInSpy (403).
        4. Return LoginResponse(user, session).
        """

    # ─── Me ─────────────────────────────────────────────────────────────

    async def get_me(self, user_id: UUID) -> MeResponse:
        profile = await repository.get_profile(user_id)
        if profile is None:
            raise ProfileNotFound(str(user_id))
        return MeResponse(**profile)

    async def update_me(self, user_id: UUID, req: UpdateMeRequest) -> MeResponse:
        fields = req.model_dump(exclude_none=True)
        if not fields:
            return await self.get_me(user_id)
        await repository.update_profile(user_id, **fields)
        return await self.get_me(user_id)
```

**Exceções locais:**

```python
class AuthError(Exception): ...
class EmailAlreadyRegistered(AuthError): ...
class InvalidCredentials(AuthError): ...
class UserNotInSpy(AuthError): ...
class ProfileNotFound(AuthError): ...
class SupabaseAuthError(AuthError): ...    # genérico p/ erros não classificados
```

**App-metadata merge** (AUTH-10):
```python
def _merge_projects(existing: dict | None, new: str) -> dict:
    md = dict(existing or {})
    projects = list(md.get("projects", []))
    if new not in projects:
        projects.append(new)
    md["projects"] = projects
    return md
```

**Rollback (AUTH-09):**
```python
try:
    auth_user = supabase.auth.admin.create_user(...)
    try:
        await repository.create_profile(auth_user.id, ...)
    except Exception:
        # melhor esforço — registramos e tentamos limpar.
        try:
            supabase.auth.admin.delete_user(auth_user.id)
        except Exception:
            logger.exception("rollback failed; orphan auth user", extra={...})
        raise ProfileCreationFailed(...)
```

**Bridge para F1:** signup chama `service.consume_extracted` se `whatsapp_session_id` for fornecido. Como evitamos circular import, usamos a factory já existente: `from app.modules.whatsapp.service import get_service as get_whatsapp_service`. Lazy import dentro da função.

## 7. Routes (`app/modules/auth/routes.py`)

```python
router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/signup", response_model=SuccessResponse[SignupResponse])
async def signup(
    req: SignupRequest,
    service: AuthService = Depends(get_auth_service),
) -> SuccessResponse[SignupResponse]:
    try:
        result = await service.signup(req)
    except EmailAlreadyRegistered:
        raise HTTPException(409, detail="email_already_registered")
    except ProfileCreationFailed:
        raise HTTPException(500, detail="profile_creation_failed")
    except SupabaseAuthError as exc:
        raise HTTPException(400, detail=str(exc))
    return SuccessResponse(data=result)

@router.post("/login", response_model=SuccessResponse[LoginResponse])
async def login(...) -> SuccessResponse[LoginResponse]:
    # 401 invalid_credentials, 403 user_not_in_spy, 400 fallback

@router.get("/me", response_model=SuccessResponse[MeResponse])
async def get_me(
    user_id: UUID = Depends(get_current_user_id),
    service: AuthService = Depends(get_auth_service),
) -> SuccessResponse[MeResponse]:
    return SuccessResponse(data=await service.get_me(user_id))

@router.patch("/me", response_model=SuccessResponse[MeResponse])
async def patch_me(...): ...
```

**`get_current_user_id`** vive em `app/core/security.py` — extrai o JWT via `HTTPBearer`, valida com Supabase (`supabase.auth.get_user(token)`), retorna o UUID. Cache em memória de 30s por token pra evitar round-trip a cada call (opcional, mas barato).

## 8. Frontend — `src/lib/supabase.js`

```javascript
import { createClient } from '@supabase/supabase-js';

const url = import.meta.env.VITE_SUPABASE_URL;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

if (!url || !anonKey) {
  console.warn('[supabase] VITE_SUPABASE_* missing — auth will fail.');
}

export const supabase = createClient(url, anonKey, {
  auth: {
    persistSession: true,           // localStorage (default)
    autoRefreshToken: true,         // refresh em background
    detectSessionInUrl: false,      // sem OAuth callback em M1
  },
});
```

E `src/lib/api.js`:

```javascript
const BASE = import.meta.env.VITE_API_BASE_URL;

async function callApi(path, { method = 'GET', body, auth = false, signal } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (auth) {
    const { data } = await supabase.auth.getSession();
    if (data.session?.access_token) {
      headers.Authorization = `Bearer ${data.session.access_token}`;
    }
  }
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
    signal,
  });
  const text = await res.text();
  const json = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const err = new Error(json?.detail || `HTTP ${res.status}`);
    err.status = res.status;
    err.detail = json?.detail;
    err.body = json;
    throw err;
  }
  return json?.data ?? json;
}

export const api = {
  signup: (payload) => callApi('/api/auth/signup', { method: 'POST', body: payload }),
  login: (payload) => callApi('/api/auth/login', { method: 'POST', body: payload }),
  me: () => callApi('/api/auth/me', { auth: true }),
};
```

## 9. Frontend — `src/screens/LoginScreen.jsx`

Reusa o estilo visual do `LeadFormScreen.jsx` (dark + orange + corners):

```jsx
export default function LoginScreen() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();      // p/ ?email= pre-fill
  const [email, setEmail] = useState(searchParams.get('email') ?? '');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const { user, session } = await api.login({ email: email.trim().toLowerCase(), password });
      await supabase.auth.setSession({
        access_token: session.access_token,
        refresh_token: session.refresh_token,
      });
      navigate('/app/reports');
    } catch (e) {
      if (e.status === 401) setError('Email ou senha incorretos.');
      else if (e.status === 403) setError('Sua conta ainda não tem acesso ao Spy. Faça o diagnóstico em /spy.');
      else setError('Não foi possível entrar. Tente novamente em instantes.');
    } finally {
      setSubmitting(false);
    }
  };

  return (/* dark-themed form similar to LeadFormScreen */);
}
```

## 10. `App.jsx` — wire-up

```jsx
function MainFlow() {
  const [phase, setPhase] = useState('agent');
  const [whatsappSessionId, setWhatsappSessionId] = useState(null);
  ...
  return phase === 'qr' ? (
    <QRScreen
      onSimulate={goGenerating}
      onSessionCreated={setWhatsappSessionId}        // NEW
    />
  ) : phase === 'lead' ? (
    <LeadFormScreen
      onSubmit={...}
      whatsappSessionId={whatsappSessionId}         // NEW prop
    />
  ) : ...
}

// Routes additions:
<Route path="/login" element={<LoginScreen />} />
```

`LeadFormScreen.jsx` deixa de chamar `onSubmit?.(payload)` mockado e passa a:

```javascript
const handleSubmit = async (e) => {
  e.preventDefault();
  setSubmitting(true);
  try {
    const result = await api.signup({
      name, email: email.toLowerCase(), phone, password,
      ticket_medio: ticketMedio ? parseFloat(ticketMedio) : null,
      whatsapp_session_id: whatsappSessionId,
    });
    await supabase.auth.setSession({
      access_token: result.session.access_token,
      refresh_token: result.session.refresh_token,
    });
    navigate('/app/reports/latest');
  } catch (e) {
    if (e.status === 409) {
      navigate(`/login?email=${encodeURIComponent(email)}`);   // AUTH-15
    } else if (e.status === 422) {
      setFieldErrors(e.body?.errors ?? {});
    } else {
      setError('Falha ao criar conta. Tente novamente.');
    }
  } finally {
    setSubmitting(false);
  }
};
```

## 11. Mapping de erros — auth

| Camada / Origem | Excessão / status | Detail | HTTP |
|---|---|---|---|
| Supabase: email duplicado | `gotrue.AuthApiError("User already registered")` | `email_already_registered` | 409 |
| Supabase: senha fraca | `AuthApiError("password is too weak")` | `password_too_weak` | 400 |
| Supabase: outros | qualquer outro `AuthApiError` | str(exc) | 400 |
| `repository.create_profile` falha | `ProfileCreationFailed` | `profile_creation_failed` | 500 |
| Login: invalid credentials | `AuthApiError("Invalid login credentials")` | `invalid_credentials` | 401 |
| Login: user sem projects['spy'] | `UserNotInSpy` | `user_not_in_spy` | 403 |
| `get_me`: perfil ausente | `ProfileNotFound` | `profile_not_found` | 404 |
| Falta JWT / inválido | (em security.py) | `not_authenticated` | 401 |

## 12. Estratégia de testes

```
backend/app/tests/auth/
├── conftest.py
├── test_auth_repository.py
├── test_auth_service.py
└── test_auth_routes.py
```

**Fixtures:**
- `fake_supabase_admin` — `MagicMock(spec=Client)` com `auth.admin.create_user`, `auth.admin.delete_user`, `auth.admin.update_user_by_id`, `auth.sign_in_with_password`. Cada retorna estruturas semelhantes ao gotrue real.
- `fake_repository` — monkeypatch `app.modules.auth.repository` calls.
- `fake_whatsapp_service` — monkeypatch `consume_extracted` (sucesso, falha, sessão ausente).

**Casos prioritários:**

| Arquivo | Caso | Verifica |
|---|---|---|
| `test_auth_service.py` | signup happy path | cria user → app_metadata merge → profile → consume_extracted → retorna session |
| | signup email duplicado | raise EmailAlreadyRegistered → 409 no route |
| | signup whatsapp_session expirada | `report_pending=False`, `session_warning="whatsapp_session_unavailable"` |
| | signup profile create falha | delete_user é chamado (rollback) + raise ProfileCreationFailed |
| | signup app_metadata merge existente | projects: ['news'] → ['news','spy'] (sem duplicar) |
| | login happy | retorna user + session |
| | login invalid_credentials | 401 indistinto pra email errado E senha errada |
| | login user sem 'spy' | 403 user_not_in_spy |
| | get_me autenticado | retorna perfil |
| | get_me sem perfil | ProfileNotFound |
| `test_auth_routes.py` | POST /signup happy | 200 envelope SuccessResponse |
| | POST /signup body inválido | 422 com errors |
| | POST /signup 409 | mapped corretamente |
| | POST /login happy | 200 envelope |
| | POST /login 401 / 403 | mapped corretamente |
| | GET /me com JWT válido | 200 |
| | GET /me sem token | 401 not_authenticated |
| | PATCH /me partial | atualiza só campos enviados |
| `test_auth_repository.py` | create_profile insert | dict correto, retorna None |
| | get_profile com row | retorna dict |
| | get_profile sem row | retorna None |
| | update_profile parcial | só campos passados no UPDATE |

Total alvo: ~25 testes novos. Suite agregada ≥ 80 verde.

## 13. Wiring de segurança (`app/core/security.py`)

Atualmente existe `get_current_user` que valida JWT contra Supabase. Adicionar helper menor:

```python
async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> UUID:
    user = await get_current_user(credentials)
    return UUID(user.id)
```

Manter `get_current_user` pra quem precisa do objeto completo (poucos casos). Cache opcional de 30s pra reduzir round-trip ao Supabase em endpoints com muitas chamadas autenticadas (não prioritário em M1).

## 14. Bridge com F1 sem circular import

`AuthService.signup` precisa chamar `consume_extracted` do F1, mas `app.modules.whatsapp.service` importa `app.modules.whatsapp.state` (que importa `mask`), etc. Pra evitar grafo cíclico futuro, fazemos lazy import:

```python
async def _maybe_consume_whatsapp_session(
    self, session_id: UUID | None, user_id: UUID
) -> tuple[bool, str | None]:
    """Returns (report_pending, session_warning)."""
    if session_id is None:
        return (False, None)
    from app.modules.whatsapp.service import get_service as get_whatsapp_service
    try:
        wpp = get_whatsapp_service()
        payload = await wpp.consume_extracted(session_id, user_id)
        return (payload is not None, None)
    except Exception:
        logger.warning(
            "auth.signup.consume_whatsapp_failed",
            extra={"session_id": str(session_id), "user_id": str(user_id)},
            exc_info=True,
        )
        return (False, "whatsapp_session_unavailable")
```

## 15. Observações abertas

1. **Email confirmation no Supabase Auth** — confirmamos com o user que está **desligado**. Se um dia ligarmos, o admin `create_user(email_confirm=True)` ainda funciona porque o admin path bypassa o flow do user. Pra signup direto, é nosso caminho.
2. **Auto-login via admin** — usamos `auth.admin.create_user` + `auth.sign_in_with_password` pra obter session tokens. Alternativa: `auth.admin.generate_link("signup")` + parsing manual — mais complexo e dependente de SMTP. Manter o sign-in deliberado.
3. **Refresh tokens em SSE** — o EventSource do navegador não permite atualizar header `Authorization` em meio de stream. Em M1 isso é OK porque o SSE da F1 é anônimo (pré-signup). Endpoints autenticados são REST normais. Não há SSE pós-login em M1.
4. **Rate limit** — Supabase Auth tem rate limit nativo (~5 logins/min por IP). Não vamos implementar nosso por cima em M1. Logamos 429 do upstream se vier.
5. **Logout** — Supabase-js cuida via `supabase.auth.signOut()`. Backend não precisa de endpoint próprio.

## 16. Pontes para próximas features

- **F3 (Report Processing)** consome o `ExtractedPayload` que `consume_extracted` retornou no signup. F2 não persiste o payload em DB — guarda em memória até F3 entrar. F3 vai criar `medzee_spy.reports` (a definir lá).
- **F4 (Frontend Integration)** estende: route guards em `/app/*` (require auth via `supabase.auth.getSession()`), logout button, dashboard real consumindo `/api/auth/me`.
