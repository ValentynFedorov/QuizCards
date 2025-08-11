import React, { useState } from 'react';

const FlashcardItem = ({ flashcard, index }) => {
  const [isFlipped, setIsFlipped] = useState(false);

  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-sm hover:shadow-md transition-shadow">
      <div
        className="p-6 cursor-pointer min-h-[120px] flex flex-col justify-center"
        onClick={() => setIsFlipped(!isFlipped)}
      >
        <div className="flex justify-between items-start mb-3">
          <span className="text-xs font-medium text-primary-600 bg-primary-100 px-2 py-1 rounded">
            Card {index + 1}
          </span>
          <span className="text-xs text-gray-400">
            Click to {isFlipped ? 'show question' : 'show answer'}
          </span>
        </div>
        
        <div className="flex-1">
          {isFlipped ? (
            <div>
              <h4 className="text-sm font-medium text-gray-600 mb-2">Answer:</h4>
              <p className="text-gray-800">{flashcard.answer}</p>
            </div>
          ) : (
            <div>
              <h4 className="text-sm font-medium text-gray-600 mb-2">Question:</h4>
              <p className="text-gray-800 font-medium">{flashcard.question}</p>
            </div>
          )}
        </div>
        
        <div className="flex justify-center mt-4">
          <div className="flex space-x-1">
            <div className={`w-2 h-2 rounded-full ${!isFlipped ? 'bg-primary-500' : 'bg-gray-300'}`}></div>
            <div className={`w-2 h-2 rounded-full ${isFlipped ? 'bg-primary-500' : 'bg-gray-300'}`}></div>
          </div>
        </div>
      </div>
    </div>
  );
};

const FlashcardsSection = ({ extractedText, flashcards, onGenerateFlashcards, isLoading }) => {
  const [numCards, setNumCards] = useState(5);

  if (!extractedText) {
    return null;
  }

  const handleGenerate = () => {
    onGenerateFlashcards(numCards);
  };

  return (
    <div className="card">
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl font-bold text-gray-800">Flashcards</h2>
        <div className="flex items-center space-x-4">
          <div className="flex items-center space-x-2">
            <label htmlFor="numCards" className="text-sm text-gray-600">
              Number of cards:
            </label>
            <select
              id="numCards"
              value={numCards}
              onChange={(e) => setNumCards(parseInt(e.target.value))}
              className="border border-gray-300 rounded px-2 py-1 text-sm focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              disabled={isLoading}
            >
              {[3, 4, 5, 6, 7, 8, 9, 10].map(num => (
                <option key={num} value={num}>{num}</option>
              ))}
            </select>
          </div>
          <button
            className="btn-primary"
            onClick={handleGenerate}
            disabled={isLoading}
          >
            {isLoading ? (
              <span className="flex items-center">
                <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                Generating Flashcards...
              </span>
            ) : (
              <span className="flex items-center">
                <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                </svg>
                Generate Flashcards
              </span>
            )}
          </button>
        </div>
      </div>

      {flashcards && flashcards.flashcards && flashcards.flashcards.length > 0 ? (
        <div className="space-y-6">
          <div className="flex justify-between items-center">
            <p className="text-sm text-gray-600">
              Generated {flashcards.total_count} flashcard{flashcards.total_count !== 1 ? 's' : ''}
            </p>
            <p className="text-xs text-gray-500">
              Click on any card to flip between question and answer
            </p>
          </div>
          
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {flashcards.flashcards.map((flashcard, index) => (
              <FlashcardItem
                key={index}
                flashcard={flashcard}
                index={index}
              />
            ))}
          </div>
        </div>
      ) : (
        <div className="text-center py-8 text-gray-500">
          <svg className="w-16 h-16 mx-auto mb-4 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
          </svg>
          <p>Click "Generate Flashcards" to create flashcards from your content</p>
        </div>
      )}
    </div>
  );
};

export default FlashcardsSection;
