import { useCallback, useEffect, useRef, useState } from 'react';
import {
  MessageCircle,
  Lock,
  Loader2,
  AlertCircle,
  RefreshCw,
  CheckCircle2,
} from 'lucide-react';
import { COLORS } from '../constants/colors.js';
import Logo from '../components/Logo.jsx';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
const CORNER_SIZE = 20;
const CORNER_WIDTH = 3;

function Corner({ position }) {
  const base = {
    position: 'absolute',
    width: CORNER_SIZE,
    height: CORNER_SIZE,
    pointerEvents: 'none',
  };
  const styles = {
    tl: { ...base, top: -1, left: -1, borderTop: `${CORNER_WIDTH}px solid ${COLORS.orange}`, borderLeft: `${CORNER_WIDTH}px solid ${COLORS.orange}`, borderTopLeftRadius: 8 },
    tr: { ...base, top: -1, right: -1, borderTop: `${CORNER_WIDTH}px solid ${COLORS.orange}`, borderRight: `${CORNER_WIDTH}px solid ${COLORS.orange}`, borderTopRightRadius: 8 },
    bl: { ...base, bottom: -1, left: -1, borderBottom: `${CORNER_WIDTH}px solid ${COLORS.orange}`, borderLeft: `${CORNER_WIDTH}px solid ${COLORS.orange}`, borderBottomLeftRadius: 8 },
    br: { ...base, bottom: -1, right: -1, borderBottom: `${CORNER_WIDTH}px solid ${COLORS.orange}`, borderRight: `${CORNER_WIDTH}px solid ${COLORS.orange}`, borderBottomRightRadius: 8 },
  };
  return <div style={styles[position]} />;
}

