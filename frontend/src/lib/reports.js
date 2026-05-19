// F3 — Reports lib (REPORT-19, REPORT-19a, REPORT-21).
//
// Two surfaces:
//   - useReportPolling(idOrLatest)  → hook que faz polling em
//                                     /api/reports/{latest|id} enquanto
//                                     o status é transitório.
//   - listReports({ page, pageSize }) → lista paginada do user.
//
// Resiliência:
//   - 401 (sessão expirada) → tenta refresh do Supabase 1x; se falhar,
//     emite status='unauthorized' pra DetailPage redirecionar pra /login.
//   - 404 nas primeiras tentativas é tratado como transient (worker
//     pode não ter criado a row ainda). Após MAX_404_MS sem nada,
//     promove pra status='failed' pra UI mostrar fallback.
//   - Cap absoluto de MAX_TOTAL_MS de polling antes de desistir
//     com status='failed' (error='timeout_aguardando_relatorio').
//   - Page Visibility API: quando a aba fica oculta, pausa o polling
//     pro browser não throttle e re-disparar fora de ritmo. Resume
//     suavemente quando volta.

import { useEffect, useRef, useState } from 'react';
import { callApi } from './api';
import { supabase } from './supabase';

// 5s é suficiente pra UX (status transita raro: pending→generating→completed)
// e evita martelar o backend enquanto o worker corre (~30-120s típico).
const POLL_MS = 5000;
// Backend pode levar até ~7 min no free tier do uazapi (history sync atrasado
// + retry budget 220s + extract real). Damos 8 min de margem antes de desistir.
const MAX_TOTAL_MS = 8 * 60_000;
// 60s ainda é tolerância pro worker criar a row de reports. Em races típicas
// (signup chega antes do extract terminar) o row pode levar +30s pra surgir.
const MAX_404_MS = 60_000;
const TERMINAL = new Set(['completed', 'partial', 'failed', 'unauthorized']);

