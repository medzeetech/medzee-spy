# STATE — Memória persistente entre sessões

> Decisões, blockers, lições, todos e ideias adiadas. Atualizar ao final de cada sessão e ao registrar qualquer escolha relevante.

## Decisões

- **D1 (2026-05-17) — WhatsApp via sidecar Node.js com Baileys.**
  Por quê: backend é Python; não há porta Python madura do Baileys; `whatsapp-web.js` exige Puppeteer/Chrome (mais pesado). Baileys é WebSocket puro, sem browser, e tem a comunidade mais ativa.
  Como aplicar: novo diretório `whatsapp-sidecar/` no monorepo, expondo REST + WS local; FastAPI fala com ele via `httpx`. Sessão por usuário (`sessionId = user_id` ou `whatsapp_session_id` temporário antes do signup).

- **D2 (2026-05-17) — LLM provider-agnostic, default Anthropic Claude.**
  Por quê: prompt envolve análise textual extensa; Claude tem context window grande e bom desempenho em PT-BR. Mantém abstração para trocar por OpenAI/Gemini sem reescrever pipeline.
  Como aplicar: criar `app/clients/llm.py` com interface `complete(messages, model, ...)` e adapter Anthropic. Modelo default: `claude-sonnet-4-6`.

- **D3 (2026-05-17) — Reutilizar instância Supabase do projeto "News" com prefixo `medzee_` nas tabelas.**
  Por quê: pedido explícito do briefing.
  Como aplicar: todas as migrations criam tabelas `medzee_users_profile`, `medzee_reports`, `medzee_whatsapp_sessions`. Supabase Auth é compartilhado entre projetos (sem prefixo).

- **D4 (2026-05-17) — Nenhuma mensagem persistida no banco.**
  Por quê: privacidade prometida na landing ("Sem armazenamento de conteúdo após análise") + risco regulatório (dados de saúde).
  Como aplicar: pipeline lê em memória → gera relatório → descarta mensagens. Persiste apenas o relatório estruturado e metadados agregados (counts, médias).

## Blockers

_(nenhum no momento)_

## Lições

_(serão preenchidas durante a execução)_

## Todos (cross-sessão)

- [ ] Confirmar com Patrick: modelo LLM default (Claude vs OpenAI) — atualmente D2 propõe Claude.
- [ ] Confirmar: estrutura monorepo aceita adicionar `whatsapp-sidecar/` na raiz?
- [ ] Definir storage de sessão Baileys (filesystem vs. Supabase Storage) — começar com filesystem local em `whatsapp-sidecar/sessions/<id>/` e ignorar no git.

## Ideias adiadas

- Cache do relatório entre re-execuções no mesmo período (evita refaturar LLM).
- Score de "saúde comercial" persistente para evolução temporal real (hoje mockado em `/app/dashboard`).
- Detectar pico de demanda fora do expediente e sugerir agente de IA (gancho de upsell).
- Comparativo entre atendentes (requer identificação por número/handle no Baileys).

## Preferences

_(será preenchido quando o usuário sinalizar preferências de modelo, estilo de commit, etc.)_
