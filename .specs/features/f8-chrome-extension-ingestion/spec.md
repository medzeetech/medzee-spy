# F8 — Chrome Extension Ingestion (pivô do provider WhatsApp)

## Problem Statement

A coleta atual depende do **uazapi paid** que se mostrou instável puxando histórico de conversas: a sincronização (`/message/history-sync`) entrega resultados inconsistentes, instâncias morrem em 1-2min após `connected`, e o tier free não suporta `/chat/find`. O M1 funciona em smoke mas falha sob carga real — vide STATE.md L11–L14.

Resultado prático: relatórios falham silenciosamente ou demoram demais; a tese de produto (mostrar diagnóstico real do WhatsApp do médico) fica refém de uma SaaS terceira que não entrega.

**Pivô:** substituir o provider externo por uma **Chrome Extension MV3** que lê o WhatsApp Web aberto na sessão real do usuário (no browser dele) e envia os últimos 30 dias direto ao backend. Sem cliente WhatsApp no servidor. Sem Baileys. Sem uazapi.

## Goals

- [ ] **G1** — Coletar últimos 30 dias do WhatsApp do user **sem provider externo** e sem lib não-oficial server-side
- [ ] **G2** — Fluxo ponta-a-ponta completo (cadastro → instalação extensão → coleta → relatório) em ≤ 5 min do clique no `/spy`
- [ ] **G3** — Taxa de sucesso da coleta ≥ 95% no público-alvo (Chrome desktop com WhatsApp Web já logado)
- [ ] **G4** — Backend deixa de depender de uazapi (módulo vira opcional/deprecated atrás de feature flag)

## Out of Scope

| Item | Razão |
|---|---|
| Mobile (Android/iOS) | Chrome mobile não suporta extensões. Redirect com "em breve mobile". |
| Firefox / Safari / Edge | Chrome only neste milestone. Reaproveita Manifest V3 quando portarmos. |
| Re-uso do código uazapi | Será **deprecated atrás de feature flag** (`PROVIDER=uazapi|extension`), não removido neste milestone. Permite rollback. |
| Migration de relatórios antigos | Clean slate: relatórios pré-F8 ficam imutáveis no DB, novos vêm da extensão. |
| Auto-update de relatório (recurring) | Adiado pro M2. Cada extração é manual ("Atualizar análise"). |
| Multi-WhatsApp por user | Adiado. 1 user = 1 WhatsApp Web logado. |
| Push notification da extensão | Adiado. Extensão é stateless: dispara coleta sob comando do frontend. |

---

## User Stories

### P1: User cadastrado coleta WhatsApp via extensão e vê relatório ⭐ MVP

**User Story:** Como **médico/dono de clínica**, quero **conectar meu WhatsApp via extensão Chrome no meu desktop e receber um diagnóstico comercial dos últimos 30 dias**, sem depender de QR code nem app de terceiros.

**Why P1:** É o coração do pivô. Sem isso, F8 não entrega valor — a estabilidade da coleta é o motivo do pivô existir.

**Acceptance Criteria:**

