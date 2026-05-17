# Medzee Spy

**Vision:** Diagnóstico comercial automatizado que analisa o histórico recente do WhatsApp de uma clínica e devolve um relatório acionável (funil, tempo de resposta, voz do paciente, oportunidades perdidas, benchmark) em poucos minutos.
**For:** Gestores e profissionais de clínicas médicas, odontológicas e da área de saúde (com fallback parcial para outros segmentos).
**Solves:** Clínicas perdem receita por falhas comerciais no WhatsApp (resposta lenta, follow-up ausente, objeções não tratadas) e não têm visibilidade objetiva do problema. Hoje a diligência depende de auditoria manual cara e lenta.

## Goals

- **Tempo até o primeiro relatório < 5 minutos** desde a leitura do QR Code até a tela final do relatório autenticado.
- **Taxa de conclusão do funil ≥ 60%** (QR lido → cadastro feito → relatório gerado), medida nos primeiros 30 dias.
- **Cobertura de análise:** processar ≥ 90% das mensagens dos últimos 30 dias de todas as conversas detectadas na sessão conectada.
- **Login pós-cadastro automático** — usuário nunca digita credenciais para chegar no relatório.

## Tech Stack

**Core:**
- Backend: FastAPI 0.115 (Python 3.12)
- Frontend: React 19.2 + Vite 8 + Tailwind 3.4 + react-router 7
- Auth / DB: Supabase 2.9 (instância reutilizada do projeto "News")
- WhatsApp: **Baileys** via sidecar Node.js (decisão D1 — ver `STATE.md`)
- LLM: provider-agnostic (Anthropic Claude por padrão — ver decisão D2 em STATE.md)

**Key dependencies:**
- `@elevenlabs/react` — agente de voz "Marina" no fluxo público
- `qrcode.react` — render do QR no frontend (o QR real vem do sidecar Baileys)
- `recharts` — gráficos do dashboard e do relatório
- `supabase-py` — client Python para auth/db
- `httpx` — comunicação FastAPI ↔ sidecar WhatsApp

## Scope

**v1 includes:**
- Rota `/spy` exibe QR Code real gerado pela sessão Baileys e mantém WS aberto até a leitura.
- Tela de "geração" (placeholder/loading) enquanto backend extrai e processa.
- Formulário de cadastro (nome, e-mail, telefone, ticket médio, senha) salva no Supabase e cria usuário via Supabase Auth.
- Endpoint backend que extrai mensagens dos últimos 30 dias e dispara processamento LLM.
- Endpoint backend que retorna o relatório estruturado vinculado ao `user_id`.
- Tela final do relatório já autenticada — sem login manual.
- Prompt de análise comercial focado em saúde, com fallback genérico para outros segmentos.
- README com instruções de execução local e variáveis de ambiente.

**Explicitly out of scope:**
- Geração recorrente de relatórios (já existe UI mockada em `/app/reports` — fica para v2).
- Dashboard agregado `/app/dashboard` com dados reais (mantém mocks em v1).
- Conexão simultânea de múltiplos WhatsApps por usuário.
- Pagamento, planos, billing.
- Webhooks externos / integração CRM.
- Persistência do conteúdo bruto das mensagens — armazena apenas metadados e o relatório final (compromisso de privacidade da landing).
- Reaproveitamento de sessão Baileys entre dispositivos (cada sessão é stateless por usuário).
- App mobile nativo.

## Constraints

- **Timeline:** entrega ponta a ponta funcionando — sem prazo absoluto definido na task, priorizar caminho feliz primeiro.
- **Técnicas:**
  - Backend é Python — Baileys exige Node.js, daí o sidecar (D1).
  - Privacidade: nenhuma mensagem persiste após análise; só metadados agregados.
  - Mesma instância Supabase do projeto "News" — coexistir com schemas existentes via prefixo `medzee_` ou schema separado.
  - WhatsApp Web pode banir sessões automatizadas — sessão Baileys deve simular cliente legítimo e ser efêmera.
- **Recursos:** mono-dev (Patrick), monorepo já criado no GitHub.
