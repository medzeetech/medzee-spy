import { COLORS } from '../../constants/colors.js';
import { BENCHMARKS } from '../../data/reportData.js';
import SectionHeader from './SectionHeader.jsx';

const SEGMENT_LABEL = {
  saude: 'Saúde',
  odonto: 'Odonto',
  outro: 'sua área',
};

export default function BenchmarkSection({ benchmarks, clinicSegment }) {
  const data = benchmarks && benchmarks.length > 0 ? benchmarks : BENCHMARKS;
  const segmentLabel = SEGMENT_LABEL[clinicSegment] || SEGMENT_LABEL.outro;

  return (
    <section style={{ marginBottom: 56 }}>
      <SectionHeader
        kicker="05 — Benchmark"
        title="Você vs. clínicas similares"
        sub={`Média de clínicas de ${segmentLabel} conectadas à Medzee*`}
      />

      <div
        style={{
          background: COLORS.paper,
          border: `1px solid ${COLORS.hairline}`,
          borderRadius: 16,
          padding: 'clamp(18px, 3vw, 26px)',
        }}
      >
        <div className="flex flex-col" style={{ gap: 26 }}>
          {data.map((b) => {
            const worse = b.better === 'lower' ? b.clinic > b.market : b.clinic < b.market;
            const maxVal = Math.max(b.clinic, b.market) * 1.15;
            const clinicPct = (b.clinic / maxVal) * 100;
            const marketPct = (b.market / maxVal) * 100;

            const clinicGradient = worse
              ? `linear-gradient(90deg, ${COLORS.wineSoft}, ${COLORS.wine})`
              : `linear-gradient(90deg, ${COLORS.orange}, ${COLORS.orangeDeep})`;

            const pillBg = worse ? 'rgba(92,29,46,0.15)' : 'rgba(255,107,53,0.15)';
            const pillColor = worse ? COLORS.wine : COLORS.orangeDeep;
            const pillText = worse ? 'Abaixo do mercado' : 'Acima do mercado';

            return (
              <div key={b.metric} className="flex flex-col" style={{ gap: 10 }}>
                <div className="flex items-center justify-between" style={{ gap: 12, flexWrap: 'wrap' }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: COLORS.ink, letterSpacing: '-0.01em' }}>
                    {b.metric}
                  </div>
                  <div
                    style={{
                      background: pillBg,
                      color: pillColor,
                      fontSize: 10.5,
                      fontWeight: 700,
                      padding: '4px 10px',
                      borderRadius: 99,
                      textTransform: 'uppercase',
                      letterSpacing: '0.1em',
                    }}
                  >
                    {pillText}
                  </div>
                </div>

                {/* Sua clínica */}
                <div className="flex items-center" style={{ gap: 12 }}>
                  <div style={{ fontSize: 11, color: COLORS.inkSoft, width: 80, flexShrink: 0 }}>Sua clínica</div>
                  <div className="flex-1" style={{ position: 'relative', height: 22, background: COLORS.sunken, borderRadius: 4, overflow: 'hidden' }}>
                    <div
                      style={{
                        height: '100%',
                        width: `${clinicPct}%`,
                        background: clinicGradient,
                        borderRadius: 4,
                        transition: 'width 0.6s ease',
                      }}
                    />
                  </div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: COLORS.ink, width: 70, textAlign: 'right', flexShrink: 0 }}>
                    {b.clinic}{b.unit}
                  </div>
                </div>

                {/* Mercado */}
                <div className="flex items-center" style={{ gap: 12 }}>
                  <div style={{ fontSize: 11, color: COLORS.inkSoft, width: 80, flexShrink: 0 }}>Mercado</div>
                  <div className="flex-1" style={{ position: 'relative', height: 22, background: COLORS.sunken, borderRadius: 4, overflow: 'hidden' }}>
                    <div
                      style={{
                        height: '100%',
                        width: `${marketPct}%`,
                        background: COLORS.lavender,
                        borderRadius: 4,
                      }}
                    />
                  </div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: COLORS.inkSoft, width: 70, textAlign: 'right', flexShrink: 0 }}>
                    {b.market}{b.unit}
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <div
          style={{
            marginTop: 22,
            paddingTop: 14,
            borderTop: `1px solid ${COLORS.hairline}`,
            fontSize: 11,
            color: COLORS.inkMute,
            lineHeight: 1.5,
          }}
        >
          *estimativa baseada em pesquisas setoriais da rede Medzee; atualizado periodicamente conforme a base cresce.
        </div>
      </div>
    </section>
  );
}
