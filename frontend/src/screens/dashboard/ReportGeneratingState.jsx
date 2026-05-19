import { Sparkles, MessageCircle, Brain, Wifi } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';
import { useUazapiStats, useWhatsappStatus } from '../../lib/whatsapp.js';

// F5: 3 fases reais + contagem de msgs derivada da porcentagem.
//
// Timings calibrados em 2026-05-19 com base no pipeline real:
//   - Coleta DB (RPC) + transform + metrics: ~2s
//   - LLM call (~18k tokens in, 4k out, claude-sonnet-4-6): 10-25s
//   - Persist update_completed (payload jsonb): <1s
//   - Total esperado: 15-30s no caminho feliz
//
// Quando passar de TIMEOUT_HINT_MS (90s) sem terminar, mostra subline
// honesto avisando que está demorando mais que o normal — o poll continua
// até atingir o cap de 8min em useReportPolling.
//
// Fases:
//   1. PULL (0-5s)        — uazapiStats.chat_count ao vivo, msgs animam
//                            de 0 → total proporcional a pct
//   2. LLM  (5-25s)       — backend rodando Claude. Pill IA destaca,
//                            contagem msgs congela no total real
//   3. FINALIZING (25-90s) — montagem do payload + persist
//   4. SLOW (90s+)        — algo travou, mostra hint honesto
//
// A contagem visualmente cresce sincronizada com a porcentagem.

const PHASE_PULL = 'pull';
const PHASE_LLM = 'llm';
const PHASE_FINALIZING = 'finalizing';
const PHASE_SLOW = 'slow';

// Boundaries de tempo em ms (calibradas em 2026-05-19).
const PHASE_PULL_END_MS = 5_000;
const PHASE_LLM_END_MS = 25_000;
const PHASE_FINALIZING_END_MS = 90_000;

// Pct % onde cada fase termina (acompanha a divisão temporal).
const PULL_END_PCT = 40;
const LLM_END_PCT = 85;
const FINALIZING_END_PCT = 96;
const SLOW_CAP_PCT = 99;

// Quando captured_messages.message_count está em 0 (sessão nova, webhook
// ainda não chegou OU pipeline F5 vai puxar direto da uazapi via fallback),
// estimamos o total como chatCount * AVG_MSGS_PER_CHAT.
const AVG_MSGS_PER_CHAT_ESTIMATE = 30;

