// GeneratingScreen — tela "gerando relatório" durante o pipeline assíncrono.
//
// Após o PIVOT 2026-05-24 a extensão é desacoplada e não posta eventos no
// frontend; essa tela vive aqui pra suportar o flow legacy SpyFlow.jsx
// (QR → Generating → Lead) e qualquer caller que queira mostrar progresso
// enquanto `useReportPolling` aguarda o worker F3 finalizar.
//
// UI em duas fases derivadas do report.status:
//   - 'collecting' / inicial: spinner "Lendo seu WhatsApp…"
//   - 'analyzing' (report.status === 'generating' | 'completed'): "IA analisando…"

import { useEffect } from 'react';
import { Loader2, MessageSquare, Sparkles } from 'lucide-react';

import { useReportPolling } from '../lib/reports';

/**
 * Tela "gerando relatório" — pola report status até completar.
 *
 * Props:
 *   - onDone?: (reportId) => void     callback preferido.
 *   - onComplete?: () => void          callback legacy.
 */
export default function GeneratingScreen({ onDone, onComplete }) {
  // Polling do report. useReportPolling já lida com 401/refresh, 404 transient,
  // timeout, visibility — não duplicamos isso aqui.
  const report = useReportPolling('latest');

  // Stage derivado puramente do report status.
  const stage =
    report?.status === 'generating' || report?.status === 'completed'
      ? 'analyzing'
      : 'collecting';

  // Estado de erro derivado direto do report.status — sem useState/useEffect
  // (lint react-hooks/set-state-in-effect).
  const errorMessage =
    report?.status === 'failed'
      ? 'Não consegui gerar seu relatório. Tente de novo em alguns minutos.'
      : null;

  // --- dispara onDone/onComplete quando o report completa -----------------
  useEffect(() => {
    if (report?.status !== 'completed') return;
    if (onDone) {
      onDone(report.reportId);
    } else if (onComplete) {
      onComplete();
    }
  }, [report?.status, report?.reportId, onDone, onComplete]);

  // --- error UI inline ----------------------------------------------------
  if (errorMessage) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-900 text-slate-100 p-6">
        <div className="w-full max-w-md bg-slate-800 rounded-2xl p-8 shadow-2xl text-center flex flex-col gap-4">
          <h1 className="text-xl font-semibold">Algo deu errado</h1>
          <p className="text-sm text-slate-400">{errorMessage}</p>
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
            value={stage === 'collecting' ? 'iniciando…' : 'concluído'}
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
