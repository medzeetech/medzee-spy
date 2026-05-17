// F4 — WhatsApp status lib (F4-14 + F4-17 + REPORT-19a vibe).
//
// useWhatsappStatus(): polls GET /api/whatsapp/status a cada 5s e retorna
// { loading, status, error }. status é o body do WhatsappStatusResponse
// (connected, session_id, connected_since, message_count, conversation_count,
// last_message_at) — null enquanto loading=true.
//
// Polling de 5s é defensivo: o webhook traz mensagens em tempo real, mas o
// frontend só precisa refletir contagens — 5s não pesa no backend e mantém
// a UI fresca.
//
// disconnectWhatsapp(sessionId): chama DELETE /api/whatsapp/sessions/:id pra
// limpar o slot na uazapi + marcar status='disconnected' no DB. Frontend
// reseta o card pra estado "Desconectado".

import { useEffect, useRef, useState } from 'react';
import { callApi } from './api';

const POLL_MS = 5000;

export function useWhatsappStatus() {
  const [state, setState] = useState({
    loading: true,
    status: null,
    error: null,
  });
  const aliveRef = useRef(true);

  useEffect(() => {
    aliveRef.current = true;
    let timer;

    const tick = async () => {
      try {
        const status = await callApi('/api/whatsapp/status', { auth: true });
        if (!aliveRef.current) return;
        setState({ loading: false, status, error: null });
      } catch (e) {
        if (!aliveRef.current) return;
        setState((prev) => ({
          ...prev,
          loading: false,
          error: e.detail || `http_${e.status ?? 'unknown'}`,
        }));
      }
      if (aliveRef.current) timer = setTimeout(tick, POLL_MS);
    };

    tick();

    return () => {
      aliveRef.current = false;
      if (timer) clearTimeout(timer);
    };
  }, []);

  return state;
}

export async function disconnectWhatsapp(sessionId) {
  return callApi(`/api/whatsapp/sessions/${sessionId}`, {
    method: 'DELETE',
    auth: true,
  });
}

// useUazapiStats(): polls GET /api/whatsapp/uazapi-stats a cada 5s. Retorna
// { loading, stats, error } onde stats = { chat_count, message_count, raw }.
//
// Diferente de useWhatsappStatus (que reflete captured_messages local), este
// hook bate direto em chat/find no provider — então mostra "verdade ao vivo"
// do WhatsApp. Quando 'enabled' é false (ex: usuário desconectado) o hook
// fica idle pra não bater no provider à toa.
export function useUazapiStats({ enabled = true } = {}) {
  const [state, setState] = useState({
    loading: enabled,
    stats: null,
    error: null,
  });
  const aliveRef = useRef(true);

  useEffect(() => {
    aliveRef.current = true;
    if (!enabled) {
      setState({ loading: false, stats: null, error: null });
      return () => {
        aliveRef.current = false;
      };
    }
    let timer;

    const tick = async () => {
      try {
        const stats = await callApi('/api/whatsapp/uazapi-stats', { auth: true });
        if (!aliveRef.current) return;
        setState({ loading: false, stats, error: null });
      } catch (e) {
        if (!aliveRef.current) return;
        setState((prev) => ({
          ...prev,
          loading: false,
          error: e.detail || `http_${e.status ?? 'unknown'}`,
        }));
      }
      if (aliveRef.current) timer = setTimeout(tick, POLL_MS);
    };

    tick();

    return () => {
      aliveRef.current = false;
      if (timer) clearTimeout(timer);
    };
  }, [enabled]);

  return state;
}
