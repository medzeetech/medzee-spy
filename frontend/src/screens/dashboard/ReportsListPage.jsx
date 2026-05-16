import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FileText, Clock, Zap, CalendarClock, Play, Settings2, Check } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';

const FREQUENCY_OPTIONS = [
  { label: '7 dias', value: 7 },
  { label: '15 dias', value: 15 },
  { label: '30 dias', value: 30 },
  { label: '60 dias', value: 60 },
];

const MOCK_REPORTS = [
  { id: '1', date: '2026-05-16T10:30:00', type: 'manual', messages: 3370, score: 42 },
  { id: '2', date: '2026-04-16T09:00:00', type: 'frequency', messages: 2840, score: 38 },
  { id: '3', date: '2026-03-16T09:00:00', type: 'frequency', messages: 2150, score: 35 },
  { id: '4', date: '2026-02-14T14:22:00', type: 'manual', messages: 1920, score: 31 },
];

function formatDate(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short', year: 'numeric' });
}

function formatTime(iso) {
  const d = new Date(iso);
  return d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}

export default function ReportsListPage() {
  const navigate = useNavigate();
  const [frequencyEnabled, setFrequencyEnabled] = useState(true);
  const [frequencyDays, setFrequencyDays] = useState(30);
  const [showFreqConfig, setShowFreqConfig] = useState(false);

  return (
    <div style={{ maxWidth: 800 }}>
      <div className="flex items-center justify-between" style={{ marginBottom: 28 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 800, color: COLORS.ink, margin: 0, letterSpacing: '-0.02em' }}>
            Relatórios
          </h1>
          <p style={{ fontSize: 14, color: COLORS.inkSoft, margin: 0, marginTop: 4 }}>
            Gerencie e visualize seus diagnósticos
          </p>
        </div>
        <button
          type="button"
          onClick={() => navigate('/app/reports/new')}
          className="inline-flex items-center transition-all"
          style={{
            gap: 8,
            padding: '10px 18px',
            borderRadius: 12,
            border: 'none',
            background: `linear-gradient(135deg, ${COLORS.orange}, ${COLORS.orangeDeep})`,
            color: COLORS.cream,
            fontSize: 13.5,
            fontWeight: 700,
            cursor: 'pointer',
            fontFamily: "'Red Hat Display', sans-serif",
            boxShadow: '0 6px 20px -6px rgba(255,107,53,0.4)',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.transform = 'translateY(-1px)';
            e.currentTarget.style.boxShadow = '0 10px 28px -6px rgba(255,107,53,0.55)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.transform = 'translateY(0)';
            e.currentTarget.style.boxShadow = '0 6px 20px -6px rgba(255,107,53,0.4)';
          }}
        >
          <Zap size={14} />
          Gerar relatório
        </button>
      </div>

      {/* Frequency config */}
      <div
        style={{
          background: COLORS.paper,
          border: `1px solid ${COLORS.hairline}`,
          borderRadius: 16,
          padding: 20,
          marginBottom: 24,
        }}
      >
        <div className="flex items-center justify-between" style={{ marginBottom: showFreqConfig ? 16 : 0 }}>
          <div className="flex items-center" style={{ gap: 12 }}>
            <div
              style={{
                width: 36,
                height: 36,
                borderRadius: 10,
                background: frequencyEnabled ? 'rgba(255,107,53,0.1)' : COLORS.sunken,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: frequencyEnabled ? COLORS.orange : COLORS.inkMute,
              }}
            >
              <CalendarClock size={18} />
            </div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, color: COLORS.ink }}>
                Geração automática
              </div>
              <div style={{ fontSize: 12, color: COLORS.inkMute }}>
                {frequencyEnabled
                  ? `Ativo · a cada ${frequencyDays} dias`
                  : 'Desativado'}
              </div>
            </div>
          </div>
          <div className="flex items-center" style={{ gap: 8 }}>
            <button
              type="button"
              onClick={() => setShowFreqConfig((v) => !v)}
              style={{
                width: 32,
                height: 32,
                borderRadius: 8,
                border: `1px solid ${COLORS.hairline}`,
                background: COLORS.paper,
                color: COLORS.inkSoft,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Settings2 size={14} />
            </button>
            {/* Toggle */}
            <button
              type="button"
              onClick={() => setFrequencyEnabled((v) => !v)}
              style={{
                width: 44,
                height: 24,
                borderRadius: 12,
                border: 'none',
                background: frequencyEnabled ? COLORS.orange : 'rgba(0,0,0,0.12)',
                cursor: 'pointer',
                position: 'relative',
                transition: 'background 0.2s ease',
              }}
            >
              <div
                style={{
                  width: 18,
                  height: 18,
                  borderRadius: '50%',
                  background: '#fff',
                  position: 'absolute',
                  top: 3,
                  left: frequencyEnabled ? 23 : 3,
                  transition: 'left 0.2s ease',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                }}
              />
            </button>
          </div>
        </div>

        {showFreqConfig && (
          <div className="flex" style={{ gap: 8 }}>
            {FREQUENCY_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setFrequencyDays(opt.value)}
                className="transition-all"
                style={{
                  padding: '8px 16px',
                  borderRadius: 10,
                  border: `1px solid ${frequencyDays === opt.value ? COLORS.orange : COLORS.hairline}`,
                  background: frequencyDays === opt.value ? 'rgba(255,107,53,0.08)' : COLORS.paper,
                  color: frequencyDays === opt.value ? COLORS.orange : COLORS.inkSoft,
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: 'pointer',
                  fontFamily: "'Red Hat Display', sans-serif",
                }}
              >
                {frequencyDays === opt.value && <Check size={12} style={{ marginRight: 4 }} />}
                {opt.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Reports list */}
      <div className="flex flex-col" style={{ gap: 10 }}>
        {MOCK_REPORTS.map((report) => (
          <button
            key={report.id}
            type="button"
            onClick={() => navigate(`/app/reports/${report.id}`)}
            className="flex items-center justify-between transition-all"
            style={{
              padding: '16px 20px',
              borderRadius: 14,
              border: `1px solid ${COLORS.hairline}`,
              background: COLORS.paper,
              cursor: 'pointer',
              width: '100%',
              textAlign: 'left',
              fontFamily: "'Red Hat Display', sans-serif",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = 'rgba(255,107,53,0.3)';
              e.currentTarget.style.boxShadow = '0 4px 16px -4px rgba(0,0,0,0.08)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = COLORS.hairline;
              e.currentTarget.style.boxShadow = 'none';
            }}
          >
            <div className="flex items-center" style={{ gap: 14 }}>
              <div
                style={{
                  width: 40,
                  height: 40,
                  borderRadius: 10,
                  background: report.type === 'frequency' ? 'rgba(184,168,217,0.15)' : 'rgba(255,107,53,0.1)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: report.type === 'frequency' ? COLORS.lavender : COLORS.orange,
                  flexShrink: 0,
                }}
              >
                {report.type === 'frequency' ? <CalendarClock size={18} /> : <Zap size={18} />}
              </div>
              <div>
                <div style={{ fontSize: 14, fontWeight: 600, color: COLORS.ink }}>
                  Diagnóstico · {formatDate(report.date)}
                </div>
                <div className="flex items-center" style={{ gap: 12, marginTop: 2 }}>
                  <span className="inline-flex items-center" style={{ gap: 4, fontSize: 12, color: COLORS.inkMute }}>
                    <Clock size={11} /> {formatTime(report.date)}
                  </span>
                  <span
                    className="inline-flex items-center"
                    style={{
                      gap: 4,
                      fontSize: 11,
                      padding: '2px 8px',
                      borderRadius: 6,
                      background: report.type === 'frequency' ? 'rgba(184,168,217,0.15)' : 'rgba(255,107,53,0.08)',
                      color: report.type === 'frequency' ? '#7B6BA8' : COLORS.orange,
                      fontWeight: 600,
                    }}
                  >
                    {report.type === 'frequency' ? 'Frequência' : 'Pontual'}
                  </span>
                  <span style={{ fontSize: 12, color: COLORS.inkMute }}>
                    {report.messages.toLocaleString('pt-BR')} msgs
                  </span>
                </div>
              </div>
            </div>
            <div
              style={{
                fontSize: 22,
                fontWeight: 800,
                color: COLORS.orange,
                letterSpacing: '-0.02em',
              }}
            >
              {report.score}
              <span style={{ fontSize: 12, color: COLORS.inkMute, fontWeight: 500 }}>/100</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
