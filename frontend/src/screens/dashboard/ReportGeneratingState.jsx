import { Sparkles, RefreshCw } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';

function fakeProgress(elapsedMs) {
  const t = Math.min(elapsedMs / 60_000, 1);
  const phase1 = 80 * (1 - Math.pow(1 - t, 3));
  if (elapsedMs < 60_000) return phase1;
  const extra = Math.min((elapsedMs - 60_000) / 30_000, 1) * 15;
  return 80 + extra;
}

function messageFor(elapsedMs) {
  if (elapsedMs < 15_000) {
    return 'Analisando suas conversas dos últimos 30 dias…';
  }
  if (elapsedMs < 45_000) {
    return 'Identificando oportunidades e padrões de atendimento…';
  }
  if (elapsedMs < 90_000) {
    return 'Quase lá — finalizando o diagnóstico…';
  }
  return 'Está demorando mais que o normal. Pode continuar aguardando ou tentar atualizar em alguns minutos.';
}

export default function ReportGeneratingState({ elapsedMs = 0, onRetry }) {
  const pct = fakeProgress(elapsedMs);
  const message = messageFor(elapsedMs);
  const showRetry = elapsedMs >= 90_000;

  const handleRetry = () => {
    if (typeof onRetry === 'function') {
      onRetry();
    } else if (typeof window !== 'undefined') {
      window.location.reload();
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        width: '100%',
        background:
          'radial-gradient(ellipse 120% 80% at 50% -10%, #2a1530 0%, #1A1410 65%)',
        color: COLORS.cream,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '32px 20px',
        fontFamily: "'Red Hat Display', sans-serif",
      }}
    >
      <div
        className="anim-fadeup"
        style={{
          position: 'relative',
          width: '100%',
          maxWidth: 460,
          background: 'rgba(250,246,240,0.04)',
          border: '1px solid rgba(255,107,53,0.18)',
          borderRadius: 24,
          padding: 'clamp(24px, 4vw, 36px)',
          backdropFilter: 'blur(20px)',
          WebkitBackdropFilter: 'blur(20px)',
          boxShadow: '0 40px 80px -20px rgba(0,0,0,0.7)',
          textAlign: 'center',
        }}
      >
        <div
          className="inline-flex items-center"
          style={{
            gap: 8,
            padding: '6px 12px',
            borderRadius: 99,
            background: 'rgba(255,107,53,0.12)',
            border: '1px solid rgba(255,107,53,0.3)',
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
            fontSize: 'clamp(24px, 4vw, 30px)',
            fontWeight: 800,
            letterSpacing: '-0.02em',
            margin: 0,
            marginBottom: 12,
            lineHeight: 1.18,
          }}
        >
          Análise IA em curso
        </h1>

        <div
          className="flex items-center justify-center"
          style={{
            gap: 10,
            margin: '0 auto 28px',
            color: 'rgba(250,246,240,0.78)',
            fontSize: 14.5,
            lineHeight: 1.5,
            maxWidth: 380,
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
              boxShadow: '0 0 12px rgba(255,107,53,0.7)',
            }}
          />
          <span>{message}</span>
        </div>

        <div
          style={{
            height: 6,
            background: 'rgba(250,246,240,0.08)',
            borderRadius: 99,
            overflow: 'hidden',
            marginBottom: 14,
          }}
        >
          <div
            style={{
              height: '100%',
              width: `${pct}%`,
              transition: 'width 1s linear',
              background: `linear-gradient(90deg, ${COLORS.orangeDeep}, ${COLORS.orange})`,
              boxShadow: '0 0 14px rgba(255,107,53,0.6)',
              borderRadius: 99,
            }}
          />
        </div>

        <div
          style={{
            fontSize: 11.5,
            color: 'rgba(250,246,240,0.45)',
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            fontWeight: 600,
          }}
        >
          {Math.round(pct)}% concluído
        </div>

        {showRetry && (
          <button
            type="button"
            onClick={handleRetry}
            className="inline-flex items-center justify-center transition-all"
            style={{
              marginTop: 26,
              gap: 8,
              padding: '12px 22px',
              borderRadius: 14,
              border: '1px solid rgba(255,107,53,0.4)',
              background: 'rgba(255,107,53,0.12)',
              color: COLORS.cream,
              fontSize: 14,
              fontWeight: 700,
              cursor: 'pointer',
              fontFamily: "'Red Hat Display', sans-serif",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = 'rgba(255,107,53,0.2)';
              e.currentTarget.style.transform = 'translateY(-1px)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = 'rgba(255,107,53,0.12)';
              e.currentTarget.style.transform = 'translateY(0)';
            }}
          >
            <RefreshCw size={15} />
            Atualizar
          </button>
        )}
      </div>
    </div>
  );
}
