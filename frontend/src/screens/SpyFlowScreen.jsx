// F8-T21 — SpyFlowScreen state machine (inverted flow: signup → install → analyze → generating).
//
// Orquestrador do `/spy` flow conforme design §4.8. Antes (M1), o `/spy` montava
// QRScreen → GeneratingScreen → LeadFormScreen (extract via uazapi webhook). Agora
// invertemos: o user assina primeiro, instala a extensão, e só depois roda a coleta
// — porque a Chrome Extension (D11) faz ingest direto, sem QR.
//
// Estados:
//   START          → decide initial state baseado em auth + probe da extensão
//   SIGNUP         → renderiza LeadFormScreen (T23 vai injetar pairing_token pós-signup)
//   INSTALL        → renderiza ExtensionInstallScreen (polling probe)
//   ANALYZE        → CTA "Analisar meu WhatsApp" dispara start_collection
//   GENERATING     → GeneratingScreen (T24 vai consumir extension events reais)
//   WA_NEEDS_LOGIN → ext detectou WhatsApp Web sem login (QR não escaneado)
//   ABORTED        → user fechou a aba do WhatsApp Web no meio da coleta
//   DONE           → redirect /app/reports/:id
//
// Mobile guard inline: useIsMobile() === true → renderiza MobileBlockScreen
// e short-circuita o resto. Router (T22) só faz wiring de path; a decisão fica aqui
// pra não renderizar nada antes da detecção.
//
// Dependências dos contratos:
//   - LeadFormScreen.onSignupComplete({extension_pairing_token, user_id}) — virá em T23.
//   - GeneratingScreen.onDone(reportId) — virá em T24. Por enquanto fallback "latest".

import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { supabase } from '../lib/supabase';
import { useIsMobile } from '../lib/device';
import {
  useExtensionDetected,
  useExtensionEvents,
  sendToExtension,
  injectPairingToken,
  requestNewPairingToken,
} from '../lib/extension';

import MobileBlockScreen from './MobileBlockScreen.jsx';
import ExtensionInstallScreen from './ExtensionInstallScreen.jsx';
import LeadFormScreen from './LeadFormScreen.jsx';
import GeneratingScreen from './GeneratingScreen.jsx';

const STATES = {
  START: 'start',
  SIGNUP: 'signup',
  INSTALL: 'install',
  ANALYZE: 'analyze',
  GENERATING: 'generating',
  WA_NEEDS_LOGIN: 'wa_needs_login',
  ABORTED: 'aborted',
  DONE: 'done',
};

/**
 * Mapeia eventos da extensão pra próximo estado da máquina.
 * Retorna null se o evento não tem transição associada (ex: collect_started,
 * collect_progress — esses são consumidos por GeneratingScreen via useExtensionEvents).
 */
function mapEventToState(eventName) {
  switch (eventName) {
    case 'wa_needs_login':
      return STATES.WA_NEEDS_LOGIN;
    case 'aborted':
      return STATES.ABORTED;
    case 'pairing_failed':
      // refresh_token expirou no service worker — volta pra INSTALL.
      // (T23 vai garantir que LeadForm re-emite token antes; aqui o caminho é
      // re-tentar via probe + auto-pair com novo token.)
      return STATES.INSTALL;
    case 'collect_completed':
      // Final batch enviado — GeneratingScreen (T24) detecta via report polling
      // e dispara onDone. Não fazemos transição aqui.
      return null;
    default:
      // collect_started, collect_progress, extension_outdated, etc — não tratados aqui.
      return null;
  }
}

