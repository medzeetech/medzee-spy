import { Fragment } from 'react';
import { COLORS } from '../../constants/colors.js';
import {
  HEATMAP_DAYS as MOCK_HEATMAP_DAYS,
  HEATMAP_PERIODS as MOCK_HEATMAP_PERIODS,
  RESPONSE_DISTRIBUTION as MOCK_RESPONSE_DISTRIBUTION,
} from '../../data/reportData.js';
import SectionHeader from './SectionHeader.jsx';

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
  const days = heatmapDays && heatmapDays.length > 0 ? heatmapDays : MOCK_HEATMAP_DAYS;
  const periods =
    heatmapPeriods && heatmapPeriods.length > 0 ? heatmapPeriods : MOCK_HEATMAP_PERIODS;
  const distribution =
    responseTimeDistribution && responseTimeDistribution.length > 0
      ? responseTimeDistribution
      : MOCK_RESPONSE_DISTRIBUTION;

  const maxCount = Math.max(...distribution.map((d) => d.count));

  return (
    <section style={{ marginBottom: 56 }}>
      <SectionHeader
        kicker="02 — Tempo de resposta"
        title="Quando você responde — e quando não"
        sub="73% das mensagens fora do expediente ficam sem resposta. Sábado e noite são os piores horários."
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

              {periods.map((p) => (
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
            {distribution.map((row) => {
              const pct = (row.count / maxCount) * 100;
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
              Alerta crítico
            </div>
            <div style={{ fontSize: 12.5, color: COLORS.ink, lineHeight: 1.5 }}>
              24% das primeiras respostas demoram mais de 4h. A conversão desses leads é 3,4× menor do que dos respondidos em até 30min.
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
