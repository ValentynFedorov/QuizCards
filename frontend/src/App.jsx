import React, { useState } from 'react';
import { useMutation } from 'react-query';
import FileUpload from './FileUpload';
import SummarySection from './SummarySection';
import FlashcardsSection from './FlashcardsSection';
import { apiService } from './api';

function App() {
  const [extractedText, setExtractedText] = useState('');
  const [summary, setSummary] = useState(null);
  const [flashcards, setFlashcards] = useState(null);
  const [error, setError] = useState(null);

  // Upload mutation
  const uploadMutation = useMutation(
    ({ file, text }) => apiService.uploadContent(file, text),
    {
      onSuccess: (data) => {
        setExtractedText(data.text);
        setSummary(null);
        setFlashcards(null);
        setError(null);
      },
      onError: (error) => {
        console.error('Upload error:', error);
        setError(error.response?.data?.detail || 'Failed to process content');
      }
    }
  );

  // Summary mutation
  const summaryMutation = useMutation(
    (text) => apiService.generateSummary(text),
    {
      onSuccess: (data) => {
        setSummary(data);
        setError(null);
      },
      onError: (error) => {
        console.error('Summary error:', error);
        setError(error.response?.data?.detail || 'Failed to generate summary');
      }
    }
  );

  // Flashcards mutation
  const flashcardsMutation = useMutation(
    ({ text, numCards }) => apiService.generateFlashcards(text, numCards),
    {
      onSuccess: (data) => {
        setFlashcards(data);
        setError(null);
      },
      onError: (error) => {
        console.error('Flashcards error:', error);
        setError(error.response?.data?.detail || 'Failed to generate flashcards');
      }
    }
  );

  const handleFileSelect = (file) => {
    uploadMutation.mutate({ file, text: null });
  };

  const handleTextInput = (text) => {
    uploadMutation.mutate({ file: null, text });
  };

  const handleGenerateSummary = () => {
    if (extractedText) {
      summaryMutation.mutate(extractedText);
    }
  };

  const handleGenerateFlashcards = (numCards) => {
    if (extractedText) {
      flashcardsMutation.mutate({ text: extractedText, numCards });
    }
  };

  const clearError = () => {
    setError(null);
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center py-6">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <svg className="w-8 h-8 text-primary-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                </svg>
              </div>
              <div className="ml-3">
                <h1 className="text-2xl font-bold text-gray-900">
                  PDF Flashcards Generator
                </h1>
                <p className="text-sm text-gray-600">
                  Extract text, generate summaries, and create flashcards from PDFs
                </p>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Error Display */}
        {error && (
          <div className="mb-6 bg-red-50 border border-red-200 rounded-lg p-4">
            <div className="flex justify-between items-start">
              <div className="flex">
                <svg className="w-5 h-5 text-red-400 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <div className="ml-3">
                  <h3 className="text-sm font-medium text-red-800">Error</h3>
                  <p className="text-sm text-red-700 mt-1">{error}</p>
                </div>
              </div>
              <button
                onClick={clearError}
                className="text-red-400 hover:text-red-600"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          </div>
        )}

        {/* File Upload Section */}
        <div className="mb-8">
          <FileUpload
            onFileSelect={handleFileSelect}
            onTextInput={handleTextInput}
            isLoading={uploadMutation.isLoading}
          />
        </div>

        {/* Content Preview */}
        {extractedText && (
          <div className="mb-8">
            <div className="card">
              <h2 className="text-xl font-bold text-gray-800 mb-4">Extracted Content</h2>
              <div className="bg-gray-50 rounded-lg p-4 max-h-40 overflow-y-auto">
                <p className="text-gray-700 text-sm leading-relaxed">
                  {extractedText.length > 500 
                    ? `${extractedText.substring(0, 500)}...` 
                    : extractedText
                  }
                </p>
              </div>
              <div className="mt-3 flex justify-between items-center text-sm text-gray-500">
                <span>{extractedText.split(' ').length} words</span>
                <span>{extractedText.length} characters</span>
              </div>
            </div>
          </div>
        )}

        {/* Summary Section */}
        <div className="mb-8">
          <SummarySection
            extractedText={extractedText}
            summary={summary}
            onGenerateSummary={handleGenerateSummary}
            isLoading={summaryMutation.isLoading}
          />
        </div>

        {/* Flashcards Section */}
        <div className="mb-8">
          <FlashcardsSection
            extractedText={extractedText}
            flashcards={flashcards}
            onGenerateFlashcards={handleGenerateFlashcards}
            isLoading={flashcardsMutation.isLoading}
          />
        </div>
      </main>

      {/* Footer */}
      <footer className="bg-white border-t border-gray-200 mt-16">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="text-center text-sm text-gray-500">
            <p>PDF Flashcards Generator - Built with React, FastAPI, and AI</p>
          </div>
        </div>
      </footer>
    </div>
  );
}

export default App;
