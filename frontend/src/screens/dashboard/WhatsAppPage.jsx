// F4-T13 — WhatsApp connection state card.
//
// Renders 4 visual states off useWhatsappStatus():
//   1. loading            — skeleton placeholder, no flicker
//   2. disconnected       — CTA pra /spy
//   3. connected_no_messages — verde, aguardando
//   4. connected_with_data   — verde + stats + warning se >24h sem msg
// + estado de erro com card pequeno.

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Wifi,
  WifiOff,
  CheckCircle,
  AlertTriangle,
  MessageCircle,
  Power,
} from 'lucide-react';
import { COLORS } from '../../constants/colors.js';
import { useWhatsappStatus, disconnectWhatsapp } from '../../lib/whatsapp.js';

function formatRelative(isoDate) {
  if (!isoDate) return '—';
  const ms = Date.now() - new Date(isoDate).getTime();
  const minutes = Math.floor(ms / 60_000);
  const hours = Math.floor(ms / 3600_000);
  const days = Math.floor(ms / 86400_000);
  if (days >= 1) return `há ${days} ${days === 1 ? 'dia' : 'dias'}`;
  if (hours >= 1) return `há ${hours} ${hours === 1 ? 'hora' : 'horas'}`;
  if (minutes >= 1) return `há ${minutes} minutos`;
  return 'há instantes';
}

function isStale(lastMessageAt) {
  if (!lastMessageAt) return false;
  return Date.now() - new Date(lastMessageAt).getTime() > 24 * 3600 * 1000;
}

function PageHeader() {
  return (
    <div style={{ marginBottom: 28 }}>
      <h1
        style={{
          fontSize: 24,
          fontWeight: 800,
          color: COLORS.ink,
          margin: 0,
          letterSpacing: '-0.02em',
        }}
      >
        Conexão WhatsApp
      </h1>
      <p style={{ fontSize: 14, color: COLORS.inkSoft, margin: 0, marginTop: 4 }}>
        Status em tempo real da sua conexão e ingestão de mensagens
      </p>
    </div>
  );
}

function LoadingCard() {
  return (
    <div
      style={{
        background: COLORS.paper,
        border: `1px solid ${COLORS.hairline}`,
        borderRadius: 16,
        padding: 24,
        minHeight: 220,
        opacity: 0.5,
      }}
    >
      <div
        className="anim-pulse-dot"
        style={{
          width: 44,
          height: 44,
          borderRadius: 12,
          background: COLORS.sunken,
          marginBottom: 16,
        }}
      />
      <div
        style={{
          width: '60%',
          height: 18,
          borderRadius: 6,
          background: COLORS.sunken,
          marginBottom: 12,
        }}
      />
      <div
        style={{
          width: '85%',
          height: 14,
          borderRadius: 6,
          background: COLORS.sunken,
          marginBottom: 24,
        }}
      />
      <div
        style={{
          width: '100%',
          height: 48,
          borderRadius: 12,
          background: COLORS.sunken,
        }}
      />
    </div>
  );
}

function ErrorCard() {
  return (
    <div
      style={{
        background: COLORS.paper,
        border: '1px solid rgba(229,96,77,0.25)',
        borderRadius: 12,
        padding: 16,
        fontSize: 13.5,
        color: COLORS.ink,
        display: 'flex',
        alignItems: 'flex-start',
        gap: 10,
      }}
    >
      <AlertTriangle size={18} color="#E5604D" style={{ flexShrink: 0, marginTop: 1 }} />
      <span>Não foi possível carregar o status. Atualize a página.</span>
    </div>
  );
}

function DisconnectedCard() {
  const navigate = useNavigate();
  return (
    <div
      style={{
        background: COLORS.paper,
        border: `1px solid ${COLORS.hairline}`,
        borderRadius: 16,
        padding: 28,
        textAlign: 'center',
      }}
    >
      <div
        style={{
          width: 64,
          height: 64,
          borderRadius: 16,
          background: COLORS.sunken,
          color: COLORS.inkMute,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          margin: '0 auto 18px',
        }}
      >
        <WifiOff size={30} />
      </div>
      <h2
        style={{
          fontSize: 18,
          fontWeight: 700,
          color: COLORS.ink,
          margin: 0,
          marginBottom: 8,
          letterSpacing: '-0.01em',
        }}
      >
        WhatsApp não conectado
      </h2>
      <p
        style={{
          fontSize: 14,
          color: COLORS.inkSoft,
          lineHeight: 1.5,
          margin: '0 auto 22px',
          maxWidth: 380,
        }}
      >
        Conecte seu WhatsApp pra começar a coletar conversas pra análise.
      </p>
      <button
        type="button"
        onClick={() => navigate('/app/connect')}
        className="flex items-center justify-center transition-all"
        style={{
          gap: 8,
          margin: '0 auto',
          padding: '12px 22px',
          borderRadius: 12,
          border: 'none',
          background: `linear-gradient(135deg, ${COLORS.orange}, ${COLORS.orangeDeep})`,
          color: '#fff',
          fontSize: 14,
          fontWeight: 600,
          cursor: 'pointer',
          fontFamily: "'Red Hat Display', sans-serif",
          boxShadow: '0 6px 18px -8px rgba(255,107,53,0.6)',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.transform = 'translateY(-1px)';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.transform = 'translateY(0)';
        }}
      >
        <Wifi size={16} />
        Conectar WhatsApp
      </button>
    </div>
  );
}

