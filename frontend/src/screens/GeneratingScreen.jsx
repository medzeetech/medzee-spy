import { useEffect, useRef, useState } from 'react';
import {
  Wifi,
  MessageCircle,
  Activity,
  BarChart2,
  AlertCircle,
  Target,
  Sparkles,
  Check,
} from 'lucide-react';
import { COLORS } from '../constants/colors.js';
import { GEN_STEPS } from '../data/reportData.js';
import Logo from '../components/Logo.jsx';
import analiseAudio from '../assets/audio-analise.mp3';

const ICONS = { Wifi, MessageCircle, Activity, BarChart2, AlertCircle, Target, Sparkles };

export default function GeneratingScreen({ onComplete }) {
  const [active, setActive] = useState(0);
  const [done, setDone] = useState([]);
  const audioRef = useRef(null);

  // Garante que o play seja invocado mesmo se autoPlay for bloqueado em algum browser
  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;
    const tryPlay = el.play();
    if (tryPlay && typeof tryPlay.catch === 'function') {
      tryPlay.catch((e) => {
        if (e?.name !== 'AbortError') {
          console.warn('[Análise] Não foi possível reproduzir o áudio:', e);
        }
      });
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const timeouts = [];

    const run = (index) => {
      if (cancelled) return;
      if (index >= GEN_STEPS.length) {
        const t = setTimeout(() => {
          if (!cancelled) onComplete();
        }, 500);
        timeouts.push(t);
        return;
      }
      setActive(index);
      const t = setTimeout(() => {
        if (cancelled) return;
        setDone((prev) => [...prev, index]);
        run(index + 1);
      }, GEN_STEPS[index].duration);
      timeouts.push(t);
    };

    run(0);

    return () => {
      cancelled = true;
      timeouts.forEach(clearTimeout);
    };
  }, [onComplete]);

  const total = GEN_STEPS.length;
  const allDone = done.length === total;
  const fraction = (done.length + (active < total && !allDone ? 0.5 : allDone ? 0 : 0)) / total;
  const pct = Math.round(fraction * 100);

  return (
    <div
      className="flex flex-col items-center justify-center px-5"
      style={{
        minHeight: '100vh',
        background: COLORS.ink,
        color: COLORS.cream,
      }}
    >
      <audio ref={audioRef} src={analiseAudio} autoPlay preload="auto" />

      <div style={{ width: '100%', maxWidth: 440, margin: '0 auto' }}>
        <div className="flex justify-center" style={{ marginBottom: 52 }}>
          <Logo size="md" tone="dark" />
        </div>

        {/* Contador percentual */}
        <div style={{ textAlign: 'center', marginBottom: 36 }}>
          <div
            style={{
              fontSize: 56,
              fontWeight: 800,
              color: COLORS.cream,
              letterSpacing: '-0.04em',
              lineHeight: 1,
            }}
          >
            {pct}
            <span style={{ fontSize: 28, color: COLORS.orange, marginLeft: 2 }}>%</span>
          </div>
          <div
            style={{
              fontSize: 13,
              color: 'rgba(250,246,240,0.5)',
              letterSpacing: '0.04em',
              textTransform: 'uppercase',
              marginTop: 6,
            }}
          >
            Análise em andamento
          </div>
        </div>

        {/* Barra de progresso */}
        <div
          style={{
            height: 4,
            background: 'rgba(255,255,255,0.07)',
            borderRadius: 99,
            overflow: 'hidden',
            marginBottom: 36,
          }}
        >
          <div
            style={{
              height: '100%',
              width: `${pct}%`,
              transition: 'width 0.6s ease',
              background: `linear-gradient(90deg, ${COLORS.orangeDeep}, ${COLORS.orange})`,
              boxShadow: '0 0 12px rgba(255,107,53,0.6)',
            }}
          />
        </div>

        {/* Lista de passos */}
        <div className="flex flex-col" style={{ gap: 10 }}>
          {GEN_STEPS.map((step, i) => {
            const isDone = done.includes(i);
            const isActive = !isDone && i === active;
            const Icon = ICONS[step.icon];

            let opacity = 0.28;
            let textColor = 'rgba(250,246,240,0.4)';
            let fontWeight = 400;
            let iconBg = 'rgba(255,255,255,0.05)';
            let iconBorder = 'rgba(255,255,255,0.08)';
            let iconColor = 'rgba(250,246,240,0.4)';
            let translate = 0;

            if (isActive) {
              opacity = 1;
              textColor = COLORS.cream;
              fontWeight = 500;
              iconBg = 'rgba(255,107,53,0.2)';
              iconBorder = 'rgba(255,107,53,0.4)';
              iconColor = COLORS.orange;
              translate = 4;
            } else if (isDone) {
              opacity = 0.9;
              textColor = 'rgba(250,246,240,0.9)';
              fontWeight = 500;
              iconBg = 'rgba(37,211,102,0.2)';
              iconBorder = 'rgba(37,211,102,0.4)';
              iconColor = COLORS.wa;
            }

            return (
              <div
                key={i}
                className="flex items-center"
                style={{
                  gap: 14,
                  opacity,
                  transform: `translateX(${translate}px)`,
                  transition: 'all 0.4s ease',
                }}
              >
                <div
                  style={{
                    width: 32,
                    height: 32,
                    borderRadius: 9,
                    background: iconBg,
                    border: `1px solid ${iconBorder}`,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexShrink: 0,
                    transition: 'all 0.4s ease',
                  }}
                >
                  {isDone ? (
                    <Check size={16} color={iconColor} strokeWidth={2.5} />
                  ) : (
                    <span className={isActive ? 'anim-spin' : ''} style={{ display: 'flex' }}>
                      <Icon size={16} color={iconColor} strokeWidth={2.2} />
                    </span>
                  )}
                </div>
                <div
                  style={{
                    fontSize: 13.5,
                    color: textColor,
                    fontWeight,
                    transition: 'all 0.4s ease',
                  }}
                >
                  {step.label}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
