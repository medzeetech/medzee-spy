# F5 — Design

## 1. Arquitetura de coleta

### 1.1 Algoritmo `pull_last_n_per_chat`

Substitui o `pull_history(days_window)`. Vive em `app/workers/extract.py`.

```
async def pull_last_n_per_chat(
    provider, session_token, *, n_per_chat=30
) -> ExtractedPayload:
    1. chats = paginate /chat/find (sorted last_message_desc)
    2. parallel sync (Sem(20)):
         for each chat → /message/history-sync(count=n_per_chat)
       wait gather + sleep 6s pra cache popular
    3. parallel read (Sem(20)):
         for each chat → /message/find(limit=n_per_chat, offset=0)
         filter: keep only m.text != ""
         (NO cutoff_ts, NO date filter)
    4. return ExtractedPayload(conversations, partial=False)
```

**Diferenças vs `pull_history` antigo**:
- Sem `cutoff_ts`. Não descarta mensagens antigas.
- `limit=n_per_chat` (default 30) em vez de paginar até 100 + filtrar.
- Single page per chat (uazapi `/message/find` retorna ordenado mais recente primeiro).
- `partial=True` só quando timeout ou falha individual de chat.

**Por quê não paginar**: queremos *as últimas 30* por conversa. Uma página com `limit=30, offset=0` já retorna isso, sorted desc. Não há valor em ir além.

### 1.2 Hard timeout

Mantém o cap de 120s do `pull_history` antigo. Em timeout, devolve `partial=True` com o que coletou.

### 1.3 Fallback chain

```
ReportService.trigger_generate(user_id, mode='last_n_per_chat', n_per_chat=30):
    1. Tenta query local captured_messages.query_window_for_user(user_id, last_n=n_per_chat per chat)
       → se >= 1 mensagem total: usa essa.
    2. Se < 1 ou sem captured: busca sessão ativa do user → pull_last_n_per_chat(token, n_per_chat)
    3. Se isso também falhar: ExtractedPayload(message_count=0, ...) e o worker
       persiste insufficient (NÃO failed) — relatório aparece com diagnostic_summary
       explicando "nenhuma mensagem disponível, verifique conexão".
```

A leitura local de captured_messages permanece como atalho rápido (quando webhook funcionou). Não muda de schema — só muda de "filtro por dias" para "ordenar por ts desc, limit n_per_chat por chat".

## 2. Prompts

### 2.1 BASE_SYSTEM relaxado

**Antes (atual)**:
> NUNCA invente. Devolva array vazio se não tem evidência.

**Depois**:
> Análise sobre dados reais. Quando a amostra for pequena (1-30 msgs por conversa, 1-N conversas), produza um `diagnostic_summary` qualitativo e útil baseado no que conseguir ler. Se houver leads reais com follow-up perdido, liste-os. Se não houver, opportunities=[]. Mesma lógica pra objections/faqs. **Sempre devolva um relatório válido com a tool — nunca recuse.**

### 2.2 Novo campo `scope_warning`

Adicionado ao `LLM_TOOL_SCHEMA`:

```json
"scope_warning": {
  "type": ["string", "null"],
  "description": "Quando o WhatsApp claramente NÃO é de clínica de saúde/odontologia, preencha com 1 sentença descrevendo o segmento real detectado (ex: 'Atendimento de pet shop'). Use null quando for saúde/odonto OU quando não conseguir classificar."
}
```

Renderizado no frontend como Banner amarelo acima do HeroCard.

### 2.3 Segment addendums

`saude.py` e `odonto.py` permanecem. `outro.py` ganha instrução explícita:

> Especialidade não classificada — provavelmente NÃO é saúde. Use o `scope_warning` pra avisar o lead sobre o segmento detectado, MAS faça a análise mesmo assim com tom genérico de consultoria comercial (funil, tempo de resposta, oportunidades) — esses indicadores valem pra qualquer atendimento.

## 3. Worker / Service

### 3.1 `_inner` short-circuit relaxado

```diff
- if message_count < 5 or conversation_count == 0:
+ if message_count == 0:
```

Quando `message_count=0`: persiste `data_quality=insufficient` com diagnostic explicando + arrays vazios. **Não chama LLM**, evita custo.

Quando `1 <= message_count < 5`: chama LLM normalmente. O prompt já instrui a tratar sample pequena.

### 3.2 `_build_and_run` aceita mode

```python
async def trigger_generate(
    self, user_id, *,
    mode: Literal['last_n_per_chat', 'window_days'] = 'last_n_per_chat',
    n_per_chat: int = 30,
    period_days: int = 30,  # mantido pra compat com modal antigo
) -> UUID:
    ...
```

`_build_and_run` despacha:

