"""Segment addendum for fallback / unclassified clinics.

F5: explícito sobre 'fora-de-escopo'. O LLM ainda gera relatório completo,
mas usa o campo ``scope_warning`` (definido em BASE_SYSTEM) pra avisar o
lead se detectar que o WhatsApp não é de saúde.
"""

SEGMENT_ADDENDUM = """Especialidade: NÃO CLASSIFICADA (segmento desconhecido até o LLM detectar).

Estratégia:
- Faça a análise mesmo assim. Funil, tempo de resposta, oportunidades perdidas, objeções, FAQs — esses indicadores valem pra QUALQUER atendimento comercial via WhatsApp, não só saúde.
- Se detectar segmento NÃO-saúde (pet shop, advogado, e-commerce, etc.), preencha o campo `scope_warning` no JSON conforme instruções em BASE_SYSTEM. Não recuse, não devolva relatório vazio — gere o diagnóstico genérico.
- Tom: consultor comercial. Adapte vocabulário ao segmento real detectado (ex: "cliente" em vez de "paciente").
"""
