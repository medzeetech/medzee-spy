// SectionEmptyState — placeholder honesto pra quando uma seção do relatório
// não tem dados (ou os dados são insuficientes pra análise).
//
// Substitui o fallback antigo pra MOCK_DATA (números falsos) por mensagem
// transparente + sugestão de ação. Usado quando o payload do relatório
// vem com array vazio numa seção ou quando data_quality=insufficient.

import { Info } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';

export default function SectionEmptyState({ title, message, suggestion }) {
  return (
    <div
      style={{
        background: COLORS.paper,
        border: `1px dashed ${COLORS.hairline}`,
        borderRadius: 16,
        padding: 'clamp(24px, 4vw, 36px)',
        textAlign: 'center',
      }}
    >
      <div
        style={{
          width: 44,
          height: 44,
          borderRadius: 12,
          background: 'rgba(184,168,217,0.15)',
          color: COLORS.lavender,
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          marginBottom: 14,
        }}
      >
        <Info size={20} />
      </div>
      <div
        style={{
          fontSize: 15,
          fontWeight: 700,
          color: COLORS.ink,
          marginBottom: 8,
          letterSpacing: '-0.01em',
        }}
      >
        {title || 'Sem dados suficientes'}
      </div>
      {message && (
        <div
          style={{
            fontSize: 13.5,
            color: COLORS.inkSoft,
            lineHeight: 1.55,
            maxWidth: 480,
            margin: '0 auto',
          }}
        >
          {message}
        </div>
      )}
      {suggestion && (
        <div
          style={{
            fontSize: 12.5,
            color: COLORS.inkMute,
            marginTop: 12,
            fontStyle: 'italic',
            maxWidth: 480,
            marginLeft: 'auto',
            marginRight: 'auto',
          }}
        >
          {suggestion}
        </div>
      )}
    </div>
  );
}
