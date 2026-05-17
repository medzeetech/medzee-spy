# F3 — Report Processing · Design

> Blueprint técnico que mapeia [spec.md](spec.md) para código. Cada seção alimenta uma ou mais tasks em `tasks.md`.

## 1. Visão geral

F3 fecha o circuito: F1 entrega mensagens, F2 entrega identidade, F3 entrega **diagnóstico comercial**. Atalho mental:

```
  F1 extract worker termina             F3 report worker (NOVO)
  → ExtractedPayload em memória  ───→   1. Cria reports row (status=generating)
                                        2. Computa métricas determinísticas
                                        3. Sampling de conversas
                                        4. Chama Claude com prompt segmentado
                                        5. Valida JSON, compõe payload final
                                        6. UPDATE reports (status=completed)

  F2 signup termina         /app/reports/latest (poll 2s)
  → consume_extracted  ───→ ReportGeneratingState (msgs rotativas)
    → link report.user_id   ───→ status=completed → render relatório real
```

Dois pontos de integração:
- **F1→F3:** o extract worker, ao terminar (`_finalize_success` e `_finalize_partial`), passa a também chamar `generate_report_pipeline(session_id, payload)` fire-and-forget.
- **F2→F3:** `whatsapp.service.consume_extracted` adiciona um `reports_repository.link_user(session_id, user_id)` que faz UPDATE no row já criado pelo worker (no-op log se ainda não existir).

E o **B3 fix** vive dentro de F3 porque sem ele o pipeline real não roda no free tier.

## 2. Arquivos a criar/alterar

### Backend

```
backend/app/
├── clients/
│   └── llm.py                            # NOVO — protocol + adapter Anthropic
├── modules/reports/                      # NOVO módulo inteiro
│   ├── __init__.py
│   ├── schemas.py                        # ReportPayload + sub-models, Status enum
│   ├── repository.py                     # CRUD reports
│   ├── service.py                        # ReportService (get_latest, get_by_id, list_for_user)
│   ├── routes.py                         # /api/reports/{latest,id,/} (autenticados)
│   ├── metrics.py                        # NOVO — funções puras determinísticas
│   ├── sampling.py                       # NOVO — top-N + stratified random
│   ├── benchmarks.py                     # NOVO — hardcoded por clinic_segment
│   └── prompts/
│       ├── __init__.py
│       ├── base.py                       # system prompt comum
│       ├── saude.py                      # variante 'saude'
│       ├── odonto.py                     # variante 'odonto'
│       └── outro.py                      # fallback genérico
├── workers/
│   ├── extract.py                        # ALTERAR — B3 fix (delay + retry) + trigger F3
│   └── report.py                         # NOVO — generate_report_pipeline
├── clients/whatsapp/
│   └── uazapi.py                         # ALTERAR — retry 5xx no list_chats/list_messages
├── modules/whatsapp/
│   └── service.py                        # ALTERAR — consume_extracted chama reports.link_user
└── api/router.py                         # ALTERAR — inclui reports_router em /reports

backend/app/tests/reports/                # NOVO
├── __init__.py
├── conftest.py                           # fixtures: fake_llm, fake_repository, sample_payload
├── test_metrics.py
├── test_sampling.py
├── test_service.py
├── test_routes.py
├── test_worker.py
└── test_llm_anthropic.py
```

Atualizações nos testes existentes:
- `tests/whatsapp/test_extract.py` — adicionar caso pro retry 5xx e delay.
- `tests/whatsapp/test_service.py` — adicionar caso pro link_user em reports.

### Frontend

```
frontend/src/
├── lib/
│   └── reports.js                        # NOVO — useReportPolling hook + fetchers
├── screens/dashboard/
│   ├── ReportGeneratingState.jsx         # NOVO — msgs rotativas + barra fake
│   ├── ReportsListPage.jsx               # ALTERAR — fetch real /api/reports/
│   ├── ReportDetailPage.jsx              # ALTERAR — fetch /api/reports/:id + hook
│   └── components/
│       ├── BenchmarkSection.jsx          # ALTERAR — label dinâmico por segment
│       ├── FunnelSection.jsx             # (já consome FUNNEL — passar payload)
│       └── ...outros são puros (re-aproveitam shape)
└── data/reportData.js                    # MANTER como fallback de loading state (opcional)
```

### Migration

```
SQL via mcp__supabase__apply_migration name="f3_1_reports"
```

## 3. Migration SQL

