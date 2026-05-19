# F8 — Design

## Componentes a tocar

### 1. `whatsapp/service.py::_handle_connection_event`

Quando `logged_in is True`, ADICIONAR:

```python
# F8: pre-generate report em background (não bloqueia o handler).
# Roda enquanto user preenche LeadForm pra entregar relatório
# instantâneo quando ele completar signup.
asyncio.create_task(
    _kick_off_pre_generate(session_id),
    name=f"pre-generate-{session_id}",
)
```

### 2. NOVA fn `_kick_off_pre_generate(session_id)` em `whatsapp/service.py`

Idempotência: se já existe row de report pra essa session, não cria outra.

```python
async def _kick_off_pre_generate(session_id: UUID) -> None:
    from app.modules.reports import repository as reports_repo
    from app.modules.reports.service import _build_and_run_with_timeout

    try:
        # Idempotência: se já existe (webhook duplicado), skip.
        existing = await reports_repo.get_existing_for_session(session_id)
        if existing is not None:
            logger.info("service.pre_generate.already_exists", ...)
            return

        # Cria row anônima (user_id=NULL — será linkado no signup).
        report_id = await reports_repo.create_generating(
            whatsapp_session_id=session_id,
            user_id=None,
            clinic_segment="outro",  # default, será atualizado no link
        )

        # Resolve uazapi token via DB (sem user_id).
        whatsapp_session = await whatsapp_repo.get(session_id)
        if whatsapp_session is None:
            logger.warning("pre_generate: session sumiu", ...)
            return

        # Dispara o pipeline com user_id=None.
        asyncio.create_task(
            _build_and_run_with_timeout(
                report_id=report_id,
                user_id=None,  # ⚠️ NOVO: pipeline aceita None
                mode="last_n_per_chat",
                n_per_chat=30,
                whatsapp_session_id=session_id,
            ),
        )
    except Exception:
        logger.exception("pre_generate.failed", ...)
```

### 3. `reports/service.py::_build_and_run` — aceitar `user_id=None`

Atualmente recebe `user_id: UUID` (não None). Mudar pra `UUID | None`.

Onde usa user_id:
- `captured_repo.query_last_n_per_chat(user_id)` → sem user_id não tem captured (webhook recém-ligou). Pular esse path e ir direto pro uazapi fallback.
- `_try_uazapi_last_n(user_id, ...)` → precisa de `whatsapp_repo.get_active_for_user(user_id)` que retorna a session. Quando user_id=None, usar `whatsapp_session_id` direto via novo helper `get_session_by_id`.

Novo helper:
```python
async def _try_uazapi_last_n_by_session(session_id, report_id, n_per_chat):
    """Versão anônima: usa session_id direto, sem precisar de user_id."""
    session = await whatsapp_repo.get(session_id)
    if session and session.get("uazapi_token"):
        ...
```

### 4. `reports/repository.py::create_generating` — aceitar `user_id=None`

Provavelmente já aceita (campo é nullable). Confirmar e ajustar tipo se preciso.

### 5. `whatsapp/service.py::consume_extracted` — linkar pre-report

Já temos:
```python
existing = await reports_repo.get_existing_for_session(session_id)
if existing is not None:
    await reports_repo.link_user(session_id, user_id)
```

Esse `link_user` precisa também atualizar `clinic_segment` se o user tem profile com `clinic_segment` setado (vai vir como default 'outro' no pre-generate; user pode ter selecionado no LeadForm).

Adicionar:
```python
# Resolve segment do users_profile (acabou de ser criado no signup).
clinic_segment = await _resolve_clinic_segment(user_id)
await reports_repo.link_user_and_segment(session_id, user_id, clinic_segment)
```

### 6. Frontend: simplificar `LeadFormScreen.handleSubmit`

Remover warmup (`waitForUazapiReady`) — não precisa mais. Não chamar `generateReport` pós-signup.

```js
// signup OK + setSession
onSubmit?.(payload);

// F8: pre-generate já rodou em background. Vai direto pro relatório.
navigate('/app/reports/latest');
```

`/app/reports/latest` retorna o report pre-gerado (linkado via consume_extracted).

## Edge cases

| Cenário | Comportamento |
|---|---|
| Webhook 'connected' duplicado | `get_existing_for_session` retorna existing → skip create |
| User abandona signup | Row órfã user_id=NULL. TTL futuro limpa. Aceitável. |
| Pre-generate falha (uazapi down persistente) | Status=failed na row. Signup linka mesmo assim. Frontend mostra failed → user clica "Gerar de novo" (mesmo botão manual). |
| Signup chega antes do pre-generate terminar | Row tá em `generating`. Frontend polla normal. Termina em ~10-25s (menos do que F7v2 atual). |
| `_resolve_clinic_segment` no kickoff (sem user) | Usa default 'outro'. Worker honra esse default — não chama LLM com outro segmento. Quando linkar pós-signup, NÃO regenera (custo). Banner scope_warning compensa se LLM identificou segmento real. |

## Migration

Nenhuma migration de schema necessária — `reports.user_id` já é nullable.

## Tests

Skip por hora (smoke E2E em prod já valida).

## Métricas pra observar

- `service.pre_generate.dispatched` (count por dia)
- `service.consume_extracted.linked_pre_report` (count por dia)
- Razão linked/dispatched = taxa de conversão signup
- Tempo médio entre `pre_generate.dispatched` e `worker.report.exit` (gargalo? warmup uazapi domina)