1. **WHEN** user acessa `/spy` em Chrome desktop **THEN** sistema **SHALL** detectar browser e exibir tela de cadastro (sem QR — fluxo invertido vs. F1/F4/F5)
2. **WHEN** user completa cadastro (nome, email, senha, ticket médio) **THEN** sistema **SHALL** criar usuário no Supabase Auth + perfil em `users_profile` + emitir `extension_pairing_token` (JWT curto, 15min TTL)
3. **WHEN** cadastro completa **THEN** frontend **SHALL** transicionar para tela "Instale a extensão" com botão deep-link `chrome://webstore` (ou link de side-load durante dev) e o `extension_pairing_token` injetado no `localStorage` + `window.medzee_spy`
4. **WHEN** user instala extensão **AND** retorna ao `/spy/aguardando` **THEN** content-script da extensão **SHALL** ler `extension_pairing_token` do `window.medzee_spy` e fazer `POST /api/extension/pair` pra trocar token efêmero por refresh-token vinculado ao `user_id`
5. **WHEN** extensão está pareada **AND** user clica "Analisar meu WhatsApp" **THEN** extensão **SHALL** abrir nova aba em `https://web.whatsapp.com` (se não estiver aberta) e injetar content-script de coleta
6. **WHEN** content-script detecta WhatsApp Web logado (sessão ativa) **THEN** extensão **SHALL** ler IndexedDB do WhatsApp Web (`wawc`/`signal`) ou DOM (fallback) e extrair últimos 30 dias de todas as conversas
7. **WHEN** coleta termina **THEN** extensão **SHALL** fazer `POST /api/extension/messages` em batch (chunked a cada 1000 msgs) com payload `{user_id, batch_id, messages: [{wa_chatid, ts, sender, text, ...}]}`
8. **WHEN** backend recebe último batch **AND** worker F3 termina **THEN** frontend (poll 5s em `/api/reports/latest`) **SHALL** transicionar pra `/app/reports/:id` com relatório renderizado
9. **WHEN** user retorna depois e clica "Atualizar análise" **THEN** extensão **SHALL** re-coletar e backend **SHALL** gerar **novo** relatório (não atualiza o anterior — histórico preservado)

**Independent Test:** Em ambiente dev, com extensão side-loaded, completar fluxo: signup → install → web.whatsapp.com → ver relatório real em ≤ 5min. Métricas no DB confirmam `reports.status='completed'` + `captured_messages` populadas com `source='extension'`.

**Requirement IDs:** CHX-01, CHX-02, CHX-03, CHX-04, CHX-05, CHX-06

---

### P1: Bloqueio mobile com redirect claro ⭐ MVP

**User Story:** Como **médico acessando do celular**, quero **entender que a análise só roda no computador e voltar mais tarde**, em vez de ver tela quebrada.

**Why P1:** Mobile representa parcela significativa do tráfego de landing pages médicas; falhar silenciosamente perde lead. Decisão de produto: bloqueio total + mensagem clara.

**Acceptance Criteria:**

1. **WHEN** user acessa qualquer rota de `/spy/*` em browser mobile (iOS/Android) **THEN** sistema **SHALL** detectar via `navigator.userAgent` e exibir tela `MobileBlockScreen`
2. **WHEN** `MobileBlockScreen` está visível **THEN** sistema **SHALL** mostrar mensagem "A análise do Medzee Spy roda só no Chrome desktop. Abra esse link no seu computador:" + URL com botão "Copiar link"
3. **WHEN** user clica "Enviar pro meu email" (CTA secundário) **THEN** sistema **SHALL** validar email + persistir em `medzee_spy.mobile_redirect_leads` (tabela nova) pra futuro retargeting (não envia email no MVP — capture-only)
4. **WHEN** user mobile tenta acessar `/app/*` (logado) **THEN** sistema **SHALL** redirecionar pra `MobileBlockScreen` com mensagem "Sua análise está pronta, acesse pelo computador"

**Independent Test:** Em Chrome DevTools, emular iPhone 14 + Pixel 7 acessando `/spy` → ver `MobileBlockScreen` em ambos. Validar `mobile_redirect_leads` recebe insert ao clicar "Enviar pro email".

**Requirement IDs:** CHX-07, CHX-08

---

### P1: Auto-detecção da extensão no /spy ⭐ MVP

**User Story:** Como **user retornando ao /spy depois de instalar a extensão**, quero **continuar de onde parei sem precisar clicar no ícone da extensão**, mantendo o fluxo fluido.

**Why P1:** UX é o diferencial. Forçar user a clicar no ícone da extensão (Caminho B sem auto-detect) introduz fricção que mata conversão.

**Acceptance Criteria:**

