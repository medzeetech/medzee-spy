# F8 — Chrome Extension Ingestion · Context

**Gathered:** 2026-05-24
**Spec:** `.specs/features/f8-chrome-extension-ingestion/spec.md`
**Status:** Ready for design

---

## Feature Boundary

Pivô do provider WhatsApp: substituir uazapi (instável puxando histórico) por **Chrome Extension MV3** que lê WhatsApp Web na sessão real do user e envia últimos 30 dias direto pro backend. Sem cliente WhatsApp no servidor, sem Baileys, sem QR no /spy.

Mantido: pipeline F3 (worker Claude), schema `medzee_spy.reports`, auth F2, F6 DX.

---

## Implementation Decisions

### Arquitetura do provider

- **Caminho B (decidido)**: extensão Chrome é O cliente WhatsApp. Backend só recebe POST batch.
- Sem Baileys/whatsapp-web.js no servidor.
- uazapi vira opcional atrás de feature flag `WHATSAPP_PROVIDER=extension|uazapi` (default `extension`).
- Cleanup definitivo do código uazapi: **fora deste milestone** (mantém rollback).

### Fluxo de cadastro vs. extração

- **Ordem invertida** vs. F1/F4/F5: cadastro **primeiro**, extração **depois**.
- Trade-off aceito: perde "wow factor" de ver QR funcionando antes do cadastro, mas ganha simplicidade brutal no backend (sem session anônima + bind posterior).
- Implementação:
  1. `/spy` → cadastro (mesmo formulário do LeadForm atual)
  2. Backend gera `extension_pairing_token` (JWT 15min TTL) vinculado ao novo `user_id`
  3. Frontend injeta token em `window.medzee_spy` + `localStorage`
  4. Tela "Instale a extensão" com link Chrome Web Store
  5. Extensão lê token na primeira execução → `POST /api/extension/pair` troca por refresh-token persistente
  6. Frontend transiciona pra "Analisar meu WhatsApp"

### Trigger da extração (UX)

- **Auto-detecção da extensão**: `window.postMessage({type:'medzee:probe'})` com timeout 500ms.
- Se instalada **E pareada**: pula tela de install, vai direto pra "Analisar meu WhatsApp".
- Se instalada **mas não pareada**: dispara pairing silencioso (se token ainda válido).
- Se não instalada: CTA "Instalar extensão".
- Extração inicia quando user clica "Analisar meu WhatsApp" → extensão abre `web.whatsapp.com` (se necessário) → coleta → POST batch.

### Mobile

- **Bloqueio total** + redirect com mensagem clara.
- `MobileBlockScreen` detecta UA mobile e mostra: "A análise roda só no Chrome desktop. Abra esse link no seu computador: medzee.com/spy" + botão "Copiar link" + CTA secundário "Enviar pro meu email" (capture-only, sem envio no MVP).
- Nova tabela `medzee_spy.mobile_redirect_leads(email, user_agent, created_at)` pra retargeting futuro.
- Sem fallback via Baileys/QR — bloqueio brutalista, simples.

### Source da coleta no WhatsApp Web

- **Primário**: IndexedDB do WhatsApp Web (`wawc` database, store `message`).
- **Fallback**: scraping do DOM (mais lento, menos confiável; só se IndexedDB falhar).
- Filtro: últimos 30 dias por `ts` (timestamp do WhatsApp).
- Escopo: TODAS as conversas (sem distinção entre individual/grupo no MVP).

### Wire shape extensão → backend

- Batch size: **1000 msgs por POST** (chunked se > 1000).
- Endpoint: `POST /api/extension/messages` com body `{batch_id, batch_index, total_batches, messages: [...]}`.
- Header: `Authorization: Bearer <refresh-token>` + `X-Extension-Version: 1.0.0`.
- Backend responde `202 Accepted` durante recebimento, dispara worker F3 só após `batch_index == total_batches - 1`.
- Mensagens reaproveitam estrutura `captured_messages` (mesma tabela do F4, novo campo `source='extension'`).

### Tratamento de WhatsApp Web não-logado

- Extensão detecta tela de QR via DOM selector (`div[data-testid="qrcode"]` ou equivalente).
- Posta `{type:'medzee:wa_needs_login'}` pro frontend.
- Frontend mostra "Logue no WhatsApp Web aqui →" com botão "Já loguei, tentar de novo".
- Sem timeout — user controla quando voltar.

