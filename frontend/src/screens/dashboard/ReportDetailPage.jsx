import { useEffect } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, ArrowLeft, RefreshCw, WifiOff } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';
import { useReportPolling } from '../../lib/reports.js';
import ReportGeneratingState from './ReportGeneratingState.jsx';
import ReportTopbar from '../../components/report/ReportTopbar.jsx';
import HeroCard from '../../components/report/HeroCard.jsx';
import Banner from '../../components/report/Banner.jsx';
import FunnelSection from '../../components/report/FunnelSection.jsx';
import ResponseTimeSection from '../../components/report/ResponseTimeSection.jsx';
import VoiceSection from '../../components/report/VoiceSection.jsx';
import OpportunitiesSection from '../../components/report/OpportunitiesSection.jsx';
import BenchmarkSection from '../../components/report/BenchmarkSection.jsx';
import FinalCTA from '../../components/report/FinalCTA.jsx';

function BackButton({ onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center transition-all"
      style={{
        gap: 6,
        padding: '8px 14px',
        borderRadius: 10,
        border: `1px solid ${COLORS.hairline}`,
        background: COLORS.paper,
        color: COLORS.ink,
        fontSize: 13,
        fontWeight: 600,
        cursor: 'pointer',
        fontFamily: "'Red Hat Display', sans-serif",
        marginBottom: 24,
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = COLORS.sunken; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = COLORS.paper; }}
    >
      <ArrowLeft size={14} />
      Voltar aos relatórios
    </button>
  );
}

function PartialBanner() {
  return (
    <div
      className="flex items-start"
      style={{
        gap: 10,
        padding: '12px 16px',
        borderRadius: 12,
        border: `1px solid ${COLORS.hairline}`,
        background: 'rgba(232,179,60,0.1)',
        color: COLORS.ink,
        fontSize: 13,
        lineHeight: 1.5,
        marginBottom: 20,
      }}
    >
      <WifiOff size={16} style={{ color: COLORS.gold, flexShrink: 0, marginTop: 2 }} />
      <span>
        <em>análise baseada em parte das conversas (problema temporário de conexão com o WhatsApp)</em>
      </span>
    </div>
  );
}

function FailedCard({ errorCode }) {
  return (
    <div
      style={{
        background: COLORS.paper,
        border: `1px solid ${COLORS.hairline}`,
        borderRadius: 20,
        padding: 'clamp(28px, 4vw, 40px)',
        textAlign: 'center',
        maxWidth: 520,
        margin: '40px auto',
      }}
    >
      <div
        style={{
          width: 56,
          height: 56,
          borderRadius: 14,
          background: 'rgba(92,29,46,0.1)',
          color: COLORS.wine,
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          marginBottom: 20,
        }}
      >
        <AlertTriangle size={26} />
      </div>
      <h2
        style={{
          fontSize: 22,
          fontWeight: 800,
          color: COLORS.ink,
          margin: 0,
          marginBottom: 12,
          letterSpacing: '-0.02em',
          lineHeight: 1.25,
        }}
      >
        Não conseguimos gerar essa análise.
      </h2>
      <p
        style={{
          fontSize: 14,
          color: COLORS.inkSoft,
          lineHeight: 1.55,
          margin: 0,
          marginBottom: 24,
        }}
      >
        O processo falhou (código: {errorCode ?? 'desconhecido'}). Tente reconectar o WhatsApp.
      </p>
      <Link
        to="/spy"
        className="inline-flex items-center justify-center transition-all"
        style={{
          gap: 8,
          padding: '12px 22px',
          borderRadius: 12,
          border: 'none',
          background: `linear-gradient(135deg, ${COLORS.orange}, ${COLORS.orangeDeep})`,
          color: COLORS.cream,
          fontSize: 14,
          fontWeight: 700,
          cursor: 'pointer',
          fontFamily: "'Red Hat Display', sans-serif",
          textDecoration: 'none',
          boxShadow: '0 6px 20px -6px rgba(255,107,53,0.4)',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.transform = 'translateY(-1px)';
          e.currentTarget.style.boxShadow = '0 10px 28px -6px rgba(255,107,53,0.55)';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.transform = 'translateY(0)';
          e.currentTarget.style.boxShadow = '0 6px 20px -6px rgba(255,107,53,0.4)';
        }}
      >
        <RefreshCw size={15} />
        Tentar de novo
      </Link>
    </div>
  );
}

