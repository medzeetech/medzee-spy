import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { BarChart3, FileText, MessageCircle, LogOut, User } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';
import Logo from '../../components/Logo.jsx';

const NAV_ITEMS = [
  { to: '/app/dashboard', label: 'Dashboard', Icon: BarChart3 },
  { to: '/app/reports', label: 'Relatórios', Icon: FileText },
  { to: '/app/whatsapp', label: 'Conexão WhatsApp', Icon: MessageCircle },
];

function NavItem({ to, label, Icon }) {
  return (
    <NavLink
      to={to}
      className="flex items-center transition-colors"
      style={({ isActive }) => ({
        gap: 10,
        padding: '10px 14px',
        borderRadius: 10,
        background: isActive ? COLORS.sunken : 'transparent',
        color: isActive ? COLORS.ink : COLORS.inkSoft,
        fontSize: 13.5,
        fontWeight: isActive ? 600 : 500,
        textDecoration: 'none',
        fontFamily: "'Red Hat Display', sans-serif",
      })}
    >
      <Icon size={16} />
      {label}
    </NavLink>
  );
}

export default function DashboardLayout() {
  const navigate = useNavigate();
  const userName = 'Dr. João';

  return (
    <div style={{ background: COLORS.cream, minHeight: '100vh' }}>
      {/* Mobile topbar */}
      <header
        className="flex lg:hidden items-center justify-between"
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 10,
          background: COLORS.cream,
          borderBottom: `1px solid ${COLORS.hairline}`,
          padding: '12px 16px',
        }}
      >
        <Logo size="sm" tone="light" />
        <div className="flex items-center" style={{ gap: 8 }}>
          {NAV_ITEMS.map(({ to, Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              title={label}
              style={({ isActive }) => ({
                width: 36,
                height: 36,
                borderRadius: 10,
                border: `1px solid ${COLORS.hairline}`,
                background: isActive ? COLORS.sunken : COLORS.paper,
                color: isActive ? COLORS.orange : COLORS.ink,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                textDecoration: 'none',
              })}
            >
              <Icon size={16} />
            </NavLink>
          ))}
        </div>
      </header>

      <div className="flex">
        {/* Sidebar */}
        <aside
          className="hidden lg:flex flex-col"
          style={{
            width: 240,
            minHeight: '100vh',
            position: 'sticky',
            top: 0,
            background: COLORS.cream,
            borderRight: `1px solid ${COLORS.hairline}`,
            padding: '24px 18px',
            flexShrink: 0,
          }}
        >
          <div style={{ marginBottom: 28 }}>
            <Logo size="sm" tone="light" />
          </div>

          <nav className="flex flex-col" style={{ gap: 2, flex: 1 }}>
            {NAV_ITEMS.map((item) => (
              <NavItem key={item.to} {...item} />
            ))}
          </nav>

          {/* User card */}
          <div
            style={{
              background: COLORS.paper,
              border: `1px solid ${COLORS.hairline}`,
              borderRadius: 12,
              padding: 14,
              marginBottom: 12,
            }}
          >
            <div className="flex items-center" style={{ gap: 10 }}>
              <div
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: '50%',
                  background: `linear-gradient(135deg, ${COLORS.orange}, ${COLORS.orangeDeep})`,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: COLORS.cream,
                  flexShrink: 0,
                }}
              >
                <User size={14} />
              </div>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, color: COLORS.ink }}>{userName}</div>
                <div style={{ fontSize: 11, color: COLORS.inkMute }}>Plano Spy</div>
              </div>
            </div>
          </div>

          <button
            type="button"
            onClick={() => navigate('/spy')}
            className="flex items-center justify-center transition-all"
            style={{
              gap: 8,
              padding: '10px 14px',
              borderRadius: 10,
              border: `1px solid ${COLORS.hairline}`,
              background: COLORS.paper,
              color: COLORS.inkSoft,
              fontSize: 12.5,
              fontWeight: 600,
              cursor: 'pointer',
              fontFamily: "'Red Hat Display', sans-serif",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = COLORS.sunken; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = COLORS.paper; }}
          >
            <LogOut size={13} />
            Sair
          </button>
        </aside>

        {/* Main content */}
        <main
          className="flex-1"
          style={{
            padding: 'clamp(20px, 4vw, 40px)',
            maxWidth: '100%',
            minWidth: 0,
          }}
        >
          <Outlet />
        </main>
      </div>
    </div>
  );
}
