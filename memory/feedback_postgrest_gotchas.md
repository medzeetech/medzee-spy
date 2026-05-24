---
name: feedback-postgrest-gotchas
description: PostgREST/supabase-py tem 3 armadilhas silenciosas — exija count="exact", evite on_conflict com partial index, sempre limite explícito
metadata:
  type: feedback
---

3 armadilhas do PostgREST/supabase-py que causaram bugs visíveis em produção no Medzee Spy (smoke 2026-05-19, ver STATE.md L11-L13):

1. **`.upsert(on_conflict='col1,col2')` quebra com índice unique PARTIAL**.
   PostgREST traduz pra `ON CONFLICT (cols)` que exige índice unique **não-partial**. Se a tabela tem `CREATE UNIQUE INDEX ... WHERE x IS NOT NULL`, o insert estoura `APIError 42P10 — there is no unique or exclusion constraint matching`. **Como aplicar**: pra deduplicação contra partial index, use `INSERT` plain + dedup batch em Python + fallback row-by-row no `23505 unique_violation`. O índice partial fica como defesa em profundidade.

2. **`.select(...)` SEM `count="exact"` retorna no máximo 1000 rows e `len(rows)` mente**.
   PostgREST default `Range: 0-999`. Se você conta `len(rows)` pra obter total, vai dizer 1000 mesmo com 50k linhas no DB. **Como aplicar**: pra COUNT real use `.select(cols, count="exact").limit(N).execute()` e leia `result.count` (PostgREST manda header `Prefer: count=exact`). Pra amostras grandes, sempre passe `.limit()` explícito.

3. **Top-N por grupo em Python = falha quando 1 grupo domina**.
   Combinado com (2): se você tenta top-N agrupando em Python depois de `.select().order(group_col)`, e 1 grupo tem milhares de rows, ele sozinho ocupa todo o budget de 1000 — outros grupos somem da amostra. **Como aplicar**: top-N por grupo em volume não-trivial = window function PostgreSQL via RPC (`ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ... DESC) WHERE rn <= N`), nunca em Python depois de `.select`.

**Why:** 3 sintomas em produção causados pelos 3 issues: webhook perdia 100% das msgs (1), dashboard exibia "1.000 mensagens" com 8.6k reais (2), relatório sempre dava "10 msgs em 2 conversas" mesmo com 47 chats (3). Os 3 fixes em [[project-stack]] resolveram tudo (commits `3ca748e`, `fe1ea8c`, `ad64b99`).

**How to apply:** Toda nova query Supabase no projeto: (a) se faz dedup → não use on_conflict com partial, (b) se precisa de count → use count="exact", (c) se top-N por grupo com >1k rows → use RPC com window function.
