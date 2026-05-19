# F7 — Tasks

Branch: `feat/f7-auto-generate-on-signup` (criada a partir de `feat/f4-forward-capture`).

## Implementação (atômica)

- **F7-1** `LeadFormScreen.handleSubmit`: importar `generateReport` de `../lib/reports.js`.
- **F7-2** Após `setSession` + `onSubmit`, se `whatsappSessionId != null`, disparar `generateReport({n_per_chat: 30})` dentro de try/catch.
- **F7-3** Em sucesso, `navigate(\`/app/reports/${report_id}\`)` (substitui o `/app/reports/latest` atual).
- **F7-4** Em falha do generate, log + fallback `navigate('/app/reports/latest')`.
- **F7-5** Sem `whatsappSessionId`, `navigate('/app/dashboard')` (caminho raro mas defensivo).
- **F7-6** Spinner do botão "Criar conta e ver relatório" continua até navegação real — não solta antes.

## Docs

- **F7-7** Atualizar `ROADMAP.md`: F7 como milestone de UX crítico.
- **F7-8** Atualizar `STATE.md`: D11 (decisão de orquestrar no frontend, não no backend).
- **F7-9** Memory: nova entrada `feedback_signup_auto_generate.md` reforçando que o relatório DEVE existir imediatamente pós-signup (não exigir clique manual).

## Commit + push

- **F7-10** Commit único (mudança pequena e atômica), push em `feat/f7-auto-generate-on-signup`. Merge em `dev` quando smoke validar.
