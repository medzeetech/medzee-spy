import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ConversationProvider, useConversation } from '@elevenlabs/react';
import { Phone, PhoneOff, Mic, MicOff, Loader2, RefreshCw } from 'lucide-react';
import { COLORS } from '../constants/colors.js';
import Logo from '../components/Logo.jsx';
import AudioVisualizer from '../components/AudioVisualizer.jsx';

const AGENT_ID = 'agent_8601krmch56bfbbv5wjya2jw0y3x';

const STATUS_PILLS = {
  disconnected: { dot: COLORS.inkMute, bg: 'rgba(250,246,240,0.05)', border: 'rgba(250,246,240,0.12)', color: 'rgba(250,246,240,0.7)', text: 'Pronta para conversar' },
  connecting: { dot: COLORS.orange, bg: 'rgba(255,107,53,0.12)', border: 'rgba(255,107,53,0.3)', color: COLORS.orange, text: 'Conectando…', pulse: true },
  listening: { dot: COLORS.wa, bg: 'rgba(37,211,102,0.12)', border: 'rgba(37,211,102,0.3)', color: COLORS.wa, text: 'Ouvindo você' },
  speaking: { dot: COLORS.orange, bg: 'rgba(255,107,53,0.12)', border: 'rgba(255,107,53,0.3)', color: COLORS.orange, text: 'Falando' },
};

function StatusPill({ kind }) {
  const cfg = STATUS_PILLS[kind] ?? STATUS_PILLS.disconnected;
  return (
    <div
      className="inline-flex items-center"
      style={{
        gap: 8,
        padding: '6px 14px',
        borderRadius: 99,
        background: cfg.bg,
        border: `1px solid ${cfg.border}`,
        color: cfg.color,
        fontSize: 12.5,
        fontWeight: 600,
        letterSpacing: '0.02em',
      }}
    >
      <span
        className={cfg.pulse ? 'anim-pulse-dot' : ''}
        style={{ width: 7, height: 7, borderRadius: '50%', background: cfg.dot, display: 'inline-block' }}
      />
      {cfg.text}
    </div>
  );
}

