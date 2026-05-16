import { COLORS } from '../../constants/colors.js';

export default function SectionHeader({ kicker, title, sub }) {
  return (
    <div style={{ marginBottom: 24 }}>
      <div
        style={{
          fontSize: 10.5,
          color: COLORS.orangeDeep,
          textTransform: 'uppercase',
          letterSpacing: '0.18em',
          fontWeight: 600,
          marginBottom: 10,
        }}
      >
        {kicker}
      </div>
      <h2
        style={{
          fontSize: 'clamp(22px, 3vw, 30px)',
          fontWeight: 700,
          letterSpacing: '-0.02em',
          color: COLORS.ink,
          margin: 0,
          marginBottom: 10,
          lineHeight: 1.15,
        }}
      >
        {title}
      </h2>
      <p
        style={{
          fontSize: 14,
          color: COLORS.inkSoft,
          maxWidth: 620,
          margin: 0,
          lineHeight: 1.55,
        }}
      >
        {sub}
      </p>
    </div>
  );
}
