import axios from 'axios';

const API_BASE_URL = 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const apiService = {
  // Upload PDF or text
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

  // Generate summary
  generateSummary: async (text) => {
    const response = await api.post('/summarize', { text });
    return response.data;
  },

  // Generate flashcards
  generateFlashcards: async (text, numCards = 5) => {
    const response = await api.post(`/flashcards?num_cards=${numCards}`, { text });
    return response.data;
  },

  // Health check
  healthCheck: async () => {
    const response = await api.get('/');
    return response.data;
  },
};

export default apiService;
