import { Download } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';

// Friendly labels pro clinic_segment do users_profile / report payload.
const SEGMENT_LABEL = {
  saude: 'Saúde / Clínica',
  odonto: 'Odontologia',
  outro: 'Atendimento geral',
};

function buildSubtitle({ clinicSegment, messageCount, conversationCount, createdAt }) {
  const parts = [];
  if (clinicSegment) {
    parts.push(SEGMENT_LABEL[clinicSegment] || SEGMENT_LABEL.outro);
  }
  if (typeof messageCount === 'number' && messageCount > 0) {
    parts.push(
      `${messageCount.toLocaleString('pt-BR')} ${messageCount === 1 ? 'mensagem' : 'mensagens'} analisada${messageCount === 1 ? '' : 's'}`
    );
  }
  if (typeof conversationCount === 'number' && conversationCount > 0) {
    parts.push(
      `${conversationCount} ${conversationCount === 1 ? 'conversa' : 'conversas'}`
    );
  }
  if (createdAt) {
    const d = new Date(createdAt);
    if (!Number.isNaN(d.getTime())) {
      parts.push(
        d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' })
      );
    }
  }
  return parts.join(' • ');
}

export default function ReportTopbar({
  // Nome a exibir (ex.: "Patrick Queiroz"). Fallback genérico se ausente.
  ownerName,
  // Status badge — default 'monitorando'. Pode virar null pra ocultar.
  status = 'monitorando',
  // Dados da análise pro subtítulo
  clinicSegment,
  messageCount,
  conversationCount,
  createdAt,
}) {
  const subtitle = buildSubtitle({
    clinicSegment,
    messageCount,
    conversationCount,
    createdAt,
  });
  const displayName = ownerName || 'Sua conexão WhatsApp';

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
          {ownerName ? 'Conta analisada' : 'WhatsApp conectado'}
        </div>
        <div className="flex items-center" style={{ gap: 10, flexWrap: 'wrap', marginBottom: 4 }}>
          <span style={{ fontSize: 16, fontWeight: 600, color: COLORS.ink, letterSpacing: '-0.01em' }}>
            {displayName}
          </span>
          {status && (
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
              {status}
            </span>
          )}
        </div>
        {subtitle && (
          <div style={{ fontSize: 11.5, color: COLORS.inkSoft }}>
            {subtitle}
          </div>
        )}
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
