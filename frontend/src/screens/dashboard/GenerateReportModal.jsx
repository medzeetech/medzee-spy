// F5 — GenerateReportModal.
//
// Mudança vs F4: o filtro mudou de "janela temporal (7/15/30/60 dias)" pra
// "últimas N mensagens de cada conversa" — estratégia que funciona em
// qualquer tier uazapi (não depende do provider sincronizar histórico
// antigo). N controla cobertura comercial vs custo LLM.
//
// Error surface:
//   - 429 detail='too_many_generations_retry_in_Xs' → extract X, show countdown
//   - other → generic "try again"
// (F5: 422 'not_enough_data' não existe mais — relatório sempre dispara)
//
// On success, o parent navega pra /app/reports/{id} (polling F3 toma conta).

import { useState } from 'react';
import { Zap, MessageCircle, X, Loader2 } from 'lucide-react';
import { COLORS } from '../../constants/colors.js';
import { generateReport } from '../../lib/reports.js';

const N_OPTIONS = [
  { value: 10, label: '10 msgs por conversa', hint: 'Visão rápida' },
  { value: 20, label: '20 msgs por conversa', hint: 'Boa amostra' },
  { value: 30, label: '30 msgs por conversa', hint: 'Recomendado' },
  { value: 50, label: '50 msgs por conversa', hint: 'Análise profunda' },
];

