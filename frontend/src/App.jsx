import { useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import AgentScreen from './screens/AgentScreen.jsx';
import QRScreen from './screens/QRScreen.jsx';
import GeneratingScreen from './screens/GeneratingScreen.jsx';
import LeadFormScreen from './screens/LeadFormScreen.jsx';
import ReportScreen from './screens/ReportScreen.jsx';
import SpyFlow from './screens/SpyFlow.jsx';
import DashboardLayout from './screens/dashboard/DashboardLayout.jsx';
import DashboardPage from './screens/dashboard/DashboardPage.jsx';
import ReportsListPage from './screens/dashboard/ReportsListPage.jsx';
import ReportDetailPage from './screens/dashboard/ReportDetailPage.jsx';
import WhatsAppPage from './screens/dashboard/WhatsAppPage.jsx';

function MainFlow() {
  const [phase, setPhase] = useState('agent');
  const navigate = useNavigate();

  const goQR = () => setPhase('qr');
  const goGenerating = () => setPhase('generating');
  const goLead = () => setPhase('lead');
  const goReport = () => navigate('/app/reports/latest');
  const reset = () => setPhase('agent');

  if (phase === 'agent') return <AgentScreen onShowQR={goQR} />;
  if (phase === 'qr') return <QRScreen onSimulate={goGenerating} />;
  if (phase === 'generating') return <GeneratingScreen onComplete={goLead} />;
  if (phase === 'lead') return <LeadFormScreen onSubmit={goReport} />;
  return <ReportScreen onReset={reset} />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<MainFlow />} />
        <Route path="/spy" element={<SpyFlow />} />
        <Route path="/app" element={<DashboardLayout />}>
          <Route index element={<Navigate to="dashboard" replace />} />
          <Route path="dashboard" element={<DashboardPage />} />
          <Route path="reports" element={<ReportsListPage />} />
          <Route path="reports/:id" element={<ReportDetailPage />} />
          <Route path="whatsapp" element={<WhatsAppPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
