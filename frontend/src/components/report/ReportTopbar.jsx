import { Download } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';

export default function ReportTopbar() {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between" style={{ gap: 16, marginBottom: 28 }}>
      <div>
        <div
          style={{
            fontSize: 10.5,
            color: COLORS.inkMute,
            textTransform: 'uppercase',
            letterSpacing: '0.18em',
            fontWeight: 600,
            marginBottom: 6,
          }}
        >
          Clínica conectada
        </div>
        <div className="flex items-center" style={{ gap: 10, flexWrap: 'wrap', marginBottom: 4 }}>
          <span style={{ fontSize: 16, fontWeight: 600, color: COLORS.ink, letterSpacing: '-0.01em' }}>
            Clínica São Bento
          </span>
          <span
            className="inline-flex items-center"
            style={{
              background: '#E8F5E9',
              color: '#2E7D32',
              borderRadius: 99,
              padding: '3px 10px',
              fontSize: 11,
              fontWeight: 600,
              gap: 5,
            }}
          >
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#2E7D32' }} />
            monitorando
          </span>
        </div>
        <div style={{ fontSize: 11.5, color: COLORS.inkSoft }}>
          Cardiologia • 4 atendentes • 28 dias analisados
        </div>
      </div>

      <button
        type="button"
        className="inline-flex items-center transition-colors self-start sm:self-auto"
        style={{
          gap: 8,
          padding: '9px 14px',
          borderRadius: 10,
          border: `1px solid ${COLORS.hairline}`,
          background: COLORS.paper,
          color: COLORS.ink,
          fontSize: 12.5,
          fontWeight: 600,
          cursor: 'pointer',
          fontFamily: "'Red Hat Display', sans-serif",
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = COLORS.sunken;
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = COLORS.paper;
        }}
      >
        <Download size={14} />
        Exportar relatório
      </button>
    </div>
  );
}
