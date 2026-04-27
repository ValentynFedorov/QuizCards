import React, { useEffect, useMemo, useState } from 'react';

const QuizModeSection = ({
  extractedText,
  quiz,
  onGenerateQuiz,
  isLoading,
  onAnalyzeQuizPerformance,
  weakTopics,
  adaptiveReview,
  isAnalyzing,
}) => {
  const [numQuestions, setNumQuestions] = useState(8);
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

  const answeredCount = useMemo(() => Object.keys(selectedAnswers).length, [selectedAnswers]);

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

  const buildAttemptsPayload = () =>
    questions.map((question, index) => ({
      question: question.question,
      options: question.options,
      correct_option: question.correct_option,
      selected_option: selectedAnswers[index] ?? null,
      explanation: question.explanation,
      wrong_option_explanations: question.wrong_option_explanations || [],
    }));

  const handleAnalyzePerformance = async () => {
    if (!questions.length) return;
    await onAnalyzeQuizPerformance(buildAttemptsPayload());
  };

  return (
    <section className="glass-card section-appear">
      <div className="section-header">
        <div>
          <h2 className="section-title">Quiz Mode</h2>
          <p className="section-subtitle">Practice recall with instant feedback, weakness mapping, and review scheduling.</p>
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
            {[6, 8, 10, 12, 14, 16, 18, 20].map((count) => (
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
          {quiz.doc_hash && <span className="meta-pill">Doc hash: {quiz.doc_hash.slice(0, 8)}…</span>}
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
              <div className="progress-fill" style={{ width: `${((currentIndex + 1) / questions.length) * 100}%` }} />
            </div>
          </div>

          <div className="quiz-card">
            <h3>{currentQuestion?.question}</h3>
            {currentQuestion?.source_position && (
              <p className="quiz-source">Source: {currentQuestion.source_position}</p>
            )}
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
            <button className="btn-ghost" onClick={handleBack} disabled={currentIndex === 0}>
              Previous
            </button>
            <button className="btn-neon" onClick={handleNext} disabled={selectedAnswers[currentIndex] === undefined}>
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
            <p>Accuracy: {Math.round((score / questions.length) * 100)}%</p>
          </div>

          <div className="result-review">
            {questions.map((question, index) => {
              const selected = selectedAnswers[index];
              const isCorrect = selected === question.correct_option;
              const wrongExplanation =
                selected !== undefined ? question.wrong_option_explanations?.[selected] : null;
              return (
                <div key={`${question.question}-${index}`} className={`review-item ${isCorrect ? 'correct' : 'wrong'}`}>
                  <p className="review-question">{question.question}</p>
                  <p>
                    Your answer:{' '}
                    <strong>{selected !== undefined ? question.options[selected] : 'Not answered'}</strong>
                  </p>
                  {!isCorrect && (
                    <p>
                      Correct answer: <strong>{question.options[question.correct_option]}</strong>
                    </p>
                  )}
                  <p className="review-explanation">{isCorrect ? question.explanation : wrongExplanation || question.explanation}</p>
                </div>
              );
            })}
          </div>

          <div className="quiz-actions">
            <button className="btn-ghost" onClick={() => setShowResults(false)}>
              Review Again
            </button>
            <button className="btn-neon" onClick={handleAnalyzePerformance} disabled={isAnalyzing}>
              {isAnalyzing ? 'Analyzing…' : 'Analyze Weak Topics'}
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

      {(weakTopics?.weak_topics?.length > 0 || adaptiveReview?.queue?.length > 0) && (
        <div className="insights-duo">
          {weakTopics?.weak_topics?.length > 0 && (
            <div className="insight-panel">
              <h3>Weak Topics</h3>
              <p className="insight-summary">Overall accuracy: {Math.round((weakTopics.overall_accuracy || 0) * 100)}%</p>
              <ul>
                {weakTopics.weak_topics.map((topic) => (
                  <li key={topic.topic}>
                    <strong>{topic.topic}</strong> — mistakes: {topic.mistakes}/{topic.attempts} ({Math.round(topic.accuracy * 100)}%)
                    <span>{topic.recommendation}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {adaptiveReview?.queue?.length > 0 && (
            <div className="insight-panel">
              <h3>Adaptive Review Queue</h3>
              <ul>
                {adaptiveReview.queue.slice(0, 10).map((item) => (
                  <li key={item.item_id}>
                    <strong>{item.prompt}</strong>
                    <span>
                      Priority {item.priority} · Next review in {item.next_review_minutes} min
                    </span>
                    <span>{item.reason}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
};

export default QuizModeSection;
