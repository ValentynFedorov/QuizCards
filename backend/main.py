import os
import io
import json
import re
from typing import Dict, List, Optional, Union
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import fitz  # PyMuPDF
import pdfplumber
from transformers import pipeline, AutoTokenizer
import torch

# Initialize FastAPI app
app = FastAPI(
    title="PDF Flashcards API",
    description="Extract text from PDFs, generate summaries and flashcards",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],  # React dev servers
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize models globally to avoid reloading
summarizer = None
flashcard_generator = None

@app.on_event("startup")
async def startup_event():
    """Load ML models on startup"""
    global summarizer, flashcard_generator
    
    print("Loading models...")
    
    # Load summarization model
    try:
        summarizer = pipeline(
            "summarization",
            model="facebook/bart-large-cnn",
            device=0 if torch.cuda.is_available() else -1
        )
        print("✅ Summarization model loaded successfully")
    except Exception as e:
        print(f"⚠️  Failed to load BART model, falling back to T5: {e}")
        summarizer = pipeline(
            "summarization",
            model="google/flan-t5-base",
            device=0 if torch.cuda.is_available() else -1
        )
    
    # Load flashcard generation model (using T5 for text-to-text generation)
    try:
        flashcard_generator = pipeline(
            "text2text-generation",
            model="google/flan-t5-base",
            device=0 if torch.cuda.is_available() else -1
        )
        print("✅ Flashcard generation model loaded successfully")
    except Exception as e:
        print(f"❌ Failed to load flashcard model: {e}")
        # Fallback to using the summarizer for flashcards
        flashcard_generator = summarizer

# Pydantic models
class TextInput(BaseModel):
    text: str

class SummaryResponse(BaseModel):
    summary: str
    original_length: int
    summary_length: int

class Flashcard(BaseModel):
    question: str
    answer: str

class FlashcardsResponse(BaseModel):
    flashcards: List[Flashcard]
    total_count: int