```sql
-- f3_1_reports
-- F3 §REPORT-01..04: relatório por sessão WhatsApp consumida.
create table if not exists medzee_spy.reports (
  id                    uuid primary key default gen_random_uuid(),
  user_id               uuid references auth.users(id) on delete cascade,
  whatsapp_session_id   uuid references medzee_spy.whatsapp_sessions(id) on delete set null,
  status                text not null check (status in (
                          'pending','generating','completed','partial','failed'
                        )),
  payload               jsonb,           -- ReportPayload completo (null até completed)
  prompt_version        text,
  model                 text,
  clinic_segment        text,            -- saude|odonto|outro (snapshot)
  error_code            text,            -- llm_timeout|llm_invalid_json|extract_failed|...
  message_count         int,
  score                 int,
  created_at            timestamptz not null default now(),
  generated_at          timestamptz,
  updated_at            timestamptz not null default now()
);

-- (user_id, created_at desc) atende GET /reports/latest e /reports/ listagem.
create index if not exists reports_user_created_idx
  on medzee_spy.reports (user_id, created_at desc);

-- Busca por sessão (worker link + F2 bridge).
create index if not exists reports_session_idx
  on medzee_spy.reports (whatsapp_session_id);

-- RLS — só dono lê/atualiza o próprio relatório.
alter table medzee_spy.reports enable row level security;

create policy "reports_owner_select"
  on medzee_spy.reports
  for select to authenticated
  using (auth.uid() = user_id);

create policy "reports_owner_update"
  on medzee_spy.reports
  for update to authenticated
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- Worker (service_role) cria/atualiza pré-JWT — bypass RLS via service_role.
grant select, insert, update on medzee_spy.reports
  to authenticated, service_role;

-- updated_at via trigger (reusa function da F1).
drop trigger if exists trg_reports_set_updated_at on medzee_spy.reports;
create trigger trg_reports_set_updated_at
  before update on medzee_spy.reports
  for each row execute function medzee_spy.set_updated_at();

comment on table medzee_spy.reports is
  'Commercial report for a clinic owner. 1 row per consumed whatsapp_session.';
```

## 4. Pydantic schemas

`app/modules/reports/schemas.py` espelha o shape do `frontend/src/data/reportData.js` pra reduzir transformação no frontend.

```python
from __future__ import annotations
from enum import Enum
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


class ReportStatus(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


# ─── Sub-modelos (1:1 com a UI) ────────────────────────────────────────

class FunnelStage(BaseModel):
    stage: str                              # "Primeiro contato", "Respondidos", ...
    count: int
    pct: float                              # 0-100


class ResponseTimeBucket(BaseModel):
    faixa: Literal["< 5min", "5–30min", "30min–1h", "1h–4h", "4h–24h", "> 24h"]
    count: int
    color: str                              # hex


class HeatmapPeriod(BaseModel):
    label: Literal["Madrug.", "Manhã", "Tarde", "Noite"]
    values: list[float]                     # 7 entries (Seg..Dom), msgs/dia avg


class Opportunity(BaseModel):
    tag: str                                # "P-XXXX" pseudo-id
    context: str                            # snippet/resumo da conversa
    reason: str                             # por que é oportunidade perdida
    value_brl: float                        # estimativa de receita perdida
    when: str                               # "3 dias", "8 dias", etc


class Objection(BaseModel):
    label: str
    pct: float
    count: int
    color: str


class FAQ(BaseModel):
    q: str
    count: int


class SentimentSlice(BaseModel):
    name: Literal["Positivo", "Neutro", "Negativo"]
    value: int                              # 0-100 (soma das 3 = 100)
    color: str


class BenchmarkMetric(BaseModel):
    metric: str                             # "Tempo 1ª resposta", ...
    clinic: float
    market: float
    unit: str                               # "h", "%", "R$"
    better: Literal["lower", "higher"]


# ─── Payload completo ──────────────────────────────────────────────────

class ReportPayload(BaseModel):
    """Snapshot que o frontend renderiza nas 9 seções."""
    # Métricas top-level
    message_count: int
    conversation_count: int
    period_days: int = 30
    score: int = Field(ge=0, le=100)
    clinic_segment: Literal["saude", "odonto", "outro"]

    # Texto LLM
    diagnostic_summary: str                 # 3-5 sentenças

    # Hard data (determinístico)
    funnel: list[FunnelStage]
    response_time_distribution: list[ResponseTimeBucket]
    heatmap_days: list[str] = Field(default_factory=lambda: ["Seg","Ter","Qua","Qui","Sex","Sáb","Dom"])
    heatmap_periods: list[HeatmapPeriod]

    # Soft data (LLM)
    opportunities: list[Opportunity]
    objections: list[Objection]
    faqs: list[FAQ]
    sentiment: list[SentimentSlice]

    # Hardcoded por segment + asterisco honesto
    benchmarks: list[BenchmarkMetric]


# ─── Responses HTTP ────────────────────────────────────────────────────

class ReportResponse(BaseModel):
    id: UUID
    status: ReportStatus
    payload: ReportPayload | None           # null até status=completed/partial
    error_code: str | None
    message_count: int | None
    score: int | None
    created_at: str                         # ISO
    generated_at: str | None


class ReportSummary(BaseModel):
    """Item leve da listagem (sem payload)."""
    id: UUID
    status: ReportStatus
    message_count: int | None
    score: int | None
    created_at: str


class ReportListResponse(BaseModel):
    items: list[ReportSummary]
    total: int
    page: int = 1
    page_size: int = 20
```

## 5. LLM client (`app/clients/llm.py`)

Protocol + adapter Anthropic. Forçamos JSON via `tool_use` (Anthropic API) — é a forma robusta de garantir structured output em Claude.

