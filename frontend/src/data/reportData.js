// UI helpers — não são dados de relatório. Tudo de relatório vem do backend.
//
// Os mocks antigos (FUNNEL, HEATMAP_*, RESPONSE_DISTRIBUTION, OBJECTIONS,
// FAQS, SENTIMENT, OPPORTUNITIES, BENCHMARKS) foram REMOVIDOS porque eram
// fallback enganoso quando o payload do relatório vinha vazio — frontend
// renderizava "47 oportunidades perdidas / R$ 38.400 / 4h 22min" inventados.
// Agora cada section trata `null` / array vazio via <SectionEmptyState />.

export const GEN_STEPS = [
  { label: 'Conectando ao WhatsApp da clínica…', icon: 'Wifi', duration: 900 },
  { label: 'Lendo histórico de conversas…', icon: 'MessageCircle', duration: 1100 },
  { label: 'Analisando mensagens…', icon: 'Activity', duration: 1400 },
  { label: 'Mapeando funil de conversão…', icon: 'BarChart2', duration: 1200 },
  { label: 'Identificando oportunidades…', icon: 'AlertCircle', duration: 1300 },
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