export default function GenerateReportModal({ open, onClose, onSuccess }) {
  const [nPerChat, setNPerChat] = useState(30);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  if (!open) return null;

  const handleSubmit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const result = await generateReport({ n_per_chat: nPerChat });
      onSuccess(result.report_id);
    } catch (e) {
      if (e.status === 429) {
        const match = /retry_in_(\d+)s/.exec(e.detail || '');
        const secs = match ? match[1] : '60';
        setError(`Aguarde ${secs} segundos entre relatórios.`);
      } else {
        setError('Não foi possível gerar o relatório. Tente novamente.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleBackdropClick = (e) => {
    if (e.target === e.currentTarget && !submitting) {
      onClose();
    }
  };

  return (
    <div
      onClick={handleBackdropClick}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        padding: 20,
        fontFamily: "'Red Hat Display', sans-serif",
      }}
    >
      <div
        style={{
          background: COLORS.paper,
          border: `1px solid ${COLORS.hairline}`,
          borderRadius: 16,
          boxShadow: '0 20px 60px -12px rgba(0,0,0,0.25)',
          width: '100%',
          maxWidth: 420,
          padding: 24,
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between"
          style={{ marginBottom: 20 }}
        >
          <div className="flex items-center" style={{ gap: 12 }}>
            <div
              style={{
                width: 36,
                height: 36,
                borderRadius: 10,
                background: 'rgba(255,107,53,0.1)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: COLORS.orange,
              }}
            >
              <Zap size={18} />
            </div>
            <div>
              <div
                style={{ fontSize: 16, fontWeight: 700, color: COLORS.ink }}
              >
                Gerar relatório
              </div>
              <div style={{ fontSize: 12, color: COLORS.inkMute }}>
                Últimas mensagens de cada conversa
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            style={{
              width: 32,
              height: 32,
              borderRadius: 8,
              border: `1px solid ${COLORS.hairline}`,
              background: COLORS.paper,
              color: COLORS.inkSoft,
              cursor: submitting ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              opacity: submitting ? 0.5 : 1,
            }}
            aria-label="Fechar"
          >
            <X size={14} />
          </button>
        </div>

        {/* Explainer */}
        <div
          style={{
            fontSize: 12.5,
            color: COLORS.inkSoft,
            lineHeight: 1.5,
            marginBottom: 14,
            padding: '10px 12px',
            borderRadius: 10,
            background: COLORS.sunken,
          }}
        >
          A análise lê as <strong>últimas N mensagens</strong> de cada conversa
          do seu WhatsApp. Mais mensagens = análise mais profunda + tempo um
          pouco maior.
        </div>

        {/* N-per-chat selector */}
        <div
          className="flex flex-col"
          style={{ gap: 8, marginBottom: 20 }}
          role="radiogroup"
          aria-label="Mensagens por conversa"
        >
          {N_OPTIONS.map((opt) => {
            const isSelected = nPerChat === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                role="radio"
                aria-checked={isSelected}
                onClick={() => setNPerChat(opt.value)}
                disabled={submitting}
                className="flex items-center transition-all"
                style={{
                  gap: 12,
                  padding: '12px 14px',
                  borderRadius: 12,
                  border: `1px solid ${
                    isSelected ? COLORS.orange : COLORS.hairline
                  }`,
                  background: isSelected
                    ? 'rgba(255,107,53,0.08)'
                    : COLORS.paper,
                  color: isSelected ? COLORS.orange : COLORS.ink,
                  fontSize: 14,
                  fontWeight: isSelected ? 700 : 500,
                  cursor: submitting ? 'not-allowed' : 'pointer',
                  fontFamily: "'Red Hat Display', sans-serif",
                  textAlign: 'left',
                  width: '100%',
                  opacity: submitting ? 0.6 : 1,
                }}
              >
                <span
                  style={{
                    width: 18,
                    height: 18,
                    borderRadius: '50%',
                    border: `2px solid ${
                      isSelected ? COLORS.orange : COLORS.hairline
                    }`,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexShrink: 0,
                  }}
                >
                  {isSelected && (
                    <span
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: '50%',
                        background: COLORS.orange,
                      }}
                    />
                  )}
                </span>
                <MessageCircle
                  size={14}
                  style={{
                    color: isSelected ? COLORS.orange : COLORS.inkMute,
                    flexShrink: 0,
                  }}
                />
                <span style={{ flex: 1 }}>{opt.label}</span>
                <span
                  style={{
                    fontSize: 11,
                    color: isSelected ? COLORS.orange : COLORS.inkMute,
                    fontWeight: 500,
                  }}
                >
                  {opt.hint}
                </span>
              </button>
            );
          })}
        </div>

        {/* Error banner */}
        {error && (
          <div
            role="alert"
            style={{
              padding: '10px 12px',
              borderRadius: 10,
              background: 'rgba(92,29,46,0.08)',
              border: '1px solid rgba(92,29,46,0.2)',
              color: COLORS.wine,
              fontSize: 13,
              fontWeight: 500,
              lineHeight: 1.4,
              marginBottom: 16,
            }}
          >
            {error}
          </div>
        )}

        {/* Buttons */}
        <div className="flex" style={{ gap: 10 }}>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            style={{
              flex: 1,
              padding: '11px 16px',
              borderRadius: 12,
              border: `1px solid ${COLORS.hairline}`,
              background: COLORS.paper,
              color: COLORS.inkSoft,
              fontSize: 13.5,
              fontWeight: 600,
              cursor: submitting ? 'not-allowed' : 'pointer',
              fontFamily: "'Red Hat Display', sans-serif",
              opacity: submitting ? 0.5 : 1,
            }}
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting}
            className="inline-flex items-center justify-center transition-all"
            style={{
              flex: 1,
              gap: 8,
              padding: '11px 16px',
              borderRadius: 12,
              border: 'none',
              background: `linear-gradient(135deg, ${COLORS.orange}, ${COLORS.orangeDeep})`,
              color: COLORS.cream,
              fontSize: 13.5,
              fontWeight: 700,
              cursor: submitting ? 'wait' : 'pointer',
              fontFamily: "'Red Hat Display', sans-serif",
              boxShadow: '0 6px 20px -6px rgba(255,107,53,0.4)',
              opacity: submitting ? 0.85 : 1,
            }}
          >
            {submitting ? (
              <>
                <Loader2 size={14} className="anim-spin" />
                Gerando...
              </>
            ) : (
              <>
                <Zap size={14} />
                Gerar agora
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