def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract text from PDF using PyMuPDF with fallback to pdfplumber"""
    text = ""
    
    try:
        # Try PyMuPDF first
        pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
        for page_num in range(pdf_document.page_count):
            page = pdf_document.get_page(page_num)
            text += page.get_text()
        pdf_document.close()
        
        if text.strip():
            return text
    except Exception as e:
        print(f"PyMuPDF extraction failed: {e}")
    
    try:
        # Fallback to pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        print(f"pdfplumber extraction failed: {e}")
        raise HTTPException(status_code=400, detail="Could not extract text from PDF")
    
    if not text.strip():
        raise HTTPException(status_code=400, detail="No text found in PDF")
    
    return text

def clean_text(text: str) -> str:
    """Clean and normalize extracted text"""
    # Remove excessive whitespace and normalize
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    return text

def chunk_text(text: str, max_length: int = 1024) -> List[str]:
    """Split text into chunks for model processing"""
    words = text.split()
    chunks = []
    current_chunk = []
    current_length = 0
    
    for word in words:
        word_length = len(word) + 1  # +1 for space
        if current_length + word_length > max_length and current_chunk:
            chunks.append(' '.join(current_chunk))
            current_chunk = [word]
            current_length = word_length
        else:
            current_chunk.append(word)
            current_length += word_length
    
    if current_chunk:
        chunks.append(' '.join(current_chunk))
    
    return chunks

def generate_summary(text: str) -> str:
    """Generate summary using the loaded model"""
    if not summarizer:
        raise HTTPException(status_code=500, detail="Summarization model not loaded")
    
    # Clean the text
    text = clean_text(text)
    
    # If text is too long, chunk it and summarize each chunk
    max_input_length = 1024  # Safe length for most models
    
    if len(text) <= max_input_length:
        try:
            # Use max_new_tokens instead of max_length for summarization
            result = summarizer(text, max_new_tokens=100, min_length=30, do_sample=False)
            return result[0]['summary_text']
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Summarization failed: {str(e)}")
    else:
        # Process in chunks
        chunks = chunk_text(text, max_input_length)
        chunk_summaries = []
        
        for chunk in chunks:
            try:
                result = summarizer(chunk, max_new_tokens=80, min_length=20, do_sample=False)
                chunk_summaries.append(result[0]['summary_text'])
            except Exception as e:
                print(f"Failed to summarize chunk: {e}")
                continue
        
        if not chunk_summaries:
            raise HTTPException(status_code=500, detail="Failed to summarize any text chunks")
        
        # Combine and summarize the chunk summaries
        combined_summary = ' '.join(chunk_summaries)
        if len(combined_summary) > max_input_length:
            # If still too long, truncate
            combined_summary = combined_summary[:max_input_length]
        
        try:
            final_result = summarizer(combined_summary, max_new_tokens=120, min_length=50, do_sample=False)
            return final_result[0]['summary_text']
        except Exception as e:
            # Return the combined summaries if final summarization fails
            return combined_summary

def generate_flashcards(text: str, num_cards: int = 5) -> List[Dict[str, str]]:
    """Generate flashcards using the loaded model"""
    if not flashcard_generator:
        raise HTTPException(status_code=500, detail="Flashcard generation model not loaded")
    
    text = clean_text(text)
    flashcards = []
    
    # Split text into sentences for creating question-answer pairs
    sentences = [s.strip() for s in text.split('.') if s.strip()]
    
    # If we have fewer sentences than requested cards, use chunks
    if len(sentences) < num_cards:
        chunks = chunk_text(text, 200)  # Smaller chunks for better context
        content_pieces = chunks[:num_cards]
    else:
        # Use sentences, taking every nth sentence to get variety
        step = max(1, len(sentences) // num_cards)
        content_pieces = [sentences[i] for i in range(0, min(len(sentences), num_cards * step), step)][:num_cards]
    
    for i, content in enumerate(content_pieces):
        try:
            # Create more specific prompts for better question generation
            prompts = [
                f"Create a question about this information: {content}",
                f"What question would test understanding of: {content}",
                f"Generate a quiz question for: {content}",
                f"Ask about the key point in: {content}",
                f"What would you ask to test knowledge of: {content}"
            ]
            
            # Use different prompt for each flashcard
            prompt = prompts[i % len(prompts)]
            
            # Generate just the question first
            result = flashcard_generator(
                prompt, 
                max_new_tokens=50,  # Use max_new_tokens instead of max_length
                temperature=0.8, 
                do_sample=True,
                pad_token_id=flashcard_generator.tokenizer.eos_token_id
            )
            
            generated_question = result[0]['generated_text'].strip()
            
            # Clean up the generated question
            if not generated_question.endswith('?'):
                generated_question += '?'
            
            # Use the original content as the answer, but make it more concise
            answer = content.strip()
            if len(answer) > 150:
                # Summarize long answers
                answer_prompt = f"Summarize this in one sentence: {content}"
                answer_result = flashcard_generator(
                    answer_prompt,
                    max_new_tokens=30,
                    temperature=0.3,
                    do_sample=False,
                    pad_token_id=flashcard_generator.tokenizer.eos_token_id
                )
                answer = answer_result[0]['generated_text'].strip()
            
            flashcards.append({
                "question": generated_question,
                "answer": answer
            })
            
        except Exception as e:
            print(f"Failed to generate flashcard {i}: {e}")
            # Create a simple fallback flashcard
            if content:
                # Extract key information for question
                words = content.split()
                if len(words) > 5:
                    # Create a fill-in-the-blank style question
                    key_word = words[len(words)//2]  # Pick a word from the middle
                    question_text = content.replace(key_word, "_____", 1)
                    flashcards.append({
                        "question": f"Fill in the blank: {question_text}?",
                        "answer": key_word
                    })
                else:
                    flashcards.append({
                        "question": f"What does this statement describe: '{content}'?",
                        "answer": "The information provided in the text."
                    })
    
    # Ensure we have the requested number of cards
    while len(flashcards) < num_cards and text:
        # Create additional simple flashcards from remaining content
        remaining_sentences = [s for s in sentences if s not in [fc["answer"] for fc in flashcards]]
        if remaining_sentences:
            sentence = remaining_sentences[0]
            flashcards.append({
                "question": f"What information is provided about this topic?",
                "answer": sentence
            })
        else:
            break
    
    return flashcards[:num_cards]

# API Endpoints

@app.get("/")
async def root():
    """Health check endpoint"""
    return {"message": "PDF Flashcards API is running"}

class UploadResponse(BaseModel):
    text: str
    word_count: int
    char_count: int

@app.post("/upload", response_model=UploadResponse)
async def upload_file(
    file: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None)
):
    """Upload PDF file or submit text directly"""
    if not file and not text:
        raise HTTPException(status_code=400, detail="Either file or text must be provided")
    
    extracted_text = ""
    
    if file:
        # Validate file type
        if not file.content_type == "application/pdf":
            raise HTTPException(status_code=400, detail="Only PDF files are allowed")
        
        # Read and extract text from PDF
        try:
            pdf_bytes = await file.read()
            extracted_text = extract_text_from_pdf(pdf_bytes)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error processing PDF: {str(e)}")
    else:
        extracted_text = text
    
    if not extracted_text or not extracted_text.strip():
        raise HTTPException(status_code=400, detail="No text content found")
    
    return UploadResponse(
        text=extracted_text,
        word_count=len(extracted_text.split()),
        char_count=len(extracted_text)
    )

@app.post("/summarize", response_model=SummaryResponse)
async def create_summary(input_data: TextInput):
    """Generate summary from text"""
    if not input_data.text or not input_data.text.strip():
        raise HTTPException(status_code=400, detail="Text content is required")
    
    try:
        summary = generate_summary(input_data.text)
        
        return SummaryResponse(
            summary=summary,
            original_length=len(input_data.text.split()),
            summary_length=len(summary.split())
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Summary generation failed: {str(e)}")

@app.post("/flashcards", response_model=FlashcardsResponse)
async def create_flashcards(input_data: TextInput, num_cards: int = 5):
    """Generate flashcards from text"""
    if not input_data.text or not input_data.text.strip():
        raise HTTPException(status_code=400, detail="Text content is required")
    
    if num_cards < 1 or num_cards > 10:
        raise HTTPException(status_code=400, detail="Number of cards must be between 1 and 10")
    
    try:
        flashcards_data = generate_flashcards(input_data.text, num_cards)
        flashcards = [Flashcard(**card) for card in flashcards_data]
        
        return FlashcardsResponse(
            flashcards=flashcards,
            total_count=len(flashcards)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Flashcard generation failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
