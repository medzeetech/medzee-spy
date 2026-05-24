import { Sparkles } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';
import SectionHeader from './SectionHeader.jsx';
import SectionEmptyState from './SectionEmptyState.jsx';

export default function FunnelSection({ funnel }) {
  const data = funnel && funnel.length > 0 ? funnel : null;
  const totalInitial = data && data.length > 0 ? data[0].count : 0;
  const finalCount = data && data.length > 0 ? data[data.length - 1].count : 0;

  if (!data) {
    return (
      <section style={{ marginBottom: 56 }}>
        <SectionHeader
          kicker="01 — Saúde do funil"
          title="Onde o paciente desiste"
          sub="Mapeamento das etapas do atendimento até o agendamento."
        />
        <SectionEmptyState
          title="Funil sem dados suficientes"
          message="Pra mapear onde o paciente desiste, precisamos de pelo menos algumas conversas completas no período."
          suggestion="Continue usando o WhatsApp da clínica normalmente. Mais conversas = funil mais preciso."
        />
      </section>
    );
  }

  return (
    <section style={{ marginBottom: 56 }}>
      <SectionHeader
        kicker="01 — Saúde do funil"
        title="Onde o paciente desiste"
        sub={`${totalInitial} ${totalInitial === 1 ? 'conversa iniciada' : 'conversas iniciadas'}. ${finalCount} ${finalCount === 1 ? 'virou' : 'viraram'} agendamento.`}
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
          {data.map((row, i) => {
            const prev = i > 0 ? data[i - 1] : null;
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

        {(() => {
          // Maior gargalo = a maior queda entre 2 estágios consecutivos.
          // Calculado a partir dos dados reais — sem mais "153 pacientes (53%)"
          // hardcoded.
          if (data.length < 2) return null;
          let worstDropIdx = -1;
          let worstDrop = 0;
          for (let i = 1; i < data.length; i++) {
            const drop = data[i - 1].pct - data[i].pct;
            if (drop > worstDrop) {
              worstDrop = drop;
              worstDropIdx = i;
            }
          }
          if (worstDropIdx === -1) return null;
          const from = data[worstDropIdx - 1];
          const to = data[worstDropIdx];
          const dropCount = from.count - to.count;
          return (
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
                  <strong style={{ fontWeight: 700 }}>Maior gargalo:</strong> entre "{from.stage}" e "{to.stage}" — perdem-se{' '}
                  <strong style={{ color: COLORS.orangeDeep, fontWeight: 700 }}>
                    {dropCount} {dropCount === 1 ? 'paciente' : 'pacientes'} ({worstDrop.toFixed(1)}%)
                  </strong>.
                </div>
              </div>
            </div>
          );
        })()}
      </div>
    </section>
  );
}
