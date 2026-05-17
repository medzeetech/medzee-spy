import { Activity, TrendingDown, AlertCircle, Clock, Target } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';
import bgCard from '../../assets/background-card.svg';

const DEFAULT_PILLS = [
  {
    icon: AlertCircle,
    iconColor: COLORS.orange,
    label: 'Oportunidades perdidas',
    value: '47',
    sub: '11,4% das conversas',
  },
  {
    icon: Clock,
    iconColor: COLORS.gold,
    label: 'Tempo médio 1ª resposta',
    value: '4h 22min',
    sub: 'Mercado: 48 min',
  },
  {
    icon: Target,
    iconColor: COLORS.orange,
    label: 'Taxa de conversão',
    value: '12,4%',
    sub: 'Mercado: 24%',
  },
];

function formatBRL(v) {
  if (v == null) return null;
  return v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 });
}

export default function HeroCard({ score, messageCount, diagnosticSummary }) {
  const headlineValue = formatBRL(score) ?? 'R$ 38.400';
  const summary =
    diagnosticSummary && diagnosticSummary.trim().length > 0
      ? diagnosticSummary
      : 'Nos últimos 28 dias, sua clínica deixou passar receita equivalente a 45 consultas particulares. Abaixo, onde isso aconteceu.';
  const PILLS =
    messageCount != null
      ? [
          {
            ...DEFAULT_PILLS[0],
            sub: `de ${messageCount.toLocaleString('pt-BR')} mensagens`,
          },
          DEFAULT_PILLS[1],
          DEFAULT_PILLS[2],
        ]
      : DEFAULT_PILLS;

  return (
    <div
      style={{
        position: 'relative',
        overflow: 'hidden',
        borderRadius: 24,
        padding: 'clamp(28px, 5vw, 48px)',
        backgroundColor: '#630A36',
        color: COLORS.cream,
        marginBottom: 56,
      }}
    >
      <div
        aria-hidden="true"
        style={{
          position: 'absolute',
          inset: 0,
          backgroundImage: `url("${bgCard}")`,
          backgroundSize: '111.527% 134.554%',
          backgroundPosition: '50% 69.72%',
          backgroundRepeat: 'no-repeat',
          pointerEvents: 'none',
        }}
      />

      <div style={{ position: 'relative' }}>
        {/* Kicker */}
        <div
          className="flex items-center"
          style={{
            gap: 8,
            color: COLORS.orange,
            fontSize: 11,
            fontWeight: 700,
            textTransform: 'uppercase',
            letterSpacing: '0.22em',
            marginBottom: 18,
          }}
        >
          <Activity size={13} />
          Diagnóstico comercial • WhatsApp
        </div>

        {/* Número principal + caption */}
        <div className="flex flex-col sm:flex-row sm:items-end" style={{ gap: 14, marginBottom: 20 }}>
          <div
            style={{
              fontSize: 'clamp(44px, 8vw, 88px)',
              fontWeight: 800,
              color: COLORS.cream,
              letterSpacing: '-0.04em',
              lineHeight: 1,
            }}
          >
            {headlineValue}
          </div>
          <div
            className="inline-flex items-center"
            style={{
              gap: 8,
              color: COLORS.orangeSoft,
              fontSize: 13.5,
              paddingBottom: 6,
            }}
          >
            <TrendingDown size={16} />
            receita estimada perdida
          </div>
        </div>

        <p
          style={{
            color: 'rgba(250,246,240,0.8)',
            fontSize: 14.5,
            lineHeight: 1.5,
            maxWidth: 580,
            marginBottom: 32,
            margin: '0 0 32px',
          }}
        >
          {summary}
        </p>

        {/* Pills */}
        <div
          className="grid grid-cols-1 sm:grid-cols-3"
          style={{
            gap: 14,
          }}
        >
          {PILLS.map((p) => {
            const Icon = p.icon;
            return (
              <div
                key={p.label}
                style={{
                  background: 'rgba(255,255,255,0.04)',
                  border: '1px solid rgba(255,229,217,0.12)',
                  borderRadius: 16,
                  padding: 18,
                  backdropFilter: 'blur(20px)',
                  WebkitBackdropFilter: 'blur(20px)',
                }}
              >
                <div
                  className="flex items-center"
                  style={{
                    gap: 8,
                    marginBottom: 14,
                  }}
                >
                  <Icon size={13} color={p.iconColor} strokeWidth={2.2} />
                  <span
                    style={{
                      fontSize: 10.5,
                      textTransform: 'uppercase',
                      letterSpacing: '0.14em',
                      color: 'rgba(250,246,240,0.73)',
                      fontWeight: 600,
                    }}
                  >
                    {p.label}
                  </span>
                </div>
                <div
                  style={{
                    fontSize: 'clamp(28px, 4vw, 36px)',
                    fontWeight: 700,
                    color: COLORS.cream,
                    letterSpacing: '-0.025em',
                    lineHeight: 1.05,
                    marginBottom: 6,
                  }}
                >
                  {p.value}
                </div>
                <div
                  style={{
                    fontSize: 12,
                    color: 'rgba(250,246,240,0.6)',
                  }}
                >
                  {p.sub}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
