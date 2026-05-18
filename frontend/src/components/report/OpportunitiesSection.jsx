import { useState } from 'react';
import { COLORS } from '../../constants/colors.js';
import SectionHeader from './SectionHeader.jsx';
import SectionEmptyState from './SectionEmptyState.jsx';

const HEADERS = ['ID', 'Contexto', 'Por que perdeu', 'Valor est.', 'Quando'];

function formatBRL(v) {
  if (!v) return '—';
  return v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 });
}

function Row({ row }) {
  const [hover, setHover] = useState(false);
  return (
    <div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      className="flex flex-col md:grid"
      style={{
        gridTemplateColumns: 'minmax(80px, 0.7fr) 1.6fr 1.4fr 100px 80px',
        gap: 12,
        padding: '14px 18px',
        borderTop: `1px solid ${COLORS.hairline}`,
        background: hover ? COLORS.sunken : 'transparent',
        transition: 'background 0.15s ease',
        alignItems: 'flex-start',
      }}
    >
      <div
        style={{
          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
          fontSize: 12,
          color: COLORS.inkSoft,
          fontWeight: 600,
        }}
      >
        <span className="md:hidden" style={{ color: COLORS.inkMute, marginRight: 6, fontFamily: "'Red Hat Display'", fontWeight: 500 }}>ID</span>
        {row.tag}
      </div>
      <div style={{ fontSize: 13, color: COLORS.ink, lineHeight: 1.45 }}>
        <span className="md:hidden" style={{ color: COLORS.inkMute, marginRight: 6, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.1em' }}>Contexto</span>
        {row.context}
      </div>
      <div style={{ fontSize: 13, color: COLORS.wineSoft, lineHeight: 1.45, fontWeight: 500 }}>
        <span className="md:hidden" style={{ color: COLORS.inkMute, marginRight: 6, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 500 }}>Por que perdeu</span>
        {row.reason}
      </div>
      <div style={{ fontSize: 13, color: COLORS.ink, fontWeight: 700 }}>
        <span className="md:hidden" style={{ color: COLORS.inkMute, marginRight: 6, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 500 }}>Valor</span>
        {formatBRL(row.value ?? row.value_brl)}
      </div>
      <div style={{ fontSize: 12, color: COLORS.inkSoft }}>
        <span className="md:hidden" style={{ color: COLORS.inkMute, marginRight: 6, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.1em' }}>Quando</span>
        {row.when}
      </div>
    </div>
  );
}

export default function OpportunitiesSection({ opportunities }) {
  const data = opportunities && opportunities.length > 0 ? opportunities : null;

  if (!data) {
    return (
      <section style={{ marginBottom: 56 }}>
        <SectionHeader
          kicker="04 — Oportunidades perdidas"
          title="Conversas que não viraram consulta"
          sub="Casos onde houve interesse explícito sem follow-up adequado."
        />
        <SectionEmptyState
          title="Nenhuma oportunidade perdida identificada na amostra"
          message="Isso pode ser excelente — significa que cada interesse virou follow-up. OU os dados ainda são poucos pra identificar padrões."
          suggestion="Conforme mais conversas acumulam, leads sem retorno ficam visíveis aqui automaticamente."
        />
      </section>
    );
  }

  return (
    <section style={{ marginBottom: 56 }}>
      <SectionHeader
        kicker="04 — Oportunidades perdidas"
        title="Conversas que não viraram consulta"
        sub={`${data.length} ${data.length === 1 ? 'caso identificado' : 'casos identificados'} com interesse explícito sem fechamento. Pacientes anonimizados.`}
      />

      <div
        style={{
          background: COLORS.paper,
          border: `1px solid ${COLORS.hairline}`,
          borderRadius: 16,
          overflow: 'hidden',
        }}
      >
        {/* Header (≥ md) */}
        <div
          className="hidden md:grid"
          style={{
            gridTemplateColumns: 'minmax(80px, 0.7fr) 1.6fr 1.4fr 100px 80px',
            gap: 12,
            padding: '12px 18px',
            background: COLORS.sunken,
            fontSize: 10.5,
            textTransform: 'uppercase',
            letterSpacing: '0.12em',
            color: COLORS.inkSoft,
            fontWeight: 600,
          }}
        >
          {HEADERS.map((h) => (
            <div key={h}>{h}</div>
          ))}
        </div>

        {data.map((r) => (
          <Row key={r.tag} row={r} />
        ))}
      </div>
    </section>
  );
}
