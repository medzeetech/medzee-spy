import { RefreshCw } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';
import Logo from '../Logo.jsx';

export default function MobileTopbar({ onReset }) {
  return (
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
      <button
        type="button"
        onClick={onReset}
        aria-label="Reiniciar demo"
        style={{
          width: 36,
          height: 36,
          borderRadius: 10,
          border: `1px solid ${COLORS.hairline}`,
          background: COLORS.paper,
          color: COLORS.ink,
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <RefreshCw size={15} />
      </button>
    </header>
  );
}