- `mode='last_n_per_chat'` → captured_messages.query_last_n_per_chat(user_id, n_per_chat) → senão → pull_last_n_per_chat(token, n_per_chat).
- `mode='window_days'` → caminho antigo intacto (retrocompat — pode aposentar depois).

### 3.3 captured_messages repo

Novo método:

```python
async def query_last_n_per_chat(user_id: UUID, *, n_per_chat: int = 30) -> list[CapturedMessage]:
    """
    SELECT * FROM captured_messages
    WHERE user_id = $1
    ORDER BY wa_chatid, ts DESC
    -- post-process: keep only first N per wa_chatid
    """
```

Implementação simples: puxa tudo do user (último window grande, ex 90d), agrupa em Python, mantém top-N por chat. Em produção com volume virar window function.

## 4. Endpoint

`POST /api/reports/generate` aceita body novo (retrocompat):

```json
{
  "mode": "last_n_per_chat",     // novo, default
  "n_per_chat": 30,              // novo, default 30
  "period_days": 30              // antigo, ignorado se mode=last_n_per_chat
}
```

Validações:
- `n_per_chat in [10, 20, 30, 50, 100]` (limita custo LLM).
- Rate limit mantido (1/min por user).
- Threshold mínimo eliminado — sempre dispara worker. Worker resolve "0 mensagens" como `insufficient`, não como `not_enough_data` 422.

## 5. Frontend

### 5.1 `GenerateReportModal`

Simplifica:

```
┌────────────────────────────────────┐
│ Gerar relatório                    │
├────────────────────────────────────┤
│                                    │
│  Vamos analisar as últimas         │
│  30 mensagens de cada conversa     │
│  do seu WhatsApp.                  │
│                                    │
│  Quantas mensagens por conversa?   │
│  ◯ 10  ◯ 20  ⬤ 30  ◯ 50           │
│                                    │
│           [ Gerar agora ]          │
└────────────────────────────────────┘
```

`generateReport()` no `lib/reports.js` muda assinatura:

```js
export async function generateReport({ n_per_chat = 30 } = {}) {
  return callApi('/api/reports/generate', {
    method: 'POST', auth: true,
    body: { mode: 'last_n_per_chat', n_per_chat },
  });
}
```

### 5.2 `ReportGeneratingState` (logado)

Adiciona prop `liveStats` vindo de hook novo `useLiveExtractStats(reportId)`:

```js
function useLiveExtractStats(reportId, enabled) {
  // pola /api/whatsapp/uazapi-stats a cada 2.5s enquanto report status != terminal
  // retorna { chat_count, message_count, source: 'live'|'snapshot' }
}
```

Render: substitui os PHASES fake por:

```
🟠 Coletando do WhatsApp…
   47 conversas detectadas
   1.234 mensagens lidas

🟠 IA analisando…
   sample de 30 conversas → Claude
```

### 5.3 `GeneratingScreen` (público, pós-LeadForm)

Mesmo padrão — pollar `/api/whatsapp/uazapi-stats` enquanto o relatório é criado. O timer fake `GEN_STEPS` vai pro lixo.

### 5.4 `ReportDetailPage` — banner fora-de-escopo

Render extra acima do HeroCard quando `payload.scope_warning`:

```jsx
{payload.scope_warning && (
  <ScopeWarningBanner text={payload.scope_warning} />
)}
```

`ScopeWarningBanner` = card amarelo, ícone Info, copy: "Detectamos: {text}. Nossa análise é otimizada pra saúde, mas geramos um diagnóstico genérico do seu atendimento."

## 6. Observabilidade

Logs padronizados (qualquer pipeline run):

```
worker.report.enter        → user_id, mode, n_per_chat, captured_count_local
service.reports.collect    → source=captured_local|uazapi_live, chat_count, message_count
service.reports.payload    → conversations=N, messages=M, msgs_per_chat_avg=K
worker.report.llm_call.*   → already exists
worker.report.exit         → status, message_count, score, elapsed_ms
```

Cada log carrega `report_id` pra grep fácil.

## 7. Migração / Compat

- Schema DB: **nenhuma migration nova**.
- API: `period_days` no body do `/generate` mantido pra não quebrar requests pendentes; ignorado quando `mode=last_n_per_chat`.
- Front: `lib/reports.js` muda assinatura (uso interno único — só o modal).

## 8. Trade-offs aceitos

- **Cobertura por conversa fica capada em 30 msgs.** Conversas longas (50+ trocas) viram amostra. Aceitável: o relatório é diagnóstico comercial, não auditoria forense.
- **Custo LLM cresce com nº de chats.** 71 chats × 30 msgs = ~2.130 msgs de contexto. Sampling no `sample_conversations` (já existe) corta pro budget Claude.
- **`scope_warning` é heurística do LLM.** Pode errar (falso positivo/negativo). Aceitável — é só um banner, o relatório existe nos dois casos.