```python
from __future__ import annotations
from typing import Protocol, Any
import json
import logging

import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Base."""


class LLMUnavailable(LLMError):
    """5xx / network / timeout (transient → retry candidato)."""


class LLMInvalidResponse(LLMError):
    """Resposta veio mas não passou no schema."""


class LLMClient(Protocol):
    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],     # JSON Schema do output esperado
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> dict[str, Any]: ...


class AnthropicClient:
    """Claude via Messages API. Force JSON via tool_use (single tool)."""

    _ENDPOINT = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: str, model: str, timeout_s: float = 90.0):
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_s

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        body = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": [
                {
                    "name": "submit_report",
                    "description": "Submit the structured commercial report.",
                    "input_schema": schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": "submit_report"},
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self._timeout) as http:
            try:
                resp = await http.post(self._ENDPOINT, json=body, headers=headers)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                raise LLMUnavailable(f"transport: {exc!r}") from exc

        if resp.status_code >= 500:
            raise LLMUnavailable(f"upstream {resp.status_code}: {resp.text[:200]}")
        if resp.status_code == 429:
            raise LLMUnavailable(f"rate_limited: {resp.text[:200]}")
        if resp.status_code >= 400:
            raise LLMError(f"upstream {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        # data["content"] = [{"type": "tool_use", "name": "submit_report", "input": {...}}]
        for block in data.get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == "submit_report":
                return block.get("input") or {}
        raise LLMInvalidResponse(f"no tool_use block in response: {data!r}")


def get_llm_client() -> LLMClient:
    """Factory — escolhe adapter por LLM_PROVIDER (D2)."""
    if settings.LLM_PROVIDER == "anthropic":
        return AnthropicClient(
            api_key=settings.ANTHROPIC_API_KEY,
            model=settings.LLM_MODEL,
        )
    raise NotImplementedError(f"LLM_PROVIDER={settings.LLM_PROVIDER!r}")
```

**Por que tool_use?** Claude às vezes adiciona prosa antes/depois de um JSON livre. Forçar via tool definition (Anthropic valida o input_schema do lado deles) elimina o problema. Equivalente do "JSON mode" da OpenAI.

## 6. Sampling (`app/modules/reports/sampling.py`)

Mantém custo previsível. Função pura.

```python
from app.modules.whatsapp.schemas import ConversationPayload, MessagePayload, ExtractedPayload

# Heurística calibrada: PT-BR conta ~3.5 chars por token. 60k tokens → ~210k chars.
# Margem pra system prompt + métricas + schema: budget de 150k chars de conversa.
_MAX_CONVERSATION_CHARS = 150_000
# Pra preservar contexto: primeiras 10 + últimas 20 msgs de uma conversa muito longa.
_KEEP_HEAD = 10
_KEEP_TAIL = 20


def sample_conversations(payload: ExtractedPayload) -> list[ConversationPayload]:
    """Devolve um subset cujo custo total cabe no LLM budget.

    Estratégia:
      1. Filtra grupos (clínica não vende em grupo de WhatsApp).
      2. Ordena por message_count desc.
      3. Greedy: vai pegando do topo até estourar o budget.
      4. Conversa individual gigantesca → trunca head/tail.
    """
    candidates = [c for c in payload.conversations if not c.is_group]
    candidates.sort(key=lambda c: len(c.messages), reverse=True)

    out: list[ConversationPayload] = []
    used = 0
    for conv in candidates:
        truncated = _truncate_if_needed(conv)
        cost = _estimate_chars(truncated)
        if used + cost > _MAX_CONVERSATION_CHARS and out:
            break
        out.append(truncated)
        used += cost
    return out


def _estimate_chars(conv: ConversationPayload) -> int:
    return sum(len(m.text or "") for m in conv.messages)


def _truncate_if_needed(conv: ConversationPayload) -> ConversationPayload:
    if len(conv.messages) <= _KEEP_HEAD + _KEEP_TAIL:
        return conv
    head = conv.messages[:_KEEP_HEAD]
    tail = conv.messages[-_KEEP_TAIL:]
    return conv.model_copy(update={"messages": head + tail})
```

## 7. Metrics (`app/modules/reports/metrics.py`)

Funções puras (sem I/O), totalmente testáveis sem mock.

