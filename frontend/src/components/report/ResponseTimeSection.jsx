import { Fragment } from 'react';
import { COLORS } from '../../constants/colors.js';
import SectionHeader from './SectionHeader.jsx';
import SectionEmptyState from './SectionEmptyState.jsx';

const DEFAULT_DAYS = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'];

function heatStyle(val) {
  if (val === 0) {
    return { bg: COLORS.sunken, color: COLORS.inkMute, text: '—' };
  }
  const ratio = val / 12;
  const formatted = val < 1 ? `${Math.round(val * 60)}m` : `${val.toFixed(1)}h`;

  if (ratio < 0.15) return { bg: COLORS.orangeSoft, color: COLORS.ink, text: formatted };
  if (ratio < 0.35) return { bg: `${COLORS.gold}80`, color: COLORS.ink, text: formatted };
  if (ratio < 0.6) return { bg: `${COLORS.wineSoft}CC`, color: COLORS.cream, text: formatted };
  return { bg: COLORS.wine, color: COLORS.cream, text: formatted };
}

export default function ResponseTimeSection({
  heatmapDays,
  heatmapPeriods,
  responseTimeDistribution,
}) {
  const days = heatmapDays && heatmapDays.length > 0 ? heatmapDays : DEFAULT_DAYS;
  const periods = heatmapPeriods && heatmapPeriods.length > 0 ? heatmapPeriods : null;
  const distribution =
    responseTimeDistribution && responseTimeDistribution.length > 0
      ? responseTimeDistribution
      : null;

  if (!periods && !distribution) {
    return (
      <section style={{ marginBottom: 56 }}>
        <SectionHeader
          kicker="02 — Tempo de resposta"
          title="Quando você responde — e quando não"
          sub="Análise de tempo até a 1ª resposta por dia/horário."
        />
        <SectionEmptyState
          title="Sem mensagens suficientes pra calcular tempo de resposta"
          message="Precisamos de pelo menos algumas conversas com troca de mensagens (cliente → clínica → cliente) pra medir tempos."
          suggestion="O cálculo fica mais preciso conforme mais conversas acumulam no período."
        />
      </section>
    );
  }

  const maxCount = distribution ? Math.max(...distribution.map((d) => d.count), 1) : 0;
  const totalResponses = distribution ? distribution.reduce((s, b) => s + (b.count || 0), 0) : 0;

  return (
    <section style={{ marginBottom: 56 }}>
      <SectionHeader
        kicker="02 — Tempo de resposta"
        title="Quando você responde — e quando não"
        sub={
          totalResponses > 0
            ? `Análise de ${totalResponses.toLocaleString('pt-BR')} primeiras respostas no período.`
            : 'Análise de tempo até a 1ª resposta por dia/horário.'
        }
      />

      <div
        className="grid grid-cols-1 lg:grid-cols-[1.4fr_1fr]"
        style={{ gap: 20 }}
      >
        {/* Heatmap */}
        <div
          style={{
            background: COLORS.paper,
            border: `1px solid ${COLORS.hairline}`,
            borderRadius: 16,
            padding: 'clamp(18px, 3vw, 22px)',
          }}
        >
          <div style={{ marginBottom: 4 }}>
            <h3
              style={{
                fontSize: 15,
                fontWeight: 700,
                color: COLORS.ink,
                margin: 0,
                letterSpacing: '-0.01em',
              }}
            >
              Mapa de calor por dia e período
            </h3>
            <div style={{ fontSize: 12, color: COLORS.inkSoft, marginTop: 4 }}>
              Tempo médio até a 1ª resposta (horas)
            </div>
          </div>

          <div style={{ marginTop: 18, overflowX: 'auto' }}>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '60px repeat(7, minmax(38px, 1fr))',
                gap: 4,
                minWidth: 360,
              }}
            >
              <div />
              {days.map((day) => (
                <div
                  key={day}
                  style={{
                    fontSize: 10.5,
                    color: COLORS.inkMute,
                    textTransform: 'uppercase',
                    letterSpacing: '0.12em',
                    fontWeight: 600,
                    textAlign: 'center',
                    paddingBottom: 4,
                  }}
                >
                  {day}
                </div>
              ))}

              {(periods || []).map((p) => (
                <Fragment key={p.label}>
                  <div
                    style={{
                      fontSize: 11,
                      color: COLORS.inkSoft,
                      fontWeight: 600,
                      display: 'flex',
                      alignItems: 'center',
                    }}
                  >
                    {p.label}
                  </div>
                  {p.values.map((v, i) => {
                    const s = heatStyle(v);
                    return (
                      <div
                        key={`${p.label}-${i}`}
                        style={{
                          aspectRatio: '1.1',
                          background: s.bg,
                          color: s.color,
                          borderRadius: 6,
                          fontSize: 10.5,
                          fontWeight: 600,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                        }}
                      >
                        {s.text}
                      </div>
                    );
                  })}
                </Fragment>
              ))}
            </div>
          </div>

          {/* Legenda */}
          <div
            className="flex items-center"
            style={{ gap: 8, marginTop: 16, fontSize: 11, color: COLORS.inkSoft }}
          >
            <span>Rápido</span>
            {[COLORS.orangeSoft, `${COLORS.gold}80`, `${COLORS.wineSoft}CC`, COLORS.wine].map((c) => (
              <span
                key={c}
                style={{ width: 18, height: 12, borderRadius: 3, background: c, display: 'inline-block' }}
              />
            ))}
            <span>Lento</span>
          </div>
        </div>

        {/* Distribuição */}
        <div
          style={{
            background: COLORS.paper,
            border: `1px solid ${COLORS.hairline}`,
            borderRadius: 16,
            padding: 'clamp(18px, 3vw, 22px)',
          }}
        >
          <h3
            style={{
              fontSize: 15,
              fontWeight: 700,
              color: COLORS.ink,
              margin: 0,
              letterSpacing: '-0.01em',
            }}
          >
            Distribuição das 1ªs respostas
          </h3>
          <div style={{ fontSize: 12, color: COLORS.inkSoft, marginTop: 4, marginBottom: 18 }}>
            Em quanto tempo a clínica responde
          </div>

          <div className="flex flex-col" style={{ gap: 12 }}>
            {(distribution || []).map((row) => {
              const pct = maxCount > 0 ? (row.count / maxCount) * 100 : 0;
              return (
                <div key={row.faixa} className="flex flex-col" style={{ gap: 4 }}>
                  <div className="flex items-center justify-between">
                    <span style={{ fontSize: 12.5, color: COLORS.ink, fontWeight: 500 }}>{row.faixa}</span>
                    <span style={{ fontSize: 12.5, color: COLORS.inkSoft, fontWeight: 600 }}>{row.count}</span>
                  </div>
                  <div
                    style={{
                      height: 6,
                      background: COLORS.sunken,
                      borderRadius: 99,
                      overflow: 'hidden',
                    }}
                  >
                    <div
                      style={{
                        height: '100%',
                        width: `${pct}%`,
                        background: row.color,
                        borderRadius: 99,
                      }}
                    />
                  </div>
                </div>
              );
            })}
          </div>

          {(() => {
            // Alerta sai dos dados reais: % de respostas > 4h. Sem chute.
            if (!distribution || totalResponses === 0) return null;
            const slow = distribution
              .filter((b) => ['4h–24h', '> 24h'].includes(b.faixa))
              .reduce((s, b) => s + (b.count || 0), 0);
            const slowPct = (slow / totalResponses) * 100;
            if (slowPct < 5) return null;
            return (
              <div
                style={{
                  marginTop: 22,
                  borderLeft: `3px solid ${COLORS.wine}`,
                  background: 'rgba(92,29,46,0.05)',
                  borderRadius: 10,
                  padding: '12px 14px',
                }}
              >
                <div
                  style={{
                    fontSize: 11,
                    color: COLORS.wine,
                    fontWeight: 700,
                    textTransform: 'uppercase',
                    letterSpacing: '0.12em',
                    marginBottom: 4,
                  }}
                >
                  Alerta
                </div>
                <div style={{ fontSize: 12.5, color: COLORS.ink, lineHeight: 1.5 }}>
                  <strong>{slowPct.toFixed(1)}%</strong> das primeiras respostas levam mais de 4h. Leads com resposta lenta costumam converter menos.
                </div>
              </div>
            );
          })()}
        </div>
      </div>
    </section>
  );
}
