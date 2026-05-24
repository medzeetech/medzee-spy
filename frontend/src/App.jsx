// F8-T22 — Router wiring para o novo /spy flow invertido.
//
// Changes vs M1:
//   - `/` continua sendo AgentScreen (landing pública).
//   - `/spy` e `/spy/*` agora montam SpyFlowScreen (state machine T21)
//     em vez do antigo SpyFlow.jsx (QR → Generating → Lead).
//   - `/app/*` (dashboard logado) ganha mobile guard via AppMobileGuard:
//     em mobile a extensão não roda, então não há sentido em renderizar
//     dashboards — MobileBlockScreen captura email pra retargeting.
//   - Rotas legacy standalone (`/qr`, `/lead-form`, `/connect`) redirecionam
//     pra `/spy` (single entry point do funil).
//   - SpyFlow.jsx legacy fica no disco até a próxima limpeza; só removemos
//     o wiring por enquanto pra reduzir blast radius do PR.

import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';

import AgentScreen from './screens/AgentScreen.jsx';
import LoginScreen from './screens/LoginScreen.jsx';
import SpyFlowScreen from './screens/SpyFlowScreen.jsx';
import MobileBlockScreen from './screens/MobileBlockScreen.jsx';
import DashboardLayout from './screens/dashboard/DashboardLayout.jsx';
import DashboardPage from './screens/dashboard/DashboardPage.jsx';
import ReportsListPage from './screens/dashboard/ReportsListPage.jsx';
import ReportDetailPage from './screens/dashboard/ReportDetailPage.jsx';
import WhatsAppPage from './screens/dashboard/WhatsAppPage.jsx';

import { useIsMobile } from './lib/device.js';

function AppMobileGuard({ children }) {
  const isMobile = useIsMobile();
  if (isMobile) return <MobileBlockScreen />;
  return children;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<AgentScreen />} />

        {/* New inverted /spy flow (T21 state machine) */}
        <Route path="/spy" element={<SpyFlowScreen />} />
        <Route path="/spy/*" element={<SpyFlowScreen />} />

        <Route path="/login" element={<LoginScreen />} />

        {/* Logged-in area — mobile-guarded (extension only runs on desktop) */}
        <Route
          path="/app"
          element={
            <AppMobileGuard>
              <DashboardLayout />
            </AppMobileGuard>
          }
        >
          <Route index element={<Navigate to="dashboard" replace />} />
          <Route path="dashboard" element={<DashboardPage />} />
          <Route path="reports" element={<ReportsListPage />} />
          <Route path="reports/:id" element={<ReportDetailPage />} />
          <Route path="reports/latest" element={<ReportDetailPage />} />
          <Route path="whatsapp" element={<WhatsAppPage />} />
        </Route>

        {/* Legacy redirects — antigas standalone screens viram parte do /spy flow */}
        <Route path="/qr" element={<Navigate to="/spy" replace />} />
        <Route path="/lead-form" element={<Navigate to="/spy" replace />} />
        <Route path="/connect" element={<Navigate to="/spy" replace />} />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
