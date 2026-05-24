import { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { getState, clearState, type MedzeePersistedState } from "../lib/storage.js";
import { getStatus, UnauthorizedError } from "../lib/api-client.js";
import type {
  MedzeeRuntimeMessage,
  MedzeeRuntimeReply,
} from "../lib/messages.js";
import "./popup.css";

const EXT_VERSION = chrome.runtime.getManifest().version;
const WA_WEB_URL = "https://web.whatsapp.com/";

// Frontend URL baked from VITE_FRONTEND_URL no .env (com fallback prod
// se o build não tiver o env setado).
const SITE_URL =
  (import.meta as ImportMeta & { env?: Record<string, string | undefined> })
    .env?.VITE_FRONTEND_URL?.replace(/\/+$/, "") ?? "https://medzee-spy.vercel.app";
const SITE_LOGIN_URL = `${SITE_URL}/login`;
const REPORT_URL = `${SITE_URL}/app/reports/latest`;

function formatDateTime(iso: string | null): string {
  if (!iso) return "nunca";
  try {
    const d = new Date(iso);
    return d.toLocaleString("pt-BR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function openTab(url: string): void {
  void chrome.tabs.create({ url });
}

async function sendToSW(message: MedzeeRuntimeMessage): Promise<MedzeeRuntimeReply> {
  return (await chrome.runtime.sendMessage(message)) as MedzeeRuntimeReply;
}

function StatusBadge({
  children,
  tone,
}: {
  children: React.ReactNode;
  tone: "ok" | "info" | "warn";
}) {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}

function App() {
  const [state, setState] = useState<MedzeePersistedState | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionError, setActionError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const s = await getState();
    setState(s);
    setLoading(false);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const s = await getState();
      if (!cancelled) {
        setState(s);
        setLoading(false);
      }

      // Valida session contra backend — cobre o caso de session "zumbi"
      // (user deletado em auth.users mas JWT ainda não expirou). Se 401,
      // limpa state localmente e a UI re-renderiza pra "Não conectado".
      if (s.session) {
        try {
          await getStatus();
        } catch (err) {
          if (cancelled) return;
          if (err instanceof UnauthorizedError) {
            // eslint-disable-next-line no-console
            console.warn("[popup] session zumbi detectada, limpando");
            await clearState();
            // chrome.storage.onChanged listener (abaixo) já vai disparar
            // refresh — não precisa setState aqui.
          }
        }
      }
    })();

    // Re-read whenever storage changes (probe just synced a fresh session,
    // collection progress ticked, user logged out, etc).
    const onChange = (
      changes: { [k: string]: chrome.storage.StorageChange },
      area: chrome.storage.AreaName,
    ) => {
      if (area === "local" && changes["medzee"]) {
        void refresh();
      }
    };
    chrome.storage.onChanged.addListener(onChange);

    return () => {
      cancelled = true;
      chrome.storage.onChanged.removeListener(onChange);
    };
  }, [refresh]);

  const onLogout = useCallback(async () => {
    setActionError(null);
    try {
      await sendToSW({ type: "medzee:logout" });
      await refresh();
    } catch (err) {
      setActionError(`Falha ao sair: ${String(err)}`);
    }
  }, [refresh]);

  const onStart = useCallback(async () => {
    setActionError(null);
    try {
      const reply = await sendToSW({ type: "medzee:start" });
      if (reply.type === "medzee:error") {
        setActionError(reply.message ?? `Erro: ${reply.code}`);
      }
    } catch (err) {
      setActionError(`Erro ao iniciar: ${String(err)}`);
    }
  }, []);

  if (loading || !state) {
    return <div className="popup popup--loading">Carregando…</div>;
  }

  const session = state.session;
  const collecting = !!state.collection_in_progress;
  const hasHistory = !!state.last_collection_at;

  let body: React.ReactNode;

  if (!session) {
    // No session synced from the site yet. Either the user isn't logged in
    // on medzee-spy.vercel.app or they haven't opened a tab there since
    // installing the extension.
    body = (
      <>
        <StatusBadge tone="warn">Não conectado</StatusBadge>
        <p className="popup__msg">
          Faça login (ou cadastre-se) em <strong>medzee-spy.vercel.app</strong>{" "}
          numa aba do Chrome. A extensão pega a sessão automaticamente —
          sem precisar digitar a senha aqui.
        </p>
        <button
          className="popup__cta"
          onClick={() => openTab(SITE_LOGIN_URL)}
        >
          Abrir Medzee Spy
        </button>
      </>
    );
  } else if (collecting && state.collection_in_progress) {
    const cip = state.collection_in_progress;
    body = (
      <>
        <StatusBadge tone="info">Coletando…</StatusBadge>
        <p className="popup__email-display">{session.email}</p>
        <p className="popup__msg">
          {cip.batches_sent} / {cip.total_batches} batches enviados
        </p>
        <div className="popup__spinner" aria-label="Coletando">
          ⏳
        </div>
      </>
    );
  } else if (hasHistory) {
    // DONE state: user já tem relatório. Primário = "Ver relatório" (volta
    // pro app já logado). Secundário = "Gerar novo relatório".
    body = (
      <>
        <StatusBadge tone="ok">Relatório pronto</StatusBadge>
        <p className="popup__email-display">{session.email}</p>
        <p className="popup__msg">
          Última análise:{" "}
          <strong>{state.last_collection_message_count} mensagens</strong>
          <br />
          em {formatDateTime(state.last_collection_at)}
        </p>
        {actionError && <div className="popup__error">{actionError}</div>}
        <button className="popup__cta" onClick={() => openTab(REPORT_URL)}>
          Ver relatório
        </button>
        <button
          className="popup__cta popup__cta--secondary"
          onClick={onStart}
        >
          Gerar novo relatório
        </button>
        <button
          className="popup__cta popup__cta--secondary"
          onClick={onLogout}
        >
          Sair
        </button>
      </>
    );
  } else {
    // IDLE state: user logado, sem nenhuma análise ainda. Primário = "Gerar
    // relatório". Secundário = "Abrir WhatsApp Web" (caso user esteja vendo
    // o popup de outra aba que não a do WA Web).
    body = (
      <>
        <StatusBadge tone="ok">Conectado</StatusBadge>
        <p className="popup__email-display">{session.email}</p>
        <p className="popup__msg">
          Vá pro WhatsApp Web (aba aberta no Chrome) e clique em{" "}
          <strong>Gerar relatório</strong> abaixo.
        </p>
        {actionError && <div className="popup__error">{actionError}</div>}
        <button className="popup__cta" onClick={onStart}>
          Gerar relatório
        </button>
        <button
          className="popup__cta popup__cta--secondary"
          onClick={() => openTab(WA_WEB_URL)}
        >
          Abrir WhatsApp Web
        </button>
        <button
          className="popup__cta popup__cta--secondary"
          onClick={onLogout}
        >
          Sair
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
