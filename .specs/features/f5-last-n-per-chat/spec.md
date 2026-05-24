# F5 — Last-N Messages per Chat + Always-Generates Report

## Why

O fluxo atual (F4) está bloqueado:

1. **Pull por janela temporal (7/15/30/60 dias) não funciona consistentemente.** `uazapi` paid recusa entregar mensagens antigas — o cache só popula via `/message/history-sync`, e mesmo após sync o filtro por `cutoff_ts` descarta o que vem. Resultado: `payload.message_count == 0` na maioria das tentativas.
2. **Webhook `messages` não é confiável neste tier.** `captured_messages` fica vazia mesmo após o WhatsApp conectado e enviando msgs reais.
3. **Quando dá zero, o relatório morre.** Short-circuit "insufficient" persiste um payload vazio; LeadFormScreen / GeneratingScreen ficam girando; user não vê *nada* do que foi coletado nem chega a ler um relatório.
4. **UI mente.** GeneratingScreen mostra fases falsas com timer; user não enxerga "X conversas / Y mensagens lidas" em tempo real; quando o relatório falha o user só vê "Não conseguimos gerar".

O user explicitamente pediu:

> "ler qr code, obter conversas, obter mensagens, IA lê e gera relatório, exibe pro lead persistindo usuário... idependente do contexto, mas informando que se nao for contexto medico esta fora do escopo, mas faça o relatorio"

> "puxar as ultimas 30 mensagens de cada conversa"

## What

**MUDA**:

1. **Coleta por chat, não por janela temporal.** Para cada conversa retornada por `/chat/find`, dispara `/message/history-sync count=30` e lê as **últimas 30 mensagens** via `/message/find limit=30`. Sem cutoff por dias. Sem filtro por timestamp.
2. **Relatório SEMPRE gera.** Mesmo com poucas mensagens (≥1), o LLM roda e devolve algo útil. Se a sample for muito pequena, o `diagnostic_summary` é explícito sobre isso, mas o relatório existe e é mostrado.
3. **Fora-de-escopo é informado, não bloqueante.** Se a IA detectar que não é saúde/odonto, devolve um campo `scope_warning` com o segmento detectado e o relatório vira "diagnóstico genérico de atendimento comercial" — em vez de relatório vazio.
4. **Observabilidade real.** `GeneratingScreen` (público, pós-LeadForm) e `ReportGeneratingState` (logado, on-demand) polam `/api/whatsapp/status` + `/api/whatsapp/uazapi-stats` e mostram: "Lendo 47 conversas… 1.234 mensagens coletadas… IA analisando…". Sem timer falso.

**MANTÉM**:

- Pipeline F3 (metrics determinísticas + sample + LLM + persist).
- Schema `medzee_spy.reports`.
- Auth F2.
- Webhook handler (continua persistindo em `captured_messages` quando funciona — só deixa de ser caminho crítico).

**REMOVE / DEPRECA**:

- Período 7/15/30/60 como input obrigatório no modal (vira preset opcional).
- Threshold rígido `REPORTS_GENERATE_MIN_MESSAGES=10` na route (vira ≥1).
- Short-circuit `< 5 mensagens` no worker (vira `< 1`, ou seja, só não chama LLM se for *zero* mesmo).
- Fallback `pull_history(days_window=N)` é substituído por `pull_last_n_per_chat(n_per_chat=N)`.

## Acceptance criteria

- [ ] **AC1** — User loga, vai pra `/app/reports`, clica "Gerar agora". Em ≤ 90s vê um relatório renderizado, com pelo menos `diagnostic_summary` preenchido + `funnel` + métricas determinísticas. Mesmo se só 1 conversa foi coletada.
- [ ] **AC2** — Enquanto o relatório gera, a tela de loading mostra: "X conversas detectadas · Y mensagens coletadas · IA analisando…" — atualizando a cada 2-3s.
- [ ] **AC3** — Se WhatsApp conectado for de um veterinário (não-saúde), o relatório aparece com banner amarelo no topo: "Detectamos atendimento veterinário — análise feita em modo genérico" + diagnóstico mesmo assim.
- [ ] **AC4** — Se a 1ª tentativa coletar 0 mensagens (history-sync falhou pra todo chat), o relatório aparece com `data_quality=insufficient` + `diagnostic_summary` honesto + botão "Tentar de novo" — não cai em FailedCard.
- [ ] **AC5** — No `/app/whatsapp` (dashboard logado), as contagens "conversas / mensagens" do `uazapiStats` aparecem em tempo real (já existe, valida que sobrevive ao refactor).
- [ ] **AC6** — Logs do backend, ao gerar 1 relatório, deixam visível: `chat_count=N`, `messages_collected=M`, `messages_per_chat_avg=K`, `llm_elapsed_ms=T`, `final_status=completed|partial|failed`.

## Out of scope

- Trocar provider WhatsApp (continua uazapi paid).
- Persistir mensagens (continua opt-in via webhook, mas não é caminho crítico).
- Geração recorrente automática.
- Multi-WhatsApp por user.