```python
def compute_message_count(payload: ExtractedPayload) -> int
def compute_conversation_count(payload: ExtractedPayload) -> int

def compute_response_time_distribution(payload) -> list[ResponseTimeBucket]:
    """Para cada par (msg do lead, próxima msg da clínica), calcular delay.
    Buckets: <5min, 5-30min, 30min-1h, 1h-4h, 4h-24h, >24h.
    Color: 2 primeiros = orange (rápido), 2 médios = amber, últimos 2 = dark."""

def compute_heatmap(payload) -> list[HeatmapPeriod]:
    """Para cada msg, mapear ts → (dia_semana, período_dia).
    Períodos: Madrugada(0-6), Manhã(6-12), Tarde(12-18), Noite(18-24).
    Output: 4 periods × 7 days, valor = média de msgs/dia (count / num_dias_da_amostra)."""

def compute_funnel(payload) -> list[FunnelStage]:
    """5 estágios:
      1. Primeiro contato = total de conversations (1 contato = 1 conversa).
      2. Respondidos = conversations com pelo menos 1 msg from_me=True.
      3. Engajados = conversations com >=3 msgs.
      4. Receberam info / valor = conversations cujas msgs da clínica contêm
         regex de valor (`R$\s?\d+` ou keywords `valor|preço|investimento|consulta`).
      5. Agendamento confirmado = conversations com keywords de confirmação
         (`agendado|confirmado|marcado|reservei|reservar|consultório|ver te|nos vemos`).
    pct é relativo ao estágio 1.
    """

def compute_score(
    message_count: int,
    response_time_distribution: list[ResponseTimeBucket],
    funnel: list[FunnelStage],
) -> int:
    """0-100, ponderado:
      response_time_score (35%) = % de respostas em <30min normalizado
      conversion_score    (30%) = pct do último estágio do funnel (capped at 25%)
      response_rate_score (20%) = pct do segundo estágio (Respondidos / Primeiro)
      volume_score        (15%) = log-scale, 0 em <50 msgs, 100 em >=2000 msgs
    """
```

Regex pt-BR para o funil em `_keywords.py`:

```python
KW_VALUE = re.compile(r"\bR\$\s?\d|\b(valor|preç[oa]|investimento|consulta|orçamento|particular)\b", re.I)
KW_BOOKED = re.compile(r"\b(agendad[oa]|confirmad[oa]|marcad[oa]|reservei|reservar|nos vemos|ver vc|consultório)\b", re.I)
```

## 8. Benchmarks (`app/modules/reports/benchmarks.py`)

Hardcoded por especialidade. Label conforme **REPORT-22**.

```python
from app.modules.reports.schemas import BenchmarkMetric

# Valores defensáveis baseados em pesquisas setoriais (Sebrae 2023, RD Station
# Marketing Pulse 2024, médias de mercado consultor). Asterisco no frontend
# deixa claro que é estimativa da rede Medzee.
_BENCHMARKS_BY_SEGMENT: dict[str, list[BenchmarkMetric]] = {
    "saude": [
        BenchmarkMetric(metric="Tempo 1ª resposta",         clinic=0, market=0.8,  unit="h", better="lower"),
        BenchmarkMetric(metric="Taxa de conversão",         clinic=0, market=24.0, unit="%", better="higher"),
        BenchmarkMetric(metric="Mensagens sem resposta",    clinic=0, market=6,    unit="%", better="lower"),
        BenchmarkMetric(metric="Follow-up pós-orçamento",   clinic=0, market=58,   unit="%", better="higher"),
    ],
    "odonto": [
        BenchmarkMetric(metric="Tempo 1ª resposta",         clinic=0, market=0.5,  unit="h", better="lower"),
        BenchmarkMetric(metric="Taxa de conversão",         clinic=0, market=30.0, unit="%", better="higher"),
        BenchmarkMetric(metric="Mensagens sem resposta",    clinic=0, market=4,    unit="%", better="lower"),
        BenchmarkMetric(metric="Follow-up pós-orçamento",   clinic=0, market=65,   unit="%", better="higher"),
    ],
    "outro": [
        BenchmarkMetric(metric="Tempo 1ª resposta",         clinic=0, market=1.2,  unit="h", better="lower"),
        BenchmarkMetric(metric="Taxa de conversão",         clinic=0, market=20.0, unit="%", better="higher"),
        BenchmarkMetric(metric="Mensagens sem resposta",    clinic=0, market=8,    unit="%", better="lower"),
        BenchmarkMetric(metric="Follow-up pós-orçamento",   clinic=0, market=50,   unit="%", better="higher"),
    ],
}


def build_benchmarks(
    *,
    clinic_segment: str,
    clinic_response_time_h: float,
    clinic_conversion_pct: float,
    clinic_unanswered_pct: float,
    clinic_followup_pct: float,
) -> list[BenchmarkMetric]:
    """Retorna benchmarks com clinic preenchido + market hardcoded."""
    seg = clinic_segment if clinic_segment in _BENCHMARKS_BY_SEGMENT else "outro"
    template = _BENCHMARKS_BY_SEGMENT[seg]
    clinic_values = [
        clinic_response_time_h,
        clinic_conversion_pct,
        clinic_unanswered_pct,
        clinic_followup_pct,
    ]
    return [
        m.model_copy(update={"clinic": v}) for m, v in zip(template, clinic_values, strict=True)
    ]
```

## 9. Prompts (`app/modules/reports/prompts/`)

**System prompt comum** (`base.py`):