1. **WHEN** user volta pro `/spy` ou `/spy/aguardando` em Chrome desktop **THEN** frontend **SHALL** fazer `window.postMessage({type:'medzee:probe'})` e esperar resposta da extensão (timeout 500ms)
2. **WHEN** extensão responde `{type:'medzee:installed', paired:true}` **THEN** frontend **SHALL** pular a tela "Instale a extensão" e ir direto pra "Analisar meu WhatsApp"
3. **WHEN** extensão responde `{type:'medzee:installed', paired:false}` **THEN** frontend **SHALL** disparar pairing (caso o pairing_token ainda esteja no localStorage e válido)
4. **WHEN** sem resposta da extensão após 500ms **THEN** frontend **SHALL** assumir não instalada e mostrar CTA "Instalar extensão"
5. **WHEN** extensão é desinstalada e user volta **THEN** sistema **SHALL** detectar via probe falhada e mostrar tela "Reinstale a extensão pra atualizar sua análise"

**Independent Test:** Com extensão instalada + pareada, abrir `/spy` em aba nova — não deve mostrar tela de install. Desinstalar extensão, recarregar — deve mostrar.

**Requirement IDs:** CHX-09, CHX-10

---

### P2: Tratamento de WhatsApp Web não logado / sem mensagens

**User Story:** Como **user com WhatsApp Web nunca logado no Chrome do desktop**, quero **ver instrução clara em vez de erro críptico**.

**Why P2:** Edge case real (médico com Chrome novo, web.whatsapp.com nunca aberto). Não é MVP-blocker mas evita drop-off.

**Acceptance Criteria:**

1. **WHEN** extensão abre `web.whatsapp.com` **AND** detecta tela de QR (não-logado) **THEN** extensão **SHALL** postar `{type:'medzee:wa_needs_login'}` pro frontend
2. **WHEN** frontend recebe `wa_needs_login` **THEN** sistema **SHALL** mostrar tela "Logue no WhatsApp Web aqui →" com instrução pra escanear QR e instrução pra voltar
3. **WHEN** extensão detecta sessão WhatsApp Web ativa mas DB local vazio (cache não sincronizado) **THEN** extensão **SHALL** aguardar até 2min por sync inicial antes de declarar falha
4. **WHEN** após 2min ainda sem msgs **THEN** sistema **SHALL** gerar relatório com `data_quality=insufficient` + banner "Não detectamos conversas no seu WhatsApp Web — verifique se você usa esse WhatsApp pra atendimento" (em linha com D10: relatório sempre gera)

**Independent Test:** Em Chrome dev, fazer logout do WhatsApp Web → tentar análise → ver tela "logue aqui". Em conta sem mensagens → ver relatório com data_quality=insufficient.

**Requirement IDs:** CHX-11, CHX-12

---

### P2: Deprecar uazapi atrás de feature flag

**User Story:** Como **dev/operador**, quero **poder voltar pro uazapi com 1 env var** caso a extensão tenha bug grave em prod, sem rebuild.

**Why P2:** Rede de segurança. Não é UX, é operação. Permite rollback rápido.

**Acceptance Criteria:**

1. **WHEN** backend inicializa **THEN** sistema **SHALL** ler `WHATSAPP_PROVIDER=extension|uazapi` (default `extension`) e roteamento via Strategy pattern em `app/clients/whatsapp/`
2. **WHEN** `WHATSAPP_PROVIDER=extension` **THEN** endpoints `/api/whatsapp/sessions/*` retornam **410 Gone** com `Use /api/extension/* endpoints instead` no body
3. **WHEN** `WHATSAPP_PROVIDER=uazapi` **THEN** sistema **SHALL** manter F1/F4/F5 funcionais (sem mudar comportamento)
4. **WHEN** ROADMAP marca uazapi como removido **THEN** PR de cleanup remove `app/clients/whatsapp/uazapi.py` + `app/workers/extract.py` + módulo `captured_messages` legacy (decisão futura, fora desse milestone)

**Independent Test:** Setar env `WHATSAPP_PROVIDER=uazapi` e validar que `/api/whatsapp/sessions` ainda cria sessão. Voltar pra `extension` e validar 410.

