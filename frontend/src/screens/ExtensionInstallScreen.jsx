// F8-T20 — ExtensionInstallScreen (CHX-03, CHX-09).
//
// Tela mostrada após o signup pra instruir o user a instalar a extensão do Chrome.
// Faz polling a cada 1s pra detectar a extensão (via `useExtensionDetected`); quando
// detecta `installed:true && paired:true`, dispara `onPaired()` exatamente uma vez.
//
// Decisão: o pareamento automático rola pelo lado da extensão — o probe content-script
// (T12) lê `localStorage['medzee_spy:pairing_token']` e dispara o pair flow. Aqui só
// garantimos que o token está injetado e ficamos polling até o probe responder paired.

import { useEffect, useRef, useState } from 'react';
import { Puzzle, Loader2, Check } from 'lucide-react';

import { useExtensionDetected, injectPairingToken } from '../lib/extension';

// Placeholder até T27 (Web Store submission) trazer o ID real.
const CHROME_STORE_URL = 'https://chrome.google.com/webstore/detail/medzee-spy/PENDING_ID';

/**
 * Tela "Instale a extensão". Pola a cada 1s via `useExtensionDetected` até detectar
 * a extensão pareada, então chama `onPaired()` (uma vez).
 *
 * Props:
 *   - pairingToken: string — emitido pelo signup; injetado em localStorage/window
 *     pra que o probe content-script faça auto-pair.
 *   - onPaired: () => void — callback disparado uma vez quando pareamento confirmado.
 *   - step?: string — texto opcional do header (default "Passo 2 de 3").
 */
export default function ExtensionInstallScreen({ pairingToken, onPaired, step = 'Passo 2 de 3' }) {
  // Injeta o token uma vez — o probe content-script (T12) lê e auto-pareia.
  useEffect(() => {
    if (pairingToken) {
      injectPairingToken(pairingToken);
    }
  }, [pairingToken]);

  // Tick incrementa a cada 1s; é usado como `key` do <ExtensionProbe/> abaixo, o que
  // remonta o componente e força `useExtensionDetected` a probar de novo. Truque
  // necessário porque o hook só dispara seu effect na montagem (deps=[timeoutMs]).
  const [pollTick, setPollTick] = useState(0);
  useEffect(() => {
    const interval = setInterval(() => setPollTick((t) => t + 1), 1000);
    return () => clearInterval(interval);
  }, []);

  // Guard via ref pra garantir que `onPaired` é chamado exatamente uma vez (sem
  // cascading render — usar state aqui dispararia warning react-hooks/set-state-in-effect).
  const firedRef = useRef(false);
  const [probe, setProbe] = useState(null);
  const done = !!(probe && probe.installed && probe.paired);

  function handleProbeResult(result) {
    setProbe(result);
    if (firedRef.current) return;
    if (result && result.installed && result.paired) {
      firedRef.current = true;
      onPaired?.();
    }
  }

  let statusBlock;
  if (done) {
    statusBlock = (
      <p className="text-sm text-emerald-400 flex items-center justify-center gap-2">
        <Check className="w-4 h-4" /> Extensão conectada! Indo pra próxima tela…
      </p>
    );
  } else if (probe === null) {
    statusBlock = <Spinner label="Detectando extensão…" />;
  } else if (!probe.installed) {
    statusBlock = <Spinner label="Aguardando instalação…" />;
  } else if (!probe.paired) {
    statusBlock = <Spinner label="Extensão detectada, pareando…" />;
  } else {
    // installed && paired — guard acima dispara onPaired no próximo tick.
    statusBlock = <Spinner label="Conectando…" />;
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-900 text-slate-100 p-6">
      <div className="w-full max-w-md bg-slate-800 rounded-2xl p-8 shadow-2xl flex flex-col gap-6">
        <header className="space-y-2">
          <p className="text-xs uppercase tracking-wider text-amber-400">{step}</p>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-3">
            <Puzzle className="w-7 h-7 text-amber-400" />
            Instale a extensão
          </h1>
          <p className="text-sm text-slate-400">
            Pra ler seu WhatsApp Web sem QR code, instale a extensão do Chrome.
            É gratuita, leva 30 segundos.
          </p>
        </header>

        <a
          href={CHROME_STORE_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="block w-full text-center px-4 py-3 bg-amber-500 hover:bg-amber-400 text-slate-900 rounded-lg font-semibold transition-colors"
        >
          ▶ Instalar do Chrome Web Store
        </a>

        <div className="bg-slate-900/60 rounded-lg p-3 text-center">{statusBlock}</div>

        {/* Probe remontado a cada tick — força `useExtensionDetected` a re-rodar. */}
        <ExtensionProbe key={pollTick} onResult={handleProbeResult} />

        <details className="text-xs text-slate-500">
          <summary className="cursor-pointer hover:text-slate-300">Modo desenvolvedor</summary>
          <p className="mt-2 leading-relaxed">
            Em modo dev: abra{' '}
            <code className="bg-slate-700 px-1.5 py-0.5 rounded">chrome://extensions</code>,
            ative &quot;Developer mode&quot;, clique em &quot;Load unpacked&quot; e selecione a pasta{' '}
            <code className="bg-slate-700 px-1.5 py-0.5 rounded">./extension/dist/</code>.
          </p>
        </details>

        <footer className="text-xs text-slate-500 text-center pt-2 border-t border-slate-700">
          Medzee Spy · diagnóstico comercial do WhatsApp
        </footer>
      </div>
    </div>
  );
}

function Spinner({ label }) {
  return (
    <p className="text-sm text-slate-400 flex items-center justify-center gap-2">
      <Loader2 className="w-4 h-4 animate-spin" /> {label}
    </p>
  );
}

/**
 * Wrapper que chama `useExtensionDetected` e reporta o resultado pro parent.
 * Remontado a cada tick via prop `key`, o que reinicializa o hook (effect re-roda
 * com timeoutMs=500). Mantém o hook em isolado pra que o `key` trick só re-rode o
 * probe — não a tela inteira.
 */
function ExtensionProbe({ onResult }) {
  const result = useExtensionDetected(500);
  useEffect(() => {
    onResult(result);
  }, [result, onResult]);
  return null;
}
