import { Sparkles } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';

// Hard cap pra fake progress. NÃO chega a 100% até o backend confirmar
// `completed` (REPORT-19a). Curva ease-out até 80% nos primeiros 60s,
// marca-passo até 95% até 90s, depois trava em 95%.
function fakeProgress(elapsedMs) {
  const t = Math.min(elapsedMs / 60_000, 1);
  const phase1 = 80 * (1 - Math.pow(1 - t, 3));
  if (elapsedMs < 60_000) return phase1;
  const extra = Math.min((elapsedMs - 60_000) / 30_000, 1) * 15;
  return 80 + extra;
}

function messageFor(elapsedMs) {
  if (elapsedMs < 15_000) {
    return 'Analisando suas conversas dos últimos 30 dias…';
  }
  if (elapsedMs < 45_000) {
    return 'Identificando oportunidades e padrões de atendimento…';
  }
  if (elapsedMs < 90_000) {
    return 'Quase lá — finalizando o diagnóstico…';
  }
  // Após 90s, mensagem tranquilizadora sem CTA — recarregar reinicia o
  // pipeline e perde progresso. Polling no pano de fundo continua.
  return 'Finalizando os últimos detalhes. Aguarde mais um instante.';
}

export default function ReportGeneratingState({ elapsedMs = 0 }) {
  const pct = fakeProgress(elapsedMs);
  const message = messageFor(elapsedMs);

  return (
    <div
      style={{
        width: '100%',
        minHeight: 'calc(100vh - 80px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '24px 16px',
        fontFamily: "'Red Hat Display', sans-serif",
      }}
    >
      <div
        className="anim-fadeup"
        style={{
          position: 'relative',
          width: '100%',
          maxWidth: 480,
          background: COLORS.paper,
          border: `1px solid ${COLORS.hairline}`,
          borderRadius: 20,
          padding: 'clamp(24px, 4vw, 36px)',
          boxShadow: '0 12px 32px -16px rgba(0,0,0,0.08)',
          textAlign: 'center',
        }}
      >
        <div
          className="inline-flex items-center"
          style={{
            gap: 8,
            padding: '6px 12px',
            borderRadius: 99,
            background: 'rgba(255,107,53,0.1)',
            border: '1px solid rgba(255,107,53,0.25)',
            color: COLORS.orange,
            fontSize: 11.5,
            fontWeight: 600,
            letterSpacing: '0.04em',
            marginBottom: 20,
          }}
        >
          <Sparkles size={13} />
          Diagnóstico Spy
        </div>

        <h1
          style={{
            fontSize: 'clamp(22px, 3.6vw, 28px)',
            fontWeight: 800,
            letterSpacing: '-0.02em',
            color: COLORS.ink,
            margin: 0,
            marginBottom: 12,
            lineHeight: 1.2,
          }}
        >
          Análise IA em curso
        </h1>

        <div
          className="flex items-center justify-center"
          style={{
            gap: 10,
            margin: '0 auto 28px',
            color: COLORS.inkSoft,
            fontSize: 14.5,
            lineHeight: 1.5,
            maxWidth: 400,
            minHeight: 44,
          }}
        >
          <span
            className="anim-pulse-dot"
            style={{
              width: 8,
              height: 8,
              borderRadius: 99,
              background: COLORS.orange,
              flexShrink: 0,
              boxShadow: '0 0 10px rgba(255,107,53,0.5)',
            }}
          />
          <span>{message}</span>
        </div>

        <div
          style={{
            height: 6,
            background: COLORS.sunken,
            borderRadius: 99,
            overflow: 'hidden',
            marginBottom: 12,
          }}
        >
          <div
            style={{
              height: '100%',
              width: `${pct}%`,
              transition: 'width 1s linear',
              background: `linear-gradient(90deg, ${COLORS.orangeDeep}, ${COLORS.orange})`,
              borderRadius: 99,
            }}
          />
        </div>

        <div
          style={{
            fontSize: 11.5,
            color: COLORS.inkMute,
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            fontWeight: 600,
          }}
        >
          {Math.round(pct)}% concluído
        </div>
      </div>
    </div>
  );
}