```python
SYSTEM = """Você é a Marina, consultora comercial da Medzee. Seu trabalho é analisar conversas de WhatsApp de uma clínica nos últimos 30 dias e produzir um diagnóstico estruturado em JSON.

REGRAS DURAS:
- Responda EXCLUSIVAMENTE chamando a tool `submit_report`. Não escreva prosa.
- Tom: consultivo, direto, em PT-BR. Sem floreio.
- Oportunidades, objeções e FAQs DEVEM vir de mensagens reais — não invente.
- Valores em BRL: use médias da especialidade quando o lead não citar preço. Para saúde particular, ~R$ 250–1.500 por consulta/procedimento (escolha conforme o contexto).
- Se a amostra for pequena (<50 msgs), priorize padrões qualitativos sobre números.

ESTRUTURA OBRIGATÓRIA (preencher a tool):
- diagnostic_summary: 3-5 sentenças, primeiro o ponto mais crítico, depois 1-2 pontos positivos. Tom de consultoria, não palestra motivacional.
- opportunities: top 5 leads que ficaram sem follow-up adequado. Cada um com tag (P-XXXX gerado), context (resumo da mensagem que pediu algo), reason (por que virou oportunidade perdida), value_brl (estimativa), when ("X dias").
- objections: top 3 objeções recorrentes (preço, convênio, horário, deslocamento, dúvida procedimento, etc). pct = % do total de leads que mencionaram, count = quantos.
- faqs: top 5 perguntas frequentes não respondidas ou mal respondidas. q = pergunta no formato breve, count = frequência.
- sentiment: distribuição em 3 fatias (Positivo/Neutro/Negativo) totalizando 100.
"""
```

**Variantes** (`saude.py`, `odonto.py`, `outro.py`) só **acrescentam** orientação de domínio ao final do system prompt:

```python
# saude.py
SEGMENT_ADDENDUM = """Especialidade: SAÚDE (clínica médica geral, especialidades).
Foque em: convênios mencionados (Unimed, Bradesco, Amil, particular), urgência clínica vs eletiva, exames complementares pedidos, conversão de primeira consulta vs retorno.
Valores típicos: consulta particular R$ 250–800, exame R$ 80–600, procedimento R$ 1.000–5.000.
"""

# odonto.py
SEGMENT_ADDENDUM = """Especialidade: ODONTOLOGIA.
Foque em: estética (clareamento, lente, alinhador), tratamento (canal, implante, ortodontia), parcelamento (forte driver em odonto), avaliação inicial gratuita vs paga.
Valores típicos: avaliação R$ 0–150, limpeza R$ 150–300, lente R$ 1.800–3.500/dente, implante R$ 2.500–4.500.
"""

# outro.py
SEGMENT_ADDENDUM = """Especialidade: NÃO CLASSIFICADA. Use tom genérico de atendimento comercial.
Identifique o tipo de serviço pelas mensagens e adapte.
"""
```

**User prompt** montado pelo worker (`prompts/__init__.py`):

```python
def build_user_prompt(
    *,
    clinic_segment: str,
    metrics_snapshot: dict,
    sampled_conversations: list[ConversationPayload],
) -> str:
    """
    Estrutura:
      ## MÉTRICAS DURAS (já calculadas, não recompute)
      message_count: 3.370 / conversation_count: 412 / response_rate: 88.6%
      ...
      ## CONVERSAS (top-volume + amostra)
      ### Conversa P-XXXX (15 mensagens)
      [2026-04-29 09:14] LEAD: ...
      [2026-04-29 11:02] CLÍNICA: ...
      ...
    """
```

`prompts/__init__.py` expõe:
```python
def get_system_prompt(clinic_segment: str) -> str:
    base = BASE_SYSTEM
    addendum = _ADDENDUM_BY_SEGMENT.get(clinic_segment, _ADDENDUM_BY_SEGMENT["outro"])
    return base + "\n\n" + addendum

PROMPT_VERSION = "v1.0.0"   # bump sempre que mudar
```

**JSON Schema** do tool (`prompts/schema.py`) — gerado direto de pydantic via `ReportPayload.model_json_schema()` mas filtrado pros 5 campos LLM (`diagnostic_summary, opportunities, objections, faqs, sentiment`), porque o resto é determinístico e composto depois.

## 10. Repository (`app/modules/reports/repository.py`)

Mesma forma do F2:

```python
async def create_generating(
    *, whatsapp_session_id: UUID, user_id: UUID | None, clinic_segment: str | None
) -> UUID: ...

async def update_completed(
    report_id: UUID, *, payload: dict, model: str, prompt_version: str,
    message_count: int, score: int,
) -> None: ...

async def update_partial(...) -> None: ...

async def update_failed(report_id: UUID, *, error_code: str) -> None: ...

async def link_user(whatsapp_session_id: UUID, user_id: UUID) -> int:
    """UPDATE reports SET user_id WHERE whatsapp_session_id = ? AND user_id IS NULL.
    Retorna o número de rows afetadas (0 se report não existir ainda — race ok)."""

async def get_by_id(report_id: UUID, *, user_id: UUID) -> dict | None:
    """Filtra por user_id como defesa em profundidade. RLS já protege, mas
    explícito > implícito (REPORT-17)."""

async def get_latest_for_user(user_id: UUID) -> dict | None: ...

async def list_for_user(user_id: UUID, *, page: int, page_size: int) -> tuple[list[dict], int]: ...
```

PII safety: log `email_domain` se viesse — aqui só logamos `user_id` (UUID, safe) e `whatsapp_session_id` (UUID).

## 11. Service + Routes

