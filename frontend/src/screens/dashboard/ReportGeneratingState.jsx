import { useEffect, useRef, useState } from 'react';
import { Sparkles, MessageCircle, Brain, Wifi } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';
import { useUazapiStats, useWhatsappStatus } from '../../lib/whatsapp.js';

// F5: 3 fases reais + contagem animada de msgs.
//
// Fase 1: COLETANDO        — uazapiStats.chat_count (real, ao vivo)
//                            + msgs animadas de 0 → totalCaptured em ~3s
// Fase 2: SINCRONIZANDO    — chat_count > 0, animação já terminou,
//                            mostra total real (vem do captured_messages
//                            via /api/whatsapp/status)
// Fase 3: IA ANALISANDO    — backend já recebeu payload, LLM rodando
//                            (heurística temporal — uazapiStats não revela isso)
//
// O elapsedMs vem do polling de /api/reports/{id}; >=30s presume LLM.
//
// A contagem de mensagens animada é DELIBERADA (não é mock): o total real
// vem do snapshot captured_messages, mas a UX simula a leitura
// progressivamente em ~3s pra dar feedback visual de "lendo agora".
// Quando atinge o total, congela no número certo.

const PHASE_PULL = 'pull';
const PHASE_LLM = 'llm';
const PHASE_FINALIZING = 'finalizing';

// Duração da animação de contagem (de 0 → total).
const COUNT_ANIMATION_MS = 3000;
// Frequência de tick: 60ms ≈ 50 frames em 3s — smooth sem custar nada.
const COUNT_TICK_MS = 60;

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

// Hook que anima um contador de 0 → target em duração fixa. Quando target
// mudar (ex.: polling refresh do status sobe), continua de onde está e
// re-ajusta o passo. Idempotente: chamadas com mesmo target não reiniciam.
//
// Nota implementação: o reset pra 0 quando target=0 não vai num setValue
// no body do effect (lint react/set-state-in-effect). Em vez disso, o
// próprio interval cuida do display: enquanto target=0, o effect nem
// arranca, e o último valor anterior fica congelado. Quando target sobe,
// arranca a animação a partir do valor atual.
function useAnimatedCount(target) {
  const [value, setValue] = useState(0);
  const startRef = useRef(null);
  const startValueRef = useRef(0);

  useEffect(() => {
    if (target <= 0) {
      // Sem animação: o display fica no último valor. Não setState aqui.
      return undefined;
    }
    // Snapshot do estado atual no momento que arranca a animação.
    startRef.current = Date.now();
    let startValue = startValueRef.current;
    setValue((prev) => {
      startValue = prev;
      startValueRef.current = prev;
      return prev;
    });

    const handle = setInterval(() => {
      const elapsed = Date.now() - startRef.current;
      const ratio = Math.min(1, elapsed / COUNT_ANIMATION_MS);
      // Ease-out: rápido no começo, suaviza no fim.
      const eased = 1 - Math.pow(1 - ratio, 2);
      const next = Math.floor(startValue + (target - startValue) * eased);
      setValue(next >= target ? target : next);
      if (ratio >= 1) {
        clearInterval(handle);
      }
    }, COUNT_TICK_MS);

    return () => clearInterval(handle);
  }, [target]);

  return value;
}

export default function ReportGeneratingState({ elapsedMs = 0 }) {
  // 2 fontes:
  //   - useUazapiStats: chat_count ao vivo via uazapi /chat/find
  //   - useWhatsappStatus: message_count do captured_messages (total
  //     real persistido localmente — é esse que animamos)
  const uazapiStats = useUazapiStats({ enabled: true, intervalMs: 3000 });
  const { status: waStatus } = useWhatsappStatus();
  const chatCount = uazapiStats?.stats?.chat_count ?? 0;
  const totalCapturedMsgs = waStatus?.message_count ?? 0;

  // Anima 0 → total em ~3s. Quando totalCapturedMsgs é 0, fica em 0.
  const animatedMsgCount = useAnimatedCount(totalCapturedMsgs);

  const hasData = chatCount > 0 || totalCapturedMsgs > 0;
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
    headline = hasData ? 'Lendo suas conversas…' : 'Conectando ao WhatsApp…';
    if (totalCapturedMsgs > 0) {
      subline = `Lendo ${animatedMsgCount.toLocaleString('pt-BR')} de ${totalCapturedMsgs.toLocaleString('pt-BR')} mensagens em ${chatCount} ${chatCount === 1 ? 'conversa' : 'conversas'}.`;
    } else if (chatCount > 0) {
      subline = `Já vimos ${chatCount} ${chatCount === 1 ? 'conversa' : 'conversas'} no seu WhatsApp.`;
    } else {
      subline = 'Buscando a lista de conversas no seu WhatsApp.';
    }
  } else if (phase === PHASE_LLM) {
    const msgs = totalCapturedMsgs || animatedMsgCount;
    headline = 'IA analisando o conteúdo…';
    subline = `Cruzando ${msgs.toLocaleString('pt-BR')} mensagens de ${chatCount} ${chatCount === 1 ? 'conversa' : 'conversas'} pra gerar insights.`;
  } else {
    headline = 'Finalizando seu diagnóstico…';
    subline = 'Montando funil, oportunidades perdidas e benchmarks.';
  }

  // O valor exibido na pill de msgs:
  //   - durante PULL: o contador animado (cresce visualmente)
  //   - durante LLM/FINALIZING: o total fixo
  const displayedMsgs = phase === PHASE_PULL ? animatedMsgCount : totalCapturedMsgs;

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
        {(chatCount > 0 || totalCapturedMsgs > 0) && (
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
              value={displayedMsgs.toLocaleString('pt-BR')}
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
