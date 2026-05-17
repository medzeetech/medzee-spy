# Concerns / dívida técnica / riscos

## Risco — alto

### R1 — Banimento da sessão WhatsApp
**Evidência:** Baileys/whatsapp-web.js operam sobre WhatsApp Web não oficial; sessões automatizadas que extraem volume grande de mensagens em pouco tempo podem ser banidas pela Meta.
**Impacto:** Usuário perde o WhatsApp da clínica → catastrófico para reputação do produto.
**Mitigação:** Limitar throughput (delay entre fetches), respeitar paginação natural do Baileys, encerrar sessão imediatamente após extração, jamais enviar mensagem em nome do usuário.

### R2 — Conteúdo sensível de saúde sendo enviado para LLM externo
**Evidência:** Mensagens de pacientes podem conter dados sensíveis (LGPD art. 11). Decisão D4 evita persistência em DB, mas o conteúdo passa por LLM provider.
**Impacto:** Risco regulatório + reputacional.
**Mitigação:** Documentar na landing que mensagens são processadas (sem armazenamento); ofuscar nomes/CPF antes de enviar para o LLM (pipeline de scrub em F3); preferir provider com BAA/contrato adequado.

## Risco — médio

### R3 — Supabase compartilhado com projeto "News"
**Evidência:** D3 manda reutilizar a mesma instância.
**Impacto:** Migrations descuidadas podem afetar o outro projeto; quotas (auth, storage) ficam compartilhadas.
**Mitigação:** Prefixo `medzee_` em todas as tabelas; RLS estrita por user; nunca rodar migrations destrutivas sem revisar `supabase db diff`.

### R4 — Frontend está com mocks profundamente espalhados
**Evidência:** `src/data/reportData.js` é importado por 6+ componentes. Substituir por API real é mecânico mas largo.
**Impacto:** Risco de divergência entre forma do mock e payload real → bugs visuais.
**Mitigação:** Em F3, definir o payload do `reports.payload` JSONB **espelhando exatamente** a forma de `reportData.js` (mesmas chaves, mesmos tipos). Documentar no spec da feature.

## Risco — baixo

### R5 — Paleta de cores duplicada
**Evidência:** Cores existem em `tailwind.config.js` E em `src/constants/colors.js`.
**Impacto:** Divergência se alguém mudar só um.
**Mitigação:** Adiar — não bloqueia M1. Resolver em refactor pós-task.

### R6 — `package-lock.json` na raiz do monorepo
**Evidência:** Arquivo `package-lock.json` (~muitos KB) está na raiz, fora do `frontend/`. Provavelmente artefato de execução acidental de `npm install` na raiz.
**Impacto:** Confusão para novos devs.
**Mitigação:** Remover e adicionar à raiz um `.gitignore` que cubra `node_modules/`, `*.lock` indevidos. Decidir se a raiz vira workspace (`pnpm-workspace.yaml`) quando o sidecar entrar.

### R7 — Sem CI configurada
**Evidência:** Nenhum `.github/workflows/`.
**Impacto:** Erros de lint/type/test só pegam localmente.
**Mitigação:** Workflow mínimo em F5 (lint frontend + pytest backend).

### R8 — Hardcoded ElevenLabs Agent ID
**Evidência:** `AGENT_ID` em `AgentScreen.jsx:8`.
**Impacto:** Difícil trocar de agente sem deploy.
**Mitigação:** Mover para `import.meta.env.VITE_ELEVENLABS_AGENT_ID` em F4 (low effort).

### R9 — `qrcode.react` ainda gera QR de URL estática
**Evidência:** `QRScreen.jsx:6` usa `QR_VALUE = 'https://medzee.com.br/conectar'`. O QR real vem do Baileys (base64 PNG ou string).
**Impacto:** Esperado — substituído em F4.

## Componentes frágeis (cuidar ao editar)

- `AgentScreen.jsx`: watchdog de conexão, refs de timeout, três efeitos sincronizados. Bugs aqui quebram o fluxo "/" inteiro.
- `LeadFormScreen.jsx`: máscaras de telefone/moeda, validação em duas etapas, autoplay de áudio. Mudanças exigem testar manualmente em mobile.
- `GeneratingScreen.jsx`: animação de etapas com `setTimeout` aninhado — substituir pela progressão real em F4 com cuidado para não regredir UX.

## Não bloqueia M1
- Migração para TypeScript no frontend.
- Substituir mocks de `/app/dashboard` (fica em M2).
- Containerização (Docker/compose) — desejável mas adiada.
