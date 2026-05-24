# F5 — Tasks

Pipeline atômico, cada task = 1 commit conceitual.

## Wave 1 — Backend pipeline

- **F5-1** Adicionar `pull_last_n_per_chat(provider, token, *, n_per_chat=30)` em `app/workers/extract.py` (paralelo, sem cutoff, single-page por chat). Mantém `pull_history` legado.
- **F5-2** Adicionar `query_last_n_per_chat(user_id, *, n_per_chat=30)` em `app/modules/captured_messages/repository.py`.
- **F5-3** Atualizar `GenerateReportRequest` em `app/modules/captured_messages/schemas.py` pra aceitar `mode: 'last_n_per_chat'|'window_days'` (default `last_n_per_chat`) + `n_per_chat: 10|20|30|50` (default 30). `period_days` opcional.

## Wave 2 — Service + route

- **F5-4** `ReportService.trigger_generate` aceita `mode` + `n_per_chat`. `_build_and_run` despacha pro caminho certo.
- **F5-5** Route `POST /api/reports/generate`: eliminar threshold rígido `not_enough_data`, **sempre despacha worker** (o worker decide insufficient). Manter rate limit. Aceitar novo body.

## Wave 3 — Prompts + worker

- **F5-6** `BASE_SYSTEM` (`prompts/base.py`): relaxar tom "nunca recuse, sempre devolva relatório". Adicionar instrução `scope_warning` quando segmento != saúde/odonto.
- **F5-7** `LLM_TOOL_SCHEMA` (`prompts/schema.py`): novo campo `scope_warning: string|null`. Não obrigatório.
- **F5-8** `outro.py`: addendum atualizado pra usar `scope_warning` + tom genérico mas útil.
- **F5-9** `app/workers/report.py`: short-circuit relaxado pra `message_count == 0`. Quando 1-4 msgs, chama LLM normalmente.
- **F5-10** `app/modules/reports/schemas.py`: adicionar `scope_warning: str | None = None` em `ReportPayload`. Worker `_compose` passa o campo do LLM dict pra cá.

## Wave 4 — Frontend

- **F5-11** `lib/reports.js`: `generateReport({ n_per_chat })` substitui assinatura antiga (mantém `period_days` como fallback opcional).
- **F5-12** `GenerateReportModal.jsx`: opções 10/20/30/50 em vez de 7/15/30/60 dias. Copy: "últimas N mensagens de cada conversa".
- **F5-13** `lib/whatsapp.js`: já tem `useUazapiStats` — só validar polling rápido (2.5s) durante geração.
- **F5-14** `ReportGeneratingState.jsx`: substituir PHASES fake por mensagens guiadas pelos `uazapiStats` reais (chat_count, message_count).
- **F5-15** `GeneratingScreen.jsx` (público): mesma lógica — mostrar contagens reais polando endpoint público (ou skip se anônimo).
- **F5-16** `ReportDetailPage.jsx`: novo `ScopeWarningBanner` quando `payload.scope_warning` presente.

## Wave 5 — Docs + commit

- **F5-17** Atualizar `.specs/project/STATE.md` (decisão D9 + obsoletar B3 follow-up).
- **F5-18** Atualizar `.specs/project/ROADMAP.md` (F5 entry).
- **F5-19** Commit em chunks (Wave 1-2, Wave 3, Wave 4, Wave 5).
