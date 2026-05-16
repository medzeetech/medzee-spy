import { ArrowRight } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';

export default function FinalCTA() {
  return (
    <div
      style={{
        position: 'relative',
        overflow: 'hidden',
        background: COLORS.ink,
        borderRadius: 20,
        padding: 'clamp(28px, 4vw, 44px)',
        color: COLORS.cream,
        marginBottom: 32,
      }}
    >
      <div
        style={{
          position: 'absolute',
          top: -80,
          right: -80,
          width: 260,
          height: 260,
          borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(255,107,53,0.25), transparent 70%)',
          pointerEvents: 'none',
        }}
      />

      <div
        className="flex flex-col lg:flex-row lg:items-center"
        style={{ gap: 24, position: 'relative' }}
      >
        <div className="flex-1">
          <div
            style={{
              fontSize: 11,
              color: COLORS.orange,
              textTransform: 'uppercase',
              letterSpacing: '0.18em',
              fontWeight: 700,
              marginBottom: 12,
            }}
          >
            Esses números podem mudar
          </div>
          <h3
            style={{
              fontSize: 'clamp(20px, 3vw, 28px)',
              fontWeight: 700,
              color: COLORS.cream,
              letterSpacing: '-0.02em',
              lineHeight: 1.2,
              margin: 0,
              marginBottom: 12,
            }}
          >
            Um agente de IA no WhatsApp responde em segundos, 24/7, e fecha o que sua equipe não consegue.
          </h3>
          <p
            style={{
              fontSize: 14,
              color: 'rgba(250,246,240,0.67)',
              lineHeight: 1.55,
              margin: 0,
              maxWidth: 540,
            }}
          >
            A Medzee aprende com o histórico real da sua clínica — esse mesmo que você acabou de ver — e atende como se fosse a melhor pessoa do seu time.
          </p>
        </div>

        <button
          type="button"
          className="inline-flex items-center justify-center transition-all self-start lg:self-auto"
          style={{
            gap: 8,
            padding: '14px 22px',
            borderRadius: 12,
            border: 'none',
            background: COLORS.orange,
            color: COLORS.cream,
            fontSize: 14,
            fontWeight: 700,
            cursor: 'pointer',
            fontFamily: "'Red Hat Display', sans-serif",
            flexShrink: 0,
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = COLORS.orangeDeep;
            e.currentTarget.style.transform = 'translateY(-1px)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = COLORS.orange;
            e.currentTarget.style.transform = 'translateY(0)';
          }}
        >
          Conhecer o agente
          <ArrowRight size={16} />
        </button>
      </div>
    </div>
  );
}
