// F8-T19 — MobileBlockScreen (CHX-07, CHX-08).
//
// Fullscreen mostrada quando user acessa /spy (ou rotas dependentes da extensão)
// num dispositivo mobile. Bloqueia onboarding e captura email pra retargeting via
// POST /api/extension/mobile-lead.
//
// Nota: a decisão de renderizar essa tela é responsabilidade do parent
// (App.jsx / SpyFlowScreen.jsx via useIsMobile). Aqui só renderizamos o conteúdo.

import { useState } from 'react';
import { Smartphone, Monitor, Check, Copy } from 'lucide-react';

import { callApi } from '../lib/api.js';

// Hard-coded pra MVP — virar VITE_SPY_URL quando tivermos domínio definitivo.
const SPY_URL = 'https://medzee.com/spy';

function isValidEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

export default function MobileBlockScreen() {
  const [email, setEmail] = useState('');
  const [emailErr, setEmailErr] = useState('');
  const [submitState, setSubmitState] = useState('idle'); // idle | sending | done | error
  const [copyState, setCopyState] = useState('idle'); // idle | copied | failed

  async function handleSubmit(e) {
    e.preventDefault();
    if (!isValidEmail(email)) {
      setEmailErr('Email inválido');
      return;
    }
    setEmailErr('');
    setSubmitState('sending');
    try {
      await callApi('/api/extension/mobile-lead', {
        method: 'POST',
        body: {
          email,
          user_agent: typeof navigator !== 'undefined' ? navigator.userAgent : null,
          source_url: typeof window !== 'undefined' ? window.location.href : null,
        },
      });
      setSubmitState('done');
    } catch (err) {
      console.error('[mobile-lead] failed', err);
      setSubmitState('error');
    }
  }

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(SPY_URL);
      setCopyState('copied');
      setTimeout(() => setCopyState('idle'), 2000);
    } catch {
      setCopyState('failed');
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-900 text-slate-100 p-6">
      <div className="w-full max-w-md bg-slate-800 rounded-2xl p-8 shadow-2xl flex flex-col gap-6">
        <div className="flex items-center justify-center gap-3 text-4xl">
          <Smartphone className="w-10 h-10 text-amber-400" />
          <span className="text-slate-500">→</span>
          <Monitor className="w-10 h-10 text-emerald-400" />
        </div>

        <header className="text-center space-y-2">
          <h1 className="text-xl font-semibold tracking-tight">
            A análise do Medzee Spy roda só no Chrome desktop.
          </h1>
          <p className="text-sm text-slate-400">
            A extensão que lê seu WhatsApp Web não está disponível no celular.
          </p>
        </header>

        <section className="space-y-2">
          <p className="text-xs text-slate-400 uppercase tracking-wider">
            Abra este link no seu computador:
          </p>
          <div className="flex items-stretch gap-2">
            <code className="flex-1 bg-slate-900 rounded-lg px-3 py-2 text-sm text-amber-300 truncate">
              {SPY_URL}
            </code>
            <button
              type="button"
              onClick={handleCopy}
              className="px-3 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg text-sm font-medium flex items-center gap-1"
              aria-label="Copiar link"
            >
              {copyState === 'copied' ? (
                <Check className="w-4 h-4 text-emerald-400" />
              ) : (
                <Copy className="w-4 h-4" />
              )}
              {copyState === 'copied' ? 'Copiado' : 'Copiar'}
            </button>
          </div>
          {copyState === 'failed' && (
            <p className="text-xs text-rose-400">
              Não consegui copiar — selecione o link manualmente.
            </p>
          )}
        </section>

        <div className="flex items-center gap-3 text-xs text-slate-500">
          <span className="flex-1 h-px bg-slate-700" />
          <span>ou</span>
          <span className="flex-1 h-px bg-slate-700" />
        </div>

        {submitState === 'done' ? (
          <section className="bg-emerald-900/30 border border-emerald-700/50 rounded-lg p-4 text-center">
            <Check className="w-8 h-8 text-emerald-400 mx-auto mb-2" />
            <p className="text-sm">
              Anotamos! Volte aqui quando estiver no desktop —
              <br />
              a análise vai estar pronta pra rodar.
            </p>
          </section>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-2">
            <label htmlFor="mobile-lead-email" className="text-xs text-slate-400 uppercase tracking-wider block">
              Avise-me quando estiver no desktop:
            </label>
            <div className="flex items-stretch gap-2">
              <input
                id="mobile-lead-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="seu@email.com.br"
                className="flex-1 bg-slate-900 rounded-lg px-3 py-2 text-sm placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-amber-400"
                disabled={submitState === 'sending'}
                required
              />
              <button
                type="submit"
                className="px-4 py-2 bg-amber-500 hover:bg-amber-400 text-slate-900 rounded-lg text-sm font-semibold disabled:opacity-50"
                disabled={submitState === 'sending'}
              >
                {submitState === 'sending' ? 'Enviando…' : 'Enviar'}
              </button>
            </div>
            {emailErr && <p className="text-xs text-rose-400">{emailErr}</p>}
            {submitState === 'error' && (
              <p className="text-xs text-rose-400">
                Algo deu errado. Tente de novo ou copie o link acima.
              </p>
            )}
          </form>
        )}

        <footer className="text-xs text-slate-500 text-center pt-2 border-t border-slate-700">
          Medzee Spy · diagnóstico comercial do WhatsApp
        </footer>
      </div>
    </div>
  );
}
