# F7 — Auto-Generate Report on Signup

## Why

**Coração do produto**: a promessa do Medzee Spy é mostrar pro lead o relatório **imediatamente após o cadastro**, sem fricção. O fluxo `/spy` foi desenhado exatamente pra isso:

> Scan QR → Generating placeholder → LeadForm → Relatório PRONTO

Hoje (pós-F5), o fluxo quebrou:

1. User scan QR → conecta WhatsApp
2. User preenche LeadForm + cria conta
3. Backend signup retorna 200, frontend navega pra `/app/reports/latest`
4. **404 Not Found** — não existe relatório nenhum
5. User cai numa tela vazia, sem ação clara

Razão: F1 (auto-extract on connect) foi **desligado** no commit `3ca748e` (matava instâncias). Pós-F5, relatório só roda quando user clica "Gerar relatório" manualmente. Mas no fluxo de cadastro, o user não TEM esse contexto — ele acabou de completar signup e espera ver o relatório, não uma lista vazia.

> User feedback explícito (2026-05-19):
> *"precisamos consertar! pois é o coração do nosso projeto"*

## What

**Auto-disparar `POST /api/reports/generate` imediatamente após signup bem-sucedido**, então navegar pra `/app/reports/{report_id}` (rota com polling que mostra `ReportGeneratingState`).

### Fluxo novo

1. User completa LeadForm step 2 (senha)
2. Frontend `LeadFormScreen.handleSubmit`:
   1. `POST /api/auth/signup` → recebe `session + user`
   2. `supabase.auth.setSession(...)` (autentica o cliente)
   3. **NOVO**: `POST /api/reports/generate` com defaults (`mode='last_n_per_chat'`, `n_per_chat=30`)
   4. Navega pra `/app/reports/{report_id}` (não mais `/latest`)
3. `ReportDetailPage` poll `/api/reports/{id}` a cada 5s
4. `ReportGeneratingState` mostra "Lendo conversas… IA analisando…" calibrado pra ~15-30s
5. Status vira `completed` → render do relatório completo

### Fluxos absorvidos por F7

- `/spy` (lead novo, ticket médio) — gera relatório automaticamente
- `/` MainFlow (com AgentScreen + ticket médio) — mesmo comportamento

### Não-objetivos

- Não muda nada no backend: o `POST /api/reports/generate` já existe e funciona (F5). O `auth.signup` continua single-purpose (criar user + profile + bridge whatsapp session). A composição "signup + generate" vive no frontend.
- Não reativa F1 extract_30d_pipeline (continua deprecated — destruía instâncias).
- Não muda `/app/reports` (lista logada). Botão "Gerar relatório" continua funcionando pra users que querem regenerar.

## Acceptance criteria

- [ ] **AC1** — Após scan QR + LeadForm + signup, user é navegado pra `/app/reports/{report_id}` (não pra `/app/reports/latest`).
- [ ] **AC2** — `ReportGeneratingState` aparece imediatamente com o `elapsedMs` correto desde o `created_at` (não reseta).
- [ ] **AC3** — Após ~15-30s o status vira `completed` e o relatório real aparece (mesmo do teste F4/F5 que validou).
- [ ] **AC4** — Se `POST /reports/generate` falhar com 429 (rate limit, raríssimo no signup novo), fallback navega pra `/app/reports/latest` com toast amigável.
- [ ] **AC5** — Se o user já tem session ativa mas SEM mensagens capturadas (webhook ainda não chegou), o F5 fallback `pull_last_n_per_chat` puxa do uazapi e o relatório gera mesmo assim (já testado).
- [ ] **AC6** — Logs do backend mostram a sequência: `signup.enter` → `signup.exit` → `route.reports.generate.dispatched` → `worker.report.llm_call.start` → `worker.report.exit`.

## Edge cases

| Cenário | Comportamento |
|---|---|
| Generate retorna 429 | Toast + navega pra `/app/reports/latest` (fallback antigo) |
| Generate retorna outro 4xx/5xx | Toast com erro + navega pra `/app/reports` (lista) |
| Generate timeout (>30s no frontend, raríssimo) | Toast "Demorando mais que o normal" + navega pra `/app/reports/latest` |
| User clica "Voltar" ou refresh durante geração | URL `/app/reports/{id}` preserva — polling resume (Fix do commit `7cbcd1e`) |
| Signup OK mas sem `whatsapp_session_id` (caminho `/login` direto?) | Não dispara generate — navega pra `/app/dashboard` |

## Out of scope

- Reativar extract_30d_pipeline.
- Mover composição pro backend (acoplaria auth a reports — anti-padrão).
- Adicionar campo "auto-generate yes/no" na UI — sempre dispara.
