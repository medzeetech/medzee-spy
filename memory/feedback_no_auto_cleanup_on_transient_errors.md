---
name: feedback-no-auto-cleanup-on-transient-errors
description: Não dispare cleanup destrutivo automático em resposta a erros transitórios — preserve recursos e deixe o caller decidir
metadata:
  type: feedback
---

No Medzee Spy (smoke 2026-05-19, STATE.md L14), o `extract.py::_fail` chamava `provider.delete_instance(token)` em QUALQUER falha do pipeline (incluindo `UazapiUnavailable` que vem de um 500 transitório do `/chat/find`). Resultado: toda instância morria 1-2min após cada conexão porque uazapi free devolve 500 no `/chat/find` durante history sync inicial. User precisava re-scanear QR a cada tentativa.

**Why:** Cleanup automático em path de erro só faz sentido quando o erro é DEFINITIVO (banido, recurso destruído server-side, etc). Pra erros transitórios, destruir o recurso amplifica o problema — força o user a reconstruir tudo do zero.

**How to apply:** Em qualquer feature que tenha cleanup automático no caminho de erro (delete, drop, reset, force-close), faça matriz `code → ação`:
- `banned` / `definitive` → deleta
- `unavailable` / `timeout` / `unknown` / `transient` → preserva o recurso, só publica evento de falha e deixa o caller (ou retry humano) decidir
A regra no projeto agora: `_fail` em workers só deleta em `code='banned'` (commit `3ca748e`). Mesmo padrão pra próximas features de cleanup automático.
