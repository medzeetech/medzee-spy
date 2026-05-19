---
name: feedback-pre-generate-on-connect
description: Aproveitar tempo que user gasta preenchendo form pra pré-gerar output em background (não esperar fim do signup)
metadata:
  type: feedback
---

User insight 2026-05-19 (F8): em qualquer fluxo de onboarding com (a) etapa rápida que gera trabalho assíncrono no backend e (b) etapas subsequentes de input do usuário, **dispare o trabalho assíncrono ASSIM QUE o trigger acontece**, não ao final do flow. Aproveite o tempo de UI do user pra rodar o pipeline em paralelo.

**Why**: a sequência tradicional "user completa tudo → backend trabalha → user vê output" desperdiça o tempo de preenchimento do user (30-90s típico) que poderia estar sendo usado pra coleta+processamento. Resultado dessa otimização: output IMEDIATO pós-último-clique (vs 30-60s de espera adicional).

**How to apply**: 
- Trigger = webhook/evento que confirma capacidade de gerar (ex: WhatsApp connected via uazapi)
- Crie row anônima (FK nullable) + dispare worker
- No último passo (ex: signup), linka FK ao user. Output já está pronto.
- Trade-off: queima recursos do worker pra users que abandonam o flow. Aceitável quando custo unitário (cents Claude API) << valor de converter o user.

Vide [[project-stack]] §F8 e .specs/features/f8-pre-generate-on-qr-connected/ pra implementação no Medzee Spy.
