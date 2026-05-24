// F8 — Device detection (CHX-07).
//
// useIsMobile(): hook que combina 3 sinais pra decidir se o device é mobile.
// Necessário porque a Chrome Extension (D11) só roda em desktop — em mobile
// o /spy redireciona pra MobileBlockScreen com captura de email.
//
// Sinais (any positive → mobile):
//   1. UA regex casa com padrões mobile (iPhone, Android, etc.)
//   2. matchMedia('(pointer:coarse)') → device touch
//   3. window.innerWidth < 900 → fallback de viewport estreita
//
// Detecção síncrona no primeiro render (sem flicker), reativa a `resize`
// e a mudanças no media query (orientation change, hotplug de mouse).

import { useEffect, useState } from 'react';

const MOBILE_UA_REGEX =
  /iPhone|iPad|iPod|Android|Mobile|Phone|webOS|BlackBerry|IEMobile|Opera Mini/i;

function detect() {
  // SSR guard — Vite é CSR-only mas custa nada e evita surpresa futura.
  if (typeof window === 'undefined') return false;
  const ua = window.navigator?.userAgent ?? '';
  const uaHit = MOBILE_UA_REGEX.test(ua);
  const coarse =
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(pointer:coarse)').matches;
  const narrow = window.innerWidth < 900;
  return uaHit || (coarse && narrow);
}

/**
 * Hook que detecta se o device atual é mobile.
 *
 * @returns {boolean} true se o device é detectado como mobile.
 *   Síncrono no primeiro render (sem flicker), reativo a resize
 *   e a mudanças no media query pointer:coarse.
 */
export function useIsMobile() {
  const [isMobile, setIsMobile] = useState(detect);

  useEffect(() => {
    function onResize() {
      setIsMobile(detect());
    }
    window.addEventListener('resize', onResize);
    // Também escuta change do mq — alguns browsers disparam em hotplug
    // de mouse/touch ou rotação de orientação.
    const mq = window.matchMedia?.('(pointer:coarse)');
    mq?.addEventListener?.('change', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      mq?.removeEventListener?.('change', onResize);
    };
  }, []);

  return isMobile;
}
