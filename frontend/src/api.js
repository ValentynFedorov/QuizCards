import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const apiService = {
  uploadContent: async (file, text) => {
    const formData = new FormData();

    if (file) {
      formData.append('file', file);
    }

    if (text) {
      formData.append('text', text);
    }

    const response = await api.post('/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });

    return response.data;
  },

  generateSummary: async (text) => {
    const response = await api.post('/summarize', { text });
    return response.data;
  },

  generateFlashcards: async (text, numCards = 5, mode = 'qa') => {
    const params = new URLSearchParams({
      num_cards: String(numCards),
      mode,
    });
    const response = await api.post(`/flashcards?${params.toString()}`, { text });
    return response.data;
  },

  generateKeyPoints: async (text, maxPoints = 8) => {
    const response = await api.post(`/key-points?max_points=${maxPoints}`, { text });
    return response.data;
  },

  generateQuiz: async (text, numQuestions = 5, mode = 'fast', ollamaModel = '') => {
    const params = new URLSearchParams({
      num_questions: String(numQuestions),
      mode,
    });

    if (ollamaModel?.trim()) {
      params.append('ollama_model', ollamaModel.trim());
    }

    const response = await api.post(`/quiz?${params.toString()}`, { text });
    return response.data;
  },

  startStudyJob: async ({
    text,
    numCards = 6,
    numQuestions = 6,
    flashcardMode = 'qa',
    quizMode = 'fast',
    ollamaModel = '',
    includeSummary = true,
    includeKeyPoints = true,
  }) => {
    const response = await api.post('/jobs/study', {
      text,
      num_cards: numCards,
      num_questions: numQuestions,
      flashcard_mode: flashcardMode,
      quiz_mode: quizMode,
      ollama_model: ollamaModel?.trim() || null,
      include_summary: includeSummary,
      include_key_points: includeKeyPoints,
    });
    return response.data;
  },

  getStudyJob: async (jobId) => {
    const response = await api.get(`/jobs/study/${jobId}`);
    return response.data;
  },

  generateQuizInsights: async (attempts) => {
    const response = await api.post('/quiz/insights', { attempts });
    return response.data;
  },

  generateAdaptiveReview: async (attempts, flashcards = []) => {
    const response = await api.post('/review/adaptive', {
      attempts,
      flashcards,
    });
    return response.data;
  },

  getCacheStats: async () => {
    const response = await api.get('/system/cache');
    return response.data;
  },

  healthCheck: async () => {
    const response = await api.get('/');
    return response.data;
  },
};

export default apiService;