export function useReportPolling(idOrLatest = 'latest') {
  const [state, setState] = useState({
    status: 'pending',
    payload: null,
    error: null,
    elapsedMs: 0,
    reportId: null,
    createdAt: null,
  });

  const startRef = useRef(Date.now());
  const aliveRef = useRef(true);
  const refreshedRef = useRef(false);
  // Fix 2026-05-19: persiste startRef do report através de re-mounts.
  // Antes, sair da tela e voltar reiniciava elapsedMs em 0 mesmo com o
  // worker rodando há minutos — barra de progresso voltava a 0%.
  // Agora prioriza data.created_at como base; mount inicial vira fallback.
  const reportCreatedAtMsRef = useRef(null);

  useEffect(() => {
    aliveRef.current = true;
    startRef.current = Date.now();
    refreshedRef.current = false;
    reportCreatedAtMsRef.current = null;
    let timer;

    const path =
      idOrLatest === 'latest'
        ? '/api/reports/latest'
        : `/api/reports/${idOrLatest}`;

    const setSafe = (next) => {
      if (aliveRef.current) setState(next);
    };

    const schedule = (delay = POLL_MS) => {
      if (!aliveRef.current) return;
      timer = setTimeout(tick, delay);
    };

    async function tick() {
      if (!aliveRef.current) return;
      // Prefere created_at do report (preserva tempo real através de
      // re-mounts). Mount inicial usa startRef até primeiro fetch chegar.
      const baseMs = reportCreatedAtMsRef.current ?? startRef.current;
      const elapsed = Date.now() - baseMs;

      // Cap absoluto — não fica girando pra sempre.
      if (elapsed > MAX_TOTAL_MS) {
        setSafe((prev) => ({
          ...prev,
          status: 'failed',
          error: 'timeout_aguardando_relatorio',
          elapsedMs: elapsed,
        }));
        return;
      }

      // Se a aba está oculta, pausa o loop. Vai retomar via
      // visibilitychange handler.
      if (typeof document !== 'undefined' && document.hidden) {
        schedule(POLL_MS);
        return;
      }

      try {
        const data = await callApi(path, { auth: true });
        if (!aliveRef.current) return;
        // Caching do created_at no ref pra próximos ticks usarem a base
        // estável (resiste a re-mount da tela).
        if (data.created_at && reportCreatedAtMsRef.current === null) {
          const parsed = new Date(data.created_at).getTime();
          if (!Number.isNaN(parsed)) reportCreatedAtMsRef.current = parsed;
        }
        const baseMsFresh = reportCreatedAtMsRef.current ?? startRef.current;
        const elapsedFresh = Date.now() - baseMsFresh;
        setSafe({
          status: data.status,
          payload: data.payload,
          error: data.error_code ?? null,
          elapsedMs: elapsedFresh,
          reportId: data.id ?? null,
          createdAt: data.created_at ?? null,
        });
        if (!TERMINAL.has(data.status)) {
          schedule();
        }
      } catch (e) {
        if (!aliveRef.current) return;
        const httpStatus = e.status;

        // 401 — token expirou em background. Tenta refresh 1x.
        if (httpStatus === 401 && !refreshedRef.current) {
          refreshedRef.current = true;
          try {
            await supabase.auth.refreshSession();
            // Re-tenta imediatamente sem esperar o intervalo padrão.
            schedule(0);
            return;
          } catch {
            setSafe((prev) => ({
              ...prev,
              status: 'unauthorized',
              error: 'session_expired',
              elapsedMs: elapsed,
            }));
            return;
          }
        }
        if (httpStatus === 401) {
          // Já tentamos refresh nesta sessão de polling. Desiste.
          setSafe((prev) => ({
            ...prev,
            status: 'unauthorized',
            error: 'session_expired',
            elapsedMs: elapsed,
          }));
          return;
        }

        // 404 — worker ainda não criou a row. Aceita até MAX_404_MS.
        if (httpStatus === 404 && elapsed < MAX_404_MS) {
          setSafe((prev) => ({
            ...prev,
            status: 'pending',
            elapsedMs: elapsed,
          }));
          schedule();
          return;
        }
        if (httpStatus === 404) {
          // Passou da janela de tolerância — algo deu errado no worker.
          setSafe((prev) => ({
            ...prev,
            status: 'failed',
            error: 'report_not_created',
            elapsedMs: elapsed,
          }));
          return;
        }

        // Erro genérico de rede — não derruba o loop, só anota.
        setSafe((prev) => ({
          ...prev,
          error: e.detail || `http_${httpStatus ?? 'unknown'}`,
          elapsedMs: elapsed,
        }));
        schedule();
      }
    }

    // Resume the poll loop when the tab becomes visible again, so a long
    // hidden interval doesn't keep stale state visually.
    const onVisibility = () => {
      if (!aliveRef.current) return;
      if (!document.hidden) {
        if (timer) clearTimeout(timer);
        schedule(0);
      }
    };
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', onVisibility);
    }

    tick();

    return () => {
      aliveRef.current = false;
      if (timer) clearTimeout(timer);
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', onVisibility);
      }
    };
  }, [idOrLatest]);

  return state;
}

export async function listReports({ page = 1, pageSize = 20 } = {}) {
  return callApi(`/api/reports?page=${page}&page_size=${pageSize}`, {
    auth: true,
  });
}

export async function getReport(id) {
  return callApi(`/api/reports/${id}`, { auth: true });
}

/**
 * Trigger an on-demand report (F5 default: last-N msgs per chat).
 * Returns { report_id, status: 'generating' } on success.
 *
 * Aceita várias chamadas:
 *   generateReport()                       → mode=last_n_per_chat, n=30
 *   generateReport({ n_per_chat: 50 })     → custom N
 *   generateReport({ mode, n_per_chat, period_days }) → controle total
 *
 * F4 legacy compat: generateReport(30) (number) é interpretado como n_per_chat.
 *
 * Throws (via callApi) on:
 *   - 429 detail='too_many_generations_retry_in_Xs' → extrai X e mostra "Aguarde X seg"
 *   - other → erro genérico
 *
 * F5 removeu o 422 'not_enough_data' do backend — agora sempre dispara
 * e o relatório sempre existe (insufficient é estado válido, não erro).
 */
export async function generateReport(opts = {}) {
  const params = typeof opts === 'number' ? { n_per_chat: opts } : opts;
  const body = {
    mode: params.mode || 'last_n_per_chat',
    n_per_chat: params.n_per_chat ?? 30,
  };
  if (params.period_days) body.period_days = params.period_days;
  return callApi('/api/reports/generate', {
    method: 'POST',
    auth: true,
    body,
  });
}
