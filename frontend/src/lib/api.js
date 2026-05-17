import { supabase } from './supabase';

const BASE = import.meta.env.VITE_API_BASE_URL;

async function callApi(path, { method = 'GET', body, auth = false, signal } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (auth) {
    const { data } = await supabase.auth.getSession();
    if (data.session?.access_token) {
      headers.Authorization = `Bearer ${data.session.access_token}`;
    }
  }
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
    signal,
  });
  const text = await res.text();
  const json = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const err = new Error(json?.detail || `HTTP ${res.status}`);
    err.status = res.status;
    err.detail = json?.detail;
    err.body = json;
    throw err;
  }
  return json?.data ?? json;
}

export const api = {
  signup: (payload) => callApi('/api/auth/signup', { method: 'POST', body: payload }),
  login: (payload) => callApi('/api/auth/login', { method: 'POST', body: payload }),
  me: () => callApi('/api/auth/me', { auth: true }),
};

export { callApi };
