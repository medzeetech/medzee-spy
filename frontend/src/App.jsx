import { useState } from 'react';
import AgentScreen from './screens/AgentScreen.jsx';
import QRScreen from './screens/QRScreen.jsx';
import GeneratingScreen from './screens/GeneratingScreen.jsx';
import LeadFormScreen from './screens/LeadFormScreen.jsx';
import ReportScreen from './screens/ReportScreen.jsx';

export default function App() {
  const [phase, setPhase] = useState('agent');

  const goQR = () => setPhase('qr');
  const goGenerating = () => setPhase('generating');
  const goLead = () => setPhase('lead');
  const goReport = () => setPhase('report');
  const reset = () => setPhase('agent');

  if (phase === 'agent') return <AgentScreen onShowQR={goQR} />;
  if (phase === 'qr') return <QRScreen onSimulate={goGenerating} />;
  if (phase === 'generating') return <GeneratingScreen onComplete={goLead} />;
  if (phase === 'lead') return <LeadFormScreen onSubmit={goReport} />;
  return <ReportScreen onReset={reset} />;
}
