// F8 — SpyFlowScreen state machine (PIVOT 2026-05-24).
//
// Orquestrador do `/spy` flow após o pivot login-based. A extensão é desacoplada
// do frontend (tem auth própria), então o /spy flow simplifica pra:
//
//   START → SIGNUP → INSTALL → (terminal: user clica "Pronto" → window.open /app/reports/latest)
//
// Estados removidos vs versão anterior: ANALYZE, GENERATING, WA_NEEDS_LOGIN,
// ABORTED. Essas responsabilidades migraram pra extensão (popup tem "Iniciar
// análise", trata WhatsApp Web sem login, etc.).
//
// Mobile guard inline: useIsMobile() === true → renderiza MobileBlockScreen.

import { useEffect, useState } from 'react';

import { supabase } from '../lib/supabase';
import { useIsMobile } from '../lib/device';
import { callApi } from '../lib/api';

import MobileBlockScreen from './MobileBlockScreen.jsx';
import ExtensionInstallScreen from './ExtensionInstallScreen.jsx';
import LeadFormScreen from './LeadFormScreen.jsx';

const STATES = {
  START: 'start',
  SIGNUP: 'signup',
  INSTALL: 'install',
};

export default function SpyFlowScreen() {
  const isMobile = useIsMobile();

  const [state, setState] = useState(STATES.START);
  const [email, setEmail] = useState(null);

  // ON MOUNT: decide initial state baseado em auth.
  // Se já logado (session Supabase válida E backend reconhece o user),
  // pula SIGNUP e vai pra INSTALL. Caso contrário (sessão zumbi de user
  // deletado, JWT expirado, etc.), limpa session e vai pra SIGNUP.
  useEffect(() => {
    if (state !== STATES.START) return;
    let cancelled = false;

    async function decide() {
      const { data } = await supabase.auth.getSession();
      if (cancelled) return;
      const session = data?.session;
      const localToken = session?.access_token;

      if (!localToken) {
        setState(STATES.SIGNUP);
        return;
      }

      // Valida que o user ainda existe no backend (cobre caso de auth.users
      // ter sido wiped enquanto o browser manteve session cacheada).
      try {
        const me = await callApi('/api/auth/me', { auth: true });
        if (cancelled) return;
        const realEmail = me?.email ?? session.user?.email ?? null;
        setEmail(realEmail);
        setState(STATES.INSTALL);
      } catch (err) {
        if (cancelled) return;
        // 401/404 → session zumbi. Limpa e força novo cadastro.
        // eslint-disable-next-line no-console
        console.warn('[spy] session inválida, limpando:', err?.status);
        try {
          await supabase.auth.signOut();
        } catch {
          // signOut pode falhar offline — segue mesmo assim.
        }
        setEmail(null);
        setState(STATES.SIGNUP);
      }
    }

    decide();
    return () => {
      cancelled = true;
    };
  }, [state]);

  // Mobile short-circuit — renderiza MobileBlockScreen e nada mais.
  if (isMobile) return <MobileBlockScreen />;

  switch (state) {
    case STATES.START:
      return <Centered>Carregando…</Centered>;

    case STATES.SIGNUP:
      return (
        <LeadFormScreen
          showTicketMedio
          onSignupComplete={({ email: signupEmail }) => {
            if (signupEmail) setEmail(signupEmail);
            setState(STATES.INSTALL);
          }}
        />
      );

    case STATES.INSTALL:
      return <ExtensionInstallScreen userEmail={email} step="Passo 2 de 2" />;

    default:
      return null;
  }
}

// --- inline sub-components (file-scoped) -----------------------------------

function Centered({ children }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-900 text-slate-100">
      {children}
    </div>
  );
}
