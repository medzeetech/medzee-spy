---
name: feedback-signup-auto-generate
description: Signup deve disparar relatório automaticamente — clique manual é fricção que mata a proposta de valor
metadata:
  type: feedback
---

User explicitamente flagged em 2026-05-19 como bug crítico ("precisamos consertar! pois é o coração do nosso projeto"):

> Como F1 (auto-extract) está deprecated e o /reports/latest retorna 404 (sem placeholder), o flow correto agora é: signup → vai pra dashboard → clica "Gerar relatório" manualmente.

**Why:** A promessa de valor do Medzee Spy é "scan QR → relatório PRONTO em poucos minutos, automaticamente". Forçar clique manual em "Gerar relatório" pós-signup quebra essa promessa — user já se comprometeu (deu nome, email, telefone, senha) esperando ver o relatório imediatamente, não uma lista vazia.

**How to apply:** Em QUALQUER fluxo onde a proposta de valor exige um output automático (Spy: relatório, News: triagem, futuro: outros), o trigger do output deve ser parte ATÔMICA do fluxo de onboarding — não uma ação manual extra. Aceitar latência (15-30s no caso F5) mostrando estado intermediário ("Gerando…") é OK; pedir clique extra após o user já ter pagado o custo do signup NÃO é.

Padrão escolhido (D11 em STATE.md): orquestração no frontend após signup (`signup → generate → navigate`). Backend mantém boundaries (`auth` ≠ `reports`). Fallback graceful se generate falhar — não bloqueia signup. Vide [[project-stack]] §LeadFormScreen handleSubmit.
