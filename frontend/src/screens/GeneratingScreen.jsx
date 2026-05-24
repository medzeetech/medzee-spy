// F8-T24 — GeneratingScreen consumindo extension events + report polling.
//
// Antes (M1) essa tela era animação cosmética com timers fakes + áudio, rodando
// enquanto o backend extraía via uazapi webhook. Agora (F8/Wave 5) o `/spy` flow
// passa pela Chrome extension:
//   1. extensão emite `medzee:event` (batch_sent, collect_completed, etc) via window.postMessage
//   2. backend cria/atualiza row em /api/reports/latest conforme batches chegam
//   3. quando status === 'completed', dispara onDone(reportId)
//
// UI em duas fases:
//   - Coletando: mostra X/Y batches enviados + N msgs (extension-driven)
//   - IA analisando: após collect_completed OU quando report.status === 'generating'
//
// Erros da extensão (collect_failed, wa_needs_login, aborted, pairing_failed) são
// reportados via onError(event) se o parent quiser tratar; senão, inline error UI.

import { useEffect, useState } from 'react';
import { Loader2, MessageSquare, Sparkles } from 'lucide-react';

import { useReportPolling } from '../lib/reports';

/**
 * Tela "gerando relatório" — consome eventos da extensão + pola report status.
 *
 * Props:
 *   - onDone?: (reportId) => void     callback preferido (F8 contract).
 *   - onComplete?: () => void          callback legacy (M1 compat).
 *   - onError?: (event) => void        opcional; se ausente, mostra error UI inline.
 */
