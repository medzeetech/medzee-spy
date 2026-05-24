// M2 simplificado — sem mais fake stats de uazapi/whatsapp.
//
// A extensão Chrome agora coleta as mensagens fora do nosso runtime, então
// não temos visibilidade de "X conversas / Y mensagens" durante a geração.
// O backend polling do report row (useReportPolling) é a única fonte de
// verdade — quando ele transiciona pra completed/partial/failed, mostramos
// o relatório ou o erro. Enquanto isso, spinner honesto.

import { Sparkles } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';

export default function ReportGeneratingState({ elapsedMs = 0 }) {
  const seconds = Math.max(0, Math.round(elapsedMs / 1000));

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
          maxWidth: 520,
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
            marginBottom: 10,
            lineHeight: 1.2,
          }}
        >
          Gerando seu relatório…
        </h1>

        <p
          style={{
            color: COLORS.inkSoft,
            fontSize: 14,
            lineHeight: 1.55,
            margin: '0 auto 24px',
            maxWidth: 440,
            minHeight: 44,
          }}
        >
          Cruzando suas conversas pra montar funil, oportunidades e benchmarks.
          Costuma levar entre 60 e 90 segundos.
        </p>

        <div
          style={{
            height: 6,
            background: COLORS.sunken,
            borderRadius: 99,
            overflow: 'hidden',
            marginBottom: 12,
            position: 'relative',
          }}
        >
          <div
            className="anim-pulse-dot"
            style={{
              height: '100%',
              width: '40%',
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
          {seconds}s
        </div>
      </div>
    </div>
  );
}
