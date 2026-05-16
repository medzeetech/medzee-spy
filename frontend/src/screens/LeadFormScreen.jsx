import { useEffect, useRef, useState } from 'react';
import { User, Mail, Phone, ArrowRight, Volume2, Lock } from 'lucide-react';
import { COLORS } from '../constants/colors.js';
import Logo from '../components/Logo.jsx';
import resultadoAudio from '../assets/resultado.mp3';

function maskPhone(value) {
  const digits = value.replace(/\D/g, '').slice(0, 11);
  if (digits.length === 0) return '';
  if (digits.length <= 2) return `(${digits}`;
  if (digits.length <= 6) return `(${digits.slice(0, 2)}) ${digits.slice(2)}`;
  if (digits.length <= 10) return `(${digits.slice(0, 2)}) ${digits.slice(2, 6)}-${digits.slice(6)}`;
  return `(${digits.slice(0, 2)}) ${digits.slice(2, 7)}-${digits.slice(7)}`;
}

function isValidEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

function FieldIcon({ Icon }) {
  return (
    <div
      style={{
        position: 'absolute',
        left: 14,
        top: '50%',
        transform: 'translateY(-50%)',
        color: 'rgba(250,246,240,0.4)',
        display: 'flex',
        alignItems: 'center',
        pointerEvents: 'none',
      }}
    >
      <Icon size={16} strokeWidth={2} />
    </div>
  );
}