export default function GeneratingScreen({ onDone, onComplete, onError }) {
  const [collectProgress, setCollectProgress] = useState({
    batchesSent: 0,
    totalBatches: 0,
    messagesSent: 0,
  });
  // 'collecting' (default) | 'analyzing' (após collect_completed da extensão).
  // Em fallback, derivamos `analyzing` durante render se report.status já é generating.
  const [collectCompleted, setCollectCompleted] = useState(false);
  const [errorEvent, setErrorEvent] = useState(null);

  // Polling do report. useReportPolling já lida com 401/refresh, 404 transient,
  // timeout, visibility — não duplicamos isso aqui.
  const report = useReportPolling('latest');

  // --- subscribe direto em window.postMessage da extensão -----------------
  // Inline aqui (em vez de via useExtensionEvents) pra contornar a regra
  // react-hooks/set-state-in-effect: setState em callback de subscribe externo
  // é permitido; setState no body do effect (como ficaria com o hook) não é.
  useEffect(() => {
    function onMessage(event) {
      if (event.source !== window) return;
      const data = event.data;
      if (!data || typeof data !== 'object') return;
      if (data.type !== 'medzee:event') return;

      const ev = data.event;
      const payload = data.data ?? {};

      if (ev === 'batch_sent') {
        setCollectProgress((prev) => ({
          batchesSent: (payload.batch_index ?? prev.batchesSent - 1) + 1,
          totalBatches: payload.total_batches ?? prev.totalBatches,
          messagesSent: prev.messagesSent + (payload.received ?? 0),
        }));
      } else if (ev === 'collect_completed') {
        setCollectCompleted(true);
      } else if (
        ev === 'collect_failed' ||
        ev === 'wa_needs_login' ||
        ev === 'aborted' ||
        ev === 'pairing_failed' ||
        ev === 'extension_outdated'
      ) {
        setErrorEvent(ev);
        if (onError) onError(ev);
      }
    }

    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [onError]);

  // Stage derivado: se a extensão já confirmou conclusão OU se o report já está
  // sendo gerado/concluído, a coleta acabou — mostramos "IA analisando".
  const stage =
    collectCompleted ||
    report?.status === 'generating' ||
    report?.status === 'completed'
      ? 'analyzing'
      : 'collecting';

  // --- dispara onDone/onComplete quando o report completa -----------------
  useEffect(() => {
    if (report?.status !== 'completed') return;
    if (onDone) {
      onDone(report.reportId);
    } else if (onComplete) {
      onComplete();
    }
  }, [report?.status, report?.reportId, onDone, onComplete]);

  // --- error UI inline (fallback se onError não foi passado) --------------
  if (errorEvent) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-900 text-slate-100 p-6">
        <div className="w-full max-w-md bg-slate-800 rounded-2xl p-8 shadow-2xl text-center flex flex-col gap-4">
          <h1 className="text-xl font-semibold">Algo deu errado</h1>
          <p className="text-sm text-slate-400">
            {errorEvent === 'wa_needs_login' &&
              'Você precisa fazer login no WhatsApp Web antes da gente continuar.'}
            {errorEvent === 'aborted' &&
              'A coleta foi interrompida. Talvez a aba do WhatsApp Web tenha sido fechada.'}
            {errorEvent === 'collect_failed' &&
              'Não consegui ler suas conversas. Verifique se o WhatsApp Web está aberto.'}
            {errorEvent === 'pairing_failed' &&
              'Sua sessão com a extensão expirou. Recarregue a página pra parear de novo.'}
            {errorEvent === 'extension_outdated' &&
              'Sua versão da extensão está desatualizada. Atualize pela Chrome Web Store.'}
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="px-4 py-2 bg-amber-500 hover:bg-amber-400 text-slate-900 rounded-lg font-semibold transition-colors"
          >
            Tentar de novo
          </button>
        </div>
      </div>
    );
  }

  // --- main UI ------------------------------------------------------------
  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-900 text-slate-100 p-6">
      <div className="w-full max-w-md bg-slate-800 rounded-2xl p-8 shadow-2xl flex flex-col gap-6">
        <header className="text-center space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">
            {stage === 'collecting' ? 'Lendo seu WhatsApp…' : 'IA analisando…'}
          </h1>
          <p className="text-sm text-slate-400">
            {stage === 'collecting'
              ? 'Coletando os últimos 30 dias de conversas direto do seu navegador.'
              : 'Gerando seu diagnóstico comercial.'}
          </p>
        </header>

        <div className="space-y-3">
          <ProgressRow
            icon={<MessageSquare className="w-5 h-5" />}
            label="Coletando do WhatsApp"
            value={
              collectProgress.totalBatches > 0
                ? `${collectProgress.batchesSent}/${collectProgress.totalBatches} batches · ${collectProgress.messagesSent} msgs`
                : 'iniciando…'
            }
            done={stage !== 'collecting'}
            spinning={stage === 'collecting'}
          />
          <ProgressRow
            icon={<Sparkles className="w-5 h-5" />}
            label="IA analisando"
            value={
              stage === 'analyzing'
                ? report?.status === 'generating'
                  ? 'Claude processando seu funil…'
                  : report?.status === 'completed'
                    ? 'Pronto!'
                    : 'Iniciando…'
                : 'aguardando coleta…'
            }
            done={report?.status === 'completed'}
            spinning={stage === 'analyzing' && report?.status !== 'completed'}
          />
        </div>

        <p className="text-xs text-slate-500 text-center pt-2 border-t border-slate-700">
          Pode demorar até 90 segundos. Não feche esta aba.
        </p>
      </div>
    </div>
  );
}

function ProgressRow({ icon, label, value, done, spinning }) {
  return (
    <div className="flex items-center gap-3 bg-slate-900 rounded-lg p-3">
      <div className={done ? 'text-emerald-400' : 'text-amber-400'}>
        {spinning && !done ? <Loader2 className="w-5 h-5 animate-spin" /> : icon}
      </div>
      <div className="flex-1">
        <p className="text-sm font-medium">{label}</p>
        <p className="text-xs text-slate-400">{value}</p>
      </div>
      {done && <span className="text-xs text-emerald-400">✓</span>}
    </div>
  );
}
