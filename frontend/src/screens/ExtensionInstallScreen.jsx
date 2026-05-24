// F8 — ExtensionInstallScreen (PIVOT 2026-05-24, 3ª iteração UX).
//
// Tela estática mostrada após o signup. Botão "Pronto, baixei e instalei"
// abre web.whatsapp.com em nova aba — lá o user clica no ícone da extensão
// pra gerar o relatório. Quando termina, a extensão mostra um botão
// "Ver relatório" que volta pro app já logado.

import { Puzzle, Download, MessageCircle, Video } from 'lucide-react';

// PENDING_ID: replaced after Chrome Web Store submission (T27)
const CHROME_STORE_URL = 'https://chrome.google.com/webstore/detail/medzee-spy/PENDING_ID';
const WHATSAPP_WEB_URL = 'https://web.whatsapp.com/';

/**
 * Tela "Instale a extensão" (estática).
 *
 * Props:
 *   - userEmail?: string — email cadastrado, exibido como confirmação no rodapé.
 *   - step?: string — texto opcional do header (default "Passo 2 de 2").
 */
export default function ExtensionInstallScreen({ userEmail, step = 'Passo 2 de 2' }) {
  function openWhatsAppWeb() {
    window.open(WHATSAPP_WEB_URL, '_blank');
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-900 text-slate-100 p-6">
      <div className="w-full max-w-2xl bg-slate-800 rounded-2xl p-8 shadow-2xl flex flex-col gap-6">
        <header className="space-y-2">
          <p className="text-xs uppercase tracking-wider text-amber-400">{step}</p>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-3">
            <Puzzle className="w-7 h-7 text-amber-400" />
            Instale a extensão Medzee Spy
          </h1>
        </header>

        {/* Video placeholder */}
        <div className="aspect-video bg-slate-900 rounded-lg border border-slate-700 flex flex-col items-center justify-center text-slate-500 gap-2">
          <Video className="w-12 h-12" />
          <p className="text-sm">Vídeo explicativo (em breve)</p>
        </div>

        <div className="text-sm text-slate-400 leading-relaxed space-y-2">
          <p>A extensão Medzee Spy é gratuita e instala em 30 segundos pelo Chrome Web Store.</p>
          <p>
            <strong className="text-slate-200">Próximos passos:</strong>
          </p>
          <ol className="list-decimal list-inside space-y-1 ml-1">
            <li>Click em <strong>&quot;Baixar extensão&quot;</strong> e instale.</li>
            <li>Click em <strong>&quot;Pronto, baixei e instalei&quot;</strong> — abre o WhatsApp Web.</li>
            <li>No WhatsApp Web, click no ícone Medzee Spy (barra do Chrome) e <strong>&quot;Gerar relatório&quot;</strong>.</li>
            <li>Quando terminar, click <strong>&quot;Ver relatório&quot;</strong> na extensão pra ver sua análise.</li>
          </ol>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <a
            href={CHROME_STORE_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center justify-center gap-2 px-4 py-3 bg-amber-500 hover:bg-amber-400 text-slate-900 rounded-lg font-semibold transition-colors"
          >
            <Download className="w-5 h-5" />
            Baixar extensão
          </a>
          <button
            type="button"
            onClick={openWhatsAppWeb}
            className="flex items-center justify-center gap-2 px-4 py-3 bg-emerald-600 hover:bg-emerald-500 text-slate-100 rounded-lg font-semibold transition-colors"
          >
            <MessageCircle className="w-5 h-5" />
            Pronto, baixei e instalei
          </button>
        </div>

        <details className="text-xs text-slate-500">
          <summary className="cursor-pointer hover:text-slate-300">Modo desenvolvedor</summary>
          <p className="mt-2 leading-relaxed">
            Em modo dev: abra <code className="bg-slate-700 px-1.5 py-0.5 rounded">chrome://extensions</code>,
            ative &quot;Modo desenvolvedor&quot;, clique em &quot;Carregar sem compactação&quot; e selecione a pasta
            <code className="bg-slate-700 px-1.5 py-0.5 rounded">./extension/dist/</code>.
          </p>
        </details>

        {userEmail && (
          <p className="text-xs text-slate-500 text-center pt-2 border-t border-slate-700">
            Email cadastrado: <span className="text-slate-300">{userEmail}</span>
          </p>
        )}
      </div>
    </div>
  );
}
