import { Sparkles } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';
import { FUNNEL } from '../../data/reportData.js';
import SectionHeader from './SectionHeader.jsx';

export default function FunnelSection() {
  return (
    <section style={{ marginBottom: 56 }}>
      <SectionHeader
        kicker="01 — Saúde do funil"
        title="Onde o paciente desiste"
        sub="412 conversas iniciadas. Apenas 51 viraram agendamento. Cada etapa esconde uma fuga — algumas evitáveis."
      />

      <div
        style={{
          background: COLORS.paper,
          border: `1px solid ${COLORS.hairline}`,
          borderRadius: 16,
          padding: 'clamp(18px, 3vw, 24px)',
        }}
      >
        <div className="flex flex-col" style={{ gap: 14 }}>
          {FUNNEL.map((row, i) => {
            const prev = i > 0 ? FUNNEL[i - 1] : null;
            const drop = prev ? prev.pct - row.pct : 0;
            const dropCount = prev ? prev.count - row.count : 0;

            return (
              <div
                key={row.stage}
                className="flex items-center"
                style={{ gap: 14 }}
              >
                <div
                  style={{
                    fontSize: 11,
                    color: COLORS.inkMute,
                    fontWeight: 600,
                    width: 24,
                    flexShrink: 0,
                  }}
                >
                  {String(i + 1).padStart(2, '0')}
                </div>

                <div
                  className="hidden md:block"
                  style={{
                    fontSize: 13,
                    color: COLORS.ink,
                    fontWeight: 500,
                    width: 200,
                    flexShrink: 0,
                  }}
                >
                  {row.stage}
                </div>

                <div className="flex-1 flex flex-col" style={{ gap: 4, minWidth: 0 }}>
                  <div
                    className="md:hidden"
                    style={{ fontSize: 13, color: COLORS.ink, fontWeight: 500 }}
                  >
                    {row.stage}
                  </div>
                  <div
                    style={{
                      position: 'relative',
                      height: 36,
                      borderRadius: 8,
                      overflow: 'hidden',
                      background: COLORS.sunken,
                    }}
                  >
                    <div
                      style={{
                        position: 'absolute',
                        inset: 0,
                        width: `${row.pct}%`,
                        background: `linear-gradient(90deg, ${COLORS.orange}, ${COLORS.orangeDeep})`,
                        display: 'flex',
                        alignItems: 'center',
                        paddingLeft: 14,
                        color: COLORS.cream,
                        fontWeight: 700,
                        fontSize: 13,
                        transition: 'width 0.6s ease',
                      }}
                    >
                      {row.count}
                    </div>
                  </div>
                </div>

                <div
                  className="hidden md:flex flex-col items-end"
                  style={{ width: 110, flexShrink: 0 }}
                >
                  <div style={{ fontSize: 14, fontWeight: 700, color: COLORS.ink }}>
                    {row.pct.toFixed(1)}%
                  </div>
                  {prev && drop > 0 && (
                    <div style={{ fontSize: 11.5, color: COLORS.wineSoft, fontWeight: 500 }}>
                      ↓ −{drop.toFixed(1)}% ({dropCount})
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        <div
          style={{
            marginTop: 22,
            paddingTop: 18,
            borderTop: `1px dashed ${COLORS.hairline}`,
          }}
        >
          <div className="flex items-start" style={{ gap: 12 }}>
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: 9,
                background: COLORS.orangeSoft,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
              }}
            >
              <Sparkles size={15} color={COLORS.orangeDeep} />
            </div>
            <div style={{ fontSize: 13.5, color: COLORS.ink, lineHeight: 1.55 }}>
              <strong style={{ fontWeight: 700 }}>Maior gargalo:</strong> entre "engajados" e "orçamento dado" — perdem-se{' '}
              <strong style={{ color: COLORS.orangeDeep, fontWeight: 700 }}>153 pacientes (53%)</strong>. Geralmente porque o valor não é informado, ou é informado tarde demais.
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
