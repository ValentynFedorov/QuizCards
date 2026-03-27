import React, { useEffect, useMemo, useState } from 'react';

const QuizModeSection = ({ extractedText, quiz, onGenerateQuiz, isLoading }) => {
  const [numQuestions, setNumQuestions] = useState(6);
  const [generationMode, setGenerationMode] = useState('fast');
  const [ollamaModel, setOllamaModel] = useState('qwen2.5:7b');
  const [currentIndex, setCurrentIndex] = useState(0);
  const [selectedAnswers, setSelectedAnswers] = useState({});
  const [showResults, setShowResults] = useState(false);

  const questions = useMemo(() => quiz?.questions ?? [], [quiz]);
  const currentQuestion = questions[currentIndex];

  useEffect(() => {
    setCurrentIndex(0);
    setSelectedAnswers({});
    setShowResults(false);
  }, [quiz]);

  const answeredCount = useMemo(
    () => Object.keys(selectedAnswers).length,
    [selectedAnswers]
  );

  const score = useMemo(() => {
    if (!questions.length) return 0;
    return questions.reduce((acc, question, index) => {
      return acc + (selectedAnswers[index] === question.correct_option ? 1 : 0);
    }, 0);
  }, [questions, selectedAnswers]);

  if (!extractedText) {
    return null;
  }

  const handleSelectOption = (optionIndex) => {
    setSelectedAnswers((prev) => ({
      ...prev,
      [currentIndex]: optionIndex,
    }));
  };

  const handleNext = () => {
    if (currentIndex < questions.length - 1) {
      setCurrentIndex((prev) => prev + 1);
      return;
    }
    setShowResults(true);
  };

  const handleBack = () => {
    setCurrentIndex((prev) => Math.max(0, prev - 1));
  };

  return (
    <section className="glass-card section-appear">
      <div className="section-header">
        <div>
          <h2 className="section-title">Quiz Mode</h2>
          <p className="section-subtitle">Practice recall with instant feedback and scoring.</p>
        </div>
        <div className="inline-controls">
          <label htmlFor="numQuestions" className="control-label">
            Questions
          </label>
          <select
            id="numQuestions"
            value={numQuestions}
            onChange={(e) => setNumQuestions(parseInt(e.target.value, 10))}
            className="modern-select"
            disabled={isLoading}
          >
            {[4, 5, 6, 7, 8, 9, 10, 12].map((count) => (
              <option key={count} value={count}>
                {count}
              </option>
            ))}
          </select>
          <label htmlFor="generationMode" className="control-label">
            Mode
          </label>
          <select
            id="generationMode"
            value={generationMode}
            onChange={(e) => setGenerationMode(e.target.value)}
            className="modern-select"
            disabled={isLoading}
          >
            <option value="fast">Fast</option>
            <option value="high_quality">High quality (Ollama)</option>
          </select>
          {generationMode === 'high_quality' && (
            <input
              type="text"
              className="modern-input"
              value={ollamaModel}
              onChange={(e) => setOllamaModel(e.target.value)}
              placeholder="qwen2.5:7b"
              disabled={isLoading}
            />
          )}
          <button
            className="btn-neon"
            onClick={() =>
              onGenerateQuiz(numQuestions, {
                mode: generationMode,
                ollamaModel,
              })
            }
            disabled={isLoading}
          >
            {isLoading ? 'Preparing…' : 'Generate Quiz'}
          </button>
        </div>
      </div>
      {quiz?.provider && (
        <div className="toolbar-row">
          <span className="meta-pill">Provider: {quiz.provider}</span>
          <span className="meta-pill">Mode: {quiz.generation_mode || 'fast'}</span>
          {quiz.model && <span className="meta-pill">Model: {quiz.model}</span>}
          {quiz.fallback_used && <span className="meta-pill warning">Fallback used</span>}
        </div>
      )}

      {!questions.length && (
        <div className="empty-state">
          <p>Generate a quiz to test understanding and identify weak spots.</p>
        </div>
      )}

      {!!questions.length && !showResults && (
        <div className="quiz-shell">
          <div className="quiz-progress">
            <div className="quiz-progress-meta">
              <span>
                Question {currentIndex + 1} / {questions.length}
              </span>
              <span>
                Answered {answeredCount}/{questions.length}
              </span>
            </div>
            <div className="progress-track">
              <div
                className="progress-fill"
                style={{ width: `${((currentIndex + 1) / questions.length) * 100}%` }}
              />
            </div>
          </div>

          <div className="quiz-card">
            <h3>{currentQuestion?.question}</h3>
            <div className="quiz-options">
              {currentQuestion?.options?.map((option, index) => {
                const selected = selectedAnswers[currentIndex] === index;
                return (
                  <button
                    key={`${option}-${index}`}
                    className={`quiz-option ${selected ? 'selected' : ''}`}
                    onClick={() => handleSelectOption(index)}
                  >
                    <span>{String.fromCharCode(65 + index)}</span>
                    <span>{option}</span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="quiz-actions">
            <button
              className="btn-ghost"
              onClick={handleBack}
              disabled={currentIndex === 0}
            >
              Previous
            </button>
            <button
              className="btn-neon"
              onClick={handleNext}
              disabled={selectedAnswers[currentIndex] === undefined}
            >
              {currentIndex === questions.length - 1 ? 'Finish Quiz' : 'Next'}
            </button>
          </div>
        </div>
      )}

      {!!questions.length && showResults && (
        <div className="quiz-results">
          <div className="result-headline">
            <h3>
              Score: {score}/{questions.length}
            </h3>
            <p>
              Accuracy: {Math.round((score / questions.length) * 100)}%
            </p>
          </div>

          <div className="result-review">
            {questions.map((question, index) => {
              const selected = selectedAnswers[index];
              const isCorrect = selected === question.correct_option;
              return (
                <div key={`${question.question}-${index}`} className={`review-item ${isCorrect ? 'correct' : 'wrong'}`}>
                  <p className="review-question">{question.question}</p>
                  <p>
                    Your answer:{' '}
                    <strong>
                      {selected !== undefined ? question.options[selected] : 'Not answered'}
                    </strong>
                  </p>
                  {!isCorrect && (
                    <p>
                      Correct answer: <strong>{question.options[question.correct_option]}</strong>
                    </p>
                  )}
                  <p className="review-explanation">{question.explanation}</p>
                </div>
              );
            })}
          </div>

          <div className="quiz-actions">
            <button className="btn-ghost" onClick={() => setShowResults(false)}>
              Review Again
            </button>
            <button
              className="btn-neon"
              onClick={() =>
                onGenerateQuiz(numQuestions, {
                  mode: generationMode,
                  ollamaModel,
                })
              }
            >
              Regenerate Quiz
            </button>
          </div>
        </div>
      )}
    </section>
  );
};

export default QuizModeSection;