function StatsGrid({ conversationCount, messageCount }) {
  const cells = [
    { label: 'conversas', value: conversationCount, Icon: MessageCircle },
    {
      label: 'mensagens',
      value: messageCount.toLocaleString('pt-BR'),
      Icon: MessageCircle,
    },
  ];
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: 10,
        marginBottom: 16,
      }}
    >
      {cells.map(({ label, value, Icon }) => (
        <div
          key={label}
          style={{
            background: COLORS.sunken,
            borderRadius: 12,
            padding: 14,
          }}
        >
          <div
            className="flex items-center"
            style={{ gap: 6, color: COLORS.inkMute, marginBottom: 4 }}
          >
            <Icon size={13} />
            <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase' }}>
              {label}
            </span>
          </div>
          <div style={{ fontSize: 22, fontWeight: 800, color: COLORS.ink, letterSpacing: '-0.01em' }}>
            {value}
          </div>
        </div>
      ))}
    </div>
  );
}

function DisconnectButton({ onClick, disabled }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="flex items-center justify-center transition-all"
      style={{
        gap: 8,
        width: '100%',
        padding: 14,
        borderRadius: 12,
        border: `1px solid ${COLORS.hairline}`,
        background: 'transparent',
        color: COLORS.inkSoft,
        fontSize: 14,
        fontWeight: 600,
        cursor: disabled ? 'not-allowed' : 'pointer',
        fontFamily: "'Red Hat Display', sans-serif",
        opacity: disabled ? 0.6 : 1,
      }}
      onMouseEnter={(e) => {
        if (!disabled) e.currentTarget.style.background = COLORS.sunken;
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = 'transparent';
      }}
    >
      <Power size={15} />
      {disabled ? 'Desconectando…' : 'Desconectar'}
    </button>
  );
}

function ConnectedHeader({ title, subtitle }) {
  return (
    <div className="flex items-center" style={{ gap: 14, marginBottom: 18 }}>
      <div
        style={{
          width: 48,
          height: 48,
          borderRadius: 12,
          background: 'rgba(37,211,102,0.12)',
          color: COLORS.wa,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
        }}
      >
        <CheckCircle size={24} />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: 16,
            fontWeight: 700,
            color: COLORS.ink,
            letterSpacing: '-0.01em',
            lineHeight: 1.3,
          }}
        >
          {title}
        </div>
        {subtitle && (
          <div style={{ fontSize: 13, color: COLORS.inkSoft, marginTop: 3, lineHeight: 1.4 }}>
            {subtitle}
          </div>
        )}
      </div>
    </div>
  );
}

function StaleWarning() {
  return (
    <div
      style={{
        background: 'rgba(232,179,60,0.1)',
        border: '1px solid rgba(232,179,60,0.3)',
        borderRadius: 12,
        padding: 14,
        marginBottom: 16,
        display: 'flex',
        alignItems: 'flex-start',
        gap: 10,
      }}
    >
      <AlertTriangle size={16} color={COLORS.gold} style={{ flexShrink: 0, marginTop: 1 }} />
      <div style={{ fontSize: 13, color: COLORS.ink, lineHeight: 1.5 }}>
        Sem novas mensagens há mais de 24h — verifique se o WhatsApp ainda está conectado.
      </div>
    </div>
  );
}

function ConnectedNoMessages({ status, onDisconnect, disconnecting }) {
  return (
    <div
      style={{
        background: COLORS.paper,
        border: '1px solid rgba(37,211,102,0.3)',
        borderRadius: 16,
        padding: 24,
      }}
    >
      <ConnectedHeader
        title="WhatsApp conectado · aguardando primeiras mensagens"
        subtitle={`Conectado ${formatRelative(status.connected_since)}. Cada nova mensagem aparece aqui em tempo real.`}
      />
      <StatsGrid conversationCount={0} messageCount={0} />
      <DisconnectButton onClick={onDisconnect} disabled={disconnecting} />
    </div>
  );
}

function ConnectedWithData({ status, onDisconnect, disconnecting }) {
  const stale = isStale(status.last_message_at);
  const subtitle = `Conectado ${formatRelative(status.connected_since)} · última mensagem ${formatRelative(status.last_message_at)}`;
  return (
    <div
      style={{
        background: COLORS.paper,
        border: '1px solid rgba(37,211,102,0.3)',
        borderRadius: 16,
        padding: 24,
      }}
    >
      <ConnectedHeader title="WhatsApp conectado" subtitle={subtitle} />
      <StatsGrid
        conversationCount={status.conversation_count}
        messageCount={status.message_count}
      />
      {stale && <StaleWarning />}
      <DisconnectButton onClick={onDisconnect} disabled={disconnecting} />
    </div>
  );
}

export default function WhatsAppPage() {
  const { loading, status, error } = useWhatsappStatus();
  const [disconnecting, setDisconnecting] = useState(false);

  const handleDisconnect = async () => {
    if (!status?.session_id) return;
    const ok = window.confirm(
      'Desconectar o WhatsApp? A coleta de novas mensagens será pausada.'
    );
    if (!ok) return;
    setDisconnecting(true);
    try {
      await disconnectWhatsapp(status.session_id);
    } catch (e) {
      window.alert('Não foi possível desconectar. Tente novamente.');
    } finally {
      setDisconnecting(false);
    }
  };

  let content;
  if (loading && !status) {
    content = <LoadingCard />;
  } else if (error && !status) {
    content = <ErrorCard />;
  } else if (!status || !status.connected) {
    content = <DisconnectedCard />;
  } else if (status.message_count === 0) {
    content = (
      <ConnectedNoMessages
        status={status}
        onDisconnect={handleDisconnect}
        disconnecting={disconnecting}
      />
    );
  } else {
    content = (
      <ConnectedWithData
        status={status}
        onDisconnect={handleDisconnect}
        disconnecting={disconnecting}
      />
    );
  }

  return (
    <div style={{ maxWidth: 600 }}>
      <PageHeader />
      {content}
    </div>
  );
}
