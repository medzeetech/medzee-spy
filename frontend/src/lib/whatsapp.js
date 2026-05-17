// WhatsApp status lib.
//
// Polling explicitamente conservador pra não martelar o backend / uazapi:
//
// * useWhatsappStatus()       — /api/whatsapp/status         a cada 30s
// * useUazapiStats({enabled}) — /api/whatsapp/uazapi-stats   a cada 60s
//
// Razão pros valores serem altos:
//   - O endpoint /uazapi-stats proxia /chat/find no provider (gasta quota).
//   - O endpoint /status faz 2 queries em Supabase a cada hit.
//   - Múltiplas abas abertas multiplicam o tráfego (cada aba ≡ um cliente).
//   - A página não precisa refletir contagem em tempo real; o webhook é o
//     canal "live" e o polling só serve pra refletir o snapshot quando o
//     usuário olha a aba.
//
// Pausa quando a aba não está visível (document.hidden === true) — economiza
// requests enquanto o usuário está em outra aba/app. Retoma com 1 tick imediato
// no visibilitychange.
//
// disconnectWhatsapp(sessionId): DELETE /api/whatsapp/sessions/:id.

import { useEffect, useRef, useState } from 'react';
import { callApi } from './api';

const STATUS_POLL_MS = 30_000;
const UAZAPI_POLL_MS = 60_000;

function createPollingHook({ url, intervalMs, dataKey, includeLoading = true }) {
  return function useResource({ enabled = true } = {}) {
    const [state, setState] = useState({
      loading: includeLoading && enabled,
      [dataKey]: null,
      error: null,
    });
    const aliveRef = useRef(true);

    useEffect(() => {
      aliveRef.current = true;
      if (!enabled) {
        setState({ loading: false, [dataKey]: null, error: null });
        return () => {
          aliveRef.current = false;
        };
      }

      let timer;

      const tick = async () => {
        if (typeof document !== 'undefined' && document.hidden) {
          // Pausa enquanto a aba está oculta — retoma via visibilitychange.
          return;
        }
        try {
          const data = await callApi(url, { auth: true });
          if (!aliveRef.current) return;
          setState({ loading: false, [dataKey]: data, error: null });
        } catch (e) {
          if (!aliveRef.current) return;
          setState((prev) => ({
            ...prev,
            loading: false,
            error: e.detail || `http_${e.status ?? 'unknown'}`,
          }));
        }
        if (aliveRef.current) timer = setTimeout(tick, intervalMs);
      };

      const handleVisibility = () => {
        if (!aliveRef.current) return;
        if (!document.hidden) {
          if (timer) clearTimeout(timer);
          tick();
        }
      };

      tick();
      if (typeof document !== 'undefined') {
        document.addEventListener('visibilitychange', handleVisibility);
      }

      return () => {
        aliveRef.current = false;
        if (timer) clearTimeout(timer);
        if (typeof document !== 'undefined') {
          document.removeEventListener('visibilitychange', handleVisibility);
        }
      };
    }, [enabled]);

    return state;
  };
}

const useWhatsappStatusInner = createPollingHook({
  url: '/api/whatsapp/status',
  intervalMs: STATUS_POLL_MS,
  dataKey: 'status',
});

export function useWhatsappStatus() {
  return useWhatsappStatusInner({ enabled: true });
}

export const useUazapiStats = createPollingHook({
  url: '/api/whatsapp/uazapi-stats',
  intervalMs: UAZAPI_POLL_MS,
  dataKey: 'stats',
});

export async function disconnectWhatsapp(sessionId) {
  return callApi(`/api/whatsapp/sessions/${sessionId}`, {
    method: 'DELETE',
    auth: true,
  });
}
