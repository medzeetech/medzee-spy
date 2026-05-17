import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { User, Mail, Phone, ArrowRight, ArrowLeft, Volume2, Lock, DollarSign, Eye, EyeOff } from 'lucide-react';
import { COLORS } from '../constants/colors.js';
import Logo from '../components/Logo.jsx';
import { api } from '../lib/api.js';
import { supabase } from '../lib/supabase.js';
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

function maskCurrency(value) {
  const digits = value.replace(/\D/g, '');
  if (digits.length === 0) return '';
  const num = parseInt(digits, 10) / 100;
  return num.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

export default function LeadFormScreen({ onSubmit, showTicketMedio = false, whatsappSessionId = null }) {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [ticketMedio, setTicketMedio] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [touched, setTouched] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [fieldErrors, setFieldErrors] = useState({});
  const [error, setError] = useState(null);
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
  const ticketDigits = ticketMedio.replace(/\D/g, '');

  const step1Errors = {
    name: name.trim().length < 2 ? 'Informe seu nome completo' : null,
    email: !isValidEmail(email) ? 'Informe um e-mail válido' : null,
    phone: phoneDigits.length < 10 ? 'Informe um telefone válido' : null,
    ticketMedio: showTicketMedio && ticketDigits.length === 0 ? 'Informe o ticket médio' : null,
  };
  const step1Valid = !step1Errors.name && !step1Errors.email && !step1Errors.phone && !step1Errors.ticketMedio;

  const step2Errors = {
    password: password.length < 6 ? 'A senha deve ter pelo menos 6 caracteres' : null,
    confirmPassword: confirmPassword !== password ? 'As senhas não coincidem' : null,
  };
  const step2Valid = !step2Errors.password && !step2Errors.confirmPassword;

  const handleNextStep = (e) => {
    e.preventDefault();
    setTouched({ name: true, email: true, phone: true, ticketMedio: true });
    if (!step1Valid) return;
    setStep(2);
    setTouched({});
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setTouched({ password: true, confirmPassword: true });
    if (!step2Valid || submitting) return;
    setSubmitting(true);
    setFieldErrors({});
    setError(null);

    const normalizedEmail = email.trim().toLowerCase();
    const payload = {
      name: name.trim(),
      email: normalizedEmail,
      phone,
      password,
      ticket_medio: ticketMedio ? parseFloat(ticketMedio.replace(/\D/g, '')) / 100 : null,
      whatsapp_session_id: whatsappSessionId ?? null,
    };

    try {
      const result = await api.signup(payload);
      if (result?.session?.access_token && result?.session?.refresh_token) {
        await supabase.auth.setSession({
          access_token: result.session.access_token,
          refresh_token: result.session.refresh_token,
        });
      }
      onSubmit?.(payload);
      // F4 pivot: relatório é on-demand agora (user clica "Gerar relatório"
      // na lista). Vai pra /app/whatsapp pra ver "Conectado · aguardando
      // primeiras mensagens" e acompanhar coleta em tempo real.
      navigate('/app/whatsapp');
    } catch (err) {
      if (err?.status === 409) {
        navigate(`/login?email=${encodeURIComponent(normalizedEmail)}`);
        return;
      }
      if (err?.status === 422) {
        const detail = err.body?.detail;
        if (Array.isArray(detail)) {
          const next = {};
          detail.forEach((item) => {
            const key = Array.isArray(item.loc) ? item.loc[1] : null;
            if (key && !next[key]) next[key] = item.msg || 'Valor inválido';
          });
          setFieldErrors(next);
        } else {
          setError('Falha ao criar conta. Tente novamente.');
        }
        return;
      }
      setError('Falha ao criar conta. Tente novamente.');
    } finally {
      setSubmitting(false);
    }
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

  const passwordInputStyle = (hasError) => ({
    ...inputStyle(hasError),
    paddingRight: 44,
  });

  const errorStyle = {
    color: '#E5604D',
    fontSize: 11.5,
    marginTop: 4,
    paddingLeft: 4,
  };

  const labelStyle = {
    display: 'block',
    fontSize: 10.5,
    color: 'rgba(250,246,240,0.65)',
    textTransform: 'uppercase',
    letterSpacing: '0.14em',
    fontWeight: 600,
    marginBottom: 6,
    paddingLeft: 4,
  };

  const buttonStyle = {
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
        {/* Step indicator */}
        <div className="flex items-center justify-center" style={{ gap: 8, marginBottom: 20 }}>
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: '50%',
              background: `linear-gradient(135deg, ${COLORS.orange}, ${COLORS.orangeDeep})`,
              color: COLORS.cream,
              fontSize: 12,
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            1
          </div>
          <div
            style={{
              width: 32,
              height: 2,
              background: step === 2 ? COLORS.orange : 'rgba(250,246,240,0.15)',
              borderRadius: 2,
              transition: 'background 0.3s ease',
            }}
          />
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: '50%',
              background: step === 2
                ? `linear-gradient(135deg, ${COLORS.orange}, ${COLORS.orangeDeep})`
                : 'rgba(250,246,240,0.08)',
              border: step === 2 ? 'none' : '1px solid rgba(250,246,240,0.15)',
              color: step === 2 ? COLORS.cream : 'rgba(250,246,240,0.4)',
              fontSize: 12,
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'all 0.3s ease',
            }}
          >
            2
          </div>
        </div>

        {/* Audio indicator */}
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

        {step === 1 && (
          <>
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

            <form onSubmit={handleNextStep} noValidate>
              {/* Nome */}
              <div style={{ marginBottom: 14 }}>
                <label htmlFor="lead-name" style={labelStyle}>Nome</label>
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
                    style={inputStyle(touched.name && !!step1Errors.name)}
                  />
                </div>
                {touched.name && step1Errors.name && <div style={errorStyle}>{step1Errors.name}</div>}
                {fieldErrors.name && <div style={errorStyle}>{fieldErrors.name}</div>}
              </div>

              {/* Email */}
              <div style={{ marginBottom: 14 }}>
                <label htmlFor="lead-email" style={labelStyle}>E-mail</label>
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
                    style={inputStyle(touched.email && !!step1Errors.email)}
                  />
                </div>
                {touched.email && step1Errors.email && <div style={errorStyle}>{step1Errors.email}</div>}
                {fieldErrors.email && <div style={errorStyle}>{fieldErrors.email}</div>}
              </div>

              {/* Telefone */}
              <div style={{ marginBottom: showTicketMedio ? 14 : 22 }}>
                <label htmlFor="lead-phone" style={labelStyle}>Telefone</label>
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
                    style={inputStyle(touched.phone && !!step1Errors.phone)}
                  />
                </div>
                {touched.phone && step1Errors.phone && <div style={errorStyle}>{step1Errors.phone}</div>}
                {fieldErrors.phone && <div style={errorStyle}>{fieldErrors.phone}</div>}
              </div>

              {/* Ticket Médio */}
              {showTicketMedio && (
                <div style={{ marginBottom: 22 }}>
                  <label htmlFor="lead-ticket" style={labelStyle}>Ticket médio</label>
                  <div style={{ position: 'relative' }}>
                    <FieldIcon Icon={DollarSign} />
                    <input
                      id="lead-ticket"
                      type="text"
                      value={ticketMedio}
                      onChange={(e) => setTicketMedio(maskCurrency(e.target.value))}
                      onBlur={() => setTouched((t) => ({ ...t, ticketMedio: true }))}
                      placeholder="R$ 0,00"
                      inputMode="numeric"
                      className="lead-input"
                      style={inputStyle(touched.ticketMedio && !!step1Errors.ticketMedio)}
                    />
                  </div>
                  {touched.ticketMedio && step1Errors.ticketMedio && <div style={errorStyle}>{step1Errors.ticketMedio}</div>}
                  {fieldErrors.ticket_medio && <div style={errorStyle}>{fieldErrors.ticket_medio}</div>}
                </div>
              )}

              <button
                type="submit"
                className="w-full inline-flex items-center justify-center transition-all"
                style={buttonStyle}
                onMouseEnter={(e) => {
                  e.currentTarget.style.transform = 'translateY(-2px)';
                  e.currentTarget.style.boxShadow = '0 14px 36px -8px rgba(255,107,53,0.65)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.transform = 'translateY(0)';
                  e.currentTarget.style.boxShadow = '0 10px 30px -8px rgba(255,107,53,0.5)';
                }}
              >
                Continuar
                <ArrowRight size={16} />
              </button>
            </form>
          </>
        )}

        {step === 2 && (
          <>
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
              Crie sua senha
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
              Escolha uma senha para acessar seus relatórios e configurações a qualquer momento.
            </p>

            {error && (
              <div
                style={{
                  padding: '10px 12px',
                  borderRadius: 10,
                  background: 'rgba(229,96,77,0.10)',
                  border: '1px solid rgba(229,96,77,0.35)',
                  color: '#E5604D',
                  fontSize: 13,
                  marginBottom: 14,
                }}
              >
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit} noValidate>
              {/* Senha */}
              <div style={{ marginBottom: 14 }}>
                <label htmlFor="lead-password" style={labelStyle}>Senha</label>
                <div style={{ position: 'relative' }}>
                  <FieldIcon Icon={Lock} />
                  <input
                    id="lead-password"
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    onBlur={() => setTouched((t) => ({ ...t, password: true }))}
                    placeholder="Mínimo 6 caracteres"
                    autoComplete="new-password"
                    className="lead-input"
                    style={passwordInputStyle(touched.password && !!step2Errors.password)}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    style={{
                      position: 'absolute',
                      right: 12,
                      top: '50%',
                      transform: 'translateY(-50%)',
                      background: 'none',
                      border: 'none',
                      color: 'rgba(250,246,240,0.4)',
                      cursor: 'pointer',
                      padding: 4,
                      display: 'flex',
                      alignItems: 'center',
                    }}
                  >
                    {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
                {touched.password && step2Errors.password && <div style={errorStyle}>{step2Errors.password}</div>}
                {fieldErrors.password && <div style={errorStyle}>{fieldErrors.password}</div>}
              </div>

              {/* Confirmar Senha */}
              <div style={{ marginBottom: 22 }}>
                <label htmlFor="lead-confirm-password" style={labelStyle}>Repetir senha</label>
                <div style={{ position: 'relative' }}>
                  <FieldIcon Icon={Lock} />
                  <input
                    id="lead-confirm-password"
                    type={showConfirmPassword ? 'text' : 'password'}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    onBlur={() => setTouched((t) => ({ ...t, confirmPassword: true }))}
                    placeholder="Repita a senha"
                    autoComplete="new-password"
                    className="lead-input"
                    style={passwordInputStyle(touched.confirmPassword && !!step2Errors.confirmPassword)}
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirmPassword((v) => !v)}
                    style={{
                      position: 'absolute',
                      right: 12,
                      top: '50%',
                      transform: 'translateY(-50%)',
                      background: 'none',
                      border: 'none',
                      color: 'rgba(250,246,240,0.4)',
                      cursor: 'pointer',
                      padding: 4,
                      display: 'flex',
                      alignItems: 'center',
                    }}
                  >
                    {showConfirmPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
                {touched.confirmPassword && step2Errors.confirmPassword && <div style={errorStyle}>{step2Errors.confirmPassword}</div>}
              </div>

              <div className="flex" style={{ gap: 10 }}>
                <button
                  type="button"
                  onClick={() => { setStep(1); setTouched({}); }}
                  className="inline-flex items-center justify-center transition-all"
                  style={{
                    gap: 6,
                    padding: 16,
                    borderRadius: 14,
                    border: '1px solid rgba(255,107,53,0.3)',
                    background: 'transparent',
                    color: COLORS.cream,
                    fontSize: 15,
                    fontWeight: 700,
                    cursor: 'pointer',
                    fontFamily: "'Red Hat Display', sans-serif",
                    flexShrink: 0,
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = 'rgba(255,107,53,0.08)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'transparent';
                  }}
                >
                  <ArrowLeft size={16} />
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="w-full inline-flex items-center justify-center transition-all"
                  style={buttonStyle}
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
                  {submitting ? 'Criando conta…' : 'Criar conta e ver relatório'}
                  {!submitting && <ArrowRight size={16} />}
                </button>
              </div>
            </form>
          </>
        )}

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
