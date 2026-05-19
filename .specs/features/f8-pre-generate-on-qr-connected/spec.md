# F8 — Pre-Generate Report on QR Connected

## Why

F7v2 disparava o relatório **DEPOIS do signup**. User esperava +30s ("Sincronizando…") + 15-30s (LLM). Total ~45-60s parado vendo loading.

User feedback (2026-05-19):
> "apos o usuario ler o qr ele ainda vai preencher uns dados, é nesse momento apos ele ler o qr que deve ser disparado o relatorio, obter as conversa, mensagens gerar o relatorio, nao esperar inicializar, tem que ser a partir do create da instancia, instantaneo"

**Insight**: o user gasta 30-90s preenchendo LeadForm. Esse tempo é DESPERDIÇADO hoje (frontend só fica esperando). Vamos aproveitar pra **pré-gerar o relatório em background** enquanto ele digita. Quando ele terminar signup, o relatório provavelmente **já está pronto**.

## What

### Fluxo novo
```
1. /spy → QR scan → uazapi webhook 'connected' chega no backend
2. ⚡ NOVO: backend cria row reports(user_id=NULL, session_id=X) e
   dispara worker async (warmup uazapi + pull + LLM)
3. Usuário preenche LeadForm (30-90s — em paralelo, pipeline roda)
4. Usuário completa signup
5. Backend signup → consume_extracted:
   - linka whatsapp_sessions.user_id (já existe)
   - ⚡ NOVO: linka reports.user_id (na row criada em #2)
6. Frontend pós-signup navega pra /app/reports/latest
   - Se status=completed → mostra relatório IMEDIATAMENTE
   - Se status=generating → polling normal, mas geralmente termina < 5s
```

### Tempo esperado (caminho feliz)

| Tempo absoluto | Evento |
|---|---|
| t=0 | QR scaneado → webhook 'connected' |
| t=0 | Backend cria row + dispara pre-generate |
| t=0-30s | User começa preencher LeadForm step 1 |
| t=15s | uazapi warmup OK |
| t=20s | LLM começa |
| t=35s | Pipeline completo → status=completed |
| t=40-90s | User digita senha + clica "Criar conta" |
| t=t+1s | signup OK, navega /app/reports/latest |
| t=t+1s | Renderiza relatório **PRONTO** (sem espera!) |

### Vs fluxo atual (F7v2)

| Métrica | F7v2 | F8 |
|---|---|---|
| Tempo entre signup e relatório visível | 30-60s | **~1s** (já pronto) |
| Bytes de UX "loading" | tela "Sincronizando 30s" + tela "Gerando 30s" | nenhuma |
| Latência total (QR → relatório) | t_form + 60s | **t_form** (sobreposto) |

## Acceptance criteria

- [ ] **AC1** — Webhook 'connected' chegou → backend cria row reports anônima e log mostra `pre_generate.dispatched`
- [ ] **AC2** — Worker corre normalmente (warmup uazapi + pull + LLM + persist), persiste payload completo na row anônima
- [ ] **AC3** — User completa signup → `consume_extracted` linka user_id na row de report. Log mostra `consume_extracted.linked_pre_report`
- [ ] **AC4** — `/api/reports/latest` retorna o relatório pre-gerado (com user_id linkado), status=completed
- [ ] **AC5** — Tempo entre signup OK e relatório visível ≤ 5s no caminho feliz (vs 30-60s do F7v2)
- [ ] **AC6** — Se pre-generate falhar (uazapi 500 persistente), row fica com status=failed. Signup linka mesmo assim. Frontend mostra empty state com CTA "Gerar relatório" (mesmo caminho do botão manual).
- [ ] **AC7** — User abandona signup (não completa) → row órfã com user_id=NULL fica no DB. TTL cleanup (futuro) ou apenas aceitar como "lead que não converteu".

## Out of scope (por enquanto)

- Reaproveitamento: se user re-scaneia QR depois (multi-session), não tenta linkar 2 reports pra mesma session.
- Cleanup automático de pre-reports órfãos > 24h (vai pra TODO futuro).
- F7v2 warmup polling: removido — não precisa mais pq o trabalho já rodou em background.

## Trade-offs aceitos

1. **Cost LLM**: user que abandonar signup queima 1 call do Claude. Aceitável no MVP — converter user vale muito mais que custo Claude (centavos).
2. **Race signup mais rápido que pre-generate**: se user é super rápido (digita em 10s), o pre-generate ainda está rodando quando signup completa. Frontend cai no fluxo de polling normal (~10-25s pra terminar). Pior caso = igual ao F7v2 atual.
3. **Webhook duplicado**: uazapi pode reenviar 'connected'. Backend precisa idempotência — checar se já existe row pre-gerada antes de criar outra.
