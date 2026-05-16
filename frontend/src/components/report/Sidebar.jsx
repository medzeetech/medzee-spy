import { ChevronRight, RefreshCw } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';
import { SIDEBAR_LINKS } from '../../data/reportData.js';
import Logo from '../Logo.jsx';

export default function Sidebar({ onReset }) {
  return (
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

      <nav className="flex flex-col" style={{ gap: 2, marginBottom: 28 }}>
        {SIDEBAR_LINKS.map((link) => (
          <button
            key={link.label}
            type="button"
            className="flex items-center justify-between text-left transition-colors"
            style={{
              padding: '9px 12px',
              borderRadius: 8,
              border: 'none',
              background: link.active ? COLORS.sunken : 'transparent',
              color: COLORS.ink,
              fontSize: 13.5,
              fontWeight: link.active ? 600 : 500,
              cursor: 'pointer',
              fontFamily: "'Red Hat Display', sans-serif",
            }}
            onMouseEnter={(e) => {
              if (!link.active) e.currentTarget.style.background = 'rgba(0,0,0,0.03)';
            }}
            onMouseLeave={(e) => {
              if (!link.active) e.currentTarget.style.background = 'transparent';
            }}
          >
            <span>{link.label}</span>
            {link.active && <ChevronRight size={14} color={COLORS.inkSoft} />}
          </button>
        ))}
      </nav>

      <div
        style={{
          background: COLORS.paper,
          border: `1px solid ${COLORS.hairline}`,
          borderRadius: 12,
          padding: 14,
          marginBottom: 18,
        }}
      >
        <div
          style={{
            fontSize: 10.5,
            color: COLORS.inkMute,
            textTransform: 'uppercase',
            letterSpacing: '0.14em',
            fontWeight: 600,
            marginBottom: 6,
          }}
        >
          Período analisado
        </div>
        <div style={{ fontSize: 12.5, color: COLORS.ink, lineHeight: 1.45, fontWeight: 500 }}>
          14 abr – 12 mai 2026
          <br />
          <span style={{ color: COLORS.inkSoft, fontWeight: 400 }}>28 dias • 3.370 mensagens</span>
        </div>
      </div>

      <button
        type="button"
        onClick={onReset}
        className="flex items-center justify-center gap-2 transition-all"
        style={{
          marginTop: 'auto',
          padding: '10px 14px',
          borderRadius: 10,
          border: `1px solid ${COLORS.hairline}`,
          background: COLORS.paper,
          color: COLORS.ink,
          fontSize: 12.5,
          fontWeight: 600,
          cursor: 'pointer',
          fontFamily: "'Red Hat Display', sans-serif",
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = COLORS.sunken;
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = COLORS.paper;
        }}
      >
        <RefreshCw size={13} />
        Reiniciar demo
      </button>
    </aside>
  );
}