function pickPhase(elapsedMs) {
  if (elapsedMs < PHASE_PULL_END_MS) return PHASE_PULL;
  if (elapsedMs < PHASE_LLM_END_MS) return PHASE_LLM;
  if (elapsedMs < PHASE_FINALIZING_END_MS) return PHASE_FINALIZING;
  return PHASE_SLOW;
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
  // 2 fontes:
  //   - useUazapiStats: chat_count ao vivo via uazapi /chat/find (sempre
  //     funciona se há sessão conectada — sem depender de webhook)
  //   - useWhatsappStatus: message_count do captured_messages local
  //     (zero quando session é nova / webhook não chegou ainda)
  const uazapiStats = useUazapiStats({ enabled: true, intervalMs: 3000 });
  const { status: waStatus } = useWhatsappStatus();
  const chatCount = uazapiStats?.stats?.chat_count ?? 0;
  const totalCapturedMsgs = waStatus?.message_count ?? 0;

  // Total estimado pra mostrar progresso quando não temos o real ainda.
  // Marcamos visualmente como estimativa (prefixo ~). Quando o real chega,
  // usa o real.
  const usingEstimate = totalCapturedMsgs === 0 && chatCount > 0;
  const totalMsgs = usingEstimate
    ? chatCount * AVG_MSGS_PER_CHAT_ESTIMATE
    : totalCapturedMsgs;

  const hasData = chatCount > 0 || totalMsgs > 0;
  const phase = pickPhase(elapsedMs);

  // Progresso calibrado pelos PHASE_*_END_MS. Em SLOW (>90s) cap em 99%
  // pra indicar "ainda processando mas demorando mais que o esperado".
  let pct;
  if (phase === PHASE_PULL) {
    pct = (elapsedMs / PHASE_PULL_END_MS) * PULL_END_PCT;
  } else if (phase === PHASE_LLM) {
    const phaseElapsed = elapsedMs - PHASE_PULL_END_MS;
    const phaseDuration = PHASE_LLM_END_MS - PHASE_PULL_END_MS;
    pct = PULL_END_PCT + (phaseElapsed / phaseDuration) * (LLM_END_PCT - PULL_END_PCT);
  } else if (phase === PHASE_FINALIZING) {
    const phaseElapsed = elapsedMs - PHASE_LLM_END_MS;
    const phaseDuration = PHASE_FINALIZING_END_MS - PHASE_LLM_END_MS;
    pct = LLM_END_PCT + (phaseElapsed / phaseDuration) * (FINALIZING_END_PCT - LLM_END_PCT);
  } else {
    pct = SLOW_CAP_PCT;
  }
  pct = Math.min(Math.max(Math.round(pct), 0), 99);

  // Contagem de msgs DERIVADA da porcentagem da barra. Normalizada por
  // PULL_END_PCT (50%) pra atingir totalMsgs no exato instante em que a
  // fase PULL termina e a barra cruza 50%. Após isso (LLM/FINALIZING)
  // congela no total enquanto a barra continua subindo (LLM rodando).
  // totalMsgs pode ser real (captured_messages) OU estimativa
  // (chatCount * 30 quando webhook ainda não populou) — diferença só
  // visual via prefixo "~".
  let displayedMsgs;
  if (phase === PHASE_PULL) {
    const pullRatio = Math.min(1, pct / PULL_END_PCT);
    displayedMsgs = Math.floor(totalMsgs * pullRatio);
  } else {
    displayedMsgs = totalMsgs;
  }
  const formatMsgs = (n) =>
    (usingEstimate ? '~' : '') + n.toLocaleString('pt-BR');

  let headline;
  let subline;
  if (phase === PHASE_PULL) {
    headline = hasData ? 'Lendo suas conversas…' : 'Conectando ao WhatsApp…';
    if (totalMsgs > 0) {
      subline = `Lendo ${formatMsgs(displayedMsgs)} de ${formatMsgs(totalMsgs)} mensagens em ${chatCount} ${chatCount === 1 ? 'conversa' : 'conversas'}.`;
    } else if (chatCount > 0) {
      subline = `Já vimos ${chatCount} ${chatCount === 1 ? 'conversa' : 'conversas'} no seu WhatsApp.`;
    } else {
      subline = 'Buscando a lista de conversas no seu WhatsApp.';
    }
  } else if (phase === PHASE_LLM) {
    headline = 'IA analisando o conteúdo…';
    if (totalMsgs > 0) {
      subline = `Cruzando ${formatMsgs(totalMsgs)} mensagens de ${chatCount} ${chatCount === 1 ? 'conversa' : 'conversas'} pra gerar insights.`;
    } else if (chatCount > 0) {
      subline = `Analisando o histórico de ${chatCount} ${chatCount === 1 ? 'conversa' : 'conversas'}.`;
    } else {
      subline = 'Processando o histórico das suas conversas.';
    }
  } else if (phase === PHASE_FINALIZING) {
    headline = 'Finalizando seu diagnóstico…';
    subline = 'Montando funil, oportunidades perdidas e benchmarks.';
  } else {
    // PHASE_SLOW — algo travou. Honesto.
    headline = 'Ainda processando…';
    subline = `A análise está demorando mais que o normal (${Math.round(elapsedMs / 1000)}s). Estamos aguardando o servidor responder — se passar de alguns minutos, volte aos relatórios e tente gerar de novo.`;
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
        {(chatCount > 0 || totalMsgs > 0) && (
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
              value={formatMsgs(displayedMsgs)}
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
