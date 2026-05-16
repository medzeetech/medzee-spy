import { QRCodeSVG } from 'qrcode.react';
import { MessageCircle, Lock, Zap } from 'lucide-react';
import { COLORS } from '../constants/colors.js';
import Logo from '../components/Logo.jsx';

const QR_VALUE = 'https://medzee.com.br/conectar';
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

export default function QRScreen({ onSimulate }) {
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

        {/* Subtexto */}
        <p
          style={{
            fontSize: 13.5,
            color: 'rgba(250,246,240,0.5)',
            lineHeight: 1.55,
            textAlign: 'center',
            margin: 0,
            marginBottom: 28,
          }}
        >
          Aponte o celular com o WhatsApp da clínica para este código. Analisamos o histórico sem armazenar conteúdo.
        </p>

        {/* QR */}
        <div className="flex justify-center" style={{ marginBottom: 24 }}>
          <div
            style={{
              position: 'relative',
              background: '#ffffff',
              borderRadius: 16,
              padding: 12,
              boxShadow: '0 0 0 1px rgba(255,107,53,0.25), 0 16px 40px -8px rgba(0,0,0,0.5)',
            }}
          >
            <QRCodeSVG value={QR_VALUE} size={200} level="M" bgColor="#FFFFFF" fgColor="#000000" />
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

        {/* Botão */}
        <button
          type="button"
          onClick={onSimulate}
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
          onMouseEnter={(e) => {
            e.currentTarget.style.boxShadow = '0 14px 36px -8px rgba(255,107,53,0.65)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.boxShadow = '0 10px 30px -8px rgba(255,107,53,0.5)';
          }}
        >
          <Zap size={16} />
          Simular Conexão
        </button>
      </div>

      <div
        style={{
          fontSize: 11.5,
          color: 'rgba(250,246,240,0.3)',
          marginTop: 24,
          textAlign: 'center',
        }}
      >
        Demo interna · Medzee Spy · Dados fictícios para apresentação
      </div>
    </div>
  );
}
