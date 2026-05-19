# F8 — Tasks

Branch atual: `feat/f7-auto-generate-on-signup` (vou continuar aqui — pequeno, conceitualmente extensão do F7).

## Backend

- **F8-1** `reports/repository.py::create_generating`: aceitar `user_id: UUID | None`.
- **F8-2** `reports/service.py::_build_and_run` + `_build_and_run_with_timeout`: aceitar `user_id: UUID | None`.
- **F8-3** Novo `_try_uazapi_last_n_by_session(session_id, report_id, n_per_chat)` (path anônimo).
- **F8-4** `_build_and_run` desvio: quando `user_id is None`, pula `query_last_n_per_chat` e vai direto pro path uazapi via session.
- **F8-5** Novo `whatsapp/service.py::_kick_off_pre_generate(session_id)`: cria row anônima + dispara worker.
- **F8-6** `_handle_connection_event`: quando `logged_in is True`, `asyncio.create_task(_kick_off_pre_generate(session_id))`.
- **F8-7** `consume_extracted`: além de `reports_repo.link_user`, também atualiza `clinic_segment` resolved do users_profile (caso pre-generate tenha rodado com default 'outro').

## Frontend

- **F8-8** `LeadFormScreen.handleSubmit`: REMOVER warmup polling + generateReport dispatch. Só fazer signup + setSession + navigate `/app/reports/latest`.
- **F8-9** Limpar import `waitForUazapiReady` (não usado mais), `generateReport` (idem) e helpers relacionados.
- **F8-10** Remover state `submitPhase` (já que não tem fase "syncing" mais — só "creating").
- **F8-11** Botão volta pra simples "Criando conta…" durante submit.

## Docs

- **F8-12** ROADMAP.md: F8 entry. F7 marcado superseded.
- **F8-13** STATE.md: D12 (decisão pre-generate on connect em vez de pós-signup).
- **F8-14** Memory: feedback_pre_generate_on_connect.md.

## Commit + push

- **F8-15** Commit único (mudanças coordenadas backend/frontend). Push em `feat/f7-auto-generate-on-signup` (branch ativa) → merge em `dev`.
