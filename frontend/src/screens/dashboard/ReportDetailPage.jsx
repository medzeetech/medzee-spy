import { useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';
import ReportTopbar from '../../components/report/ReportTopbar.jsx';
import HeroCard from '../../components/report/HeroCard.jsx';
import Banner from '../../components/report/Banner.jsx';
import FunnelSection from '../../components/report/FunnelSection.jsx';
import ResponseTimeSection from '../../components/report/ResponseTimeSection.jsx';
import VoiceSection from '../../components/report/VoiceSection.jsx';
import OpportunitiesSection from '../../components/report/OpportunitiesSection.jsx';
import BenchmarkSection from '../../components/report/BenchmarkSection.jsx';
import FinalCTA from '../../components/report/FinalCTA.jsx';

export default function ReportDetailPage() {
  const navigate = useNavigate();

  const animatedChildren = [
    <ReportTopbar key="topbar" />,
    <HeroCard key="hero" />,
    <FunnelSection key="funnel" />,
    <Banner key="banner" />,
    <ResponseTimeSection key="response" />,
    <VoiceSection key="voice" />,
    <OpportunitiesSection key="opps" />,
    <BenchmarkSection key="bench" />,
    <FinalCTA key="cta" />,
  ];

  return (
    <div>
      <button
        type="button"
        onClick={() => navigate('/app/reports')}
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
    </div>
  );
}
