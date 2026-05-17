import { PieChart, Pie, Cell } from 'recharts';
import { COLORS } from '../../constants/colors.js';
import {
  OBJECTIONS as MOCK_OBJECTIONS,
  FAQS as MOCK_FAQS,
  SENTIMENT as MOCK_SENTIMENT,
} from '../../data/reportData.js';
import SectionHeader from './SectionHeader.jsx';

function CardShell({ title, sub, children }) {
  return (
    <div
      style={{
        background: COLORS.paper,
        border: `1px solid ${COLORS.hairline}`,
        borderRadius: 16,
        padding: 'clamp(18px, 3vw, 22px)',
        display: 'flex',
        flexDirection: 'column',
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
        {title}
      </h3>
      <div style={{ fontSize: 12, color: COLORS.inkSoft, marginTop: 4, marginBottom: 18 }}>{sub}</div>
      {children}
    </div>
  );
}

export default function VoiceSection({ objections, faqs, sentiment }) {
  const objectionsData =
    objections && objections.length > 0 ? objections : MOCK_OBJECTIONS;
  const faqsData = faqs && faqs.length > 0 ? faqs : MOCK_FAQS;
  const sentimentData =
    sentiment && sentiment.length > 0 ? sentiment : MOCK_SENTIMENT;
  const positiveValue =
    sentimentData.find((s) => s.name === 'Positivo')?.value ?? sentimentData[0]?.value ?? 0;

  return (
    <section style={{ marginBottom: 56 }}>
      <SectionHeader
        kicker="03 — Voz do paciente"
        title="O que eles realmente perguntam"
        sub="Análise semântica de 3.370 mensagens. Padrões que se repetem viram FAQ — ou viram objeções não respondidas."
      />

      <div
        className="grid grid-cols-1 lg:grid-cols-[1.1fr_1fr_0.8fr]"
        style={{ gap: 20 }}
      >
        {/* Objeções */}
        <CardShell title="Top objeções identificadas" sub="Motivos que travaram conversões">
          <div className="flex flex-col" style={{ gap: 14 }}>
            {objectionsData.map((o) => (
              <div key={o.label} className="flex flex-col" style={{ gap: 5 }}>
                <div className="flex items-center justify-between">
                  <span style={{ fontSize: 12.5, color: COLORS.ink, fontWeight: 500 }}>{o.label}</span>
                  <span style={{ fontSize: 12, color: COLORS.inkSoft, fontWeight: 600 }}>
                    {o.pct}% <span style={{ color: COLORS.inkMute, fontWeight: 400 }}>({o.count})</span>
                  </span>
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
                      width: `${o.pct * 2.5}%`,
                      background: o.color,
                      borderRadius: 99,
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </CardShell>

        {/* FAQs */}
        <CardShell title="Perguntas mais frequentes" sub="Candidatas a FAQ automatizado">
          <div className="flex flex-col">
            {faqsData.map((faq, i) => (
              <div
                key={faq.q}
                className="flex items-start"
                style={{
                  gap: 12,
                  padding: '10px 0',
                  borderTop: i === 0 ? 'none' : `1px solid ${COLORS.hairline}`,
                }}
              >
                <div
                  style={{
                    width: 24,
                    height: 24,
                    borderRadius: 7,
                    background: COLORS.orangeSoft,
                    color: COLORS.orangeDeep,
                    fontSize: 11,
                    fontWeight: 700,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexShrink: 0,
                  }}
                >
                  {i + 1}
                </div>
                <div className="flex-1" style={{ minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: 13,
                      color: COLORS.ink,
                      fontStyle: 'italic',
                      lineHeight: 1.45,
                    }}
                  >
                    "{faq.q}"
                  </div>
                </div>
                <div
                  style={{
                    fontSize: 12,
                    color: COLORS.inkSoft,
                    fontWeight: 600,
                    flexShrink: 0,
                    paddingTop: 1,
                  }}
                >
                  ×{faq.count}
                </div>
              </div>
            ))}
          </div>
        </CardShell>

        {/* Sentimento */}
        <CardShell title="Sentimento geral" sub="Tom predominante das conversas">
          <div style={{ position: 'relative', display: 'flex', justifyContent: 'center', alignItems: 'center', height: 160 }}>
            <PieChart width={180} height={160}>
              <Pie
                data={sentimentData}
                dataKey="value"
                cx="50%"
                cy="50%"
                innerRadius={42}
                outerRadius={66}
                paddingAngle={3}
                strokeWidth={0}
              >
                {sentimentData.map((entry) => (
                  <Cell key={entry.name} fill={entry.color} />
                ))}
              </Pie>
            </PieChart>
            <div
              style={{
                position: 'absolute',
                inset: 0,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                pointerEvents: 'none',
              }}
            >
              <div style={{ fontSize: 26, fontWeight: 700, color: COLORS.ink, letterSpacing: '-0.02em', lineHeight: 1 }}>
                {positiveValue}%
              </div>
              <div
                style={{
                  fontSize: 10,
                  color: COLORS.inkMute,
                  textTransform: 'uppercase',
                  letterSpacing: '0.16em',
                  fontWeight: 600,
                  marginTop: 4,
                }}
              >
                positivo
              </div>
            </div>
          </div>

          <div className="flex flex-col" style={{ gap: 8, marginTop: 14 }}>
            {sentimentData.map((s) => (
              <div key={s.name} className="flex items-center justify-between" style={{ fontSize: 12.5 }}>
                <span className="flex items-center" style={{ gap: 8, color: COLORS.ink }}>
                  <span style={{ width: 8, height: 8, borderRadius: '50%', background: s.color }} />
                  {s.name}
                </span>
                <span style={{ color: COLORS.inkSoft, fontWeight: 600 }}>{s.value}%</span>
              </div>
            ))}
          </div>
        </CardShell>
      </div>
    </section>
  );
}
