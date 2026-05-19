import { Sparkles, MessageCircle, Brain, Wifi } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';
import { useUazapiStats, useWhatsappStatus } from '../../lib/whatsapp.js';

// F5: 3 fases reais + contagem de msgs derivada da porcentagem.
//
// Fase 1: COLETANDO        — uazapiStats.chat_count (real, ao vivo)
//                            + msgs cresce proporcional a pct (mesma curva
//                            da barra de progresso → UX coesa)
// Fase 2: SINCRONIZANDO    — chat_count > 0, msgs no total real
//                            (vem do captured_messages via /whatsapp/status)
// Fase 3: IA ANALISANDO    — backend já recebeu payload, LLM rodando
//                            (heurística temporal — uazapiStats não revela isso)
//
// O elapsedMs vem do polling de /api/reports/{id}; >=30s presume LLM.
//
// A contagem visualmente cresce sincronizada com a porcentagem (mesma
// derivação temporal), não em curva própria — o user vê "8.623 mensagens"
// chegar no exato instante em que a barra atinge 50% (fim da fase PULL).
// Daí em diante (LLM/FINALIZING) congela no total real enquanto a barra
// continua subindo (mas é o LLM agora, não mais leitura).

const PHASE_PULL = 'pull';
const PHASE_LLM = 'llm';
const PHASE_FINALIZING = 'finalizing';

// Fase PULL termina em pct=50% (ver computeProgress). A contagem de msgs
// é normalizada por esse 50% pra atingir 100% no fim da fase PULL.
const PULL_END_PCT = 50;

// Quando captured_messages.message_count está em 0 (sessão nova, webhook
// ainda não chegou OU pipeline F5 vai puxar direto da uazapi via fallback),
// estimamos o total como chatCount * AVG_MSGS_PER_CHAT. AVG é o n_per_chat
// padrão do GenerateReportModal (30 = "Recomendado"). É uma estimativa
// honesta — mostramos com prefixo "~" pra deixar claro.
const AVG_MSGS_PER_CHAT_ESTIMATE = 30;

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
  const phase = pickPhase(elapsedMs, hasData);

  // Progresso aproximado: 0-30s = 0-50% (pull), 30-90s = 50-90% (LLM),
  // 90s+ = 90-98% (finalizing). Cap em 98%.
  let pct;
  if (phase === PHASE_PULL) {
    pct = Math.min(PULL_END_PCT, (elapsedMs / 30_000) * PULL_END_PCT);
  } else if (phase === PHASE_LLM) {
    pct = PULL_END_PCT + Math.min(40, ((elapsedMs - 30_000) / 60_000) * 40);
  } else {
    pct = 90 + Math.min(8, ((elapsedMs - 90_000) / 60_000) * 8);
  }
  pct = Math.round(pct);

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
