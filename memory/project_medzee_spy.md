---
name: project-medzee-spy
description: Visão geral do produto Medzee Spy — diagnóstico comercial baseado no WhatsApp de clínicas médicas
metadata:
  type: project
---

Produto: **Medzee Spy** — ferramenta de diagnóstico comercial para clínicas médicas que analisa o histórico de conversas do WhatsApp e gera um relatório com funil de conversão, tempo de resposta, voz do paciente, oportunidades perdidas e benchmark do setor.

**Why:** Demo/MVP da Medzee para mostrar a médicos/clínicas o quanto eles perdem em receita por baixa eficiência no WhatsApp, com CTA final para vender o agente de IA da Medzee (que responde 24/7 no WhatsApp).

**How to apply:** Toda mudança em texto/copy deve manter o tom: "diagnóstico" duro, números concretos (R$ perdidos, % conversão), idioma pt-BR, persona "Marina" como consultora virtual. O agente conversacional usa ElevenLabs (agent ID `agent_8601krmch56bfbbv5wjya2jw0y3x`).

**Status M1 — funcional ponta-a-ponta (2026-05-19)**: smoke E2E confirmado em produção. User faz scan QR → conecta WhatsApp → captura msgs via webhook → gera relatório real com Claude → vê diagnóstico estruturado. F1 deprecated (substituído por F4 forward-capture). F2/F3/F4/F5 done.

Fluxos de tela:
- `/` (MainFlow): AgentScreen (Marina via ElevenLabs) → QRScreen → GeneratingScreen → LeadFormScreen → ReportScreen (navega para `/app/reports/latest`).
- `/spy` (SpyFlow): pula direto para QR → Generating → LeadForm (com campo ticket médio) → `/app/reports/latest`.
- `/app` (DashboardLayout com Outlet): `/app/dashboard`, `/app/reports`, `/app/reports/:id`, `/app/whatsapp`.

Pipeline real (não mais mockado): backend F4 (`captured_messages` via webhook uazapi) + F5 (`pull_last_n_per_chat` via window function RPC) alimenta worker F3 que chama Claude e persiste em [[project-stack]] `medzee_spy.reports`.