export default function SpyFlowScreen() {
  const isMobile = useIsMobile();
  const navigate = useNavigate();

  const [state, setState] = useState(STATES.START);
  const [pairingToken, setPairingToken] = useState(null);
  // userId tracked pra debugging/futuras transições (não usado direto no render).
  const [, setUserId] = useState(null);

  const probe = useExtensionDetected(500);
  const lastEvent = useExtensionEvents();

  // ON MOUNT: decide initial state baseado em auth + probe.
  // Roda até resolver pra um estado != START. Espera probe settle.
  useEffect(() => {
    if (state !== STATES.START) return;
    if (probe === null) return; // probe ainda detectando — aguarda.

    let cancelled = false;

    async function decide() {
      // Auth check via Supabase session (lib/api.js usa esse mesmo path pra Authorization).
      const { data } = await supabase.auth.getSession();
      if (cancelled) return;
      const loggedIn = !!data?.session?.access_token;

      if (!loggedIn) {
        setState(STATES.SIGNUP);
        return;
      }

      // User logado — decide entre INSTALL e ANALYZE pela probe.
      if (probe.installed && probe.paired) {
        setState(STATES.ANALYZE);
        return;
      }
      if (probe.installed && !probe.paired) {
        // Extensão instalada mas não pareada (ex: usuário retornou após signup antigo).
        // Re-emite pairing_token via backend e vai pra INSTALL.
        try {
          const token = await requestNewPairingToken();
          if (cancelled) return;
          injectPairingToken(token);
          setPairingToken(token);
          setState(STATES.INSTALL);
        } catch (err) {
          if (cancelled) return;
          // 401 ou rede caída — força re-login via signup (que vai re-emitir token).
          console.warn('[SpyFlow] requestNewPairingToken failed; fallback SIGNUP', err);
          setState(STATES.SIGNUP);
        }
        return;
      }
      // Logado mas extensão não instalada — vai pra INSTALL (sem token novo aqui;
      // user já tem session, mas precisa de token novo pra pair. Pede um.).
      try {
        const token = await requestNewPairingToken();
        if (cancelled) return;
        injectPairingToken(token);
        setPairingToken(token);
        setState(STATES.INSTALL);
      } catch (err) {
        if (cancelled) return;
        console.warn('[SpyFlow] requestNewPairingToken failed (not installed branch)', err);
        setState(STATES.SIGNUP);
      }
    }

    decide();
    return () => {
      cancelled = true;
    };
  }, [state, probe]);

  // Listen pra extension lifecycle events (CHX-09, CHX-10).
  // Usa ref pra trackear último event processado e despacha a transição via
  // queueMicrotask — evita `react-hooks/set-state-in-effect` (cascading render).
  const lastHandledEventRef = useRef(null);
  useEffect(() => {
    if (!lastEvent) return;
    if (lastHandledEventRef.current === lastEvent) return;
    lastHandledEventRef.current = lastEvent;

    const nextState = mapEventToState(lastEvent.event);
    if (!nextState) return;

    // queueMicrotask defere o setState pra fora do effect body — lint-safe.
    queueMicrotask(() => setState(nextState));
  }, [lastEvent]);

  // Mobile short-circuit — renderiza MobileBlockScreen e nada mais.
  if (isMobile) return <MobileBlockScreen />;

  switch (state) {
    case STATES.START:
      return <Centered>Carregando…</Centered>;

    case STATES.SIGNUP:
      return (
        <LeadFormScreen
          showTicketMedio
          onSignupComplete={({ extension_pairing_token, user_id }) => {
            // T23 vai garantir que LeadFormScreen passe esses campos.
            // Antes de T23 esse callback nunca dispara — LeadForm hoje só faz navigate.
            if (extension_pairing_token) {
              injectPairingToken(extension_pairing_token);
              setPairingToken(extension_pairing_token);
            }
            if (user_id) setUserId(user_id);
            setState(STATES.INSTALL);
          }}
        />
      );

    case STATES.INSTALL:
      return (
        <ExtensionInstallScreen
          pairingToken={pairingToken}
          onPaired={() => setState(STATES.ANALYZE)}
        />
      );

    case STATES.ANALYZE:
      return (
        <AnalyzeCta
          onStart={async () => {
            await sendToExtension('start_collection');
            setState(STATES.GENERATING);
          }}
        />
      );

    case STATES.GENERATING:
      return (
        <GeneratingScreen
          onDone={(reportId) => {
            // T24 vai passar reportId real; fallback "latest" enquanto isso.
            navigate(`/app/reports/${reportId ?? 'latest'}`);
            setState(STATES.DONE);
          }}
          // GeneratingScreen atual usa onComplete; T24 vai unificar pra onDone.
          // Passar ambos pra cobrir contrato antigo e novo.
          onComplete={() => {
            navigate('/app/reports/latest');
            setState(STATES.DONE);
          }}
        />
      );

    case STATES.WA_NEEDS_LOGIN:
      return <WaNeedsLogin onRetry={() => setState(STATES.ANALYZE)} />;

    case STATES.ABORTED:
      return <Aborted onRetry={() => setState(STATES.ANALYZE)} />;

    case STATES.DONE:
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

function AnalyzeCta({ onStart }) {
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  async function handleClick() {
    setLoading(true);
    setErr(null);
    try {
      await onStart();
    } catch (e) {
      console.error('[SpyFlow] start_collection failed', e);
      setErr('Não consegui falar com a extensão. Recarregue a página e tente de novo.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-900 text-slate-100 p-6">
      <div className="w-full max-w-md bg-slate-800 rounded-2xl p-8 shadow-2xl flex flex-col gap-6 text-center">
        <p className="text-xs uppercase tracking-wider text-amber-400">Passo 3 de 3</p>
        <h1 className="text-2xl font-semibold tracking-tight">
          Tudo pronto. Vamos analisar?
        </h1>
        <p className="text-sm text-slate-400">
          Vamos abrir o WhatsApp Web e ler os últimos 30 dias de conversas.
          O processamento leva cerca de 60 segundos.
        </p>
        <button
          type="button"
          onClick={handleClick}
          disabled={loading}
          className="px-6 py-3 bg-amber-500 hover:bg-amber-400 text-slate-900 rounded-lg font-semibold disabled:opacity-50 transition-colors"
        >
          {loading ? 'Iniciando…' : 'Analisar meu WhatsApp'}
        </button>
        {err && <p className="text-xs text-rose-400">{err}</p>}
        <footer className="text-xs text-slate-500 pt-2 border-t border-slate-700">
          Medzee Spy · diagnóstico comercial do WhatsApp
        </footer>
      </div>
    </div>
  );
}

function WaNeedsLogin({ onRetry }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-900 text-slate-100 p-6">
      <div className="w-full max-w-md bg-slate-800 rounded-2xl p-8 shadow-2xl flex flex-col gap-6 text-center">
        <h1 className="text-xl font-semibold tracking-tight">
          Logue no WhatsApp Web primeiro
        </h1>
        <p className="text-sm text-slate-400">
          Abra{' '}
          <a
            href="https://web.whatsapp.com/"
            target="_blank"
            rel="noopener noreferrer"
            className="text-amber-400 underline"
          >
            web.whatsapp.com
          </a>{' '}
          em uma aba, escaneie o QR code com seu celular, depois volte aqui.
        </p>
        <button
          type="button"
          onClick={onRetry}
          className="px-6 py-3 bg-amber-500 hover:bg-amber-400 text-slate-900 rounded-lg font-semibold transition-colors"
        >
          Já loguei, tentar de novo
        </button>
        <footer className="text-xs text-slate-500 pt-2 border-t border-slate-700">
          Medzee Spy · diagnóstico comercial do WhatsApp
        </footer>
      </div>
    </div>
  );
}

function Aborted({ onRetry }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-900 text-slate-100 p-6">
      <div className="w-full max-w-md bg-slate-800 rounded-2xl p-8 shadow-2xl flex flex-col gap-6 text-center">
        <h1 className="text-xl font-semibold tracking-tight">
          Coleta interrompida
        </h1>
        <p className="text-sm text-slate-400">
          A aba do WhatsApp Web foi fechada antes de terminarmos. Sem problemas,
          é só recomeçar.
        </p>
        <button
          type="button"
          onClick={onRetry}
          className="px-6 py-3 bg-amber-500 hover:bg-amber-400 text-slate-900 rounded-lg font-semibold transition-colors"
        >
          Tentar de novo
        </button>
        <footer className="text-xs text-slate-500 pt-2 border-t border-slate-700">
          Medzee Spy · diagnóstico comercial do WhatsApp
        </footer>
      </div>
    </div>
  );
}