`ReportService` é fininho — só orquestra repo e mapeia exceções pra rotas:

```python
class ReportService:
    async def get_latest(self, user_id: UUID) -> ReportResponse: ...
    async def get_by_id(self, report_id: UUID, user_id: UUID) -> ReportResponse: ...
    async def list_for_user(self, user_id: UUID, page: int, page_size: int) -> ReportListResponse: ...
```

Exceções: `ReportNotFound` → 404.

Rotas (`/api/reports/...`):

| Método | Path | Auth | Body | Sucesso | Erros |
|---|---|---|---|---|---|
| GET | `/reports/latest` | Bearer | — | `200 SuccessResponse[ReportResponse]` | 401, 404 report_not_found |
| GET | `/reports/{id}` | Bearer | — | `200 SuccessResponse[ReportResponse]` | 401, 404 |
| GET | `/reports/` | Bearer | query `?page=1&page_size=20` | `200 SuccessResponse[ReportListResponse]` | 401 |

`get_current_user_id` (do F2) já entrega o UUID via JWT.

## 12. Worker (`app/workers/report.py`)

```python
async def generate_report_pipeline(
    session_id: UUID,
    payload: ExtractedPayload,
    *,
    user_id: UUID | None = None,
) -> None:
    """Fire-and-forget. NUNCA propaga exceção pra cima do `asyncio.create_task`.

    Fluxo:
      1. clinic_segment ← se user_id setado, busca via auth (raw_app_meta_data),
         senão 'outro' (default; F2 atualiza depois via link_user).
      2. report_id ← repository.create_generating(...)
      3. Try:
         a. metrics = compute_*(payload)
         b. score = compute_score(metrics)
         c. sampled = sample_conversations(payload)
         d. system = get_system_prompt(clinic_segment)
         e. user = build_user_prompt(metrics, sampled)
         f. result = await llm.complete_json(system, user, schema, timeout=90)
            (with retry: 1x em LLMInvalidResponse com mensagem corretiva)
         g. final_payload = compose(metrics, result, benchmarks)
         h. repository.update_completed(report_id, payload, model, prompt_version,
                                       message_count, score)
      Except:
        - asyncio.TimeoutError → update_failed(error_code='llm_timeout')
        - LLMUnavailable → update_failed(error_code='llm_unavailable')
        - LLMInvalidResponse (após retry) → update_failed(error_code='llm_invalid_json')
        - generic Exception → update_failed(error_code='internal_error') + logger.exception
    """
```

`compose()` é simples merge:
```python
def compose(metrics_dict, llm_dict, benchmarks_list, *, clinic_segment, message_count, score) -> ReportPayload:
    return ReportPayload(
        **metrics_dict,        # message_count, conversation_count, funnel, response_time_*, heatmap_*
        score=score,
        clinic_segment=clinic_segment,
        diagnostic_summary=llm_dict["diagnostic_summary"],
        opportunities=[Opportunity(**o) for o in llm_dict["opportunities"]],
        objections=[Objection(**o) for o in llm_dict["objections"]],
        faqs=[FAQ(**f) for f in llm_dict["faqs"]],
        sentiment=[SentimentSlice(**s) for s in llm_dict["sentiment"]],
        benchmarks=benchmarks_list,
    )
```

Timeout (**REPORT-13**) via `asyncio.wait_for(pipeline_inner(), timeout=120)`.

## 13. Integração com F2 + F1

### F1: `app/workers/extract.py` — disparo do F3

No final de `_finalize_success` e `_finalize_partial`, após `session_store.set_payload(...)`:

```python
asyncio.create_task(
    _kick_off_report(session_id, payload),
    name=f"report-{session_id}",
)
```

`_kick_off_report` é uma função-cebola que faz lazy import pra evitar ciclo:

```python
async def _kick_off_report(session_id: UUID, payload: ExtractedPayload) -> None:
    try:
        from app.workers.report import generate_report_pipeline
    except ImportError:
        return
    # user_id pode estar setado em whatsapp_sessions se signup chegou primeiro:
    user_id = await _maybe_resolve_user_id(session_id)  # repo.get_session(...).user_id
    await generate_report_pipeline(session_id, payload, user_id=user_id)
```

### F2: `whatsapp/service.py::consume_extracted` — link

Após o `repository.link_user(session_id, user_id)` que já existe, adicionar:

```python
from app.modules.reports import repository as reports_repository
try:
    await reports_repository.link_user(session_id, user_id)
except Exception:
    logger.warning(
        "service.consume_extracted.report_link_failed",
        extra={"session_id": str(session_id), "user_id": str(user_id)},
        exc_info=True,
    )
```

Lazy import via `from app.modules.reports import repository as reports_repository` no topo do método (ou no topo do arquivo se não houver ciclo — provavelmente não há porque reports não importa whatsapp).

## 14. B3 Fix (extract.py + uazapi.py)

### `app/workers/extract.py`

No início do pipeline (antes do primeiro `provider.list_chats`):

```python
# B3: uazapi free tier needs ~5s after `connected` for history sync to
# stabilize. Without this, the first /chat/find returns 500.
await asyncio.sleep(5)
```

