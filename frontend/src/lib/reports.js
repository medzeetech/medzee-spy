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

const POLL_MS = 2000;
const MAX_TOTAL_MS = 4 * 60_000;      // 4 min: cap absoluto antes de desistir
const MAX_404_MS = 20_000;            // 20s: ainda esperando worker criar a row
const TERMINAL = new Set(['completed', 'partial', 'failed', 'unauthorized']);

export function useReportPolling(idOrLatest = 'latest') {
  const [state, setState] = useState({
    status: 'pending',
    payload: null,
    error: null,
    elapsedMs: 0,
    reportId: null,
  });

  const startRef = useRef(Date.now());
  const aliveRef = useRef(true);
  const refreshedRef = useRef(false);

  useEffect(() => {
    aliveRef.current = true;
    startRef.current = Date.now();
    refreshedRef.current = false;
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
      const elapsed = Date.now() - startRef.current;

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
        setSafe({
          status: data.status,
          payload: data.payload,
          error: data.error_code ?? null,
          elapsedMs: elapsed,
          reportId: data.id ?? null,
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