export default function QRScreen({ onSimulate, onSessionCreated }) {
  const [sessionId, setSessionId] = useState(null);
  const [qrBase64, setQrBase64] = useState(null);
  const [phase, setPhase] = useState('loading'); // loading | qr-ready | connected | failed
  const [error, setError] = useState(null);
  const eventSourceRef = useRef(null);
  // StrictMode (dev) monta o componente 2x de propósito; sem guard, POST /sessions
  // dispara duas vezes e queima 2 slots da uazapi free tier. Esse ref garante
  // que o kickoff inicial só roda uma vez por instância real do componente.
  const didKickoffRef = useRef(false);

  const cleanupSSE = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  const attachSSE = useCallback(
    (id) => {
      cleanupSSE();
      const es = new EventSource(`${API_BASE_URL}/api/whatsapp/sessions/${id}/events`);
      eventSourceRef.current = es;

      es.addEventListener('qr-updated', (ev) => {
        try {
          const payload = JSON.parse(ev.data);
          if (payload.qr) setQrBase64(payload.qr);
        } catch (e) {
          console.warn('[SSE] bad qr-updated payload', e);
        }
      });

      es.addEventListener('connected', () => {
        setPhase('connected');
        cleanupSSE();
        // dá um beat de UX antes da transição
        setTimeout(() => onSimulate?.(), 600);
      });

      es.addEventListener('extracting', () => {
        // a transição já aconteceu via "connected"; mas se chegar primeiro
        // (corrida), garante o redirecionamento.
        if (phase !== 'connected') {
          setPhase('connected');
          cleanupSSE();
          setTimeout(() => onSimulate?.(), 400);
        }
      });

      es.addEventListener('failed', (ev) => {
        try {
          const payload = JSON.parse(ev.data);
          setError(payload.message || payload.code || 'Falha desconhecida');
        } catch {
          setError('Falha desconhecida');
        }
        setPhase('failed');
        cleanupSSE();
      });

      es.addEventListener('expired', () => {
        setError('QR Code expirou. Tente novamente.');
        setPhase('failed');
        cleanupSSE();
      });

      es.onerror = () => {
        // EventSource tenta reconectar automaticamente; só logamos.
        console.warn('[SSE] connection error (auto-retry)');
      };
    },
    [cleanupSSE, onSimulate, phase],
  );

  const createSession = useCallback(async () => {
    setPhase('loading');
    setError(null);
    setQrBase64(null);
    cleanupSSE();

    try {
      const res = await fetch(`${API_BASE_URL}/api/whatsapp/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail = body.detail || `HTTP ${res.status}`;
        setError(`Falha ao criar sessão: ${detail}`);
        setPhase('failed');
        return;
      }

      const { data } = await res.json();
      setSessionId(data.session_id);
      setQrBase64(data.qr);
      setPhase('qr-ready');
      onSessionCreated?.(data.session_id);
      attachSSE(data.session_id);
    } catch (e) {
      setError(`Sem conexão com o backend: ${e.message || 'desconhecido'}`);
      setPhase('failed');
    }
  }, [attachSSE, cleanupSSE, onSessionCreated]);

  useEffect(() => {
    if (didKickoffRef.current) return cleanupSSE;
    didKickoffRef.current = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional kick-off
    createSession();
    return cleanupSSE;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const statusText = {
    loading: 'Gerando QR Code…',
    'qr-ready': 'Aponte o celular com o WhatsApp da clínica para este código.',
    connected: 'Conectado! Iniciando análise…',
    failed: error || 'Algo deu errado.',
  }[phase];

  return (
    <div
      className="flex flex-col items-center justify-center px-4 py-10"
      style={{
        minHeight: '100vh',
        background: `radial-gradient(circle at 50% 0%, #2a0f1c 0%, ${COLORS.ink} 60%)`,
        color: COLORS.cream,
      }}
    >
      <div style={{ marginBottom: 40 }}>
        <Logo size="md" tone="dark" />
      </div>

      <div
        style={{
          background: 'rgba(250,246,240,0.04)',
          border: '1px solid rgba(255,107,53,0.18)',
          borderRadius: 24,
          padding: '36px 32px 28px',
          maxWidth: 380,
          width: '100%',
          backdropFilter: 'blur(20px)',
          WebkitBackdropFilter: 'blur(20px)',
          boxShadow: '0 40px 80px -20px rgba(0,0,0,0.7)',
        }}
      >
        {/* Badge WhatsApp */}
        <div className="flex justify-center" style={{ marginBottom: 18 }}>
          <div
            className="inline-flex items-center gap-1.5"
            style={{
              background: '#25D36618',
              border: '1px solid #25D36630',
              borderRadius: 99,
              padding: '5px 13px',
              fontSize: 12,
              color: COLORS.wa,
              fontWeight: 700,
            }}
          >
            <MessageCircle size={13} fill={COLORS.wa} color={COLORS.wa} strokeWidth={0} />
            WhatsApp da Clínica
          </div>
        </div>

        {/* Título */}
        <h1
          style={{
            fontSize: 22,
            fontWeight: 800,
            color: COLORS.cream,
            letterSpacing: '-0.02em',
            textAlign: 'center',
            margin: 0,
            marginBottom: 8,
          }}
        >
          Conectar para análise
        </h1>

        {/* Subtexto / status dinâmico */}
        <p
          style={{
            fontSize: 13.5,
            color: phase === 'failed' ? '#E5604D' : 'rgba(250,246,240,0.5)',
            lineHeight: 1.55,
            textAlign: 'center',
            margin: 0,
            marginBottom: 28,
            minHeight: 42,
          }}
        >
          {statusText}
        </p>

        {/* QR área */}
        <div className="flex justify-center" style={{ marginBottom: 24 }}>
          <div
            style={{
              position: 'relative',
              background: '#ffffff',
              borderRadius: 16,
              padding: 12,
              width: 224,
              height: 224,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 0 0 1px rgba(255,107,53,0.25), 0 16px 40px -8px rgba(0,0,0,0.5)',
            }}
          >
            {phase === 'loading' && (
              <Loader2 size={48} color={COLORS.orange} className="anim-spin" strokeWidth={2.2} />
            )}

            {(phase === 'qr-ready' || phase === 'connected') && qrBase64 && (
              <img
                src={`data:image/png;base64,${qrBase64}`}
                alt="WhatsApp QR Code"
                style={{ width: 200, height: 200, display: 'block' }}
              />
            )}

            {phase === 'failed' && (
              <AlertCircle size={48} color="#E5604D" strokeWidth={2.2} />
            )}

            {/* Cantos só aparecem quando há QR válido */}
            {phase === 'qr-ready' && qrBase64 && (
              <>
                <Corner position="tl" />
                <Corner position="tr" />
                <Corner position="bl" />
                <Corner position="br" />
                <div
                  className="anim-scan"
                  style={{
                    position: 'absolute',
                    left: 12,
                    right: 12,
                    height: 2,
                    opacity: 0.85,
                    background: 'linear-gradient(90deg, transparent, #25D366, transparent)',
                    borderRadius: 2,
                    top: 12,
                  }}
                />
              </>
            )}

            {phase === 'connected' && (
              <div
                style={{
                  position: 'absolute',
                  inset: 0,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  background: 'rgba(255,255,255,0.92)',
                  borderRadius: 16,
                }}
              >
                <CheckCircle2 size={64} color={COLORS.wa} strokeWidth={2} />
              </div>
            )}
          </div>
        </div>

        {/* Texto segurança */}
        <div
          className="flex items-center justify-center gap-1.5"
          style={{
            fontSize: 11.5,
            color: 'rgba(250,246,240,0.5)',
            marginBottom: 22,
          }}
        >
          <Lock size={12} />
          Somente metadados • Nenhum conteúdo armazenado
        </div>

        {/* Botão (varia por estado) */}
        {phase === 'failed' && (
          <button
            type="button"
            onClick={createSession}
            className="w-full transition-all duration-200 hover:-translate-y-0.5"
            style={{
              padding: 15,
              borderRadius: 14,
              border: 'none',
              background: `linear-gradient(135deg, ${COLORS.orange}, ${COLORS.orangeDeep})`,
              color: COLORS.cream,
              fontSize: 15,
              fontWeight: 700,
              cursor: 'pointer',
              boxShadow: '0 10px 30px -8px rgba(255,107,53,0.5)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 8,
              fontFamily: "'Red Hat Display', sans-serif",
            }}
          >
            <RefreshCw size={16} />
            Tentar novamente
          </button>
        )}

        {phase === 'qr-ready' && sessionId && (
          <div
            style={{
              fontSize: 11,
              color: 'rgba(250,246,240,0.3)',
              textAlign: 'center',
              fontFamily: 'ui-monospace, Menlo, monospace',
            }}
          >
            session: {sessionId.slice(0, 8)}…
          </div>
        )}
      </div>

      <div
        style={{
          fontSize: 11.5,
          color: 'rgba(250,246,240,0.3)',
          marginTop: 24,
          textAlign: 'center',
        }}
      >
        Medzee Spy · {API_BASE_URL.replace(/^https?:\/\//, '')}
      </div>
    </div>
  );
}
