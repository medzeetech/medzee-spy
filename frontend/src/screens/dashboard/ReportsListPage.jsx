import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { FileText, Clock, Zap, CalendarClock, Settings2, Check } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';
import { listReports } from '../../lib/reports.js';
import GenerateReportModal from './GenerateReportModal.jsx';

const FREQUENCY_OPTIONS = [
  { label: '7 dias', value: 7 },
  { label: '15 dias', value: 15 },
  { label: '30 dias', value: 30 },
  { label: '60 dias', value: 60 },
];

const TERMINAL = new Set(['completed', 'partial', 'failed']);

function formatDateTimePt(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  const date = d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  const time = d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  return `${date} às ${time}`;
}

function GeneratingChip() {
  return (
    <span
      className="inline-flex items-center"
      style={{
        gap: 8,
        padding: '6px 12px',
        borderRadius: 99,
        background: 'rgba(255,107,53,0.1)',
        border: '1px solid rgba(255,107,53,0.25)',
        color: COLORS.orangeDeep,
        fontSize: 12,
        fontWeight: 700,
        letterSpacing: '0.02em',
      }}
    >
      <span
        className="anim-pulse-dot"
        style={{
          width: 7,
          height: 7,
          borderRadius: 99,
          background: COLORS.orange,
          boxShadow: '0 0 8px rgba(255,107,53,0.6)',
        }}
      />
      Gerando...
    </span>
  );
}

function FailedChip() {
  return (
    <span
      style={{
        padding: '4px 10px',
        borderRadius: 99,
        background: 'rgba(92,29,46,0.1)',
        color: COLORS.wine,
        fontSize: 11.5,
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.1em',
      }}
    >
      Falhou
    </span>
  );
}

export default function ReportsListPage() {
  const navigate = useNavigate();
  const [frequencyEnabled, setFrequencyEnabled] = useState(true);
  const [frequencyDays, setFrequencyDays] = useState(30);
  const [showFreqConfig, setShowFreqConfig] = useState(false);

  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    listReports({ page: 1 })
      .then((res) => {
        if (!alive) return;
        setData(res);
        setError(null);
      })
      .catch((e) => {
        if (!alive) return;
        setError(e);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const items = data?.items ?? [];

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
          onClick={() => setModalOpen(true)}
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
      {loading && (
        <div
          style={{
            padding: '40px 20px',
            borderRadius: 14,
            border: `1px solid ${COLORS.hairline}`,
            background: COLORS.paper,
            textAlign: 'center',
            color: COLORS.inkSoft,
            fontSize: 13.5,
          }}
        >
          Carregando relatórios...
        </div>
      )}

      {!loading && error && (
        <div
          style={{
            padding: '20px',
            borderRadius: 14,
            border: `1px solid ${COLORS.hairline}`,
            background: COLORS.paper,
            color: COLORS.wine,
            fontSize: 13.5,
            fontWeight: 500,
          }}
        >
          Não foi possível carregar os relatórios. Atualize a página.
        </div>
      )}

      {!loading && !error && items.length === 0 && (
        <div
          style={{
            padding: '32px 24px',
            borderRadius: 14,
            border: `1px dashed ${COLORS.hairline}`,
            background: COLORS.paper,
            color: COLORS.inkSoft,
            fontSize: 13.5,
            lineHeight: 1.5,
            textAlign: 'center',
          }}
        >
          <FileText size={24} style={{ color: COLORS.inkMute, marginBottom: 10 }} />
          <div>
            Você ainda não tem relatórios. Conecte seu WhatsApp em{' '}
            <Link to="/spy" style={{ color: COLORS.orange, fontWeight: 600 }}>
              /spy
            </Link>{' '}
            para gerar o primeiro.
          </div>
        </div>
      )}

      {!loading && !error && items.length > 0 && (
        <div className="flex flex-col" style={{ gap: 10 }}>
          {items.map((report) => {
            const isGenerating = !TERMINAL.has(report.status);
            const isFailed = report.status === 'failed';
            return (
              <Link
                key={report.id}
                to={`/app/reports/${report.id}`}
                className="flex items-center justify-between transition-all"
                style={{
                  padding: '16px 20px',
                  borderRadius: 14,
                  border: `1px solid ${COLORS.hairline}`,
                  background: COLORS.paper,
                  cursor: 'pointer',
                  width: '100%',
                  textAlign: 'left',
                  textDecoration: 'none',
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
                      background: 'rgba(255,107,53,0.1)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: COLORS.orange,
                      flexShrink: 0,
                    }}
                  >
                    <Zap size={18} />
                  </div>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 600, color: COLORS.ink }}>
                      Diagnóstico · {formatDateTimePt(report.created_at)}
                    </div>
                    <div className="flex items-center" style={{ gap: 12, marginTop: 4 }}>
                      {typeof report.message_count === 'number' && (
                        <span className="inline-flex items-center" style={{ gap: 4, fontSize: 12, color: COLORS.inkMute }}>
                          <Clock size={11} />
                          {report.message_count.toLocaleString('pt-BR')} mensagens
                        </span>
                      )}
                      {typeof report.period_days === 'number' && (
                        <span className="inline-flex items-center" style={{ gap: 4, fontSize: 12, color: COLORS.inkMute }}>
                          <CalendarClock size={11} />
                          Análise de {report.period_days} dias
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                <div className="flex items-center" style={{ gap: 12 }}>
                  {isGenerating ? (
                    <GeneratingChip />
                  ) : isFailed ? (
                    <FailedChip />
                  ) : (
                    <div
                      style={{
                        fontSize: 22,
                        fontWeight: 800,
                        color: COLORS.orange,
                        letterSpacing: '-0.02em',
                      }}
                    >
                      {typeof report.score === 'number' ? report.score : '—'}
                      <span style={{ fontSize: 12, color: COLORS.inkMute, fontWeight: 500 }}>
                        {' '}/ 100
                      </span>
                    </div>
                  )}
                </div>
              </Link>
            );
          })}
        </div>
      )}

      <GenerateReportModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSuccess={(reportId) => {
          setModalOpen(false);
          navigate(`/app/reports/${reportId}`);
        }}
      />
    </div>
  );
}
