// F8 — Frontend ↔ Chrome extension bridge (CHX-09, CHX-10, CHX-15).
//
// A extensão tem um content script `probe` injetado em medzee.com + localhost:5173
// que escuta `window.postMessage` e faz bridge com o service worker MV3. Esse
// módulo encapsula esse protocolo no lado do frontend:
//   - useExtensionDetected: probe de detecção com timeout
//   - useExtensionEvents:   subscribe em lifecycle events da extensão
//   - sendToExtension:      dispara um comando (pair/start/abort/unpair)
//   - injectPairingToken:   persiste o pairing_token onde o probe consegue ler
//   - requestNewPairingToken: re-emite token via backend (15min TTL)

import { useEffect, useState } from 'react';

import { callApi } from './api';

const PAIRING_TOKEN_LS_KEY = 'medzee_spy:pairing_token';

/**
 * Probe pra detectar se a extensão está instalada (e se já pareada).
 *
 * Estratégia: posta `medzee:probe` no window e espera resposta `medzee:installed`
 * do probe content-script. Se timeout estoura sem resposta, considera não instalada.
 *
 * @param {number} [timeoutMs=500] janela de espera antes de declarar "não instalada".
 * @returns {{installed: boolean, paired: boolean, version: string|null}|null}
 *   null enquanto detectando; objeto após settle.
 */
export function useExtensionDetected(timeoutMs = 500) {
  const [state, setState] = useState(null); // null = detectando

  useEffect(() => {
    let timer = null;
    let settled = false;

    function onMessage(event) {
      if (event.source !== window) return;
      const data = event.data;
      if (!data || typeof data !== 'object') return;
      if (data.type !== 'medzee:installed') return;
      if (settled) return;
      settled = true;
      window.removeEventListener('message', onMessage);
      if (timer) clearTimeout(timer);
      setState({
        installed: true,
        paired: !!data.paired,
        version: data.version ?? null,
      });
    }

    window.addEventListener('message', onMessage);
    window.postMessage({ type: 'medzee:probe' }, '*');

    timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      window.removeEventListener('message', onMessage);
      setState({ installed: false, paired: false, version: null });
    }, timeoutMs);

    return () => {
      settled = true;
      window.removeEventListener('message', onMessage);
      if (timer) clearTimeout(timer);
    };
  }, [timeoutMs]);

  return state;
}

/**
 * Subscribe em lifecycle events emitidos pela extensão (ex: `collect_started`,
 * `wa_needs_login`, `pairing_failed`, `aborted`, `extension_outdated`).
 *
 * Cada evento substitui o anterior — consumidores são responsáveis por reagir
 * antes do próximo chegar (ou tratar idempotente).
 *
 * @returns {{event: string, data: object|null}|null} último evento recebido,
 *   ou null se nenhum.
 */
export function useExtensionEvents() {
  const [lastEvent, setLastEvent] = useState(null);

  useEffect(() => {
    function onMessage(event) {
      if (event.source !== window) return;
      const data = event.data;
      if (!data || typeof data !== 'object') return;
      if (data.type !== 'medzee:event') return;
      setLastEvent({ event: data.event, data: data.data ?? null });
    }
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);

  return lastEvent;
}

/**
 * Envia um comando pra extensão e aguarda a resposta `medzee:cmd_result`.
 *
 * Timeout: 10s. Se a extensão não responder dentro disso, provavelmente não
 * está instalada / probe não rodou ainda — a promise rejeita.
 *
 * @param {'pair'|'start_collection'|'abort_collection'|'unpair'} cmd
 * @param {object} [payload] payload opcional do comando.
 * @returns {Promise<object>} resolves com `data.result` do reply.
 */
export function sendToExtension(cmd, payload) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let timer = null;

    function onMessage(event) {
      if (event.source !== window) return;
      const data = event.data;
      if (!data || typeof data !== 'object') return;
      if (data.type !== 'medzee:cmd_result') return;
      if (data.cmd !== cmd) return;
      if (settled) return;
      settled = true;
      window.removeEventListener('message', onMessage);
      if (timer) clearTimeout(timer);
      resolve(data.result);
    }
    window.addEventListener('message', onMessage);
    window.postMessage({ type: 'medzee:cmd', cmd, payload }, '*');

    timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      window.removeEventListener('message', onMessage);
      reject(new Error(`extension cmd ${cmd} timed out`));
    }, 10_000);
  });
}

/**
 * Persiste o pairing_token onde a extensão consegue ler:
 *   - localStorage[PAIRING_TOKEN_LS_KEY]: lido pelo auto-pair flow do probe.
 *   - window.medzee_spy.pairing_token:    fallback pra page-world helpers.
 *
 * Degrada silenciosamente se localStorage estiver bloqueado (modo privacidade).
 *
 * @param {string} token JWT de pairing (typ=extension_pairing, exp=+15min).
 */
export function injectPairingToken(token) {
  try {
    window.localStorage.setItem(PAIRING_TOKEN_LS_KEY, token);
  } catch {
    // localStorage pode estar bloqueado (privacy mode / cookies off) — segue o jogo.
  }
  if (typeof window !== 'undefined') {
    window.medzee_spy = { ...(window.medzee_spy ?? {}), pairing_token: token };
  }
}

/**
 * Pede pro backend emitir um novo pairing_token (15min TTL). Requer JWT do user.
 *
 * Idempotente: cada chamada retorna um token novo (iat diferente). Usado quando
 * o token original expira antes do user instalar a extensão.
 *
 * @returns {Promise<string>} o novo pairing_token.
 * @throws se a resposta não trouxer o campo esperado.
 */
export async function requestNewPairingToken() {
  // callApi já desembrulha o envelope {data: ...} (ver lib/api.js), então
  // a resposta aqui é `{extension_pairing_token: "..."}` direto.
  const res = await callApi('/api/auth/me/extension-pairing-token', {
    method: 'POST',
    auth: true,
  });
  const token = res?.extension_pairing_token;
  if (!token) throw new Error('no extension_pairing_token in response');
  return token;
}

export const PAIRING_TOKEN_STORAGE_KEY = PAIRING_TOKEN_LS_KEY;
