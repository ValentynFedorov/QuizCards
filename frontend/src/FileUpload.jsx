import React, { useState } from 'react';

const MAX_WORDS = 30000;

const FileUpload = ({ onFileSelect, onTextInput, isLoading }) => {
  const [activeTab, setActiveTab] = useState('pdf');
  const [textInput, setTextInput] = useState('');
  const [selectedFile, setSelectedFile] = useState(null);
  const [localError, setLocalError] = useState(null);

  const wordCount = textInput.trim() ? textInput.trim().split(/\s+/).length : 0;
  const isTextTooLong = wordCount > MAX_WORDS;

  const processFile = (file) => {
    if (!file) return;

    if (file.type !== 'application/pdf') {
      setLocalError('Only PDF files are supported.');
      return;
    }

    setLocalError(null);
    setSelectedFile(file);
    onFileSelect(file);
  };

  const handleFileChange = (event) => {
    const file = event.target.files?.[0];
    processFile(file);
  };

  const handleDragOver = (event) => {
    event.preventDefault();
  };

  const handleDrop = (event) => {
    event.preventDefault();
    const file = event.dataTransfer.files?.[0];
    processFile(file);
  };

  const handleTextSubmit = () => {
    if (!textInput.trim()) return;
    if (isTextTooLong) {
      setLocalError(`Text limit exceeded: ${wordCount}/${MAX_WORDS} words.`);
      return;
    }
    setLocalError(null);
    onTextInput(textInput);
  };

  return (
    <section className="glass-card section-appear">
      <div className="section-header">
        <div>
          <h2 className="section-title">Import Learning Material</h2>
          <p className="section-subtitle">
            Upload a PDF or paste long notes/lectures to generate study content.
          </p>
        </div>
      </div>

      <div className="tab-shell">
        <button
          className={`tab-btn ${activeTab === 'pdf' ? 'active' : ''}`}
          onClick={() => setActiveTab('pdf')}
          disabled={isLoading}
        >
          PDF Upload
        </button>
        <button
          className={`tab-btn ${activeTab === 'text' ? 'active' : ''}`}
          onClick={() => setActiveTab('text')}
          disabled={isLoading}
        >
          Text Input
        </button>
      </div>

      {activeTab === 'pdf' && (
        <div
          className="dropzone"
          onDragOver={handleDragOver}
          onDrop={handleDrop}
          onClick={() => document.getElementById('file-input')?.click()}
        >
          <p className="dropzone-title">
            {selectedFile ? selectedFile.name : 'Drop your PDF here or click to browse'}
          </p>
          <p className="dropzone-subtitle">Supports large document extraction, grounding, and study generation.</p>
          <input
            id="file-input"
            type="file"
            accept=".pdf"
            onChange={handleFileChange}
            className="hidden"
            disabled={isLoading}
          />
        </div>
      )}

      {activeTab === 'text' && (
        <div className="text-input-shell">
          <textarea
            className="modern-textarea"
            placeholder="Paste your lecture notes, handbook section, or article text…"
            value={textInput}
            onChange={(event) => setTextInput(event.target.value)}
            disabled={isLoading}
          />
          <div className="text-meta">
            <span>{textInput.length.toLocaleString()} characters</span>
            <span className={isTextTooLong ? 'text-danger' : ''}>
              {wordCount.toLocaleString()} / {MAX_WORDS.toLocaleString()} words
            </span>
          </div>
          <div className="text-action-row">
            <button
              className="btn-neon"
              onClick={handleTextSubmit}
              disabled={isLoading || !textInput.trim() || isTextTooLong}
            >
              {isLoading ? 'Processing…' : 'Process Text'}
            </button>
          </div>
        </div>
      )}

      {localError && (
        <div className="inline-error">
          <p>{localError}</p>
        </div>
      )}
    </section>
  );
};

export default FileUpload;
