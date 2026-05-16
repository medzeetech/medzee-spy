import { useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { MessageCircle, Smartphone, Unplug, Wifi, WifiOff, AlertTriangle } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';

const QR_VALUE = 'https://medzee.com.br/conectar';

export default function WhatsAppPage() {
  const [connected, setConnected] = useState(true);
  const [showConfirm, setShowConfirm] = useState(false);

  const connectedPhone = '+55 (11) 99876-5432';
  const connectedSince = '14 abr 2026 · 09:32';

  const handleDisconnect = () => {
    setConnected(false);
    setShowConfirm(false);
  };

  return (
    <div style={{ maxWidth: 600 }}>
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ fontSize: 24, fontWeight: 800, color: COLORS.ink, margin: 0, letterSpacing: '-0.02em' }}>
          Conexão WhatsApp
        </h1>
        <p style={{ fontSize: 14, color: COLORS.inkSoft, margin: 0, marginTop: 4 }}>
          Gerencie o WhatsApp conectado para análise
        </p>
      </div>

      {/* Status card */}
      <div
        style={{
          background: COLORS.paper,
          border: `1px solid ${connected ? 'rgba(37,211,102,0.3)' : COLORS.hairline}`,
          borderRadius: 16,
          padding: 24,
          marginBottom: 20,
        }}
      >
        <div className="flex items-center" style={{ gap: 14, marginBottom: 16 }}>
          <div
            style={{
              width: 44,
              height: 44,
              borderRadius: 12,
              background: connected ? 'rgba(37,211,102,0.1)' : COLORS.sunken,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: connected ? COLORS.wa : COLORS.inkMute,
            }}
          >
            {connected ? <Wifi size={22} /> : <WifiOff size={22} />}
          </div>
          <div style={{ flex: 1 }}>
            <div className="flex items-center" style={{ gap: 8 }}>
              <span style={{ fontSize: 16, fontWeight: 700, color: COLORS.ink }}>
                {connected ? 'Conectado' : 'Desconectado'}
              </span>
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: connected ? COLORS.wa : COLORS.inkMute,
                  display: 'inline-block',
                }}
              />
            </div>
            {connected && (
              <div style={{ fontSize: 13, color: COLORS.inkSoft, marginTop: 2 }}>
                Apenas 1 WhatsApp pode estar conectado por vez
              </div>
            )}
          </div>
        </div>

        {connected && (
          <>
            <div
              style={{
                background: COLORS.sunken,
                borderRadius: 12,
                padding: 16,
                marginBottom: 16,
              }}
            >
              <div className="flex items-center" style={{ gap: 10, marginBottom: 8 }}>
                <Smartphone size={16} color={COLORS.inkSoft} />
                <span style={{ fontSize: 14, fontWeight: 600, color: COLORS.ink }}>{connectedPhone}</span>
              </div>
              <div style={{ fontSize: 12, color: COLORS.inkMute }}>
                Conectado desde {connectedSince}
              </div>
            </div>

            {!showConfirm ? (
              <button
                type="button"
                onClick={() => setShowConfirm(true)}
                className="flex items-center justify-center transition-all"
                style={{
                  gap: 8,
                  width: '100%',
                  padding: 14,
                  borderRadius: 12,
                  border: '1px solid rgba(229,96,77,0.3)',
                  background: 'transparent',
                  color: '#E5604D',
                  fontSize: 14,
                  fontWeight: 600,
                  cursor: 'pointer',
                  fontFamily: "'Red Hat Display', sans-serif",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'rgba(229,96,77,0.05)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'transparent';
                }}
              >
                <Unplug size={16} />
                Desconectar WhatsApp
              </button>
            ) : (
              <div
                style={{
                  background: 'rgba(229,96,77,0.06)',
                  border: '1px solid rgba(229,96,77,0.2)',
                  borderRadius: 12,
                  padding: 16,
                }}
              >
                <div className="flex items-start" style={{ gap: 10, marginBottom: 14 }}>
                  <AlertTriangle size={18} color="#E5604D" style={{ flexShrink: 0, marginTop: 1 }} />
                  <div style={{ fontSize: 13, color: COLORS.ink, lineHeight: 1.5 }}>
                    Ao desconectar, a geração automática de relatórios será pausada. Você poderá conectar outro número depois.
                  </div>
                </div>
                <div className="flex" style={{ gap: 10 }}>
                  <button
                    type="button"
                    onClick={() => setShowConfirm(false)}
                    style={{
                      flex: 1,
                      padding: 12,
                      borderRadius: 10,
                      border: `1px solid ${COLORS.hairline}`,
                      background: COLORS.paper,
                      color: COLORS.ink,
                      fontSize: 13,
                      fontWeight: 600,
                      cursor: 'pointer',
                      fontFamily: "'Red Hat Display', sans-serif",
                    }}
                  >
                    Cancelar
                  </button>
                  <button
                    type="button"
                    onClick={handleDisconnect}
                    style={{
                      flex: 1,
                      padding: 12,
                      borderRadius: 10,
                      border: 'none',
                      background: '#E5604D',
                      color: '#fff',
                      fontSize: 13,
                      fontWeight: 600,
                      cursor: 'pointer',
                      fontFamily: "'Red Hat Display', sans-serif",
                    }}
                  >
                    Confirmar desconexão
                  </button>
                </div>
              </div>
            )}
          </>
        )}

        {!connected && (
          <div>
            <p style={{ fontSize: 14, color: COLORS.inkSoft, lineHeight: 1.5, marginBottom: 20, marginTop: 0 }}>
              Aponte o celular com o WhatsApp da clínica para o código abaixo. Analisamos o histórico sem armazenar conteúdo.
            </p>
            <div className="flex justify-center" style={{ marginBottom: 16 }}>
              <div
                style={{
                  background: '#fff',
                  borderRadius: 16,
                  padding: 16,
                  border: `1px solid ${COLORS.hairline}`,
                  boxShadow: '0 8px 24px -8px rgba(0,0,0,0.08)',
                }}
              >
                <QRCodeSVG value={QR_VALUE} size={180} level="M" bgColor="#FFFFFF" fgColor="#000000" />
              </div>
            </div>
            <div className="flex items-center justify-center" style={{ gap: 6, fontSize: 12, color: COLORS.inkMute }}>
              <MessageCircle size={13} color={COLORS.wa} />
              Aguardando leitura do QR Code…
            </div>
          </div>
        )}
      </div>

      {/* Info */}
      <div
        style={{
          background: 'rgba(59,123,176,0.06)',
          border: '1px solid rgba(59,123,176,0.15)',
          borderRadius: 12,
          padding: 16,
          fontSize: 13,
          color: COLORS.inkSoft,
          lineHeight: 1.55,
        }}
      >
        <strong style={{ color: COLORS.ink }}>Como funciona:</strong> Ao conectar, a Medzee analisa apenas metadados das conversas (tempos de resposta, volume, padrões). Nenhum conteúdo de mensagem é armazenado após a análise.
      </div>
    </div>
  );
}
