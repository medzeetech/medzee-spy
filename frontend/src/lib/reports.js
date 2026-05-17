// F3 — Reports lib (REPORT-19, REPORT-19a, REPORT-21).
//
// Two surfaces:
//   - useReportPolling(idOrLatest)  → hook that fetches /api/reports/{latest|id}
//                                     every 2s while status is transitional.
//   - listReports({ page, pageSize }) → paginated list of the user's reports.
//
// The hook returns { status, payload, error, elapsedMs } and stops polling
// once status hits a terminal state. Recovers from transient fetch failures
// without dropping the polling loop.

import { useEffect, useRef, useState } from 'react';
import { callApi } from './api';

const POLL_MS = 2000;
const TERMINAL = new Set(['completed', 'partial', 'failed']);

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

  useEffect(() => {
    aliveRef.current = true;
    startRef.current = Date.now();
    let timer;

    const path =
      idOrLatest === 'latest'
        ? '/api/reports/latest'
        : `/api/reports/${idOrLatest}`;

    async function tick() {
      try {
        const data = await callApi(path, { auth: true });
        if (!aliveRef.current) return;
        setState({
          status: data.status,
          payload: data.payload,
          error: data.error_code ?? null,
          elapsedMs: Date.now() - startRef.current,
          reportId: data.id ?? null,
        });
        if (!TERMINAL.has(data.status)) {
          timer = setTimeout(tick, POLL_MS);
        }
      } catch (e) {
        if (!aliveRef.current) return;
        // 404 (no report yet) is a transient state right after signup —
        // keep polling. Other errors also keep polling so a network blip
        // doesn't drop the loop.
        setState((prev) => ({
          ...prev,
          error: e.detail || e.status || 'fetch_failed',
          elapsedMs: Date.now() - startRef.current,
        }));
        timer = setTimeout(tick, POLL_MS);
      }
    }

    tick();

    return () => {
      aliveRef.current = false;
      if (timer) clearTimeout(timer);
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
