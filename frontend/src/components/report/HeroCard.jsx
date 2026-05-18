import { Activity, AlertCircle, Clock, Target, Info } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';
import bgCard from '../../assets/background-card.svg';

function formatBRL(v) {
  if (v == null) return null;
  return v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 });
}

function formatHoursLabel(h) {
  if (h == null) return null;
  if (h < 1) {
    const min = Math.round(h * 60);
    return `${min}min`;
  }
  const wholeH = Math.floor(h);
  const min = Math.round((h - wholeH) * 60);
  return min === 0 ? `${wholeH}h` : `${wholeH}h ${min}min`;
}

export default function HeroCard({
  score,
  messageCount,
  diagnosticSummary,
  dataQuality,
  opportunityCount,
  avgResponseHours,
  conversionPct,
}) {
  const insufficient = dataQuality === 'insufficient';

  // Headline + summary se adaptam ao estado dos dados:
  //   - sufficient: número grande (BRL estimado) + parágrafo do LLM
  //   - insufficient: ícone neutro + parágrafo explicativo (LLM já preenche
  //     um diagnostic_summary transparente no curto-circuito do worker)
  const summary =
    diagnosticSummary && diagnosticSummary.trim().length > 0
      ? diagnosticSummary
      : insufficient
        ? 'Conecte o WhatsApp da clínica e aguarde as primeiras conversas serem coletadas. Em algumas horas você terá dados suficientes para o primeiro diagnóstico.'
        : 'Análise comercial baseada nas conversas do período selecionado.';

  // Pills só fazem sentido quando temos dados de verdade. Cada pill mostra
  // valor real ou "—" quando o número específico não existe (em vez de
  // hardcoded "4h 22min" / "12,4%" como antes).
  const PILLS = insufficient
    ? null
    : [
        {
          icon: AlertCircle,
          iconColor: COLORS.orange,
          label: 'Oportunidades perdidas',
          value: opportunityCount != null ? String(opportunityCount) : '—',
          sub: messageCount != null
            ? `de ${messageCount.toLocaleString('pt-BR')} mensagens`
            : 'sem dados',
        },
        {
          icon: Clock,
          iconColor: COLORS.gold,
          label: 'Tempo médio 1ª resposta',
          value: formatHoursLabel(avgResponseHours) ?? '—',
          sub: avgResponseHours != null ? 'na sua clínica' : 'sem dados',
        },
        {
          icon: Target,
          iconColor: COLORS.orange,
          label: 'Taxa de conversão',
          value: conversionPct != null ? `${conversionPct.toFixed(1)}%` : '—',
          sub: conversionPct != null ? 'agendamentos confirmados' : 'sem dados',
        },
      ];

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

        {/* Headline (varia conforme dataQuality) */}
        {insufficient ? (
          <div
            className="flex items-center"
            style={{ gap: 14, marginBottom: 20 }}
          >
            <div
              style={{
                width: 48,
                height: 48,
                borderRadius: 12,
                background: 'rgba(255,229,217,0.12)',
                color: COLORS.orange,
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Info size={22} />
            </div>
            <div
              style={{
                fontSize: 'clamp(22px, 4vw, 32px)',
                fontWeight: 700,
                color: COLORS.cream,
                letterSpacing: '-0.02em',
                lineHeight: 1.1,
              }}
            >
              Dados ainda insuficientes
            </div>
          </div>
        ) : (
          <div className="flex flex-col sm:flex-row sm:items-end" style={{ gap: 14, marginBottom: 20 }}>
            <div
              style={{
                fontSize: 'clamp(34px, 6vw, 64px)',
                fontWeight: 800,
                color: COLORS.cream,
                letterSpacing: '-0.04em',
                lineHeight: 1,
              }}
            >
              {score != null ? `${score}/100` : '—'}
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
              Score comercial geral
            </div>
          </div>
        )}

        <p
          style={{
            color: 'rgba(250,246,240,0.8)',
            fontSize: 14.5,
            lineHeight: 1.5,
            maxWidth: 580,
            marginBottom: insufficient ? 0 : 32,
            margin: insufficient ? 0 : '0 0 32px',
          }}
        >
          {summary}
        </p>

        {/* Pills só quando tem dado */}
        {PILLS && (
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
                      fontSize: 'clamp(24px, 3vw, 32px)',
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
        )}
      </div>
    </div>
  );
}
