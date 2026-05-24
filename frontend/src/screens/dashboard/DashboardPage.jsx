// F4 polish — Dashboard with REAL data (no more mocks).
//
// Behavior:
// - Loading: skeleton minimal.
// - Sem relatórios: empty state CTA → /app/whatsapp (extensão).
// - Tem relatórios: cards de métrica usam o último relatório completo;
//   charts usam os 4 mais recentes ordenados por data ASC.
//
// Pra agregar, lemos da lista paginada /api/reports/?page=1&page_size=20
// (já existente). Cada item da lista tem score + message_count + created_at.
// Pra "Taxa de conversão" e "Tempo 1ª resposta" precisamos do payload
// completo — buscamos o relatório mais recente via /api/reports/latest.
//
// M2: WhatsApp/uazapi telemetry removida do dashboard. A ingestão agora roda
// pela extensão Chrome — qualquer status "ao vivo" é exibido em /app/whatsapp.

import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, CartesianGrid,
} from 'recharts';
import {
  TrendingUp, TrendingDown, Clock, MessageCircle, Target, Users, FileText,
} from 'lucide-react';
import { COLORS } from '../../constants/colors.js';
import { listReports, getReport } from '../../lib/reports.js';

const PT_MONTH_LABEL = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'];

function shortMonth(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return PT_MONTH_LABEL[d.getMonth()] || '';
}

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
        {trend != null && (
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
        )}
      </div>
      <div
        style={{
          fontSize: 28,
          fontWeight: 800,
          color: COLORS.ink,
          letterSpacing: '-0.02em',
          lineHeight: 1,
        }}
      >
        {value}
        <span style={{ fontSize: 14, fontWeight: 500, color: COLORS.inkMute }}>{unit}</span>
      </div>
      <div style={{ fontSize: 12.5, color: COLORS.inkSoft, marginTop: 4 }}>{label}</div>
    </div>
  );
}

function EmptyState() {
  return (
    <div
      style={{
        background: COLORS.paper,
        border: `1px solid ${COLORS.hairline}`,
        borderRadius: 20,
        padding: 'clamp(28px, 4vw, 40px)',
        textAlign: 'center',
        marginTop: 8,
      }}
    >
      <div
        style={{
          width: 56,
          height: 56,
          borderRadius: 14,
          background: 'rgba(255,107,53,0.1)',
          color: COLORS.orange,
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          marginBottom: 16,
        }}
      >
        <FileText size={26} />
      </div>
      <h2
        style={{
          fontSize: 22,
          fontWeight: 800,
          color: COLORS.ink,
          margin: 0,
          marginBottom: 8,
          letterSpacing: '-0.02em',
        }}
      >
        Sem relatórios ainda
      </h2>
      <p
        style={{
          fontSize: 14,
          color: COLORS.inkSoft,
          lineHeight: 1.55,
          margin: 0,
          marginBottom: 22,
          maxWidth: 520,
          marginLeft: 'auto',
          marginRight: 'auto',
        }}
      >
        Gere sua primeira análise rodando a extensão Medzee Spy no WhatsApp Web.
      </p>
      <Link
        to="/app/whatsapp"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 8,
          padding: '12px 22px',
          borderRadius: 12,
          background: `linear-gradient(135deg, ${COLORS.orange}, ${COLORS.orangeDeep})`,
          color: COLORS.cream,
          fontSize: 14,
          fontWeight: 700,
          textDecoration: 'none',
          fontFamily: "'Red Hat Display', sans-serif",
          boxShadow: '0 6px 20px -6px rgba(255,107,53,0.4)',
        }}
      >
        Ver extensão
      </Link>
    </div>
  );
}

function ChartCard({ title, subtitle, children, fullWidth }) {
  return (
    <div
      style={{
        background: COLORS.paper,
        border: `1px solid ${COLORS.hairline}`,
        borderRadius: 16,
        padding: 24,
        flex: fullWidth ? '1 1 100%' : '1 1 400px',
      }}
    >
      <div style={{ fontSize: 14, fontWeight: 700, color: COLORS.ink, marginBottom: 4 }}>
        {title}
      </div>
      <div style={{ fontSize: 12, color: COLORS.inkMute, marginBottom: 20 }}>
        {subtitle}
      </div>
      <div style={{ width: '100%', height: 200 }}>{children}</div>
    </div>
  );
}

