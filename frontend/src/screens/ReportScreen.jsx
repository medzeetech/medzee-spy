import { COLORS } from '../constants/colors.js';
import Sidebar from '../components/report/Sidebar.jsx';
import MobileTopbar from '../components/report/MobileTopbar.jsx';
import ReportTopbar from '../components/report/ReportTopbar.jsx';
import HeroCard from '../components/report/HeroCard.jsx';
import Banner from '../components/report/Banner.jsx';
import FunnelSection from '../components/report/FunnelSection.jsx';
import ResponseTimeSection from '../components/report/ResponseTimeSection.jsx';
import VoiceSection from '../components/report/VoiceSection.jsx';
import OpportunitiesSection from '../components/report/OpportunitiesSection.jsx';
import BenchmarkSection from '../components/report/BenchmarkSection.jsx';
import FinalCTA from '../components/report/FinalCTA.jsx';

export default function ReportScreen({ onReset }) {
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
    <div style={{ background: COLORS.cream, minHeight: '100vh' }}>
      <MobileTopbar onReset={onReset} />

      <div className="flex">
        <Sidebar onReset={onReset} />

        <main
          className="flex-1"
          style={{
            padding: 'clamp(20px, 4vw, 40px)',
            maxWidth: '100%',
            minWidth: 0,
          }}
        >
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
            Relatório gerado por Medzee Spy • Dados anonimizados • Sem armazenamento de conteúdo após análise
          </div>
        </main>
      </div>
    </div>
  );
}
