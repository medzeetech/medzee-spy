import { Mic, MicOff } from 'lucide-react';
import { COLORS } from '../constants/colors.js';

export default function AudioVisualizer({ volume = 0, isSpeaking = false, status = 'disconnected' }) {
  const connected = status === 'connected';
  const idle = !connected;

  // Cores conforme estado
  const accent = isSpeaking ? COLORS.orange : COLORS.wa;
  const accentSoft = isSpeaking ? 'rgba(255,107,53,' : 'rgba(37,211,102,';

  // Halo externo: reage ao volume
  const haloScale = 1 + (connected ? volume * 0.18 : 0);
  const haloGlow = isSpeaking
    ? `0 0 60px rgba(255,107,53,${0.25 + volume * 0.55}), 0 0 120px rgba(255,107,53,${0.1 + volume * 0.3})`
    : connected
      ? `0 0 40px rgba(37,211,102,${0.15 + volume * 0.25})`
      : '0 0 30px rgba(255,107,53,0.08)';

  const midBorder = idle
    ? 'rgba(250,246,240,0.12)'
    : isSpeaking
      ? 'rgba(255,107,53,0.6)'
      : 'rgba(37,211,102,0.4)';

  const innerScale = 1 + (connected ? volume * 0.12 : 0);

  return (
    <div
      style={{
        position: 'relative',
        width: 280,
        height: 280,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        opacity: idle ? 0.55 : 1,
        transition: 'opacity 0.4s ease',
      }}
    >
      {/* Halo externo */}
      <div
        style={{
          position: 'absolute',
          width: 280,
          height: 280,
          borderRadius: '50%',
          background: idle
            ? 'radial-gradient(circle, rgba(255,107,53,0.04), transparent 70%)'
            : `radial-gradient(circle, ${accentSoft}${0.08 + volume * 0.12}), transparent 70%)`,
          boxShadow: haloGlow,
          transform: `scale(${haloScale})`,
          transition: 'transform 0.12s ease, box-shadow 0.12s ease, background 0.4s ease',
        }}
      />

      {/* Anel médio com rotação lenta */}
      <div
        className={connected ? 'anim-rotate-slow' : ''}
        style={{
          position: 'absolute',
          width: 200,
          height: 200,
          borderRadius: '50%',
          border: `1.5px solid ${midBorder}`,
          borderTopColor: idle ? midBorder : accent,
          transition: 'border-color 0.4s ease',
        }}
      />

      {/* Segundo anel decorativo, contra-rotação */}
      {connected && (
        <div
          className="anim-rotate-slow"
          style={{
            position: 'absolute',
            width: 230,
            height: 230,
            borderRadius: '50%',
            border: `1px dashed ${accentSoft}0.2)`,
            animationDuration: '45s',
            animationDirection: 'reverse',
          }}
        />
      )}

      {/* Anel interno — gradiente pulsante */}
      <div
        style={{
          position: 'absolute',
          width: 140,
          height: 140,
          borderRadius: '50%',
          background: idle
            ? 'radial-gradient(circle at 30% 30%, rgba(255,107,53,0.15), rgba(26,20,16,0.4) 70%)'
            : `radial-gradient(circle at 30% 30%, ${accentSoft}${0.4 + volume * 0.4}), rgba(26,20,16,0.6) 75%)`,
          transform: `scale(${innerScale})`,
          transition: 'transform 0.08s ease, background 0.3s ease',
          border: `1px solid ${idle ? 'rgba(255,107,53,0.18)' : `${accentSoft}0.35)`}`,
        }}
      />

      {/* Núcleo central */}
      <div
        style={{
          position: 'relative',
          width: 80,
          height: 80,
          borderRadius: '50%',
          background: idle
            ? `linear-gradient(135deg, ${COLORS.wineDeep}, ${COLORS.ink})`
            : `linear-gradient(135deg, ${COLORS.wineDeep}, ${COLORS.wine})`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow: idle
            ? '0 6px 24px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.06)'
            : `0 8px 32px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.1), 0 0 ${20 + volume * 30}px ${accentSoft}${0.3 + volume * 0.3})`,
          transition: 'box-shadow 0.12s ease, background 0.4s ease',
          border: `1px solid ${idle ? 'rgba(255,107,53,0.2)' : `${accentSoft}0.4)`}`,
        }}
      >
        {idle ? (
          <MicOff size={28} color={COLORS.inkMute} strokeWidth={2} />
        ) : (
          <Mic size={28} color={accent} strokeWidth={2.2} />
        )}
      </div>
    </div>
  );
}
