import React, { useEffect, useMemo, useState } from 'react';

const escapeCsvValue = (value = '') => {
  const normalized = String(value).replace(/"/g, '""');
  return `"${normalized}"`;
};

const downloadTextFile = (filename, content, mimeType = 'text/plain;charset=utf-8') => {
  const blob = new Blob([content], { type: mimeType });
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  window.URL.revokeObjectURL(url);
};

const FlashcardItem = ({ flashcard, index }) => {
  const [isFlipped, setIsFlipped] = useState(false);

  return (
    <button
      className={`flashcard ${isFlipped ? 'is-flipped' : ''}`}
      onClick={() => setIsFlipped((prev) => !prev)}
      type="button"
    >
      <div className="flashcard-inner">
        <div className="flashcard-face flashcard-front">
          <div className="flashcard-meta">
            <span>Card {index + 1}</span>
            <span>Question</span>
          </div>
          <p>{flashcard.question}</p>
        </div>
        <div className="flashcard-face flashcard-back">
          <div className="flashcard-meta">
            <span>Card {index + 1}</span>
            <span>Answer</span>
          </div>
          <p>{flashcard.answer}</p>
        </div>
      </div>
    </button>
  );
};

const FlashcardsSection = ({ extractedText, flashcards, onGenerateFlashcards, isLoading }) => {
  const [numCards, setNumCards] = useState(6);
  const [cardOrder, setCardOrder] = useState([]);

  const cards = useMemo(() => flashcards?.flashcards ?? [], [flashcards]);

  useEffect(() => {
    setCardOrder(cards.map((_, index) => index));
  }, [cards]);

  const orderedCards = useMemo(
    () => cardOrder.map((index) => cards[index]).filter(Boolean),
    [cardOrder, cards]
  );

  if (!extractedText) {
    return null;
  }

  const handleGenerate = () => {
    onGenerateFlashcards(numCards);
  };

  const handleShuffle = () => {
    setCardOrder((prev) => {
      const shuffled = [...prev];
      for (let i = shuffled.length - 1; i > 0; i -= 1) {
        const j = Math.floor(Math.random() * (i + 1));
        [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
      }
      return shuffled;
    });
  };

  const handleExportCsv = () => {
    if (!cards.length) return;
    const lines = [
      'question,answer',
      ...cards.map((card) => `${escapeCsvValue(card.question)},${escapeCsvValue(card.answer)}`),
    ];
    downloadTextFile('quizcards-flashcards.csv', lines.join('\n'), 'text/csv;charset=utf-8');
  };

  const handleExportTsv = () => {
    if (!cards.length) return;
    const lines = [
      'question\tanswer',
      ...cards.map((card) => `${card.question.replace(/\t/g, ' ')}\t${card.answer.replace(/\t/g, ' ')}`),
    ];
    downloadTextFile('quizcards-flashcards.tsv', lines.join('\n'));
  };

  return (
    <section className="glass-card section-appear">
      <div className="section-header">
        <div>
          <h2 className="section-title">Flashcards Lab</h2>
          <p className="section-subtitle">
            Generate, shuffle, and export cards for spaced practice tools.
          </p>
        </div>

        <div className="inline-controls">
          <label htmlFor="numCards" className="control-label">
            Cards
          </label>
          <select
            id="numCards"
            value={numCards}
            onChange={(event) => setNumCards(parseInt(event.target.value, 10))}
            className="modern-select"
            disabled={isLoading}
          >
            {[4, 5, 6, 7, 8, 9, 10].map((count) => (
              <option key={count} value={count}>
                {count}
              </option>
            ))}
          </select>
          <button className="btn-neon" onClick={handleGenerate} disabled={isLoading}>
            {isLoading ? 'Generating…' : 'Generate Cards'}
          </button>
        </div>
      </div>

      {!!cards.length && (
        <div className="toolbar-row">
          <button className="btn-ghost" onClick={handleShuffle}>
            Shuffle
          </button>
          <button className="btn-ghost" onClick={handleExportCsv}>
            Export CSV
          </button>
          <button className="btn-ghost" onClick={handleExportTsv}>
            Export TSV
          </button>
        </div>
      )}

      {orderedCards.length ? (
        <div className="flashcards-grid">
          {orderedCards.map((card, index) => (
            <FlashcardItem key={`${card.question}-${index}`} flashcard={card} index={index} />
          ))}
        </div>
      ) : (
        <div className="empty-state">
          <p>Generate flashcards to start active recall training.</p>
        </div>
      )}
    </section>
  );
};

export default FlashcardsSection;
