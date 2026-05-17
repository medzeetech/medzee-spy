import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { LogIn, Mail, Lock, Eye, EyeOff, ArrowRight } from 'lucide-react';
import { COLORS } from '../constants/colors.js';
import Logo from '../components/Logo.jsx';
import { api } from '../lib/api.js';
import { supabase } from '../lib/supabase.js';

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

function CornerBracket({ position }) {
  const isTop = position.startsWith('top');
  const isLeft = position.endsWith('left');
  return (
    <div
      aria-hidden
      style={{
        position: 'absolute',
        width: 18,
        height: 18,
        [isTop ? 'top' : 'bottom']: 10,
        [isLeft ? 'left' : 'right']: 10,
        borderTop: isTop ? `2px solid ${COLORS.orange}` : 'none',
        borderBottom: !isTop ? `2px solid ${COLORS.orange}` : 'none',
        borderLeft: isLeft ? `2px solid ${COLORS.orange}` : 'none',
        borderRight: !isLeft ? `2px solid ${COLORS.orange}` : 'none',
        opacity: 0.55,
        borderTopLeftRadius: isTop && isLeft ? 6 : 0,
        borderTopRightRadius: isTop && !isLeft ? 6 : 0,
        borderBottomLeftRadius: !isTop && isLeft ? 6 : 0,
        borderBottomRightRadius: !isTop && !isLeft ? 6 : 0,
        pointerEvents: 'none',
      }}
      className="anim-pulse-dot"
    />
  );
}

export default function LoginScreen() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const prefillEmail = searchParams.get('email') || '';

  const [email, setEmail] = useState(prefillEmail);
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [status, setStatus] = useState('idle'); // 'idle' | 'submitting' | 'error'
  const [error, setError] = useState(null);

  useEffect(() => {
    if (prefillEmail) setEmail(prefillEmail);
  }, [prefillEmail]);

  const submitting = status === 'submitting';

  const emailValid = email.includes('@');
  const passwordValid = password.length >= 1;
  const canSubmit = emailValid && passwordValid && !submitting;

  const messageForStatus = (s) => {
    if (s === 401) return 'Email ou senha incorretos.';
    if (s === 403) return 'Sua conta ainda não tem acesso ao Spy. Faça o diagnóstico em /spy.';
    return 'Não foi possível entrar. Tente novamente em instantes.';
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!canSubmit) return;
    setStatus('submitting');
    setError(null);
    try {
      const normalizedEmail = email.trim().toLowerCase();
      const { session } = await api.login({ email: normalizedEmail, password });
      await supabase.auth.setSession({
        access_token: session.access_token,
        refresh_token: session.refresh_token,
      });
      navigate('/app/reports');
    } catch (err) {
      setError(messageForStatus(err?.status));
      setStatus('error');
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
      <div style={{ marginBottom: 32 }}>
        <Logo size="md" tone="dark" />
      </div>

      <div
        className="anim-fadeup"
        style={{
          position: 'relative',
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
        <CornerBracket position="top-left" />
        <CornerBracket position="top-right" />
        <CornerBracket position="bottom-left" />
        <CornerBracket position="bottom-right" />

        <div
          className="inline-flex items-center"
          style={{
            gap: 8,
            padding: '6px 12px',
            borderRadius: 99,
            background: 'rgba(255,107,53,0.12)',
            border: '1px solid rgba(255,107,53,0.3)',
            color: COLORS.orange,
            fontSize: 11.5,
            fontWeight: 600,
            letterSpacing: '0.04em',
            marginBottom: 18,
          }}
        >
          <LogIn size={13} />
          Acesso ao Spy
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
          Entrar na sua conta
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
          Acesse seus relatórios e configurações do Spy.
        </p>

        <form onSubmit={handleSubmit} noValidate>
          {/* Email */}
          <div style={{ marginBottom: 14 }}>
            <label htmlFor="login-email" style={labelStyle}>E-mail</label>
            <div style={{ position: 'relative' }}>
              <FieldIcon Icon={Mail} />
              <input
                id="login-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="seu@email.com.br"
                autoComplete="email"
                className="lead-input"
                style={inputStyle(false)}
              />
            </div>
          </div>

          {/* Senha */}
          <div style={{ marginBottom: 18 }}>
            <label htmlFor="login-password" style={labelStyle}>Senha</label>
            <div style={{ position: 'relative' }}>
              <FieldIcon Icon={Lock} />
              <input
                id="login-password"
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Sua senha"
                autoComplete="current-password"
                className="lead-input"
                style={passwordInputStyle(false)}
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
          </div>

          {error && (
            <div
              role="alert"
              style={{
                marginBottom: 16,
                padding: '10px 12px',
                borderRadius: 10,
                background: 'rgba(229,96,77,0.08)',
                border: '1px solid rgba(229,96,77,0.35)',
                color: '#E5604D',
                fontSize: 13,
                lineHeight: 1.4,
              }}
            >
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={!canSubmit}
            className="w-full inline-flex items-center justify-center transition-all"
            style={{
              ...buttonStyle,
              opacity: canSubmit ? 1 : 0.7,
              cursor: canSubmit ? 'pointer' : 'not-allowed',
            }}
            onMouseEnter={(e) => {
              if (!canSubmit) return;
              e.currentTarget.style.transform = 'translateY(-2px)';
              e.currentTarget.style.boxShadow = '0 14px 36px -8px rgba(255,107,53,0.65)';
            }}
            onMouseLeave={(e) => {
              if (!canSubmit) return;
              e.currentTarget.style.transform = 'translateY(0)';
              e.currentTarget.style.boxShadow = '0 10px 30px -8px rgba(255,107,53,0.5)';
            }}
          >
            {submitting ? 'Entrando…' : 'Entrar'}
            {!submitting && <ArrowRight size={16} />}
          </button>
        </form>

        <div
          className="flex items-center justify-between"
          style={{
            gap: 12,
            marginTop: 18,
            fontSize: 12,
            color: 'rgba(250,246,240,0.55)',
          }}
        >
          <a
            href="#"
            onClick={(e) => { e.preventDefault(); alert('Em breve'); }}
            style={{
              color: 'rgba(250,246,240,0.55)',
              textDecoration: 'none',
              borderBottom: '1px dashed rgba(250,246,240,0.25)',
              paddingBottom: 1,
            }}
          >
            Esqueci minha senha
          </a>
          <Link
            to="/spy"
            style={{
              color: COLORS.orange,
              textDecoration: 'none',
              fontWeight: 600,
            }}
          >
            Quero gerar um relatório
          </Link>
        </div>

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
