import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, LineChart, Line, CartesianGrid } from 'recharts';
import { TrendingUp, TrendingDown, Clock, MessageCircle, Target, Users } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';

const SCORE_HISTORY = [
  { month: 'Fev', score: 31 },
  { month: 'Mar', score: 35 },
  { month: 'Abr', score: 38 },
  { month: 'Mai', score: 42 },
];

const CONVERSION_HISTORY = [
  { month: 'Fev', taxa: 8.2 },
  { month: 'Mar', taxa: 10.1 },
  { month: 'Abr', taxa: 11.8 },
  { month: 'Mai', taxa: 12.4 },
];

const RESPONSE_HISTORY = [
  { month: 'Fev', tempo: 6.8 },
  { month: 'Mar', tempo: 5.9 },
  { month: 'Abr', tempo: 5.1 },
  { month: 'Mai', tempo: 4.4 },
];

const METRICS = [
  { label: 'Score geral', value: '42', unit: '/100', trend: '+4', positive: true, Icon: Target, color: COLORS.orange },
  { label: 'Taxa de conversão', value: '12.4', unit: '%', trend: '+0.6%', positive: true, Icon: Users, color: COLORS.wa },
  { label: 'Tempo 1a resposta', value: '4.4', unit: 'h', trend: '-0.7h', positive: true, Icon: Clock, color: COLORS.lavender },
  { label: 'Msgs analisadas', value: '3.370', unit: '', trend: '+530', positive: true, Icon: MessageCircle, color: COLORS.info },
];

function MetricCard({ label, value, unit, trend, positive, Icon, color }) {
  return (
    <div
      style={{
        background: COLORS.paper,
        border: `1px solid ${COLORS.hairline}`,
        borderRadius: 16,
        padding: 20,
        flex: '1 1 200px',
      }}
    >
      <div className="flex items-center justify-between" style={{ marginBottom: 12 }}>
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: 10,
            background: `${color}15`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color,
          }}
        >
          <Icon size={18} />
        </div>
        <div
          className="inline-flex items-center"
          style={{
            gap: 4,
            fontSize: 12,
            fontWeight: 600,
            color: positive ? COLORS.wa : '#E5604D',
            background: positive ? 'rgba(37,211,102,0.1)' : 'rgba(229,96,77,0.1)',
            padding: '3px 8px',
            borderRadius: 6,
          }}
        >
          {positive ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
          {trend}
        </div>
      </div>
      <div style={{ fontSize: 28, fontWeight: 800, color: COLORS.ink, letterSpacing: '-0.02em', lineHeight: 1 }}>
        {value}
        <span style={{ fontSize: 14, fontWeight: 500, color: COLORS.inkMute }}>{unit}</span>
      </div>
      <div style={{ fontSize: 12.5, color: COLORS.inkSoft, marginTop: 4 }}>{label}</div>
    </div>
  );
}

export default function DashboardPage() {
  return (
    <div style={{ maxWidth: 900 }}>
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ fontSize: 24, fontWeight: 800, color: COLORS.ink, margin: 0, letterSpacing: '-0.02em' }}>
          Dashboard
        </h1>
        <p style={{ fontSize: 14, color: COLORS.inkSoft, margin: 0, marginTop: 4 }}>
          Visão consolidada dos seus diagnósticos
        </p>
      </div>

      {/* Metric cards */}
      <div className="flex flex-wrap" style={{ gap: 14, marginBottom: 28 }}>
        {METRICS.map((m) => (
          <MetricCard key={m.label} {...m} />
        ))}
      </div>

      {/* Charts */}
      <div className="flex flex-wrap" style={{ gap: 14 }}>
        {/* Score evolution */}
        <div
          style={{
            background: COLORS.paper,
            border: `1px solid ${COLORS.hairline}`,
            borderRadius: 16,
            padding: 24,
            flex: '1 1 400px',
          }}
        >
          <div style={{ fontSize: 14, fontWeight: 700, color: COLORS.ink, marginBottom: 4 }}>
            Score ao longo do tempo
          </div>
          <div style={{ fontSize: 12, color: COLORS.inkMute, marginBottom: 20 }}>
            Baseado nos últimos 4 relatórios
          </div>
          <div style={{ width: '100%', height: 200 }}>
            <ResponsiveContainer>
              <LineChart data={SCORE_HISTORY}>
                <CartesianGrid strokeDasharray="3 3" stroke={COLORS.hairline} />
                <XAxis dataKey="month" tick={{ fontSize: 12, fill: COLORS.inkMute }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 12, fill: COLORS.inkMute }} />
                <Tooltip />
                <Line type="monotone" dataKey="score" stroke={COLORS.orange} strokeWidth={2.5} dot={{ r: 4, fill: COLORS.orange }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Conversion rate */}
        <div
          style={{
            background: COLORS.paper,
            border: `1px solid ${COLORS.hairline}`,
            borderRadius: 16,
            padding: 24,
            flex: '1 1 400px',
          }}
        >
          <div style={{ fontSize: 14, fontWeight: 700, color: COLORS.ink, marginBottom: 4 }}>
            Taxa de conversão
          </div>
          <div style={{ fontSize: 12, color: COLORS.inkMute, marginBottom: 20 }}>
            Benchmark setor: 24%
          </div>
          <div style={{ width: '100%', height: 200 }}>
            <ResponsiveContainer>
              <BarChart data={CONVERSION_HISTORY}>
                <CartesianGrid strokeDasharray="3 3" stroke={COLORS.hairline} />
                <XAxis dataKey="month" tick={{ fontSize: 12, fill: COLORS.inkMute }} />
                <YAxis domain={[0, 30]} tick={{ fontSize: 12, fill: COLORS.inkMute }} />
                <Tooltip />
                <Bar dataKey="taxa" fill={COLORS.orange} radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Response time */}
        <div
          style={{
            background: COLORS.paper,
            border: `1px solid ${COLORS.hairline}`,
            borderRadius: 16,
            padding: 24,
            flex: '1 1 100%',
          }}
        >
          <div style={{ fontSize: 14, fontWeight: 700, color: COLORS.ink, marginBottom: 4 }}>
            Tempo médio de 1a resposta
          </div>
          <div style={{ fontSize: 12, color: COLORS.inkMute, marginBottom: 20 }}>
            Benchmark setor: 0.8h
          </div>
          <div style={{ width: '100%', height: 200 }}>
            <ResponsiveContainer>
              <LineChart data={RESPONSE_HISTORY}>
                <CartesianGrid strokeDasharray="3 3" stroke={COLORS.hairline} />
                <XAxis dataKey="month" tick={{ fontSize: 12, fill: COLORS.inkMute }} />
                <YAxis domain={[0, 10]} tick={{ fontSize: 12, fill: COLORS.inkMute }} />
                <Tooltip />
                <Line type="monotone" dataKey="tempo" stroke={COLORS.lavender} strokeWidth={2.5} dot={{ r: 4, fill: COLORS.lavender }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
}
