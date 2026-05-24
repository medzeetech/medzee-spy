MedZee Spy — Backend + Frontend + Extensão Chrome
🎯 Objetivo
Construir uma aplicação que analisa as conversas do WhatsApp do usuário e gera um relatório comercial focado em clínicas médicas, odontológicas e área da saúde (com fallback parcial pra outros segmentos).
A coleta das mensagens é feita via extensão Chrome que roda em cima do WhatsApp Web do próprio usuário — evitando APIs não oficiais, risco de ban e problemas de QR Code/sessão.
🔁 Novo fluxo do usuário
Rota /spy — começa direto com o formulário de cadastro (nome, email, senha, dados do negócio, janela inicial de análise: 7 / 30 / 90 dias). 
Dados salvos no Supabase.
Conta criada via Supabase Auth com a senha informada.
Página pós-formulário — exibe: 
Vídeo explicativo (usar placeholder por enquanto).
Botão "Baixar extensão".
Botão "Pronto, baixei e instalei" → abre nova aba com tela de login da própria aplicação (mesmo email/senha do formulário).
Usuário instala a extensão e clica no ícone dela no Chrome → abre popup de login → autentica com o mesmo email/senha → extensão guarda sessão.
Usuário abre web.whatsapp.com (instruído pelo vídeo e pela própria extensão) e deixa a aba aberta.
Extensão coleta mensagens dos últimos N dias (conforme janela escolhida) e envia ao backend.
Backend processa → roda o prompt comercial → salva relatório vinculado ao user_id.
Tela de relatório — usuário acessa logado e vê o resultado.
Análises periódicas (opcional) — após o primeiro relatório, tela separada onde o usuário ativa coleta contínua (escolhendo janela de 7/30/90 dias) pra gerar novos relatórios recorrentes.
⚠️ As telas antigas de QR Code e loading orgânico não devem ser apagadas — apenas removidas do fluxo atual.
🧱 Stack & Infraestrutura
Repositório: monorepo no GitHub (já criado, convite enviado por email).
Banco de dados: mesmo Supabase do projeto News (reutilizar instância).
Auth: Supabase Auth (compartilhada entre app web e extensão).
Frontend: protótipo já existe — adaptar pro novo fluxo.
Extensão: Chrome (Manifest V3) — só Chrome por enquanto.
🔌 Como a extensão lê o WhatsApp Web
Caminho escolhido: hookar as stores internas via @wppconnect/wa-js.
Justificativa: o WhatsApp Web é uma SPA Webpack com stores internas (Store.Chat, Store.Msg, etc.). A lib WA-JS faz a engenharia reversa dessas stores e expõe uma API limpa pra uso em browser (WPP.chat.list(), WPP.chat.getMessages(chatId, { count }), WPP.on('chat.new_message'), etc.). É open source, ativamente mantida, e foi feita exatamente pra ser injetada via extensão.
Alternativas descartadas:
DOM scraping: WA Web usa lista virtualizada — frágil e lento.
IndexedDB direto: estrutura interna muda sem aviso.
WebSocket hook: protocolo binário complexo demais pro MVP.
📦 Escopo
1. Extensão Chrome (MV3)
 Estrutura: manifest.json, popup.html/js, background.js (service worker), content_script.js, injected.js.
 Popup de login — autentica no Supabase Auth com o email/senha do formulário e guarda a sessão.
 Content script roda em web.whatsapp.com → injeta injected.js no contexto da página.
 Injected script importa @wppconnect/wa-js, espera WPP.isReady, extrai conversas e mensagens da janela configurada.
 Background (service worker) envia batches pro backend, usa chrome.alarms pra manter coleta ativa (MV3 mata o worker após ~30s ocioso).
 Dois modos de operação: 
Coleta inicial — puxa o histórico disponível dentro da janela escolhida.
Modo ativo — escuta WPP.on('chat.new_message') enquanto a aba do WA Web tiver aberta (pra análises periódicas).
 UI de status na própria extensão: "Conectado / Coletando X de Y dias / Concluído".
2. Backend
 Endpoints: 
POST /auth/signup — cria usuário no Supabase Auth com dados do formulário.
POST /messages/batch — recebe lotes de mensagens da extensão, autenticado via JWT do Supabase.
POST /reports/generate — dispara geração do relatório quando a janela está completa.
GET /reports/:id — retorna o relatório do usuário logado.
POST /tracking/periodic — ativa/configura análises periódicas.
 Persistência no Supabase: 
Tabela users_profile (dados do formulário).
Tabela messages_raw (mensagens coletadas, indexadas por user_id e data).
Tabela reports (relatórios gerados).
Tabela tracking_config (janelas ativas, recorrência).
 Integração com LLM pra rodar o prompt sobre as mensagens.
 RLS no Supabase pra garantir que usuário só vê os próprios dados.
3. Frontend
 Reformular /spy removendo (sem apagar) QR Code e loading orgânico.
 Implementar fluxo: formulário → página com vídeo + botões → tela de login → tela de relatório.
 Tela separada de configuração de análises periódicas (janelas de 7/30/90 dias, ativar/desativar).
 Tela do relatório final com polling/realtime do status.
4. Prompt Engineering
 Criar prompt a partir do relatório de exemplo (anexar no ClickUp).
 Foco: análise comercial de WhatsApp de clínicas médicas / odontologia / saúde.
 Fallback: caso não seja da área de saúde, gerar relatório parcial / genérico ainda útil.
🛠️ Como rodar a extensão localmente (sem Chrome Web Store)
Pro MVP, não vamos publicar na store. A extensão será distribuída em modo desenvolvedor:
Devs/testers baixam a pasta da extensão.
Vão em chrome://extensions, ativam "Modo desenvolvedor".
Clicam em "Carregar sem compactação" e apontam pra pasta.
Funciona indefinidamente (com aviso amarelo no topo, apenas estético).
Pra atualizar: clica no botão "reload" da extensão.
A publicação na Chrome Web Store fica como passo posterior, quando o produto estiver validado.
⚠️ Limitações conhecidas (importante o dev saber antes de começar)
Histórico passado depende do que o WA Web sincronizou do celular. Pode não cobrir 100% dos 30/90 dias na primeira execução. UI deve mostrar progresso honesto.
Modo ativo só funciona com a aba do WA Web aberta. Comunicar isso bem no vídeo e na UI.
WA-JS pode quebrar quando WhatsApp atualiza o WA Web. Geralmente a comunidade conserta em 1–2 dias. Planejar canal de "extensão desatualizada".
Celular precisa estar online periodicamente pro WA Web seguir funcionando.
✅ Entregáveis
Sistema funcionando ponta a ponta: formulário → extensão → coleta → relatório autenticado.
Extensão distribuída como pasta pra "load unpacked".
Deploy do backend e frontend.
README do monorepo com: 
Instruções de execução local (web + backend + extensão).
Variáveis de ambiente.
Como instalar a extensão em modo desenvolvedor.