### `app/clients/whatsapp/uazapi.py`

Wrapper pequeno em volta de `list_chats` e `list_messages`:

```python
_RETRY_DELAYS_S = [2, 5, 12]   # 3 tentativas com backoff exponencial


async def _retry_5xx(call, op: str, **log_extra):
    last_exc = None
    for attempt, delay in enumerate([0, *_RETRY_DELAYS_S]):
        if delay:
            await asyncio.sleep(delay)
        try:
            return await call()
        except UazapiUnavailable as exc:
            last_exc = exc
            logger.warning(
                f"uazapi op={op} 5xx_retry attempt={attempt}/{len(_RETRY_DELAYS_S)} delay_next={_RETRY_DELAYS_S[attempt] if attempt < len(_RETRY_DELAYS_S) else 'none'}",
                extra=log_extra,
            )
            continue
    raise last_exc
```

Aplicar nos call sites `list_chats` e `list_messages`. 4xx propaga imediatamente (não é transient).

## 15. Frontend

### `frontend/src/lib/reports.js`

```javascript
import { useEffect, useRef, useState } from 'react';
import { callApi } from './api';

const TERMINAL = new Set(['completed', 'partial', 'failed']);
const POLL_MS = 2000;

export function useReportPolling(idOrLatest = 'latest') {
  const [state, setState] = useState({
    status: 'pending', payload: null, error: null, elapsedMs: 0,
  });
  const startRef = useRef(Date.now());
  const aliveRef = useRef(true);

  useEffect(() => {
    aliveRef.current = true;
    startRef.current = Date.now();
    let timer;

    async function tick() {
      try {
        const path = idOrLatest === 'latest'
          ? '/api/reports/latest'
          : `/api/reports/${idOrLatest}`;
        const data = await callApi(path, { auth: true });
        if (!aliveRef.current) return;
        setState({
          status: data.status, payload: data.payload, error: data.error_code,
          elapsedMs: Date.now() - startRef.current,
        });
        if (!TERMINAL.has(data.status)) {
          timer = setTimeout(tick, POLL_MS);
        }
      } catch (e) {
        if (!aliveRef.current) return;
        setState((s) => ({ ...s, error: e.detail || 'fetch_failed',
                                   elapsedMs: Date.now() - startRef.current }));
        // Mantém polling pra recuperar de blip de rede.
        timer = setTimeout(tick, POLL_MS);
      }
    }
    tick();

    return () => { aliveRef.current = false; clearTimeout(timer); };
  }, [idOrLatest]);

  return state;
}
```

### `ReportGeneratingState.jsx`

Mensagens rotativas + barra fake. Estado puro derivado de `elapsedMs`.

```jsx
const STEPS = [
  { until: 15_000, label: 'Analisando suas conversas dos últimos 30 dias…' },
  { until: 45_000, label: 'Identificando oportunidades e padrões de atendimento…' },
  { until: 90_000, label: 'Quase lá — finalizando o diagnóstico…' },
];
const STALL_AFTER_MS = 90_000;

function pickStep(elapsedMs) {
  for (const s of STEPS) if (elapsedMs < s.until) return s;
  return null;  // → estado "stall"
}

function fakeProgress(elapsedMs) {
  // ease-out até 80% em 60s, depois marca-passo lento até 95%.
  const t = Math.min(elapsedMs / 60_000, 1);
  const phase1 = 80 * (1 - Math.pow(1 - t, 3));
  if (elapsedMs < 60_000) return phase1;
  const extra = Math.min((elapsedMs - 60_000) / 30_000, 1) * 15;
  return 80 + extra;
}

export default function ReportGeneratingState({ elapsedMs, onRetry }) {
  const step = pickStep(elapsedMs);
  const progress = fakeProgress(elapsedMs);
  // ...renderiza com gradient dark/orange, mesma vibe do GeneratingScreen mas
  // título "Análise IA em curso" e barra progress.
}
```

### Dashboard wire-up

- `ReportsListPage.jsx` substitui `mockReports` por `await callApi('/api/reports/', { auth: true })`.
- `ReportDetailPage.jsx` usa `useReportPolling(id)`. Se `status` terminal e `payload` presente, renderiza as 9 seções com `payload.*` (compatível 1:1 com nomes do `reportData.js`).
- `BenchmarkSection.jsx` recebe `clinic_segment` via prop e troca o subtitle:
  ```jsx
  const SEGMENT_LABEL = {
    saude: 'Saúde', odonto: 'Odonto', outro: 'sua área',
  };
  // subtitle: `Média de clínicas de ${SEGMENT_LABEL[clinic_segment]} conectadas à Medzee*`
  // footnote: `*estimativa baseada em pesquisas setoriais da rede Medzee; atualizado periodicamente conforme a base cresce.`
  ```

## 16. Mapeamento de erros

