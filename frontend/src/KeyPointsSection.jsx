import React, { useState } from 'react';

const KeyPointsSection = ({ extractedText, keyPoints, onGenerateKeyPoints, isLoading }) => {
  const [maxPoints, setMaxPoints] = useState(8);

  if (!extractedText) {
    return null;
  }

  return (
    <section className="glass-card section-appear">
      <div className="section-header">
        <div>
          <h2 className="section-title">Key Insights</h2>
          <p className="section-subtitle">Digest the document into concise takeaways.</p>
        </div>
        <div className="inline-controls">
          <label htmlFor="maxPoints" className="control-label">
            Points
          </label>
          <select
            id="maxPoints"
            value={maxPoints}
            onChange={(e) => setMaxPoints(parseInt(e.target.value, 10))}
            className="modern-select"
            disabled={isLoading}
          >
            {[6, 8, 10, 12, 14, 16, 18, 20].map((count) => (
              <option key={count} value={count}>
                {count}
              </option>
            ))}
          </select>
          <button
            className="btn-neon"
            onClick={() => onGenerateKeyPoints(maxPoints)}
            disabled={isLoading}
          >
            {isLoading ? 'Generating…' : 'Generate Insights'}
          </button>
        </div>
      </div>

      {keyPoints?.key_points?.length > 0 ? (
        <ul className="insights-list">
          {keyPoints.key_points.map((point, index) => (
            <li key={`${point}-${index}`} className="insight-item">
              <span className="insight-badge">{index + 1}</span>
              <p>{point}</p>
            </li>
          ))}
        </ul>
      ) : (
        <div className="empty-state">
          <p>Generate key insights to quickly capture the most important ideas.</p>
        </div>
      )}
    </section>
  );
};

export default KeyPointsSection;