**Requirement IDs:** CHX-13

---

### P3: Tela "extensão atualizada disponível"

**User Story:** Como **user com versão antiga da extensão**, quero **ser avisado pra atualizar** quando o backend exigir wire shape novo.

**Why P3:** Importante pós-MVP quando extensão evolui. No MVP a versão é única.

**Acceptance Criteria:**

1. **WHEN** extensão envia `X-Extension-Version` em header e backend espera mínimo `v2.0.0` **AND** versão recebida `< minimum` **THEN** backend **SHALL** retornar `409 Conflict` com body `{code:'extension_outdated', min_version:'2.0.0'}`
2. **WHEN** frontend recebe 409 com `extension_outdated` **THEN** sistema **SHALL** exibir tela "Atualize a extensão" com link pra Chrome Web Store

**Requirement IDs:** CHX-14

---

### P1: Re-emissão de `extension_pairing_token` ⭐ MVP

**User Story:** Como **user que voltou ao /spy >15min depois do signup**, quero **continuar o fluxo sem refazer cadastro**, já que o token efêmero expirou mas minha conta existe.

**Why P1:** Edge case extremamente comum (user é interrompido entre cadastro e instalar a extensão). Sem isso, abandono = perdido.

**Acceptance Criteria:**

1. **WHEN** user logado acessa `POST /api/auth/me/extension-pairing-token` **THEN** backend **SHALL** emitir novo JWT (claims `{sub:user_id, typ:'extension_pairing', exp:+15min}`) idempotente
2. **WHEN** frontend detecta `paired=false` no probe E user já está logado E localStorage não tem token válido **THEN** sistema **SHALL** chamar esse endpoint silenciosamente e injetar o novo token
3. **WHEN** token antigo já existe no localStorage mas o `exp` da claim já passou **THEN** sistema **SHALL** re-emitir antes de tentar pareamento

**Independent Test:** Logar, fechar /spy, esperar 16min, reabrir → o pairing acontece silenciosamente sem o user perceber.

**Requirement IDs:** CHX-15

---

### P2: Telemetria da extensão (sem PII)

**User Story:** Como **operador do sistema**, quero **enxergar quando a extensão falha ou trava em um passo específico** sem depender do user reportar.

**Why P2:** Sem isso, falha silenciosa em prod é invisível. Crítico pra detectar quebra de wa-js antes de virar drop-off em massa.

**Acceptance Criteria:**

1. **WHEN** extensão emite evento (collect_failed | collect_started | collect_completed | wa_needs_login | service_worker_woke | pairing_failed) **THEN** sistema **SHALL** persistir em `medzee_spy.extension_telemetry` via `POST /api/extension/telemetry`
2. **WHEN** payload de telemetria inclui qualquer PII (`text`, `contact_name`, `wa_chatid`, `msg_id`) **THEN** backend **SHALL** rejeitar com 422 (validação Pydantic rigorosa)
3. **WHEN** user envia > 60 eventos/min **THEN** backend **SHALL** rate-limit com 429
4. **WHEN** evento `collect_failed` excede threshold (ex: 10/h global) **THEN** sistema **SHALL** logar com severidade WARNING pra atrair atenção em Railway logs

**Independent Test:** Forçar erro na extensão (mockar wa-js falhar) → ver row em `extension_telemetry` com `event='collect_failed'` + nenhum campo de mensagem.

**Requirement IDs:** CHX-16

---

## Edge Cases

