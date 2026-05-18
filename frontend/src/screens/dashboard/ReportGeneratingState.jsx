import { Sparkles } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';

// Fases reais do pipeline mapeadas em tempo aproximado. Cada fase tem
// janela de progresso (% início → % fim) baseada em medições do backend:
//
//   0-25s    | 0-22%  | "Coletando histórico do WhatsApp..."  (pull_history /chat/find + paginação)
//   25-70s   | 22-55% | "Lendo conversas e mensagens..."      (per-chat /message/find paralelo)
//   70-110s  | 55-78% | "Mapeando funil e padrões..."         (compute_funnel, sample_conversations)
//   110-145s | 78-92% | "IA analisando insights..."           (LLM call)
//   145s+    | 92-98% | "Finalizando..."                       (persist + retry budget)
//
// Cap em 98% até o backend devolver status='completed'. Não chega a 100%
// pra evitar mostrar conclusão antes de hora.

const PHASES = [
  { until: 25_000, msg: 'Coletando histórico do WhatsApp…', from: 0, to: 22 },
  { until: 70_000, msg: 'Lendo conversas e mensagens…', from: 22, to: 55 },
  { until: 110_000, msg: 'Mapeando funil e padrões…', from: 55, to: 78 },
  { until: 145_000, msg: 'IA analisando insights…', from: 78, to: 92 },
  { until: Infinity, msg: 'Finalizando o diagnóstico…', from: 92, to: 98 },
];

function phaseFor(elapsedMs) {
  let cursor = 0;
  for (const p of PHASES) {
    if (elapsedMs < p.until) {
      const span = p.until - cursor;
      const inPhaseMs = elapsedMs - cursor;
      const ratio = Math.min(Math.max(inPhaseMs / span, 0), 1);
      const pct = p.from + (p.to - p.from) * ratio;
      return { msg: p.msg, pct };
    }
    cursor = p.until;
  }
  // Inalcançável (último PHASES.until=Infinity), mas defensivo:
  return { msg: 'Finalizando o diagnóstico…', pct: 98 };
}

export default function ReportGeneratingState({ elapsedMs = 0 }) {
  const { msg: message, pct } = phaseFor(elapsedMs);

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
          Gerando seu diagnóstico
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
          {Math.round(pct)}% concluído · {Math.round(elapsedMs / 1000)}s
        </div>
      </div>
    </div>
  );
}