| Camada / Origem | Excessão | Persiste | HTTP |
|---|---|---|---|
| LLM 5xx / timeout / rate-limit | `LLMUnavailable` | `error_code=llm_unavailable` | — (worker async) |
| LLM resposta inválida (após retry) | `LLMInvalidResponse` | `error_code=llm_invalid_json` | — |
| Worker hard timeout 120s | `asyncio.TimeoutError` | `error_code=llm_timeout` | — |
| Extract falhou totalmente | n/a — reports row inexistente | — | GET /reports/latest 404 |
| Extract retornou partial | n/a — worker gera com `status=partial` | — | 200 |
| GET /reports/{id} de outro user | `ReportNotFound` (depois do filtro defensivo) | — | 404 (indistinto) |
| GET /reports/latest sem nenhum | `ReportNotFound` | — | 404 `report_not_found` |
| GET sem JWT | (security.py) | — | 401 |

## 17. Estratégia de testes

```
backend/app/tests/reports/
├── conftest.py              # fixtures: fake_llm, fake_repository, sample_extracted_payload (factory)
├── test_metrics.py          # cada função pura, casos limite (lista vazia, mensagens 1:1, etc)
├── test_sampling.py         # truncamento, ordering por volume, budget cap
├── test_service.py          # get_latest/get_by_id (acerto + 404 + cross-user)
├── test_routes.py           # 4 endpoints + 401 + 404 + paginação
├── test_worker.py           # happy path + cada erro mapeado + race link_user
└── test_llm_anthropic.py    # respx pra mockar Anthropic API + casos 4xx/5xx/tool_use bem-formado/mal-formado
```

**Fixtures:**
- `fake_llm` — `AsyncMock(spec=LLMClient)` com `complete_json` retornando dict válido por default; testes sobrescrevem pra raise.
- `fake_repository` — monkeypatch funcs do reports.repository.
- `sample_extracted_payload(*, message_count=200, ...)` — factory que gera um `ExtractedPayload` realista com mensagens timed dentro de janela de 30 dias.

**Casos prioritários:**

| Arquivo | Caso | Verifica |
|---|---|---|
| `test_metrics.py` | response_time_distribution clássico | 6 buckets + total bate |
| | response_time só lead → 0 respostas | buckets todos com count=0 |
| | funnel com keywords de valor | estágio 4 captura |
| | score em volume baixo | <50 msgs → score baixo previsível |
| `test_sampling.py` | budget cabe → retorna todas | sem perdas |
| | budget estoura → corta no meio | mantém top por volume |
| | conversa gigantesca → trunca | head+tail apenas |
| | filtra grupos | is_group=True não passa |
| `test_worker.py` | happy path | repo.create_generating + update_completed; status path correto |
| | LLMUnavailable após retry | update_failed(llm_unavailable) |
| | LLM JSON inválido + retry corretivo OK | update_completed |
| | LLM JSON inválido 2 vezes | update_failed(llm_invalid_json) |
| | hard timeout 120s | update_failed(llm_timeout) |
| | extract partial → still generates | status=partial |
| `test_routes.py` | GET /reports/latest happy | 200 envelope |
| | GET /reports/latest sem nenhum | 404 |
| | GET /reports/{id} cross-user | 404 (não 403, indistinto) |
| | GET /reports/?page=2 | paginação |
| | sem JWT | 401 (ou 403 default HTTPBearer) |
| `test_llm_anthropic.py` | tool_use bem-formado | retorna input dict |
| | response sem tool_use block | LLMInvalidResponse |
| | 500 upstream | LLMUnavailable |
| | timeout | LLMUnavailable |

Alvo: **~35 testes novos**. Suite agregada: 95 → ~130.

## 18. Observações abertas

1. **Cost cap em prod**: assumimos ~$0.20/relatório. Se o produto pegar tração, vale instrumentar `prompt_tokens` + `completion_tokens` no row de reports pra acompanhar gasto real. Backlog M2.
2. **Streaming LLM**: Anthropic suporta SSE streaming. Em M1 polling 2s já dá uma UX boa. Streaming reduziria o "Stall after 90s" caso o LLM esteja gerando devagar — mas adiciona complexidade. Backlog.
3. **Re-gerar relatório**: nenhum endpoint `POST /reports/{id}/regenerate` em M1. Se o LLM falhar, user precisa rodar /spy de novo.
4. **Whatsapp groups**: filtrados do sampling AND do funnel/heatmap. Mensagens em grupo não representam leads.
5. **PII no payload jsonb**: `opportunities[].context` pode conter snippets de conversas reais. Como o relatório é privado (RLS owner-only) e o uso é o próprio dono ver, achamos aceitável. Documentar no PRIVACY.md (backlog).

## 19. Pontes pra próximas features

- **F4 (Frontend Integration)** já fica praticamente coberto se T9/T10 (frontend de F3) ficarem polidos. Resta apenas o guard de rota `/app/*` que valida `supabase.auth.getSession()` antes de renderizar — pequeno escopo, possivelmente parte do mesmo PR.
- **F5 (DX & Docs)** ganha um README que cobre a tríade backend+frontend+supabase, incluindo "como subir LLM key local" e variáveis de ambiente.
- **M2 Recurring Reports** vai reusar `generate_report_pipeline` com `whatsapp_session_id=null` e payload veio de outra fonte (cron + cached). Schema atual já suporta (whatsapp_session_id é nullable).