function Transcript({ messages }) {
  const scrollRef = useRef(null);
  const visible = messages.slice(-3);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages.length]);

  if (visible.length === 0) {
    return (
      <div
        style={{
          height: 110,
          width: '100%',
          maxWidth: 520,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'rgba(250,246,240,0.35)',
          fontSize: 13,
          fontStyle: 'italic',
        }}
      >
        A conversa aparecerá aqui…
      </div>
    );
  }

  return (
    <div
      ref={scrollRef}
      style={{
        height: 110,
        width: '100%',
        maxWidth: 520,
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'flex-end',
        gap: 8,
      }}
    >
      {visible.map((m, i) => {
        const isAgent = m.source === 'ai';
        return (
          <div
            key={`${m.id}-${i}`}
            className="anim-fadeup"
            style={{
              display: 'flex',
              justifyContent: isAgent ? 'flex-start' : 'flex-end',
            }}
          >
            <div
              style={{
                maxWidth: '80%',
                background: isAgent ? 'rgba(255,107,53,0.08)' : 'rgba(250,246,240,0.06)',
                border: `1px solid ${isAgent ? 'rgba(255,107,53,0.2)' : 'rgba(250,246,240,0.12)'}`,
                borderRadius: 12,
                padding: '10px 14px',
                fontSize: 13.5,
                lineHeight: 1.45,
                color: 'rgba(250,246,240,0.85)',
              }}
            >
              {m.text}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function formatTimer(seconds) {
  const m = Math.floor(seconds / 60).toString().padStart(2, '0');
  const s = (seconds % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

function AgentScreenInner({ onShowQR }) {
  const [messages, setMessages] = useState([]);
  const [volume, setVolume] = useState(0);
  const [micError, setMicError] = useState(false);
  const [connectError, setConnectError] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [isMuted, setIsMuted] = useState(false);
  const startedAtRef = useRef(null);
  const startingRef = useRef(false);
  const watchdogRef = useRef(null);

  const handleMessage = useCallback((msg) => {
    // SDK passa { source: 'ai' | 'user', message: string }
    if (!msg || !msg.message) return;
    setMessages((prev) => [
      ...prev,
      {
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        source: msg.source,
        text: msg.message,
      },
    ]);
  }, []);

  const conversation = useConversation({
    onConnect: () => {
      setConnectError(false);
      startingRef.current = false;
      startedAtRef.current = Date.now();
      setElapsed(0);
      if (watchdogRef.current) {
        clearTimeout(watchdogRef.current);
        watchdogRef.current = null;
      }
    },
    onDisconnect: () => {
      startedAtRef.current = null;
      startingRef.current = false;
      if (watchdogRef.current) {
        clearTimeout(watchdogRef.current);
        watchdogRef.current = null;
      }
    },
    onMessage: handleMessage,
    onError: (err) => {
      console.error('[Marina]', err);
      setConnectError(true);
      startingRef.current = false;
    },
    clientTools: {
      mostrarQRCode: async () => {
        onShowQR();
        return 'QR Code exibido para o médico';
      },
      mostrarRelatorio: async () => {
        onShowQR();
        return 'Relatório iniciado';
      },
    },
  });

  const { status, isSpeaking, startSession, endSession, setMuted } = conversation;

  // Polling de volume
  useEffect(() => {
    if (status !== 'connected') {
      setVolume(0);
      return;
    }
    let raf;
    const loop = () => {
      try {
        const v = conversation.getOutputVolume();
        setVolume(typeof v === 'number' ? v : 0);
      } catch {
        setVolume(0);
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => {
      if (raf) cancelAnimationFrame(raf);
    };
  }, [status, conversation]);

  // Timer da chamada
  useEffect(() => {
    if (status !== 'connected') {
      setElapsed(0);
      return;
    }
    const tick = setInterval(() => {
      if (startedAtRef.current) {
        setElapsed(Math.floor((Date.now() - startedAtRef.current) / 1000));
      }
    }, 1000);
    return () => clearInterval(tick);
  }, [status]);

  // Reset muted ao desconectar
  useEffect(() => {
    if (status === 'disconnected') setIsMuted(false);
  }, [status]);

  const startCall = useCallback(async () => {
    if (startingRef.current || status !== 'disconnected') return;
    startingRef.current = true;
    setMicError(false);
    setConnectError(false);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((t) => t.stop());
    } catch (e) {
      console.error('Mic permission denied', e);
      setMicError(true);
      startingRef.current = false;
      return;
    }
    watchdogRef.current = setTimeout(() => {
      if (startingRef.current) {
        console.warn('[Marina] Connection watchdog fired — ending stalled session');
        startingRef.current = false;
        setConnectError(true);
        try {
          endSession();
        } catch (e) {
          console.error('Failed to end stalled session', e);
        }
      }
    }, 15000);

    try {
      await startSession({
        agentId: AGENT_ID,
        connectionType: 'websocket',
      });
    } catch (e) {
      console.error('Failed to start session', e);
      setConnectError(true);
      startingRef.current = false;
      if (watchdogRef.current) {
        clearTimeout(watchdogRef.current);
        watchdogRef.current = null;
      }
    }
  }, [startSession, endSession, status]);

  const endCall = useCallback(() => {
    if (watchdogRef.current) {
      clearTimeout(watchdogRef.current);
      watchdogRef.current = null;
    }
    startingRef.current = false;
    endSession();
  }, [endSession]);

  // Limpa watchdog ao desmontar
  useEffect(() => {
    return () => {
      if (watchdogRef.current) {
        clearTimeout(watchdogRef.current);
        watchdogRef.current = null;
      }
    };
  }, []);

  const toggleMute = useCallback(() => {
    const next = !isMuted;
    setIsMuted(next);
    try {
      setMuted(next);
    } catch (e) {
      console.error('Failed to toggle mute', e);
    }
  }, [isMuted, setMuted]);

  const statusKind = useMemo(() => {
    if (status === 'disconnected') return 'disconnected';
    if (status === 'connecting') return 'connecting';
    return isSpeaking ? 'speaking' : 'listening';
  }, [status, isSpeaking]);

  return (
    <div
      style={{
        minHeight: '100vh',
        background: 'radial-gradient(ellipse 120% 80% at 50% -10%, #3d0f20 0%, #1A1410 65%)',
        color: COLORS.cream,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '24px 20px 32px',
        fontFamily: "'Red Hat Display', sans-serif",
        position: 'relative',
      }}
    >
      {/* LOGIN — canto superior direito */}
      <Link
        to="/login"
        aria-label="Login"
        className="inline-flex items-center transition-all"
        style={{
          position: 'absolute',
          top: 24,
          right: 20,
          gap: 8,
          padding: '8px 16px',
          borderRadius: 999,
          background: 'rgba(250,246,240,0.05)',
          border: '1px solid rgba(250,246,240,0.15)',
          color: 'rgba(250,246,240,0.85)',
          fontSize: 13,
          fontWeight: 600,
          letterSpacing: '0.02em',
          textDecoration: 'none',
          fontFamily: "'Red Hat Display', sans-serif",
          zIndex: 10,
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = 'rgba(255,107,53,0.12)';
          e.currentTarget.style.borderColor = 'rgba(255,107,53,0.4)';
          e.currentTarget.style.color = COLORS.orange;
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = 'rgba(250,246,240,0.05)';
          e.currentTarget.style.borderColor = 'rgba(250,246,240,0.15)';
          e.currentTarget.style.color = 'rgba(250,246,240,0.85)';
        }}
      >
        Login
      </Link>

      {/* HEADER */}
      <div className="flex flex-col items-center" style={{ gap: 14 }}>
        <Logo size="md" tone="dark" />
        <StatusPill kind={statusKind} />
      </div>

      {/* CENTRO — visualizador + identidade + transcript */}
      <div
        className="flex flex-col items-center"
        style={{ gap: 24, width: '100%' }}
      >
        <AudioVisualizer volume={volume} isSpeaking={isSpeaking} status={status} />

        <div className="flex flex-col items-center" style={{ gap: 6 }}>
          <div
            style={{
              fontSize: 28,
              fontWeight: 800,
              color: COLORS.cream,
              letterSpacing: '-0.02em',
              lineHeight: 1,
            }}
          >
            MARINA
          </div>
          <div
            style={{
              fontSize: 11.5,
              color: COLORS.inkMute,
              textTransform: 'uppercase',
              letterSpacing: '0.18em',
              fontWeight: 600,
            }}
          >
            Consultora Virtual · Medzee
          </div>
        </div>

        <Transcript messages={messages} />
      </div>

      {/* RODAPÉ — controles */}
      <div className="flex flex-col items-center" style={{ gap: 18, width: '100%' }}>
        {micError && (
          <div
            className="flex items-start"
            style={{
              gap: 12,
              maxWidth: 440,
              padding: '14px 16px',
              background: 'rgba(229,96,77,0.1)',
              border: '1px solid rgba(229,96,77,0.3)',
              borderRadius: 14,
              color: 'rgba(250,246,240,0.85)',
              fontSize: 13,
              lineHeight: 1.5,
            }}
          >
            <MicOff size={18} color="#E5604D" style={{ flexShrink: 0, marginTop: 1 }} />
            Permita o acesso ao microfone nas configurações do navegador para conversar com a Marina.
          </div>
        )}

        {connectError && status === 'disconnected' && !micError && (
          <div
            className="flex items-center"
            style={{
              gap: 10,
              padding: '10px 16px',
              background: 'rgba(229,96,77,0.08)',
              border: '1px solid rgba(229,96,77,0.25)',
              borderRadius: 12,
              color: 'rgba(250,246,240,0.8)',
              fontSize: 12.5,
            }}
          >
            Não foi possível conectar. Tente novamente.
          </div>
        )}

        {status === 'disconnected' && (
          <button
            type="button"
            onClick={startCall}
            className="inline-flex items-center justify-center transition-all"
            style={{
              gap: 10,
              padding: '16px 32px',
              borderRadius: 999,
              border: 'none',
              background: `linear-gradient(135deg, ${COLORS.orange}, ${COLORS.orangeDeep})`,
              color: COLORS.cream,
              fontSize: 16,
              fontWeight: 700,
              cursor: 'pointer',
              boxShadow: '0 12px 36px -8px rgba(255,107,53,0.55)',
              fontFamily: "'Red Hat Display', sans-serif",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.transform = 'translateY(-2px)';
              e.currentTarget.style.boxShadow = '0 18px 44px -8px rgba(255,107,53,0.7)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.transform = 'translateY(0)';
              e.currentTarget.style.boxShadow = '0 12px 36px -8px rgba(255,107,53,0.55)';
            }}
          >
            {connectError ? <RefreshCw size={18} /> : <Phone size={18} fill={COLORS.cream} strokeWidth={0} />}
            {connectError ? 'Tentar novamente' : 'Falar com a Marina'}
          </button>
        )}

        {status === 'connecting' && (
          <button
            type="button"
            disabled
            className="inline-flex items-center justify-center"
            style={{
              gap: 10,
              padding: '16px 32px',
              borderRadius: 999,
              border: 'none',
              background: 'rgba(255,107,53,0.4)',
              color: 'rgba(250,246,240,0.85)',
              fontSize: 16,
              fontWeight: 700,
              cursor: 'not-allowed',
              opacity: 0.85,
              fontFamily: "'Red Hat Display', sans-serif",
            }}
          >
            <Loader2 size={18} className="anim-spin" />
            Conectando…
          </button>
        )}

        {status === 'connected' && (
          <div className="flex items-center" style={{ gap: 16 }}>
            <button
              type="button"
              onClick={toggleMute}
              aria-label={isMuted ? 'Desmutar' : 'Mutar'}
              style={{
                width: 52,
                height: 52,
                borderRadius: '50%',
                border: `1px solid ${isMuted ? 'rgba(255,107,53,0.4)' : 'rgba(255,255,255,0.15)'}`,
                background: isMuted ? 'rgba(255,107,53,0.2)' : 'rgba(255,255,255,0.08)',
                color: isMuted ? COLORS.orange : COLORS.cream,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                transition: 'all 0.2s ease',
              }}
            >
              {isMuted ? <MicOff size={20} /> : <Mic size={20} />}
            </button>

            <div
              style={{
                fontSize: 13,
                color: COLORS.inkMute,
                fontVariantNumeric: 'tabular-nums',
                minWidth: 48,
                textAlign: 'center',
              }}
            >
              {formatTimer(elapsed)}
            </div>

            <button
              type="button"
              onClick={endCall}
              aria-label="Encerrar chamada"
              style={{
                width: 52,
                height: 52,
                borderRadius: '50%',
                border: 'none',
                background: '#E5604D',
                color: '#fff',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                boxShadow: '0 8px 24px -6px rgba(229,96,77,0.5)',
                transition: 'transform 0.15s ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.transform = 'scale(1.06)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.transform = 'scale(1)';
              }}
            >
              <PhoneOff size={20} />
            </button>
          </div>
        )}

        <div
          style={{
            fontSize: 11,
            color: 'rgba(250,246,240,0.25)',
            textAlign: 'center',
          }}
        >
          Conversa processada por IA · Medzee · Sem gravação armazenada
        </div>
      </div>
    </div>
  );
}

export default function AgentScreen({ onShowQR }) {
  return (
    <ConversationProvider>
      <AgentScreenInner onShowQR={onShowQR} />
    </ConversationProvider>
  );
}
