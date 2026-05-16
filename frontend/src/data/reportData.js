export const FUNNEL = [
  { stage: 'Primeiro contato', count: 412, pct: 100 },
  { stage: 'Respondidos', count: 365, pct: 88.6 },
  { stage: 'Engajados (3+ msgs)', count: 287, pct: 69.7 },
  { stage: 'Receberam info / valor', count: 134, pct: 32.5 },
  { stage: 'Agendamento confirmado', count: 51, pct: 12.4 },
];

export const HEATMAP_DAYS = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'];
export const HEATMAP_PERIODS = [
  { label: 'Madrug.', values: [0, 0.3, 0.5, 2.1, 0.4, 1.8, 6.2] },
  { label: 'Manhã', values: [1.2, 0.6, 0.4, 0.5, 0.7, 4.3, 0] },
  { label: 'Tarde', values: [0.8, 0.7, 0.6, 0.5, 0.9, 5.1, 0] },
  { label: 'Noite', values: [2.4, 2.1, 1.8, 2.6, 3.2, 8.4, 12.0] },
];

export const RESPONSE_DISTRIBUTION = [
  { faixa: '< 5min', count: 74, color: '#FF6B35' },
  { faixa: '5–30min', count: 91, color: '#FF6B35' },
  { faixa: '30min–1h', count: 58, color: '#E8B33C' },
  { faixa: '1h–4h', count: 87, color: '#E8B33C' },
  { faixa: '4h–24h', count: 66, color: '#8B3A50' },
  { faixa: '> 24h', count: 37, color: '#5C1D2E' },
];

export const OBJECTIONS = [
  { label: 'Preço acima do esperado', pct: 32, count: 89, color: '#FF6B35' },
  { label: 'Convênio não atendido', pct: 24, count: 67, color: '#8B3A50' },
  { label: 'Indisponibilidade de horário', pct: 18, count: 50, color: '#E8B33C' },
  { label: 'Localização / deslocamento', pct: 14, count: 39, color: '#B8A8D9' },
  { label: 'Dúvida sobre procedimento', pct: 12, count: 33, color: '#3B7BB0' },
];

export const FAQS = [
  { q: 'Atende meu convênio?', count: 134 },
  { q: 'Qual o valor da consulta particular?', count: 118 },
  { q: 'Tem horário no fim de tarde?', count: 87 },
  { q: 'Aceita cartão / parcela?', count: 62 },
  { q: 'Vocês fazem ecocardiograma?', count: 54 },
];

export const SENTIMENT = [
  { name: 'Positivo', value: 42, color: '#FF6B35' },
  { name: 'Neutro', value: 38, color: '#B8A8D9' },
  { name: 'Negativo', value: 20, color: '#5C1D2E' },
];

export const OPPORTUNITIES = [
  { tag: 'P-1847', context: 'Pediu valor da consulta sexta às 19h', reason: 'Sem resposta (28h depois)', value: 850, when: '3 dias' },
  { tag: 'P-1839', context: 'Perguntou sobre Bradesco Saúde', reason: 'Resposta tardia, abandonou', value: 0, when: '5 dias' },
  { tag: 'P-1821', context: 'Solicitou eco no sábado', reason: 'Atendimento só na segunda, perdeu', value: 1200, when: '8 dias' },
  { tag: 'P-1810', context: 'Negociou parcelamento', reason: 'Sem follow-up após orçamento', value: 850, when: '10 dias' },
  { tag: 'P-1792', context: 'Pediu horário de manhã cedo', reason: 'Não foi oferecida alternativa', value: 850, when: '14 dias' },
  { tag: 'P-1778', context: 'Reagendamento pós-feriado', reason: 'Mensagem ignorada', value: 850, when: '18 dias' },
];

export const BENCHMARKS = [
  { metric: 'Tempo 1ª resposta', clinic: 4.4, market: 0.8, unit: 'h', better: 'lower' },
  { metric: 'Taxa de conversão', clinic: 12.4, market: 24.0, unit: '%', better: 'higher' },
  { metric: 'Mensagens sem resposta', clinic: 21, market: 6, unit: '%', better: 'lower' },
  { metric: 'Follow-up pós-orçamento', clinic: 14, market: 58, unit: '%', better: 'higher' },
];

export const GEN_STEPS = [
  { label: 'Conectando ao WhatsApp da clínica…', icon: 'Wifi', duration: 900 },
  { label: 'Lendo histórico de conversas…', icon: 'MessageCircle', duration: 1100 },
  { label: 'Analisando 3.370 mensagens…', icon: 'Activity', duration: 1400 },
  { label: 'Mapeando funil de conversão…', icon: 'BarChart2', duration: 1200 },
  { label: 'Identificando oportunidades perdidas…', icon: 'AlertCircle', duration: 1300 },
  { label: 'Comparando com benchmark do setor…', icon: 'Target', duration: 1000 },
  { label: 'Gerando relatório personalizado…', icon: 'Sparkles', duration: 900 },
];

export const SIDEBAR_LINKS = [
  { label: 'Visão geral', active: true },
  { label: 'Funil de conversão', active: false },
  { label: 'Tempo de resposta', active: false },
  { label: 'Voz do paciente', active: false },
  { label: 'Oportunidades perdidas', active: false },
  { label: 'Benchmark do setor', active: false },
];