### Re-extração

- User clica "Atualizar análise" em `/app/reports` → extensão re-coleta.
- Cada extração gera **novo relatório** (não atualiza o anterior) — preserva histórico.
- Rate limit: 1 análise / 60s por user (reusar limit existente do F4).

### Versionamento

- MVP usa `X-Extension-Version: 1.0.0` mas backend ainda não bloqueia versões antigas.
- Bloqueio (`409 extension_outdated`) é P3 — fica pronto pra ativar quando lançarmos v2.

---

## Agent's Discretion (resolvido no Design 2026-05-24)

Áreas que o user disse "você decide", agora travadas em [design.md](./design.md):

- **Implementação técnica da extensão** → MV3 + Vite + TypeScript + service worker + 2 content scripts (probe/collector) + page-world inject com `@wppconnect/wa-js`. Vide design §4.10.
- **Auth state da extensão** → `chrome.storage.local` (não `sync`, quota 100KB insuficiente); refresh_token JWT 30d. Vide §4.2/§7.
- **Estrutura do payload** → `ExtensionMessage` Pydantic com shape determinístico; chunked 1000/batch. Vide §4.2 schemas.
- **Detecção mobile** → hook `useIsMobile` em `frontend/src/lib/device.js` lendo UA + `matchMedia('(pointer:coarse)')`. Sem dep externa.
- **Side-load em dev** → padrão Chrome MV3 (`chrome://extensions` → Load unpacked → `extension/dist/`).

## User Decisions (2026-05-24)

Respostas às 5 open questions do design:

| Pergunta | Resposta |
|---|---|
| Distribuição | **Chrome Web Store** (público, review ~3 dias) |
| Re-emissão de pairing_token | **Sim** — `POST /api/auth/me/extension-pairing-token`, idempotente, JWT user-auth (CHX-15) |
| Sentry/observability | **Sim** — endpoint `/api/extension/telemetry` + tabela própria, sem PII, rate-limit 60/min (CHX-16) |
| Ícones / branding | **Reaproveitar `frontend/src/assets/logo-medzee-spy.svg`** → rasterizar via `sharp` no build (CHX-17) |
| Email no `mobile_redirect_leads` | **Capture-only** no MVP, send fica pra M3 |

---

## Specific References

- **D1, D8 (STATE.md)**: arquitetura provider-agnostic já existe (`app/clients/whatsapp/__init__.py` Protocol). F8 adiciona novo adapter `extension.py` que **não fala WhatsApp** — só recebe payload já parseado. Reaproveitar Strategy pattern.
- **D10 (STATE.md)**: "relatório sempre gera". F8 mantém — quando 0 msgs do WhatsApp Web, gera relatório com `data_quality=insufficient` + banner amarelo. Nunca 422.
- **L14 (STATE.md)**: "não dispare cleanup automático em erro transitório". F8 evita o problema na origem — extensão não tem "instância" a deletar. `_fail` no worker F3 fica intacto.
- **L11 (STATE.md)**: PostgREST + on_conflict + partial unique. Reaproveitar fix do F4 (plain INSERT + dedup batch Python + fallback 23505).
- Padrão Chrome MV3 oficial: <https://developer.chrome.com/docs/extensions/develop/migrate>

---

## Deferred Ideas

Ideias que apareceram na discussão mas ficam fora do F8:

- **Recurring reports / auto-update** — mover pra M2 conforme ROADMAP já planejado.
- **Multi-WhatsApp por user** (recepção 1, recepção 2) — Future Considerations do ROADMAP.
- **Firefox/Safari/Edge support** — reaproveitar Manifest V3 mas exige porting; M3.
- **Mobile via PWA/app nativo** — futuro, sem timeline.
- **Push notification da extensão** ("seu relatório terminou") — adiado, polling 5s no MVP.
- **Cleanup definitivo do uazapi** — feito em PR separado após smoke da F8 em prod.
- **Migração de relatórios antigos pro novo wire shape** — clean slate, não migra.
- **Detecção automática de novo período** ("último mês mudou, gerar de novo?") — recurring reports M2.
- **Email send no `mobile_redirect_leads`** — capture-only no MVP; envio real é growth-feature M2.
- **Suporte a WhatsApp Business multi-conta** — fora de escopo.
