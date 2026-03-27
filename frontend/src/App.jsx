import React, { useMemo, useState } from 'react';
import { useMutation } from 'react-query';
import FileUpload from './FileUpload';
import SummarySection from './SummarySection';
import FlashcardsSection from './FlashcardsSection';
import KeyPointsSection from './KeyPointsSection';
import QuizModeSection from './QuizModeSection';
import { apiService } from './api';

function App() {
  const [extractedText, setExtractedText] = useState('');
  const [documentMeta, setDocumentMeta] = useState({ wordCount: 0, charCount: 0 });
  const [summary, setSummary] = useState(null);
  const [flashcards, setFlashcards] = useState(null);
  const [keyPoints, setKeyPoints] = useState(null);
  const [quiz, setQuiz] = useState(null);
  const [error, setError] = useState(null);

  const uploadMutation = useMutation(
    ({ file, text }) => apiService.uploadContent(file, text),
    {
      onSuccess: (data) => {
        setExtractedText(data.text);
        setDocumentMeta({
          wordCount: data.word_count || data.text?.split(/\s+/).length || 0,
          charCount: data.char_count || data.text?.length || 0,
        });
        setSummary(null);
        setFlashcards(null);
        setKeyPoints(null);
        setQuiz(null);
        setError(null);
      },
      onError: (requestError) => {
        setError(requestError.response?.data?.detail || 'Failed to process content');
      },
    }
  );

  const summaryMutation = useMutation(
    (text) => apiService.generateSummary(text),
    {
      onSuccess: (data) => {
        setSummary(data);
        setError(null);
      },
      onError: (requestError) => {
        setError(requestError.response?.data?.detail || 'Failed to generate summary');
      },
    }
  );

  const flashcardsMutation = useMutation(
    ({ text, numCards }) => apiService.generateFlashcards(text, numCards),
    {
      onSuccess: (data) => {
        setFlashcards(data);
        setError(null);
      },
      onError: (requestError) => {
        setError(requestError.response?.data?.detail || 'Failed to generate flashcards');
      },
    }
  );

  const keyPointsMutation = useMutation(
    ({ text, maxPoints }) => apiService.generateKeyPoints(text, maxPoints),
    {
      onSuccess: (data) => {
        setKeyPoints(data);
        setError(null);
      },
      onError: (requestError) => {
        setError(requestError.response?.data?.detail || 'Failed to generate key insights');
      },
    }
  );

  const quizMutation = useMutation(
    ({ text, numQuestions, mode, ollamaModel }) =>
      apiService.generateQuiz(text, numQuestions, mode, ollamaModel),
    {
      onSuccess: (data) => {
        setQuiz(data);
        setError(null);
      },
      onError: (requestError) => {
        setError(requestError.response?.data?.detail || 'Failed to generate quiz');
      },
    }
  );

  const readingMinutes = useMemo(() => {
    if (!documentMeta.wordCount) return 0;
    return Math.max(1, Math.ceil(documentMeta.wordCount / 180));
  }, [documentMeta.wordCount]);

  const handleFileSelect = (file) => uploadMutation.mutate({ file, text: null });
  const handleTextInput = (text) => uploadMutation.mutate({ file: null, text });

  const handleGenerateSummary = () => extractedText && summaryMutation.mutate(extractedText);
  const handleGenerateFlashcards = (numCards) =>
    extractedText && flashcardsMutation.mutate({ text: extractedText, numCards });
  const handleGenerateKeyPoints = (maxPoints) =>
    extractedText && keyPointsMutation.mutate({ text: extractedText, maxPoints });
  const handleGenerateQuiz = (numQuestions, options = {}) =>
    extractedText &&
    quizMutation.mutate({
      text: extractedText,
      numQuestions,
      mode: options.mode || 'fast',
      ollamaModel: options.ollamaModel || '',
    });

  return (
    <div className="app-bg">
      <div className="ambient ambient-a" />
      <div className="ambient ambient-b" />

      <header className="app-header">
        <div className="header-left">
          <div className="logo-pill">QC</div>
          <div>
            <h1>QuizCards</h1>
            <p>From documents to real study sessions.</p>
          </div>
        </div>
        <div className="status-pill">AI study copilot</div>
      </header>

      <main className="app-main">
        {error && (
          <div className="alert-danger">
            <div>
              <h3>Request failed</h3>
              <p>{error}</p>
            </div>
            <button onClick={() => setError(null)} aria-label="Dismiss error">
              ×
            </button>
          </div>
        )}

        <FileUpload
          onFileSelect={handleFileSelect}
          onTextInput={handleTextInput}
          isLoading={uploadMutation.isLoading}
        />

        {extractedText && (
          <section className="glass-card section-appear">
            <div className="section-header">
              <div>
                <h2 className="section-title">Document Snapshot</h2>
                <p className="section-subtitle">
                  Ready for summary, insights, flashcards, and quiz practice.
                </p>
              </div>
            </div>

            <div className="metrics-grid">
              <div className="metric-item">
                <span>Words</span>
                <strong>{documentMeta.wordCount.toLocaleString()}</strong>
              </div>
              <div className="metric-item">
                <span>Characters</span>
                <strong>{documentMeta.charCount.toLocaleString()}</strong>
              </div>
              <div className="metric-item">
                <span>Est. Reading Time</span>
                <strong>{readingMinutes} min</strong>
              </div>
              <div className="metric-item">
                <span>Text Coverage</span>
                <strong>100%</strong>
              </div>
            </div>

            <div className="preview-box">
              {extractedText.length > 900 ? `${extractedText.substring(0, 900)}…` : extractedText}
            </div>
          </section>
        )}

        <SummarySection
          extractedText={extractedText}
          summary={summary}
          onGenerateSummary={handleGenerateSummary}
          isLoading={summaryMutation.isLoading}
        />

        <KeyPointsSection
          extractedText={extractedText}
          keyPoints={keyPoints}
          onGenerateKeyPoints={handleGenerateKeyPoints}
          isLoading={keyPointsMutation.isLoading}
        />

        <FlashcardsSection
          extractedText={extractedText}
          flashcards={flashcards}
          onGenerateFlashcards={handleGenerateFlashcards}
          isLoading={flashcardsMutation.isLoading}
        />

        <QuizModeSection
          extractedText={extractedText}
          quiz={quiz}
          onGenerateQuiz={handleGenerateQuiz}
          isLoading={quizMutation.isLoading}
        />
      </main>
    </div>
  );
}

export default App;
