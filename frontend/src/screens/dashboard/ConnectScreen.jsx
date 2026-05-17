// F4 — Reconnect flow for already-authenticated users.
//
// Diferenças vs /spy → QRScreen:
//   1. POST /api/whatsapp/sessions com Authorization Bearer (callApi),
//      pra backend já gravar user_id na row + state.
//   2. Não exibe form de signup depois do connect — vai direto pro
//      /app/whatsapp ("Conectado · aguardando primeiras mensagens").
//   3. Roda dentro do DashboardLayout (sidebar continua visível).
//
// Visual: card no light theme (parecido com ReportGeneratingState).

import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  MessageCircle,
  Lock,
  Loader2,
  AlertCircle,
  RefreshCw,
  CheckCircle2,
} from 'lucide-react';
import { COLORS } from '../../constants/colors.js';
import { callApi } from '../../lib/api.js';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
const CORNER_SIZE = 18;
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

export default function ConnectScreen() {
  const navigate = useNavigate();
  const [sessionId, setSessionId] = useState(null);
  const [qrBase64, setQrBase64] = useState(null);
  const [phase, setPhase] = useState('loading'); // loading | qr-ready | connected | failed
  const [error, setError] = useState(null);
  const eventSourceRef = useRef(null);
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
        // Pequeno beat pro user ver o check verde antes do redirect.
        setTimeout(() => navigate('/app/whatsapp'), 800);
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
    [cleanupSSE, navigate],
  );

  const createSession = useCallback(async () => {
    setPhase('loading');
    setError(null);
    setQrBase64(null);
    cleanupSSE();

    try {
      // Authenticated POST — backend lê o JWT e grava user_id na row
      // no momento da criação.
      const data = await callApi('/api/whatsapp/sessions', {
        method: 'POST',
        body: {},
        auth: true,
      });
      setSessionId(data.session_id);
      setQrBase64(data.qr);
      setPhase('qr-ready');
      attachSSE(data.session_id);
    } catch (e) {
      const detail = e?.detail || e?.message || 'desconhecido';
      setError(`Não foi possível criar a sessão: ${detail}`);
      setPhase('failed');
    }
  }, [attachSSE, cleanupSSE]);

  useEffect(() => {
    if (didKickoffRef.current) return cleanupSSE;
    didKickoffRef.current = true;
    createSession();
    return cleanupSSE;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const statusText = {
    loading: 'Gerando QR Code…',
    'qr-ready': 'Abra o WhatsApp da clínica > Aparelhos conectados > Conectar aparelho e escaneie.',
    connected: 'Conectado! Redirecionando…',
    failed: error || 'Algo deu errado.',
  }[phase];

  return (
    <div style={{ maxWidth: 720, margin: '0 auto' }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 24, fontWeight: 800, color: COLORS.ink, margin: 0, letterSpacing: '-0.02em' }}>
          Conectar WhatsApp
        </h1>
        <p style={{ fontSize: 14, color: COLORS.inkSoft, margin: 0, marginTop: 4 }}>
          Escaneie o QR Code abaixo no celular da clínica
        </p>
      </div>

      <div
        style={{
          background: COLORS.paper,
          border: `1px solid ${COLORS.hairline}`,
          borderRadius: 20,
          padding: 'clamp(24px, 4vw, 36px)',
          maxWidth: 420,
          margin: '0 auto',
          boxShadow: '0 12px 32px -16px rgba(0,0,0,0.08)',
        }}
      >
        {/* Badge WhatsApp */}
        <div className="flex justify-center" style={{ marginBottom: 16 }}>
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

        {/* Status text */}
        <p
          style={{
            fontSize: 13.5,
            color: phase === 'failed' ? '#E5604D' : COLORS.inkSoft,
            lineHeight: 1.55,
            textAlign: 'center',
            margin: 0,
            marginBottom: 24,
            minHeight: 42,
          }}
        >
          {statusText}
        </p>

        {/* QR area */}
        <div className="flex justify-center" style={{ marginBottom: 22 }}>
          <div
            style={{
              position: 'relative',
              background: '#ffffff',
              borderRadius: 14,
              padding: 12,
              width: 224,
              height: 224,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 0 0 1px rgba(255,107,53,0.18), 0 12px 32px -10px rgba(0,0,0,0.18)',
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

            {phase === 'qr-ready' && qrBase64 && (
              <>
                <Corner position="tl" />
                <Corner position="tr" />
                <Corner position="bl" />
                <Corner position="br" />
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
                  background: 'rgba(255,255,255,0.95)',
                  borderRadius: 14,
                }}
              >
                <CheckCircle2 size={64} color={COLORS.wa} strokeWidth={2} />
              </div>
            )}
          </div>
        </div>

        {/* Segurança */}
        <div
          className="flex items-center justify-center gap-1.5"
          style={{
            fontSize: 11.5,
            color: COLORS.inkMute,
            marginBottom: 18,
          }}
        >
          <Lock size={12} />
          Somente metadados • Conteúdo armazenado por até 30 dias
        </div>

        {/* Botão tentar de novo */}
        {phase === 'failed' && (
          <button
            type="button"
            onClick={createSession}
            className="w-full transition-all duration-200 hover:-translate-y-0.5"
            style={{
              padding: 14,
              borderRadius: 12,
              border: 'none',
              background: `linear-gradient(135deg, ${COLORS.orange}, ${COLORS.orangeDeep})`,
              color: COLORS.cream,
              fontSize: 14,
              fontWeight: 700,
              cursor: 'pointer',
              boxShadow: '0 8px 24px -8px rgba(255,107,53,0.4)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 8,
              fontFamily: "'Red Hat Display', sans-serif",
            }}
          >
            <RefreshCw size={15} />
            Tentar novamente
          </button>
        )}

        {phase === 'qr-ready' && sessionId && (
          <div
            style={{
              fontSize: 11,
              color: COLORS.inkMute,
              textAlign: 'center',
              fontFamily: 'ui-monospace, Menlo, monospace',
            }}
          >
            session: {sessionId.slice(0, 8)}…
          </div>
        )}
      </div>
    </div>
  );
}
