import React from 'react';

const SummarySection = ({ extractedText, summary, onGenerateSummary, isLoading }) => {
  if (!extractedText) {
    return null;
  }

  const compression =
    summary?.original_length && summary?.summary_length
      ? Math.max(1, Math.round((summary.summary_length / summary.original_length) * 100))
      : null;

  return (
    <section className="glass-card section-appear">
      <div className="section-header">
        <div>
          <h2 className="section-title">Smart Summary</h2>
          <p className="section-subtitle">Turn long material into a concentrated revision brief.</p>
        </div>
        <button className="btn-neon" onClick={onGenerateSummary} disabled={isLoading}>
          {isLoading ? 'Summarizing…' : 'Generate Summary'}
        </button>
      </div>

      {summary ? (
        <div className="summary-shell">
          <div className="summary-content">
            <p>{summary.summary}</p>
          </div>
          <div className="metrics-grid">
            <div className="metric-item">
              <span>Original</span>
              <strong>{summary.original_length} words</strong>
            </div>
            <div className="metric-item">
              <span>Summary</span>
              <strong>{summary.summary_length} words</strong>
            </div>
            <div className="metric-item">
              <span>Compression</span>
              <strong>{compression ? `${compression}%` : '—'}</strong>
            </div>
          </div>
        </div>
      ) : (
        <div className="empty-state">
          <p>Generate a summary to get a faster understanding before memorization.</p>
        </div>
      )}
    </section>
  );
};

export default SummarySection;
