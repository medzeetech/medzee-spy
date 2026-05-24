---
name: feedback-always-generate-report
description: User prefere relatório que sempre gera (mesmo fora-de-escopo) em vez de tela travada ou erro 422
metadata:
  type: feedback
---

User explicitamente pediu (2026-05-18) que o relatório do Medzee Spy **sempre gere algo**, independente do contexto:

> "idependente do contexto, mas informando que se nao for contexto medico esta fora do escopo, mas faça o relatorio, e exiba pro lead persistindo usuario"

**Why:** A versão anterior tinha 3 portões que matavam a UX (route 422 `not_enough_data`, worker short-circuit `< 5 msgs`, prompt instruindo recusa fora-de-saúde). Resultado: user conectava WhatsApp e via tela "gerando" infinita, sem nunca chegar num relatório — abandonava antes de ver valor. Pivot: relatório existe em todos os caminhos; aviso de fora-de-escopo vira banner amarelo (não bloqueante); shortcuts de "não vou gerar" foram removidos.

**How to apply:** Em qualquer feature futura do Medzee Spy onde houver tentação de adicionar threshold rígido / bloqueio / 422 por "dados insuficientes", **prefira persistir um output transparente** (com `data_quality=insufficient`, diagnostic explicando + arrays vazios) em vez de bloquear o usuário. O LLM tem instrução explícita pra produzir algo útil mesmo com sample mínima (vide [[project-stack]] §prompts/base.py F5 update). Banner > error page.
