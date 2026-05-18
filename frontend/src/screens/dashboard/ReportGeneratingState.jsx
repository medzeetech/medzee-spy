import { Sparkles, MessageCircle, Brain, Wifi } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';
import { useUazapiStats } from '../../lib/whatsapp.js';

// F5: 3 fases reais com observabilidade.
//
// Fase 1: COLETANDO        — uazapiStats.chat_count subindo
//                            (provider listou as conversas)
// Fase 2: SINCRONIZANDO    — chat_count > 0, message_count crescendo
//                            (uazapi popula cache via history-sync)
// Fase 3: IA ANALISANDO    — backend já recebeu payload, LLM rodando
//                            (heurística temporal — uazapiStats não revela isso)
//
// O elapsedMs vem do polling de /api/reports/{id}; se >= ~30s, presume
// que o LLM está rodando (a coleta uazapi tem timeout absoluto de ~30s
// no caminho feliz). Sem isso é só "coletando…".

const PHASE_PULL = 'pull';
const PHASE_LLM = 'llm';
const PHASE_FINALIZING = 'finalizing';

function pickPhase(elapsedMs, hasData) {
  if (elapsedMs < 30_000) return hasData ? PHASE_PULL : PHASE_PULL;
  if (elapsedMs < 90_000) return PHASE_LLM;
  return PHASE_FINALIZING;
}

function StatPill({ Icon, value, label, highlight }) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '8px 12px',
        borderRadius: 99,
        background: highlight ? 'rgba(255,107,53,0.1)' : COLORS.sunken,
        border: `1px solid ${highlight ? 'rgba(255,107,53,0.3)' : COLORS.hairline}`,
        fontSize: 12.5,
        fontWeight: 600,
        color: highlight ? COLORS.orange : COLORS.inkSoft,
      }}
    >
      <Icon size={13} />
      <span style={{ color: highlight ? COLORS.orange : COLORS.ink, fontWeight: 700 }}>
        {value}
      </span>
      <span>{label}</span>
    </div>
  );
}

export default function ReportGeneratingState({ elapsedMs = 0 }) {
  // Pola /api/whatsapp/uazapi-stats a cada 3s enquanto o relatório gera.
  // Mostra contagens reais — chats listados + msgs sincronizadas.
  const uazapiStats = useUazapiStats({ enabled: true, intervalMs: 3000 });
  const chatCount = uazapiStats?.stats?.chat_count ?? 0;
  const messageCount = uazapiStats?.stats?.message_count ?? 0;
  const hasData = chatCount > 0 || messageCount > 0;

  const phase = pickPhase(elapsedMs, hasData);

  // Progresso aproximado: 0-30s = 0-50% (pull), 30-90s = 50-90% (LLM),
  // 90s+ = 90-98% (finalizing). Cap em 98%.
  let pct;
  if (phase === PHASE_PULL) {
    pct = Math.min(50, (elapsedMs / 30_000) * 50);
  } else if (phase === PHASE_LLM) {
    pct = 50 + Math.min(40, ((elapsedMs - 30_000) / 60_000) * 40);
  } else {
    pct = 90 + Math.min(8, ((elapsedMs - 90_000) / 60_000) * 8);
  }
  pct = Math.round(pct);

  let headline;
  let subline;
  if (phase === PHASE_PULL) {
    headline = hasData
      ? 'Lendo suas conversas…'
      : 'Conectando ao WhatsApp…';
    subline = hasData
      ? `Já vimos ${chatCount} ${chatCount === 1 ? 'conversa' : 'conversas'} no seu WhatsApp.`
      : 'Buscando a lista de conversas no seu WhatsApp.';
  } else if (phase === PHASE_LLM) {
    headline = 'IA analisando o conteúdo…';
    subline = `Cruzando ${messageCount.toLocaleString('pt-BR')} mensagens de ${chatCount} ${chatCount === 1 ? 'conversa' : 'conversas'} pra gerar insights.`;
  } else {
    headline = 'Finalizando seu diagnóstico…';
    subline = 'Montando funil, oportunidades perdidas e benchmarks.';
  }

  return (
    <div
      style={{
        width: '100%',
        minHeight: 'calc(100vh - 80px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '24px 16px',
        fontFamily: "'Red Hat Display', sans-serif",
      }}
    >
      <div
        className="anim-fadeup"
        style={{
          position: 'relative',
          width: '100%',
          maxWidth: 520,
          background: COLORS.paper,
          border: `1px solid ${COLORS.hairline}`,
          borderRadius: 20,
          padding: 'clamp(24px, 4vw, 36px)',
          boxShadow: '0 12px 32px -16px rgba(0,0,0,0.08)',
          textAlign: 'center',
        }}
      >
        <div
          className="inline-flex items-center"
          style={{
            gap: 8,
            padding: '6px 12px',
            borderRadius: 99,
            background: 'rgba(255,107,53,0.1)',
            border: '1px solid rgba(255,107,53,0.25)',
            color: COLORS.orange,
            fontSize: 11.5,
            fontWeight: 600,
            letterSpacing: '0.04em',
            marginBottom: 20,
          }}
        >
          <Sparkles size={13} />
          Diagnóstico Spy
        </div>

        <h1
          style={{
            fontSize: 'clamp(22px, 3.6vw, 28px)',
            fontWeight: 800,
            letterSpacing: '-0.02em',
            color: COLORS.ink,
            margin: 0,
            marginBottom: 10,
            lineHeight: 1.2,
          }}
        >
          {headline}
        </h1>

        <p
          style={{
            color: COLORS.inkSoft,
            fontSize: 14,
            lineHeight: 1.55,
            margin: '0 auto 24px',
            maxWidth: 440,
            minHeight: 44,
          }}
        >
          {subline}
        </p>

        {/* Stats reais — só renderiza quando tem dados pra mostrar */}
        {(chatCount > 0 || messageCount > 0) && (
          <div
            style={{
              display: 'flex',
              gap: 10,
              justifyContent: 'center',
              flexWrap: 'wrap',
              marginBottom: 24,
            }}
          >
            <StatPill
              Icon={MessageCircle}
              value={chatCount.toLocaleString('pt-BR')}
              label={chatCount === 1 ? 'conversa' : 'conversas'}
              highlight={phase === PHASE_PULL}
            />
            <StatPill
              Icon={Wifi}
              value={messageCount.toLocaleString('pt-BR')}
              label="mensagens"
              highlight={phase === PHASE_PULL}
            />
            <StatPill
              Icon={Brain}
              value={phase === PHASE_LLM || phase === PHASE_FINALIZING ? '✓' : '…'}
              label="IA"
              highlight={phase === PHASE_LLM || phase === PHASE_FINALIZING}
            />
          </div>
        )}

        <div
          style={{
            height: 6,
            background: COLORS.sunken,
            borderRadius: 99,
            overflow: 'hidden',
            marginBottom: 12,
          }}
        >
          <div
            style={{
              height: '100%',
              width: `${pct}%`,
              transition: 'width 1s linear',
              background: `linear-gradient(90deg, ${COLORS.orangeDeep}, ${COLORS.orange})`,
              borderRadius: 99,
            }}
          />
        </div>

        <div
          style={{
            fontSize: 11.5,
            color: COLORS.inkMute,
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            fontWeight: 600,
          }}
        >
          {pct}% · {Math.round(elapsedMs / 1000)}s
        </div>
      </div>
    </div>
  );
}