function ReportContent({ partial, payload }) {
  const p = payload ?? {};

  // Métricas derivadas — cruzam o payload pra alimentar o HeroCard sem
  // mais hardcoded "4h 22min / 12,4% / 47 oportunidades".
  const opportunityCount = (p.opportunities || []).length;
  const conversionPct =
    p.funnel && p.funnel.length >= 5 ? p.funnel[p.funnel.length - 1]?.pct ?? null : null;
  const avgResponseHours = (() => {
    const buckets = p.response_time_distribution || [];
    const midpoints = [5 / 60 / 2, (5 + 30) / 60 / 2, (30 / 60 + 1) / 2, (1 + 4) / 2, (4 + 24) / 2, 36];
    const total = buckets.reduce((s, b) => s + (b.count || 0), 0);
    if (total === 0) return null;
    const weighted = buckets.reduce((s, b, i) => s + (b.count || 0) * midpoints[i], 0);
    return Math.round((weighted / total) * 10) / 10;
  })();

  const animatedChildren = [
    <ReportTopbar key="topbar" />,
    <HeroCard
      key="hero"
      score={p.score}
      messageCount={p.message_count}
      diagnosticSummary={p.diagnostic_summary}
      dataQuality={p.data_quality}
      opportunityCount={opportunityCount}
      avgResponseHours={avgResponseHours}
      conversionPct={conversionPct}
    />,
    <FunnelSection key="funnel" funnel={p.funnel} />,
    <Banner key="banner" />,
    <ResponseTimeSection
      key="response"
      heatmapDays={p.heatmap_days}
      heatmapPeriods={p.heatmap_periods}
      responseTimeDistribution={p.response_time_distribution}
    />,
    <VoiceSection
      key="voice"
      objections={p.objections}
      faqs={p.faqs}
      sentiment={p.sentiment}
      messageCount={p.message_count}
    />,
    <OpportunitiesSection key="opps" opportunities={p.opportunities} />,
    <BenchmarkSection
      key="bench"
      benchmarks={p.benchmarks}
      clinicSegment={p.clinic_segment}
    />,
    <FinalCTA key="cta" />,
  ];

  return (
    <>
      {partial && <PartialBanner />}
      {animatedChildren.map((child, i) => (
        <div
          key={child.key}
          className="anim-fadeup"
          style={{ animationDelay: `${i * 60}ms` }}
        >
          {child}
        </div>
      ))}
      <div
        style={{
          fontSize: 11,
          color: COLORS.inkMute,
          textAlign: 'center',
          marginTop: 32,
        }}
      >
        Relatório gerado por Medzee Spy · Dados anonimizados · Sem armazenamento de conteúdo após análise
      </div>
    </>
  );
}

export default function ReportDetailPage() {
  const navigate = useNavigate();
  const { id } = useParams();
  const pollingKey = id === 'latest' ? 'latest' : id;
  const state = useReportPolling(pollingKey);

  // Sessão expirou em background — manda pra /login preservando o redirect.
  useEffect(() => {
    if (state.status === 'unauthorized') {
      const next = encodeURIComponent(
        typeof window !== 'undefined' ? window.location.pathname : '/app/reports/latest',
      );
      navigate(`/login?next=${next}`, { replace: true });
    }
  }, [state.status, navigate]);

  if (state.status === 'unauthorized') {
    // Render mínimo enquanto o useEffect dispara o redirect.
    return null;
  }

  if (state.status === 'pending' || state.status === 'generating') {
    return <ReportGeneratingState elapsedMs={state.elapsedMs} />;
  }

  if (state.status === 'failed') {
    return (
      <div>
        <BackButton onClick={() => navigate('/app/reports')} />
        <FailedCard errorCode={state.error} />
      </div>
    );
  }

  // completed | partial
  return (
    <div>
      <BackButton onClick={() => navigate('/app/reports')} />
      <ReportContent partial={state.status === 'partial'} payload={state.payload} />
    </div>
  );
}
