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

def chunk_text_with_overlap(text: str, max_length: int = 2048, overlap: int = 100) -> List[str]:
    """Split text into overlapping chunks for better context preservation"""
    words = text.split()
    chunks = []
    start = 0
    
    while start < len(words):
        end = min(start + max_length, len(words))
        chunk_words = words[start:end]
        chunks.append(' '.join(chunk_words))
        
        # Move start position, accounting for overlap
        if end == len(words):
            break
        start = end - overlap
        
        # Ensure we don't go backwards
        if start <= chunks.__len__() * (max_length - overlap):
            start = end - overlap
    
    return chunks

def validate_text_size(text: str, max_words: int = 5000) -> bool:
    """Validate that text doesn't exceed maximum word limit"""
    word_count = len(text.split())
    return word_count <= max_words

def generate_summary(text: str) -> str:
    """Generate summary using the loaded model - supports up to 5000 words"""
    if not summarizer:
        raise HTTPException(status_code=500, detail="Summarization model not loaded")
    
    # Clean the text
    text = clean_text(text)
    word_count = len(text.split())
    
    print(f"📊 Processing text with {word_count} words for summarization")
    
    # Increased limits for handling larger documents
    max_input_length = 2048  # Increased from 1024 to handle larger chunks
    
    if len(text) <= max_input_length:
        try:
            # Use max_new_tokens instead of max_length for summarization
            result = summarizer(text, max_new_tokens=150, min_length=40, do_sample=False)
            return result[0]['summary_text']
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Summarization failed: {str(e)}")
    else:
        # Process large documents in chunks with overlap for better context
        chunks = chunk_text_with_overlap(text, max_input_length, overlap=100)
        chunk_summaries = []
        
        print(f"📄 Processing {len(chunks)} chunks for large document")
        
        for i, chunk in enumerate(chunks):
            try:
                print(f"  Processing chunk {i+1}/{len(chunks)}...")
                result = summarizer(chunk, max_new_tokens=120, min_length=30, do_sample=False)
                chunk_summaries.append(result[0]['summary_text'])
            except Exception as e:
                print(f"Failed to summarize chunk {i+1}: {e}")
                # Add a simple summary for failed chunks
                sentences = chunk.split('. ')[:3]  # Take first 3 sentences as fallback
                if sentences:
                    chunk_summaries.append('. '.join(sentences) + '.')
                continue
        
        if not chunk_summaries:
            raise HTTPException(status_code=500, detail="Failed to summarize any text chunks")
        
        # Combine and create final summary
        combined_summary = ' '.join(chunk_summaries)
        
        # If combined summary is still too long, summarize it again
        if len(combined_summary.split()) > 300:  # If more than 300 words
            try:
                # Create a final comprehensive summary
                final_prompt = f"Provide a comprehensive summary of the following key points: {combined_summary[:max_input_length]}"
                final_result = summarizer(final_prompt, max_new_tokens=200, min_length=60, do_sample=False)
                return final_result[0]['summary_text']
            except Exception as e:
                print(f"Final summarization failed: {e}")
                # Return a truncated version of combined summaries
                words = combined_summary.split()
                return ' '.join(words[:200]) + '...' if len(words) > 200 else combined_summary
        
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
    """Upload PDF file or submit text directly - supports up to 5000 words"""
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
    
    # Validate text size - support up to 5000 words
    if not validate_text_size(extracted_text, max_words=5000):
        word_count = len(extracted_text.split())
        raise HTTPException(
            status_code=413, 
            detail=f"Text is too large. Maximum 5000 words allowed, but received {word_count} words. Please upload a smaller document or reduce the text length."
        )
    
    word_count = len(extracted_text.split())
    char_count = len(extracted_text)
    
    print(f"📤 Successfully processed document: {word_count} words, {char_count} characters")
    
    return UploadResponse(
        text=extracted_text,
        word_count=word_count,
        char_count=char_count
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
