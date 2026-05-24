# Testing

## Estado atual
- Apenas pytest configurado no backend (`requirements.txt`) e `app/tests/conftest.py` com fixture `client` (`TestClient(app)`).
- **Nenhum teste real escrito**.
- Frontend não tem framework de teste (`package.json` sem `vitest`/`jest`/testing-library).
- Sem CI configurada.

## Matriz alvo M1

| Camada                                  | Tipo                | Ferramenta             | Quando criar          |
| --------------------------------------- | ------------------- | ---------------------- | --------------------- |
| Endpoints FastAPI (auth, reports, wpp)  | Integração          | pytest + httpx ASGI    | Por endpoint, em F2-F3 |
| Services (regra de negócio)             | Unit                | pytest                 | Por service           |
| Repositories (Supabase)                 | Não testar direto*  | —                      | Mockar via service    |
| LLM client                              | Unit + fake adapter | pytest                 | Em F3                 |
| Sidecar Baileys                         | Manual + smoke      | scripts/curl           | F1                    |
| Frontend (telas críticas)               | Componente leve     | _(adiar para v2)_      | —                     |

\* RLS e schema do Supabase são testados manualmente via migrations + `supabase db reset` local.

## Gate commands
- Backend: `pytest -q` (a partir de `backend/`).
- Frontend: `npm run lint` (a partir de `frontend/`).
- Sidecar: `npm run build && npm test` (quando existir).

## Princípios
- Toda task que toca endpoint cria pelo menos 1 teste de integração (caminho feliz + 1 erro).
- Fixtures que envolvem Supabase devem usar instância de teste local (`supabase start`) — não bater no Supabase compartilhado durante CI.
- Testes ficam em `backend/app/tests/<module>/test_*.py` espelhando `app/modules/<module>/`.
