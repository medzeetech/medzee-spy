 MedZee Spy — Desenvolvimento Backend + Frontend
🎯 Objetivo
Construir uma aplicação que se conecta ao WhatsApp do usuário via QR Code, extrai o histórico das conversas dos últimos 30 dias e gera um relatório de análise comercial focado em clínicas médicas, odontológicas e área da saúde (com fallback parcial para outros segmentos).
🔁 Fluxo do Usuário (página por página)
Rota /spy — Exibe QR Code do WhatsApp. Usuário lê o QR Code com o celular para conectar a sessão.
Página de "simulação" de relatório — Tela placeholder/loading mostrando como o relatório vai parecer. Nesse momento o relatório ainda não foi gerado.
Formulário de cadastro — Usuário preenche dados pessoais + senha. 
Dados salvos no Supabase.
Conta criada automaticamente com a senha fornecida (Supabase Auth).
Processamento do relatório — Backend roda o prompt sobre as mensagens dos últimos 30 dias.
Tela de relatório final — Usuário já chega logado na conta recém-criada. Relatório associado ao user_id no banco.
🧱 Stack & Infraestrutura
Repositório: monorepo no GitHub (já criado, convite enviado para o email).
Banco de dados via CLI: mesmo Supabase do projeto News (reutilizar instância).
Frontend: protótipo já existe — integrar com o backend.
Auth: Supabase Auth.
📦 Escopo
Backend
 Integração com WhatsApp Web (sugestão: Baileys ou whatsapp-web.js) para geração de QR Code e sessão.
 Extração das mensagens dos últimos 30 dias de todas as conversas.
 Endpoint: criar usuário + senha → retornar sessão autenticada.
 Endpoint: processar relatório → salvar resultado vinculado ao user_id.
 Persistência no Supabase: tabela de usuários (dados do formulário) + tabela de relatórios.
 Integração com LLM para rodar o prompt de análise.
Frontend
 Integrar protótipo existente com os endpoints.
 Tela QR Code (/spy).
 Tela de simulação/loading do relatório.
 Formulário de dados pessoais + senha.
 Tela do relatório final (rota autenticada).
 Garantir que o usuário entra logado direto na tela de resultado.
Prompt Engineering
 Criar prompt a partir do relatório de exemplo fornecido.
 Foco: análise comercial de WhatsApp de clínicas médicas / odontologia / saúde.
 Fallback: caso o WhatsApp não seja da área de saúde, gerar um relatório parcial / genérico ainda útil.
✅ Entregáveis
Sistema funcionando ponta a ponta (QR Code → relatório autenticado).
README curto com instruções de execução local e variáveis de ambiente.