export default function DashboardPage() {
  const [state, setState] = useState({ loading: true, reports: [], latest: null, error: null });

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const list = await listReports({ page: 1, pageSize: 20 });
        if (!alive) return;
        const reports = list?.items || [];
        // Tenta carregar o relatório mais recente completed pra payload (taxa
        // conversão real + benchmark do funnel etc).
        const latestId = reports.find((r) => r.status === 'completed' || r.status === 'partial')?.id;
        let latest = null;
        if (latestId) {
          try {
            latest = await getReport(latestId);
          } catch {
            latest = null;
          }
        }
        if (alive) setState({ loading: false, reports, latest, error: null });
      } catch (e) {
        if (alive)
          setState({
            loading: false,
            reports: [],
            latest: null,
            error: e.detail || `http_${e.status ?? 'unknown'}`,
          });
      }
    }
    load();
    return () => { alive = false; };
  }, []);

  const completedReports = useMemo(
    () => state.reports.filter((r) => r.status === 'completed' || r.status === 'partial'),
    [state.reports],
  );

  // Históricos: 4 últimos relatórios em ordem ascendente, com score+date.
  const scoreSeries = useMemo(() => {
    const recent = [...completedReports]
      .sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
      .slice(-4);
    return recent.map((r) => ({
      label: shortMonth(r.created_at),
      score: r.score ?? 0,
      msgs: r.message_count ?? 0,
    }));
  }, [completedReports]);

  if (state.loading) {
    return (
      <div style={{ maxWidth: 900 }}>
        <h1 style={{ fontSize: 24, fontWeight: 800, color: COLORS.ink, margin: 0, letterSpacing: '-0.02em' }}>
          Dashboard
        </h1>
        <p style={{ fontSize: 14, color: COLORS.inkSoft, margin: 0, marginTop: 4 }}>
          Carregando…
        </p>
      </div>
    );
  }

  const header = (
    <div style={{ marginBottom: 28 }}>
      <h1 style={{ fontSize: 24, fontWeight: 800, color: COLORS.ink, margin: 0, letterSpacing: '-0.02em' }}>
        Dashboard
      </h1>
      <p style={{ fontSize: 14, color: COLORS.inkSoft, margin: 0, marginTop: 4 }}>
        Visão consolidada dos seus diagnósticos
      </p>
    </div>
  );

  if (completedReports.length === 0) {
    return (
      <div style={{ maxWidth: 900 }}>
        {header}
        <EmptyState />
      </div>
    );
  }

  // Métricas top-level vêm do relatório mais recente completed.
  const latest = state.latest;
  const latestPayload = latest?.payload || null;

  const conversionPct = (() => {
    if (!latestPayload?.funnel || latestPayload.funnel.length < 5) return null;
    return latestPayload.funnel[4]?.pct ?? null;
  })();

  // Tempo médio de 1ª resposta: usar bucket médio ponderado da
  // response_time_distribution se existir.
  const avgResponseH = (() => {
    if (!latestPayload?.response_time_distribution) return null;
    const buckets = latestPayload.response_time_distribution;
    const midpoints = [5 / 60 / 2, (5 + 30) / 60 / 2, (30 / 60 + 1) / 2, (1 + 4) / 2, (4 + 24) / 2, 36];
    const total = buckets.reduce((s, b) => s + (b.count || 0), 0);
    if (total === 0) return null;
    const weighted = buckets.reduce((s, b, i) => s + (b.count || 0) * midpoints[i], 0);
    return Math.round((weighted / total) * 10) / 10; // 1 casa decimal
  })();

  // Trend vs penúltimo relatório (se houver).
  const prevReport = scoreSeries.length >= 2 ? scoreSeries[scoreSeries.length - 2] : null;
  const scoreDelta = prevReport ? (latest?.score ?? 0) - prevReport.score : null;
  const msgsDelta = prevReport ? (latest?.message_count ?? 0) - prevReport.msgs : null;

  const metrics = [
    {
      label: 'Score geral',
      value: latest?.score != null ? String(latest.score) : '—',
      unit: '/100',
      trend: scoreDelta != null ? `${scoreDelta >= 0 ? '+' : ''}${scoreDelta}` : null,
      positive: scoreDelta == null ? true : scoreDelta >= 0,
      Icon: Target,
      color: COLORS.orange,
    },
    {
      label: 'Taxa de conversão',
      value: conversionPct != null ? conversionPct.toFixed(1) : '—',
      unit: '%',
      trend: null,
      positive: true,
      Icon: Users,
      color: COLORS.wa,
    },
    {
      label: 'Tempo 1ª resposta',
      value: avgResponseH != null ? avgResponseH.toFixed(1) : '—',
      unit: 'h',
      trend: null,
      positive: true,
      Icon: Clock,
      color: COLORS.lavender,
    },
    {
      label: 'Msgs analisadas',
      value: latest?.message_count != null ? latest.message_count.toLocaleString('pt-BR') : '—',
      unit: '',
      trend:
        msgsDelta != null
          ? `${msgsDelta >= 0 ? '+' : ''}${msgsDelta.toLocaleString('pt-BR')}`
          : null,
      positive: msgsDelta == null ? true : msgsDelta >= 0,
      Icon: MessageCircle,
      color: COLORS.info,
    },
  ];

  // Banner discreto quando o último relatório é insufficient — guia o user
  // a gerar um novo em vez de mostrar cards zerados sem contexto.
  const isInsufficient = latestPayload?.data_quality === 'insufficient';

  return (
    <div style={{ maxWidth: 900 }}>
      {header}

      {isInsufficient && (
        <div
          style={{
            background: 'rgba(232,179,60,0.12)',
            border: '1px solid rgba(232,179,60,0.45)',
            borderRadius: 12,
            padding: '12px 16px',
            marginBottom: 14,
            fontSize: 13,
            color: COLORS.ink,
            lineHeight: 1.5,
          }}
        >
          O último relatório foi gerado sem mensagens suficientes — os cards
          abaixo estão zerados.{' '}
          <Link
            to="/app/reports"
            style={{ color: COLORS.orange, fontWeight: 600, textDecoration: 'none' }}
          >
            Gerar novo relatório →
          </Link>
        </div>
      )}

      <div className="flex flex-wrap" style={{ gap: 14, marginBottom: 28 }}>
        {metrics.map((m) => <MetricCard key={m.label} {...m} />)}
      </div>

      <div className="flex flex-wrap" style={{ gap: 14 }}>
        <ChartCard
          title="Score ao longo do tempo"
          subtitle={`Baseado nos últimos ${scoreSeries.length} relatório${scoreSeries.length > 1 ? 's' : ''}`}
        >
          <ResponsiveContainer>
            <LineChart data={scoreSeries}>
              <CartesianGrid strokeDasharray="3 3" stroke={COLORS.hairline} />
              <XAxis dataKey="label" tick={{ fontSize: 12, fill: COLORS.inkMute }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 12, fill: COLORS.inkMute }} />
              <Tooltip />
              <Line
                type="monotone"
                dataKey="score"
                stroke={COLORS.orange}
                strokeWidth={2.5}
                dot={{ r: 4, fill: COLORS.orange }}
              />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard
          title="Mensagens por relatório"
          subtitle="Volume analisado em cada relatório gerado"
        >
          <ResponsiveContainer>
            <BarChart data={scoreSeries}>
              <CartesianGrid strokeDasharray="3 3" stroke={COLORS.hairline} />
              <XAxis dataKey="label" tick={{ fontSize: 12, fill: COLORS.inkMute }} />
              <YAxis tick={{ fontSize: 12, fill: COLORS.inkMute }} />
              <Tooltip />
              <Bar dataKey="msgs" fill={COLORS.orange} radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>
    </div>
  );
}
