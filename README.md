# PDF Flashcards Generator

A complete full-stack application that extracts text from PDF files, generates summaries, and creates flashcards using AI models. Built with React + Vite frontend and FastAPI backend.

## 🚀 Features

- **PDF Text Extraction**: Upload PDF files and automatically extract text content
- **Text Input**: Directly input text content for processing
- **AI-Powered Summarization**: Generate concise summaries using BART or T5 models
- **Flashcard Generation**: Create question-answer flashcards using advanced language models
- **Interactive UI**: Modern, responsive interface with TailwindCSS
- **Real-time Processing**: Live feedback and loading states

## 🛠 Tech Stack

### Backend
- **FastAPI**: Modern, fast web framework for Python
- **Python 3.11+**: Required for optimal performance
- **Transformers**: Hugging Face transformers for AI models
- **PyMuPDF & pdfplumber**: PDF text extraction libraries
- **Uvicorn**: ASGI server for running the application

### Frontend
- **React 18**: Modern React with hooks
- **Vite**: Fast build tool and development server
- **TailwindCSS**: Utility-first CSS framework
- **React Query**: Data fetching and state management
- **Axios**: HTTP client for API communication

## 📋 Prerequisites

- **Python 3.11 or higher**
- **Node.js 16 or higher** (for frontend)
- **npm or yarn** (package manager)
- **Git** (for cloning the repository)

## 🏗 Installation & Setup

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/pdf-flashcards-generator.git
cd pdf-flashcards-generator
```

### 2. Backend Setup

#### Option A: Using uv (Recommended)

```bash
cd backend

# Install uv if not already installed
pip install uv

# Initialize and install dependencies
uv init
uv add fastapi uvicorn[standard] python-multipart transformers torch pymupdf pdfplumber python-dotenv accelerate
```

#### Option B: Using pip

```bash
cd backend

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Or using yarn
yarn install
```

## 🚀 Running the Application

### Start the Backend Server

```bash
cd backend

# If using uv:
uv run python main.py

# If using pip/venv:
# Ensure virtual environment is activated, then:
python main.py

# Or alternatively:
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The backend will be available at: `http://localhost:8000`

### Start the Frontend Development Server

```bash
cd frontend

# Start the development server
npm run dev

# Or using yarn:
yarn dev
```

The frontend will be available at: `http://localhost:5173`

## 📖 API Documentation

Once the backend is running, you can access the interactive API documentation at:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

### API Endpoints

- `GET /` - Health check
- `POST /upload` - Upload PDF file or text content
- `POST /summarize` - Generate summary from text
- `POST /flashcards` - Generate flashcards from text

## 💡 Usage

1. **Upload Content**:
   - Use the "PDF Upload" tab to drag & drop or select a PDF file
   - Or use the "Text Input" tab to paste text directly

2. **Generate Summary**:
   - After uploading content, click "Generate Summary"
   - The AI will create a concise summary of the main points

3. **Create Flashcards**:
   - Select the number of flashcards (3-10)
   - Click "Generate Flashcards" to create question-answer pairs
   - Click on any flashcard to flip between question and answer

## 🎯 AI Models Used

- **Summarization**: `facebook/bart-large-cnn` (primary) or `google/flan-t5-base` (fallback)
- **Flashcard Generation**: `google/flan-t5-base`

Models are automatically downloaded on first use and cached locally.

## 🔧 Configuration

### Backend Configuration

You can modify model selection and other settings in `backend/main.py`:

```python
# Change summarization model
summarizer = pipeline(
    "summarization",
    model="facebook/bart-large-cnn",  # or "google/flan-t5-base"
    device=0 if torch.cuda.is_available() else -1
)
```

### Frontend Configuration

API base URL can be changed in `frontend/src/api.js`:

```javascript
const API_BASE_URL = 'http://localhost:8000';
```

## 🐛 Troubleshooting

### Common Issues

1. **Model Loading Errors**:
   - Ensure you have sufficient disk space (models can be 1-2GB)
   - Check your internet connection for initial model download

2. **PDF Upload Fails**:
   - Ensure the file is a valid PDF
   - Try using the text input as an alternative

3. **CORS Errors**:
   - Make sure both frontend and backend are running on the specified ports
   - Check that CORS is properly configured in `main.py`

### Performance Tips

- **GPU Usage**: If you have CUDA-compatible GPU, the models will automatically use it
- **Memory**: Large PDFs may require more RAM for processing
- **First Run**: Initial model downloads may take time

## 📁 Project Structure

```
pdf-flashcards-generator/
├── backend/
│   ├── main.py              # FastAPI application
│   ├── requirements.txt     # Python dependencies
│   ├── pyproject.toml      # UV project configuration
│   └── run.py              # Server startup script
├── frontend/
│   ├── src/
│   │   ├── components/     # React components
│   │   ├── api.js         # API service
│   │   ├── App.jsx        # Main app component
│   │   └── main.jsx       # Entry point
│   ├── package.json       # Node dependencies
│   ├── vite.config.js     # Vite configuration
│   └── tailwind.config.js # TailwindCSS configuration
└── README.md              # This file
```

## 🤝 Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Hugging Face for providing the transformers library and models
- FastAPI for the excellent web framework
- React and Vite teams for the frontend tools
- TailwindCSS for the styling framework

## 🔮 Future Enhancements

- [ ] User authentication and session management
- [ ] Save and export flashcards
- [ ] Multiple language support
- [ ] Custom model fine-tuning
- [ ] Batch processing for multiple PDFs
- [ ] Integration with spaced repetition algorithms