export default function LeadFormScreen({ onSubmit }) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [touched, setTouched] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [audioPlaying, setAudioPlaying] = useState(false);
  const audioRef = useRef(null);

  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;
    const tryPlay = el.play();
    if (tryPlay && typeof tryPlay.catch === 'function') {
      tryPlay.catch((e) => {
        if (e?.name !== 'AbortError') {
          console.warn('[Resultado] Não foi possível reproduzir o áudio:', e);
        }
      });
    }
  }, []);

  const phoneDigits = phone.replace(/\D/g, '');
  const errors = {
    name: name.trim().length < 2 ? 'Informe seu nome completo' : null,
    email: !isValidEmail(email) ? 'Informe um e-mail válido' : null,
    phone: phoneDigits.length < 10 ? 'Informe um telefone válido' : null,
  };
  const formValid = !errors.name && !errors.email && !errors.phone;

  const handleSubmit = (e) => {
    e.preventDefault();
    setTouched({ name: true, email: true, phone: true });
    if (!formValid || submitting) return;
    setSubmitting(true);
    onSubmit?.({
      name: name.trim(),
      email: email.trim().toLowerCase(),
      phone,
    });
  };

  const inputStyle = (hasError) => ({
    width: '100%',
    padding: '14px 14px 14px 40px',
    borderRadius: 12,
    background: 'rgba(250,246,240,0.04)',
    border: `1px solid ${hasError ? 'rgba(229,96,77,0.5)' : 'rgba(255,107,53,0.2)'}`,
    color: COLORS.cream,
    fontSize: 14.5,
    fontFamily: "'Red Hat Display', sans-serif",
    outline: 'none',
    transition: 'border-color 0.2s ease, background 0.2s ease',
  });

  const errorStyle = {
    color: '#E5604D',
    fontSize: 11.5,
    marginTop: 4,
    paddingLeft: 4,
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        background: 'radial-gradient(ellipse 120% 80% at 50% -10%, #3d0f20 0%, #1A1410 65%)',
        color: COLORS.cream,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        padding: '24px 20px 32px',
        fontFamily: "'Red Hat Display', sans-serif",
      }}
    >
      <audio
        ref={audioRef}
        src={resultadoAudio}
        autoPlay
        preload="auto"
        onPlay={() => setAudioPlaying(true)}
        onPause={() => setAudioPlaying(false)}
        onEnded={() => setAudioPlaying(false)}
      />

      <div style={{ marginBottom: 32 }}>
        <Logo size="md" tone="dark" />
      </div>

      <div
        className="anim-fadeup"
        style={{
          width: '100%',
          maxWidth: 460,
          background: 'rgba(250,246,240,0.04)',
          border: '1px solid rgba(255,107,53,0.18)',
          borderRadius: 24,
          padding: 'clamp(24px, 4vw, 36px)',
          backdropFilter: 'blur(20px)',
          WebkitBackdropFilter: 'blur(20px)',
          boxShadow: '0 40px 80px -20px rgba(0,0,0,0.7)',
        }}
      >
        {/* Indicador de áudio tocando */}
        <div
          className="inline-flex items-center"
          style={{
            gap: 8,
            padding: '6px 12px',
            borderRadius: 99,
            background: audioPlaying ? 'rgba(255,107,53,0.12)' : 'rgba(250,246,240,0.05)',
            border: `1px solid ${audioPlaying ? 'rgba(255,107,53,0.3)' : 'rgba(250,246,240,0.12)'}`,
            color: audioPlaying ? COLORS.orange : 'rgba(250,246,240,0.5)',
            fontSize: 11.5,
            fontWeight: 600,
            letterSpacing: '0.04em',
            marginBottom: 18,
            transition: 'all 0.3s ease',
          }}
        >
          <Volume2 size={13} className={audioPlaying ? 'anim-pulse-dot' : ''} />
          {audioPlaying ? 'Marina está falando…' : 'Mensagem da Marina'}
        </div>

        <h1
          style={{
            fontSize: 'clamp(22px, 3.5vw, 26px)',
            fontWeight: 800,
            letterSpacing: '-0.02em',
            margin: 0,
            marginBottom: 10,
            lineHeight: 1.18,
          }}
        >
          Seu diagnóstico está pronto.
        </h1>
        <p
          style={{
            fontSize: 14,
            color: 'rgba(250,246,240,0.6)',
            lineHeight: 1.5,
            margin: 0,
            marginBottom: 26,
          }}
        >
          Antes de liberar o relatório completo, conte para a Marina quem é você. Ela vai usar isso para personalizar as próximas conversas.
        </p>

        <form onSubmit={handleSubmit} noValidate>
          {/* Nome */}
          <div style={{ marginBottom: 14 }}>
            <label
              htmlFor="lead-name"
              style={{
                display: 'block',
                fontSize: 10.5,
                color: 'rgba(250,246,240,0.65)',
                textTransform: 'uppercase',
                letterSpacing: '0.14em',
                fontWeight: 600,
                marginBottom: 6,
                paddingLeft: 4,
              }}
            >
              Nome
            </label>
            <div style={{ position: 'relative' }}>
              <FieldIcon Icon={User} />
              <input
                id="lead-name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                onBlur={() => setTouched((t) => ({ ...t, name: true }))}
                placeholder="Como devemos te chamar?"
                autoComplete="name"
                className="lead-input"
                style={inputStyle(touched.name && !!errors.name)}
              />
            </div>
            {touched.name && errors.name && <div style={errorStyle}>{errors.name}</div>}
          </div>

          {/* Email */}
          <div style={{ marginBottom: 14 }}>
            <label
              htmlFor="lead-email"
              style={{
                display: 'block',
                fontSize: 10.5,
                color: 'rgba(250,246,240,0.65)',
                textTransform: 'uppercase',
                letterSpacing: '0.14em',
                fontWeight: 600,
                marginBottom: 6,
                paddingLeft: 4,
              }}
            >
              E-mail
            </label>
            <div style={{ position: 'relative' }}>
              <FieldIcon Icon={Mail} />
              <input
                id="lead-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onBlur={() => setTouched((t) => ({ ...t, email: true }))}
                placeholder="seu@email.com.br"
                autoComplete="email"
                className="lead-input"
                style={inputStyle(touched.email && !!errors.email)}
              />
            </div>
            {touched.email && errors.email && <div style={errorStyle}>{errors.email}</div>}
          </div>

          {/* Telefone */}
          <div style={{ marginBottom: 22 }}>
            <label
              htmlFor="lead-phone"
              style={{
                display: 'block',
                fontSize: 10.5,
                color: 'rgba(250,246,240,0.65)',
                textTransform: 'uppercase',
                letterSpacing: '0.14em',
                fontWeight: 600,
                marginBottom: 6,
                paddingLeft: 4,
              }}
            >
              Telefone
            </label>
            <div style={{ position: 'relative' }}>
              <FieldIcon Icon={Phone} />
              <input
                id="lead-phone"
                type="tel"
                value={phone}
                onChange={(e) => setPhone(maskPhone(e.target.value))}
                onBlur={() => setTouched((t) => ({ ...t, phone: true }))}
                placeholder="(11) 99999-9999"
                autoComplete="tel"
                inputMode="tel"
                className="lead-input"
                style={inputStyle(touched.phone && !!errors.phone)}
              />
            </div>
            {touched.phone && errors.phone && <div style={errorStyle}>{errors.phone}</div>}
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="w-full inline-flex items-center justify-center transition-all"
            style={{
              gap: 10,
              padding: 16,
              borderRadius: 14,
              border: 'none',
              background: submitting
                ? 'rgba(255,107,53,0.4)'
                : `linear-gradient(135deg, ${COLORS.orange}, ${COLORS.orangeDeep})`,
              color: COLORS.cream,
              fontSize: 15,
              fontWeight: 700,
              cursor: submitting ? 'not-allowed' : 'pointer',
              boxShadow: '0 10px 30px -8px rgba(255,107,53,0.5)',
              fontFamily: "'Red Hat Display', sans-serif",
              width: '100%',
            }}
            onMouseEnter={(e) => {
              if (submitting) return;
              e.currentTarget.style.transform = 'translateY(-2px)';
              e.currentTarget.style.boxShadow = '0 14px 36px -8px rgba(255,107,53,0.65)';
            }}
            onMouseLeave={(e) => {
              if (submitting) return;
              e.currentTarget.style.transform = 'translateY(0)';
              e.currentTarget.style.boxShadow = '0 10px 30px -8px rgba(255,107,53,0.5)';
            }}
          >
            Ver meu diagnóstico
            <ArrowRight size={16} />
          </button>
        </form>

        <div
          className="flex items-center justify-center"
          style={{
            gap: 6,
            marginTop: 18,
            fontSize: 11,
            color: 'rgba(250,246,240,0.4)',
          }}
        >
          <Lock size={11} />
          Seus dados ficam só com a Medzee · Sem spam
        </div>
      </div>
    </div>
  );
}
