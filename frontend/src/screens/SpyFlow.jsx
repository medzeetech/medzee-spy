import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import QRScreen from './QRScreen.jsx';
import GeneratingScreen from './GeneratingScreen.jsx';
import LeadFormScreen from './LeadFormScreen.jsx';

export default function SpyFlow() {
  const [phase, setPhase] = useState('qr');
  const [whatsappSessionId, setWhatsappSessionId] = useState(null);
  const navigate = useNavigate();

  const goGenerating = () => setPhase('generating');
  const goLead = () => setPhase('lead');
  const goApp = () => navigate('/app/reports/latest');
  const reset = () => setPhase('qr');

  if (phase === 'qr') return <QRScreen onSimulate={goGenerating} onSessionCreated={setWhatsappSessionId} />;
  if (phase === 'generating') return <GeneratingScreen onComplete={goLead} />;
  return <LeadFormScreen onSubmit={goApp} showTicketMedio whatsappSessionId={whatsappSessionId} />;
}
