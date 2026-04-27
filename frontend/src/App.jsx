import React, { useEffect, useMemo, useState } from 'react';
import { useMutation } from 'react-query';
import FileUpload from './FileUpload';
import SummarySection from './SummarySection';
import FlashcardsSection from './FlashcardsSection';
import KeyPointsSection from './KeyPointsSection';
import QuizModeSection from './QuizModeSection';
import { apiService } from './api';

function App() {
  const [extractedText, setExtractedText] = useState('');
  const [documentMeta, setDocumentMeta] = useState({
    wordCount: 0,
    charCount: 0,
    docHash: null,
    chunkCount: 0,
  });
  const [summary, setSummary] = useState(null);
  const [flashcards, setFlashcards] = useState(null);
  const [keyPoints, setKeyPoints] = useState(null);
  const [quiz, setQuiz] = useState(null);
  const [weakTopics, setWeakTopics] = useState(null);
  const [adaptiveReview, setAdaptiveReview] = useState(null);
  const [studyJob, setStudyJob] = useState(null);
  const [error, setError] = useState(null);

  const uploadMutation = useMutation(({ file, text }) => apiService.uploadContent(file, text), {
    onSuccess: (data) => {
      setExtractedText(data.text);
      setDocumentMeta({
        wordCount: data.word_count || data.text?.split(/\s+/).length || 0,
        charCount: data.char_count || data.text?.length || 0,
        docHash: data.doc_hash || null,
        chunkCount: data.chunk_count || 0,
      });
      setSummary(null);
      setFlashcards(null);
      setKeyPoints(null);
      setQuiz(null);
      setWeakTopics(null);
      setAdaptiveReview(null);
      setStudyJob(null);
      setError(null);
    },
    onError: (requestError) => {
      setError(requestError.response?.data?.detail || 'Failed to process content');
    },
  });

  const summaryMutation = useMutation((text) => apiService.generateSummary(text), {
    onSuccess: (data) => {
      setSummary(data);
      setError(null);
    },
    onError: (requestError) => {
      setError(requestError.response?.data?.detail || 'Failed to generate summary');
    },
  });

  const flashcardsMutation = useMutation(
    ({ text, numCards, mode }) => apiService.generateFlashcards(text, numCards, mode),
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

  const keyPointsMutation = useMutation(({ text, maxPoints }) => apiService.generateKeyPoints(text, maxPoints), {
    onSuccess: (data) => {
      setKeyPoints(data);
      setError(null);
    },
    onError: (requestError) => {
      setError(requestError.response?.data?.detail || 'Failed to generate key insights');
    },
  });

  const quizMutation = useMutation(
    ({ text, numQuestions, mode, ollamaModel }) =>
      apiService.generateQuiz(text, numQuestions, mode, ollamaModel),
    {
      onSuccess: (data) => {
        setQuiz(data);
        setWeakTopics(null);
        setAdaptiveReview(null);
        setError(null);
      },
      onError: (requestError) => {
        setError(requestError.response?.data?.detail || 'Failed to generate quiz');
      },
    }
  );

  const startStudyJobMutation = useMutation((payload) => apiService.startStudyJob(payload), {
    onSuccess: (data) => {
      setStudyJob({
        jobId: data.job_id,
        status: data.status,
        stage: data.stage,
        progress: data.progress,
        message: 'Job queued',
      });
      setError(null);
    },
    onError: (requestError) => {
      setError(requestError.response?.data?.detail || 'Failed to start async study job');
    },
  });

  const quizInsightsMutation = useMutation((attempts) => apiService.generateQuizInsights(attempts));
  const adaptiveReviewMutation = useMutation(({ attempts, cards }) =>
    apiService.generateAdaptiveReview(attempts, cards)
  );

  const isAnalyzingPerformance = quizInsightsMutation.isLoading || adaptiveReviewMutation.isLoading;

  useEffect(() => {
    if (!studyJob?.jobId) return undefined;
    if (studyJob.status === 'completed' || studyJob.status === 'failed') return undefined;

    const intervalId = window.setInterval(async () => {
      try {
        const status = await apiService.getStudyJob(studyJob.jobId);
        setStudyJob({
          jobId: status.job_id,
          status: status.status,
          stage: status.stage,
          progress: status.progress,
          message: status.message,
        });

        if (status.status === 'completed' && status.result) {
          const result = status.result;
          if (result.summary) {
            setSummary({
              summary: result.summary,
              original_length: result.document?.word_count || extractedText.split(/\s+/).length,
              summary_length: result.summary.split(/\s+/).length,
              doc_hash: result.document?.doc_hash || null,
            });
          }
          if (result.key_points) {
            setKeyPoints({
              key_points: result.key_points,
              total_count: result.key_points.length,
              doc_hash: result.document?.doc_hash || null,
            });
          }
          if (result.flashcards) {
            setFlashcards({
              flashcards: result.flashcards,
              total_count: result.flashcards.length,
              mode: result.flashcards?.[0]?.mode || 'qa',
            });
          }
          if (result.quiz) {
            setQuiz(result.quiz);
          }
          if (result.document) {
            setDocumentMeta((prev) => ({
              ...prev,
              docHash: result.document.doc_hash || prev.docHash,
              chunkCount: result.document.chunk_count || prev.chunkCount,
              wordCount: result.document.word_count || prev.wordCount,
            }));
          }
          setError(null);
        }

        if (status.status === 'failed') {
          setError(status.error || 'Async study job failed');
        }
      } catch (pollError) {
        setError(pollError.response?.data?.detail || 'Failed to poll async study job');
      }
    }, 1200);

    return () => window.clearInterval(intervalId);
  }, [studyJob?.jobId, studyJob?.status, extractedText]);

  const readingMinutes = useMemo(() => {
    if (!documentMeta.wordCount) return 0;
    return Math.max(1, Math.ceil(documentMeta.wordCount / 180));
  }, [documentMeta.wordCount]);

  const handleFileSelect = (file) => uploadMutation.mutate({ file, text: null });
  const handleTextInput = (text) => uploadMutation.mutate({ file: null, text });

  const handleGenerateSummary = () => extractedText && summaryMutation.mutate(extractedText);
  const handleGenerateFlashcards = (numCards, options = {}) =>
    extractedText &&
    flashcardsMutation.mutate({
      text: extractedText,
      numCards,
      mode: options.mode || 'qa',
    });
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

  const handleRunAsyncPipeline = () => {
    if (!extractedText) return;
    startStudyJobMutation.mutate({
      text: extractedText,
      numCards: 10,
      numQuestions: 10,
      flashcardMode: 'qa',
      quizMode: 'fast',
      includeSummary: true,
      includeKeyPoints: true,
    });
  };

  const handleAnalyzeQuizPerformance = async (attempts) => {
    try {
      const [weak, review] = await Promise.all([
        quizInsightsMutation.mutateAsync(attempts),
        adaptiveReviewMutation.mutateAsync({
          attempts,
          cards: flashcards?.flashcards || [],
        }),
      ]);
      setWeakTopics(weak);
      setAdaptiveReview(review);
      setError(null);
    } catch (requestError) {
      setError(requestError.response?.data?.detail || 'Failed to analyze quiz performance');
    }
  };

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

        <FileUpload onFileSelect={handleFileSelect} onTextInput={handleTextInput} isLoading={uploadMutation.isLoading} />

        {extractedText && (
          <section className="glass-card section-appear">
            <div className="section-header">
              <div>
                <h2 className="section-title">Document Snapshot</h2>
                <p className="section-subtitle">
                  Ready for summary, insights, grounded flashcards, and adaptive quiz practice.
                </p>
              </div>
              <div className="inline-controls">
                <button
                  className="btn-neon"
                  onClick={handleRunAsyncPipeline}
                  disabled={startStudyJobMutation.isLoading || studyJob?.status === 'running'}
                >
                  {startStudyJobMutation.isLoading || studyJob?.status === 'running'
                    ? 'Running async pipeline…'
                    : 'Run Full Async Pipeline'}
                </button>
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
                <span>Chunks</span>
                <strong>{documentMeta.chunkCount.toLocaleString()}</strong>
              </div>
              <div className="metric-item">
                <span>Est. Reading Time</span>
                <strong>{readingMinutes} min</strong>
              </div>
            </div>

            {studyJob && (
              <div className="job-progress-shell">
                <div className="quiz-progress-meta">
                  <span>
                    Async pipeline: {studyJob.stage}
                    {studyJob.message ? ` — ${studyJob.message}` : ''}
                  </span>
                  <span>{studyJob.progress}%</span>
                </div>
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${studyJob.progress}%` }} />
                </div>
              </div>
            )}

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
          onAnalyzeQuizPerformance={handleAnalyzeQuizPerformance}
          weakTopics={weakTopics}
          adaptiveReview={adaptiveReview}
          isAnalyzing={isAnalyzingPerformance}
        />
      </main>
    </div>
  );
}

export default App;
