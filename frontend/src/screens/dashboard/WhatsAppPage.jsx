// F8 — Extension status page.
//
// Substitui o card de QR/uazapi por status da extensão Chrome (única forma
// suportada de ingerir conversas no M2+). Lê /api/extension/status (auth
// Supabase JWT) e mostra:
//   - paired=false → CTA pra baixar a extensão na Chrome Store
//   - paired=true  → última coleta (count + timestamp) + howto

import { useEffect, useState } from 'react';
import { CheckCircle, AlertTriangle, Download, RefreshCw } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';
import { callApi } from '../../lib/api.js';

const CHROME_STORE_URL = 'https://chrome.google.com/webstore/detail/medzee-spy/PENDING_ID';

export default function WhatsAppPage() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const res = await callApi('/api/extension/status', { auth: true });
      setStatus(res);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    // Inicial fetch — wrap em IIFE async pra não retornar a Promise pro
    // cleanup (e silenciar o react-hooks/set-state-in-effect, já que o
    // setState ocorre dentro de um callback async, não no body do effect).
    let alive = true;
    (async () => {
      try {
        const res = await callApi('/api/extension/status', { auth: true });
        if (alive) {
          setStatus(res);
          setError(null);
        }
      } catch (e) {
        if (alive) setError(e);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  if (loading) {
    return <div style={{ padding: 24, color: COLORS.inkMute }}>Carregando…</div>;
  }

  const paired = !!status?.paired;
  const lastAt = status?.last_collection_at;
  const lastCount = status?.last_collection_message_count ?? 0;

  return (
    <div style={{ maxWidth: 760, padding: 32 }}>
      <header style={{ marginBottom: 28 }}>
        <h1
          style={{
            fontSize: 24,
            fontWeight: 800,
            color: COLORS.ink,
            margin: 0,
            letterSpacing: '-0.02em',
          }}
        >
          Extensão Medzee Spy
        </h1>
        <p style={{ fontSize: 14, color: COLORS.inkMute, marginTop: 8 }}>
          Status da extensão Chrome que lê seu WhatsApp Web e envia ao Medzee Spy.
        </p>
      </header>

      {error && (
        <div
          style={{
            background: 'rgba(229,96,77,0.08)',
            border: '1px solid rgba(229,96,77,0.25)',
            borderRadius: 12,
            padding: 16,
            marginBottom: 20,
            color: COLORS.wine,
            display: 'flex',
            alignItems: 'center',
            gap: 10,
          }}
        >
          <AlertTriangle size={18} />
          Erro ao carregar status.
          <button
            type="button"
            onClick={load}
            style={{
              marginLeft: 'auto',
              color: COLORS.orangeDeep,
              textDecoration: 'underline',
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              fontFamily: "'Red Hat Display', sans-serif",
              fontSize: 13,
            }}
          >
            Tentar de novo
          </button>
        </div>
      )}

      <div
        style={{
          background: COLORS.paper,
          border: `1px solid ${COLORS.hairline}`,
          borderRadius: 16,
          padding: 24,
          marginBottom: 16,
        }}
      >
        <div className="flex items-center justify-between" style={{ marginBottom: 16 }}>
          <div className="flex items-center" style={{ gap: 12 }}>
            {paired ? (
              <CheckCircle size={24} color={COLORS.wa} />
            ) : (
              <AlertTriangle size={24} color={COLORS.orange} />
            )}
            <div>
              <div style={{ fontSize: 16, fontWeight: 700, color: COLORS.ink }}>
                {paired ? 'Extensão conectada' : 'Extensão não configurada'}
              </div>
              <div style={{ fontSize: 13, color: COLORS.inkMute, marginTop: 4 }}>
                {paired
                  ? lastAt
                    ? `Última análise: ${lastCount} mensagens em ${new Date(lastAt).toLocaleString('pt-BR')}`
                    : 'Pronta pra rodar a primeira análise'
                  : 'Instale a extensão Chrome pra começar.'}
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={load}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '8px 14px',
              background: 'transparent',
              border: `1px solid ${COLORS.hairline}`,
              borderRadius: 8,
              fontSize: 13,
              color: COLORS.ink,
              cursor: 'pointer',
              fontFamily: "'Red Hat Display', sans-serif",
            }}
          >
            <RefreshCw size={14} />
            Atualizar
          </button>
        </div>
      </div>

      {!paired && (
        <a
          href={CHROME_STORE_URL}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
            padding: '12px 20px',
            background: COLORS.orange,
            color: COLORS.cream,
            borderRadius: 12,
            fontSize: 14,
            fontWeight: 700,
            textDecoration: 'none',
          }}
        >
          <Download size={16} />
          Baixar extensão
        </a>
      )}

      {paired && (
        <div
          style={{
            padding: 16,
            background: 'rgba(37,211,102,0.08)',
            border: '1px solid rgba(37,211,102,0.2)',
            borderRadius: 12,
            fontSize: 13,
            color: COLORS.ink,
          }}
        >
          <strong>Como gerar uma análise:</strong>
          <ol style={{ marginTop: 8, paddingLeft: 20, lineHeight: 1.6 }}>
            <li>Clique no ícone Medzee Spy na barra do Chrome</li>
            <li>Click em "Abrir WhatsApp Web" — faça login lá se necessário</li>
            <li>Volte na extensão e click em "Iniciar análise"</li>
            <li>Aguarde ~60-90s. O relatório aparece em Relatórios.</li>
          </ol>
        </div>
      )}
    </div>
  );
}
