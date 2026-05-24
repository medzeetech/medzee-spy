import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { getState, clearState, type MedzeePersistedState } from "../lib/storage.js";
import "./popup.css";

const EXT_VERSION = chrome.runtime.getManifest().version;
const SPY_URL = "https://medzee.com/spy";          // TODO: env-driven in M3
const APP_URL = "https://medzee.com/app/whatsapp"; // same
const DEV_SPY_URL = "http://localhost:5173/spy";
const DEV_APP_URL = "http://localhost:5173/app/whatsapp";

function formatDateTime(iso: string | null): string {
  if (!iso) return "nunca";
  try {
    const d = new Date(iso);
    return d.toLocaleString("pt-BR", {
      day: "2-digit", month: "2-digit", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function pickUrl(prodUrl: string, devUrl: string): string {
  // Heuristic: in unpacked dev mode, target localhost. Otherwise prod.
  // chrome.runtime.id is a 32-char hex string for unpacked, longer for store.
  return chrome.runtime.id.length === 32 ? devUrl : prodUrl;
}

function openTab(url: string): void {
  void chrome.tabs.create({ url });
}

function StatusBadge({ children, tone }: { children: React.ReactNode; tone: "ok" | "info" | "warn" }) {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}

function App() {
  const [state, setState] = useState<MedzeePersistedState | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const s = await getState();
      if (!cancelled) {
        setState(s);
        setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (loading || !state) {
    return <div className="popup popup--loading">Carregando…</div>;
  }

  const paired = !!state.refresh_token;
  const collecting = !!state.collection_in_progress;
  const hasHistory = !!state.last_collection_at;

  let body: React.ReactNode;
  if (!paired) {
    body = (
      <>
        <StatusBadge tone="warn">Não conectado</StatusBadge>
        <p className="popup__msg">Conecte sua conta Medzee pra analisar seu WhatsApp.</p>
        <button className="popup__cta" onClick={() => openTab(pickUrl(SPY_URL, DEV_SPY_URL))}>
          Conectar agora
        </button>
      </>
    );
  } else if (collecting && state.collection_in_progress) {
    const cip = state.collection_in_progress;
    body = (
      <>
        <StatusBadge tone="info">Coletando…</StatusBadge>
        <p className="popup__msg">
          {cip.batches_sent} / {cip.total_batches} batches enviados
        </p>
        <div className="popup__spinner" aria-label="Coletando">⏳</div>
      </>
    );
  } else if (hasHistory) {
    body = (
      <>
        <StatusBadge tone="ok">Conectado</StatusBadge>
        <p className="popup__msg">
          Última análise: <strong>{state.last_collection_message_count} mensagens</strong><br />
          em {formatDateTime(state.last_collection_at)}
        </p>
        <button className="popup__cta" onClick={() => openTab(pickUrl(APP_URL, DEV_APP_URL))}>
          Atualizar análise
        </button>
        <button className="popup__cta popup__cta--secondary" onClick={async () => {
          await clearState();
          const s = await getState();
          setState(s);
        }}>
          Desconectar
        </button>
      </>
    );
  } else {
    body = (
      <>
        <StatusBadge tone="ok">Conectado</StatusBadge>
        <p className="popup__msg">Última análise: nunca</p>
        <button className="popup__cta" onClick={() => openTab(pickUrl(APP_URL, DEV_APP_URL))}>
          Iniciar análise
        </button>
      </>
    );
  }

  return (
    <div className="popup">
      <header className="popup__header">
        <h1 className="popup__title">Medzee Spy</h1>
      </header>
      <main className="popup__body">{body}</main>
      <footer className="popup__footer">v{EXT_VERSION}</footer>
    </div>
  );
}

const root = document.getElementById("root");
if (root) createRoot(root).render(<App />);