- **WHEN** user instala extensão mas nunca completa cadastro (token expira) **THEN** sistema **SHALL** ao reabrir `/spy` re-emitir novo `extension_pairing_token` e re-pairing automático silencioso
- **WHEN** extensão envia batch fora de ordem (race condition) **THEN** backend **SHALL** dedupar via `(user_id, wa_chatid, wa_msg_id)` no `captured_messages` (já existe índice, reaproveitar)
- **WHEN** user tem 50k+ mensagens nos últimos 30 dias **THEN** extensão **SHALL** chunkar em batches de 1000 + frontend **SHALL** mostrar progresso "X/Y conversas processadas"
- **WHEN** content-script falha (WhatsApp Web mudou DOM/IndexedDB) **THEN** extensão **SHALL** postar `{type:'medzee:collect_failed', reason:'parse_error', extension_version:'X.Y.Z'}` + backend **SHALL** logar pra observabilidade (Sentry / log estruturado)
- **WHEN** user fecha aba do WhatsApp Web no meio da coleta **THEN** extensão **SHALL** detectar via `chrome.tabs.onRemoved`, abortar coleta, postar `{type:'medzee:aborted'}`, frontend mostra "Coleta interrompida, tentar de novo?"
- **WHEN** backend recebe POST com `extension_pairing_token` expirado **THEN** retorna `401` com `code:'pairing_expired'` + frontend re-emite token + retry transparente
- **WHEN** user tem múltiplas abas `/spy` abertas **THEN** apenas a primeira que receber resposta da extensão segue o fluxo; outras mostram "Análise em andamento em outra aba"

---

## Requirement Traceability

| ID | Story | Phase | Status |
|----|-------|-------|--------|
| CHX-01 | P1 fluxo completo: signup → token efêmero | Design | Pending |
| CHX-02 | P1: install + pairing (token → refresh-token vinculado) | Design | Pending |
| CHX-03 | P1: content-script coleta IndexedDB/DOM últimos 30d | Design | Pending |
| CHX-04 | P1: batch POST `/api/extension/messages` chunked | Design | Pending |
| CHX-05 | P1: backend persiste + dispara worker F3 reusado | Design | Pending |
| CHX-06 | P1: frontend transiciona pra relatório via poll | Design | Pending |
| CHX-07 | P1: detecção mobile + `MobileBlockScreen` | Design | Pending |
| CHX-08 | P1: tabela `mobile_redirect_leads` + capture | Design | Pending |
| CHX-09 | P1: `window.postMessage` probe da extensão | Design | Pending |
| CHX-10 | P1: skip de telas quando extensão já pareada | Design | Pending |
| CHX-11 | P2: detecção WhatsApp Web não-logado | Design | Pending |
| CHX-12 | P2: relatório sempre gera quando 0 msgs (mantém D10) | Design | Pending |
| CHX-13 | P2: feature flag `WHATSAPP_PROVIDER` + 410 Gone | Design | Pending |
| CHX-14 | P3: versionamento da extensão + `extension_outdated` 409 | Design | Pending |
| CHX-15 | P1: `POST /api/auth/me/extension-pairing-token` (re-emissão idempotente) | Design | Pending |
| CHX-16 | P2: telemetria sem PII via `/api/extension/telemetry` + tabela `extension_telemetry` | Design | Pending |
| CHX-17 | P2: build pipeline ícones (rasteriza `logo-medzee-spy.svg` em 16/48/128 PNG via `sharp`) | Design | Pending |

**Coverage:** 17 total, 0 mapped to tasks, 17 unmapped ⚠️ (atualiza após Tasks phase)

---

## Success Criteria

- [ ] Taxa de sucesso da coleta ≥ 95% em Chrome desktop com WhatsApp Web logado (medir via `reports.status='completed'` / total)
- [ ] Tempo médio do clique em "Analisar meu WhatsApp" até relatório renderizado ≤ 90s para usuários com até 5k mensagens
- [ ] Zero relatórios `status='failed'` por causa de provider (uazapi-style) — todas as falhas atribuíveis a "WhatsApp Web não logado" ou "user cancelou"
- [ ] Bloqueio mobile cobre 100% dos UA mobile conhecidos (iOS Safari, Chrome Android, Samsung Internet, Firefox mobile)
- [ ] Feature flag `WHATSAPP_PROVIDER=uazapi` permite rollback completo em < 1min (apenas restart do backend)
