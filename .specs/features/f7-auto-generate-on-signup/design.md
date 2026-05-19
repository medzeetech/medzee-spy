# F7 — Design

## Composição no frontend (não no backend)

A escolha é DELIBERADA. Alternativas consideradas:

1. **Backend dispara generate dentro de `signup`** — acoplaria `auth.service` a `reports.service`, criaria dependência circular, e impede o caso (raro) em que user só quer cadastro sem gerar. **Rejeitado.**
2. **Background task no FastAPI após signup retornar** — invisível pro frontend, sem report_id pra navegar imediato. **Rejeitado.**
3. **Frontend orquestra: signup → generate → navega** — caminho mais simples, mantém boundaries de módulo, frontend já tem helpers prontos. **Escolhido.** ✅

## Mudanças

### `frontend/src/screens/LeadFormScreen.jsx`

**Localização**: dentro de `handleSubmit`, logo após `setSession` bem-sucedido, antes de `navigate`.

**Pseudo-código**:

```js
try {
  const result = await api.signup(payload);
  if (result?.session?.access_token) {
    await supabase.auth.setSession({...});
  }
  onSubmit?.(payload);

  // F7: dispara generate imediatamente e navega pro report
  if (whatsappSessionId) {
    try {
      const { report_id } = await generateReport({ n_per_chat: 30 });
      navigate(`/app/reports/${report_id}`);
      return;
    } catch (e) {
      // Fallback graceful — não bloqueia signup
      console.warn('[F7] auto-generate failed, fallback latest', e);
      navigate('/app/reports/latest');
      return;
    }
  }

  // Sem session whatsapp — apenas cadastrou (caso raro de re-login?)
  navigate('/app/dashboard');
}
```

**Por que dentro do `handleSubmit`**: o user já está vendo o spinner "Criando conta…" — adicionar 200-500ms de generate dispatch não muda percepção, e garante navegação atômica.

### `frontend/src/lib/reports.js`

Sem mudanças — `generateReport()` já aceita `{n_per_chat}` e retorna `{report_id, status: 'generating'}`.

### `frontend/src/screens/ReportScreen.jsx` (fluxo público pré-cadastro)

Atualmente esse componente é renderizado quando `onSubmit` do LeadForm não navega — vira state final do MainFlow. Após F7, esse componente NÃO é mais alcançado no caminho feliz (sempre navegamos pra `/app/reports/{id}`). Vou deixar como dead-code-mas-vivo (não remover) — pode servir como fallback se `whatsappSessionId === null`.

### Backend

Sem mudanças. `POST /api/reports/generate` (F5) já trata:
- Sem captured_messages → `pull_last_n_per_chat` via uazapi (fallback transparente)
- Rate-limit 1/min por user (raríssimo bater no signup novo)
- Hard timeout 180s (commit `7cbcd1e`)

## Rate limit no signup novo

`REPORTS_GENERATE_RATE_S=60` por user. No fluxo de signup, é a PRIMEIRA chamada do user → bucket vazio → 0 risco de bater. Logs vão confirmar.

## Atomicidade

Pergunta: e se `signup` for OK mas `generate` falhar?

- User já tem conta válida (`auth.users` + `users_profile` + JWT setado)
- Frontend faz fallback pra `/app/reports/latest` (404 mostra empty state com CTA "Gerar relatório")
- User pode clicar "Gerar relatório" manualmente — mesma feature do `ReportsListPage`

Sem perda de dados, sem inconsistência. UX é o único sacrificado no edge case.

## SpyFlow vs MainFlow

Ambos usam `LeadFormScreen`. Como o fix vive no próprio componente, ambos ganham automaticamente. SpyFlow já passa `whatsappSessionId={whatsappSessionId}`; MainFlow também (via state local). ✅

## Observabilidade

Adicionar log explícito antes do generate:
```js
console.info('[F7] auto-generate dispatch', { whatsappSessionId, n_per_chat: 30 });
```

Pra rastrear no devtools quando user reporta "ficou na tela errada". Não é necessário backend — `route.reports.generate.dispatched` já existe.
