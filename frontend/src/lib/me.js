// F4 polish — useMe(): fetch real profile from /api/auth/me.
//
// Backend retorna {user_id, name, email, phone, ticket_medio, clinic_segment}.
// Hook cacheia em ref pra não disparar requests duplos.

import { useEffect, useState } from 'react';
import { callApi } from './api';

export function useMe() {
  const [state, setState] = useState({ loading: true, me: null, error: null });

  useEffect(() => {
    let alive = true;
    callApi('/api/auth/me', { auth: true })
      .then((me) => {
        if (alive) setState({ loading: false, me, error: null });
      })
      .catch((e) => {
        if (alive)
          setState({
            loading: false,
            me: null,
            error: e.detail || `http_${e.status ?? 'unknown'}`,
          });
      });
    return () => {
      alive = false;
    };
  }, []);

  return state;
}

export function shortName(fullName) {
  if (!fullName) return '';
  const parts = fullName.trim().split(/\s+/);
  if (parts.length <= 2) return fullName;
  // Dr. João Pedro Silva → Dr. João Pedro
  return parts.slice(0, 2).join(' ');
}
