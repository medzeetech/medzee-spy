---
name: feedback-uazapi-last-n-per-chat
description: uazapi paid não entrega histórico antigo por filtro temporal — use "últimas N msgs por conversa"
metadata:
  type: feedback
---

uazapi paid (`naorpedroza.uazapi.com`) **não entrega histórico antigo via filtro de cutoff_ts**. `/chat/find` lista conversas; `/message/history-sync` popula o cache; `/message/find` lê o que foi sincronizado — mas a sincronização é limitada às últimas N mensagens por chat (não retroativa). Filtrar por dias (window_days=30) descartava quase tudo.

**Why:** Empiricamente confirmado em 2026-05-18 pelo user — após 25+ commits tentando consertar pull_history(days_window), F5 abandonou o filtro temporal em favor de "últimas N msgs de CADA conversa" (default 30). Funciona em qualquer tier.

**How to apply:** Em qualquer feature que precise puxar histórico do uazapi:
- **NÃO** chame `/chat/find` + `/message/find` com filtro temporal esperando histórico antigo.
- **CHAME** `/message/history-sync count=N` (força populate) → espere ~6s → `/message/find limit=N offset=0` (single page, devolve mais recentes primeiro).
- Pipeline canônico: `app/workers/extract.py::pull_last_n_per_chat`. Reuse em vez de reimplementar.
- Vide [[project-stack]] §F5 e ENDPOINT_AUDIT_2026-05-18.md pra detalhes do contrato real (`wa_chatid`, `wa_isGroup`, `wa_lastMsgTimestamp`).
