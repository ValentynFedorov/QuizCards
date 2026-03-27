import os
import io
import json
import re
import random
from typing import Any, Dict, List, Optional, Union
from urllib import error as urllib_error
from urllib import request as urllib_request
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
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize models globally to avoid reloading
summarizer = None
flashcard_generator = None
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_QUIZ_MODEL = os.getenv("OLLAMA_QUIZ_MODEL", "qwen2.5:7b")
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "240"))

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
        print("[OK] Summarization model loaded successfully")
    except Exception as e:
        print(f"[WARN] Failed to load BART model, falling back to T5 summarization: {e}")
        try:
            summarizer = pipeline(
                "summarization",
                model="google/flan-t5-base",
                device=0 if torch.cuda.is_available() else -1
            )
            print("[OK] Fallback summarization model loaded successfully")
        except Exception as fallback_error:
            print(f"[ERROR] Could not load any summarization model: {fallback_error}")
            summarizer = None
    
    # Load flashcard generation model (using T5 for text-to-text generation)
    try:
        flashcard_generator = pipeline(
            "text2text-generation",
            model="google/flan-t5-base",
            device=0 if torch.cuda.is_available() else -1
        )
        print("[OK] Flashcard generation model loaded successfully")
    except Exception as e:
        print(f"[WARN] Failed to load text2text flashcard model, trying text-generation fallback: {e}")
        try:
            flashcard_generator = pipeline(
                "text-generation",
                model="distilgpt2",
                device=0 if torch.cuda.is_available() else -1
            )
            print("[OK] Fallback flashcard generation model loaded successfully")
        except Exception as fallback_error:
            print(f"[ERROR] Could not load any flashcard generation model: {fallback_error}")
            flashcard_generator = None

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

class KeyPointsResponse(BaseModel):
    key_points: List[str]
    total_count: int

class QuizQuestion(BaseModel):
    question: str
    options: List[str]
    correct_option: int
    explanation: str

class QuizResponse(BaseModel):
    questions: List[QuizQuestion]
    total_count: int
    generation_mode: str = "fast"
    provider: str = "local"
    model: Optional[str] = None
    fallback_used: bool = False

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
    if not words:
        return []

    # Ensure overlap value cannot break stepping logic
    overlap = max(0, min(overlap, max_length - 1))
    step = max_length - overlap
    chunks = []

    for start in range(0, len(words), step):
        end = min(start + max_length, len(words))
        chunk_words = words[start:end]
        chunks.append(' '.join(chunk_words))
        if end >= len(words):
            break
    return chunks

def validate_text_size(text: str, max_words: int = 5000) -> bool:
    """Validate that text doesn't exceed maximum word limit"""
    word_count = len(text.split())
    return word_count <= max_words

def extract_generated_text(result: List[Dict[str, str]]) -> str:
    """Extract text from HF pipeline output for different task types."""
    if not result:
        return ""
    item = result[0] if isinstance(result, list) and result else {}
    return (item.get("summary_text") or item.get("generated_text") or "").strip()

def run_generation_model(
    model_pipeline,
    prompt: str,
    max_new_tokens: int,
    min_length: Optional[int] = None,
    temperature: float = 0.7,
    do_sample: bool = True
) -> List[Dict[str, str]]:
    """Call generation pipeline safely across model/task variants."""
    params = {
        "max_new_tokens": max_new_tokens,
        "do_sample": do_sample,
    }

    if min_length is not None:
        params["min_length"] = min_length
    if do_sample:
        params["temperature"] = temperature

    tokenizer = getattr(model_pipeline, "tokenizer", None)
    eos_token_id = getattr(tokenizer, "eos_token_id", None) if tokenizer else None
    if eos_token_id is not None:
        params["pad_token_id"] = eos_token_id

    return model_pipeline(prompt, **params)

def fallback_summary(text: str, max_sentences: int = 4, max_words: int = 180) -> str:
    """Heuristic summary when no summarization model is available."""
    sentences = [s.strip() for s in re.split(r'[.!?]\s+', clean_text(text)) if s.strip()]
    if not sentences:
        return ""
    candidate = ". ".join(sentences[:max_sentences]).strip()
    if candidate and not candidate.endswith("."):
        candidate += "."
    words = candidate.split()
    if len(words) > max_words:
        return " ".join(words[:max_words]) + "..."
    return candidate

def sanitize_statement(value: str, max_words: int = 28) -> str:
    cleaned = re.sub(r'\s+', ' ', (value or '').strip())
    cleaned = re.sub(r'^[\-\*\•\d\.\)\(]+\s*', '', cleaned)
    cleaned = cleaned.strip(' "\'`')
    words = cleaned.split()
    if len(words) > max_words:
        cleaned = " ".join(words[:max_words]).rstrip(",;:") + "..."
    return cleaned

def split_definition_sentence(sentence: str) -> Optional[tuple]:
    patterns = [
        " is defined as ",
        " can be defined as ",
        " refers to ",
        " is ",
        " are ",
        " means ",
    ]
    low = sentence.lower()
    for pattern in patterns:
        idx = low.find(pattern)
        if idx > 2:
            subject = sentence[:idx].strip(" ,;:.")
            predicate = sentence[idx + len(pattern):].strip(" ,;:.")
            if len(subject.split()) >= 1 and len(predicate.split()) >= 2:
                return subject, predicate
    return None

def build_clear_question_from_content(content: str, fallback_index: int = 1) -> str:
    statement = sanitize_statement(content, max_words=24)
    definition = split_definition_sentence(statement)
    if definition:
        subject, _ = definition
        if len(subject) <= 80:
            return f"What is {subject}?"
    if len(statement.split()) >= 6:
        topic = " ".join(statement.split()[:6]).strip(" ,;:.")
        return f"What key idea is emphasized about {topic}?"
    return f"What is the key point number {fallback_index}?"

def sanitize_question(question: str) -> str:
    cleaned = re.sub(r'\s+', ' ', (question or '').strip())
    cleaned = re.sub(r'^(question|q)\s*[:\-\)]\s*', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r'^(create|generate|write|ask)\s+(a\s+)?(question|quiz\s+question)\s*(about|for)?\s*',
        '',
        cleaned,
        flags=re.IGNORECASE
    )
    cleaned = cleaned.strip(" \"'`")
    if cleaned and not cleaned.endswith("?"):
        cleaned += "?"
    return cleaned

def is_question_clear(question: str) -> bool:
    if not question:
        return False
    q = question.strip()
    if len(q) < 12 or len(q) > 180:
        return False
    if any(token in q.lower() for token in ["create a question", "generate a question", "ask about this"]):
        return False
    return q.endswith("?")

def extract_informative_sentences(text: str, max_items: int = 8) -> List[str]:
    raw_sentences = [sanitize_statement(s, max_words=32) for s in re.split(r'[.!?]\s+', clean_text(text))]
    candidates = [s for s in raw_sentences if len(s.split()) >= 6]

    def score(sentence: str) -> int:
        words = len(sentence.split())
        length_score = 30 - abs(18 - min(words, 30))
        bonus = 0
        if re.search(r'\d', sentence):
            bonus += 3
        if any(k in sentence.lower() for k in ["because", "therefore", "important", "key", "main", "defined"]):
            bonus += 2
        return length_score + bonus

    ranked = sorted(candidates, key=score, reverse=True)
    return dedupe_items(ranked, max_items=max_items)

def parse_json_from_text(value: str) -> Dict[str, Any]:
    payload = (value or "").strip()
    if not payload:
        raise ValueError("Empty model response")

    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        pass

    json_match = re.search(r"\{.*\}", payload, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(0))

    raise ValueError("Model response did not contain valid JSON")

def call_ollama_generate(prompt: str, model: str) -> Dict[str, Any]:
    url = f"{OLLAMA_BASE_URL}/api/generate"
    request_payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.15,
        },
    }
    request_data = json.dumps(request_payload).encode("utf-8")

    req = urllib_request.Request(
        url,
        data=request_data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", errors="ignore")
            return json.loads(body)
    except urllib_error.HTTPError as http_error:
        error_body = http_error.read().decode("utf-8", errors="ignore")
        try:
            parsed_error = json.loads(error_body)
            message = parsed_error.get("error") or parsed_error
        except Exception:
            message = error_body or str(http_error)
        raise RuntimeError(f"Ollama HTTP error: {message}") from http_error
    except urllib_error.URLError as network_error:
        raise RuntimeError(
            "Cannot connect to Ollama. Start it with: ollama serve"
        ) from network_error

def list_ollama_models() -> List[str]:
    url = f"{OLLAMA_BASE_URL}/api/tags"
    try:
        with urllib_request.urlopen(url, timeout=10) as response:
            body = response.read().decode("utf-8", errors="ignore")
            payload = json.loads(body)
    except Exception:
        return []

    models = payload.get("models") or []
    names = []
    for item in models:
        name = (item or {}).get("name")
        if name:
            names.append(name)
    return names

def build_ollama_quiz_prompt(text: str, num_questions: int) -> str:
    context = clean_text(text)
    if len(context) > 12000:
        prioritized = extract_informative_sentences(context, max_items=24)
        context = ". ".join(prioritized)

    return (
        "You generate high-quality multiple-choice quiz questions from study material.\n"
        "Requirements:\n"
        "- Use the same language as the source text.\n"
        f"- Return exactly {num_questions} questions.\n"
        "- Each question must be clear, specific, and directly answerable from the context.\n"
        "- Each question must have exactly 4 options and one correct option index (0..3).\n"
        "- explanation must be concise (1 sentence).\n"
        "- Avoid vague phrasing and avoid trick questions.\n"
        "Return strict JSON only in this schema:\n"
        "{\"questions\":[{\"question\":\"...\",\"options\":[\"...\",\"...\",\"...\",\"...\"],\"correct_option\":0,\"explanation\":\"...\"}]}\n\n"
        f"Context:\n{context}"
    )

def normalize_quiz_item(item: Dict[str, Any], index: int) -> Optional[Dict[str, Union[str, int, List[str]]]]:
    question = sanitize_question(str((item or {}).get("question", "")))
    explanation = sanitize_statement(str((item or {}).get("explanation", "")), max_words=28)

    raw_options = (item or {}).get("options", [])
    if not isinstance(raw_options, list):
        raw_options = []
    options = [sanitize_statement(str(opt), max_words=20) for opt in raw_options if sanitize_statement(str(opt), max_words=20)]

    # Deduplicate options while keeping order
    unique_options = []
    seen_opts = set()
    for opt in options:
        key = opt.lower()
        if key in seen_opts:
            continue
        seen_opts.add(key)
        unique_options.append(opt)
    options = unique_options

    try:
        correct_option = int((item or {}).get("correct_option", 0))
    except Exception:
        correct_option = 0

    if not is_question_clear(question):
        source = explanation or (options[0] if options else f"topic {index + 1}")
        question = build_clear_question_from_content(source, fallback_index=index + 1)

    if len(options) < 4:
        fallback_distractors = [
            "A secondary detail from the material.",
            "A statement not supported by the source text.",
            "A claim that conflicts with the main point.",
            "An unrelated interpretation.",
        ]
        for distractor in fallback_distractors:
            if len(options) >= 4:
                break
            if distractor.lower() not in [opt.lower() for opt in options]:
                options.append(distractor)

    if len(options) > 4:
        options = options[:4]

    if correct_option < 0 or correct_option >= len(options):
        correct_option = 0

    if not question or len(options) < 4:
        return None

    return {
        "question": question,
        "options": options,
        "correct_option": correct_option,
        "explanation": explanation or options[correct_option],
    }

def generate_quiz_questions_ollama(
    text: str,
    num_questions: int = 5,
    model_name: Optional[str] = None,
) -> Dict[str, Any]:
    selected_model = (model_name or OLLAMA_QUIZ_MODEL).strip()
    prompt = build_ollama_quiz_prompt(text, num_questions)
    model_result = call_ollama_generate(prompt, selected_model)

    raw_response = model_result.get("response", "")
    parsed_payload = parse_json_from_text(raw_response)
    raw_questions = parsed_payload.get("questions") or []
    if not isinstance(raw_questions, list):
        raise ValueError("Ollama response JSON must contain a questions list")

    normalized_questions = []
    seen_questions = set()
    for idx, item in enumerate(raw_questions[: num_questions * 3]):
        if not isinstance(item, dict):
            continue
        normalized = normalize_quiz_item(item, idx)
        if not normalized:
            continue
        key = normalized["question"].strip().lower()
        if key in seen_questions:
            continue
        seen_questions.add(key)
        normalized_questions.append(normalized)
        if len(normalized_questions) >= num_questions:
            break

    return {
        "questions": normalized_questions[:num_questions],
        "model": selected_model,
    }

def generate_summary(text: str) -> str:
    """Generate summary using the loaded model - supports up to 5000 words"""
    # Clean the text
    text = clean_text(text)
    word_count = len(text.split())
    
    print(f"[INFO] Processing text with {word_count} words for summarization")

    if not summarizer:
        print("[WARN] Summarization model unavailable, using heuristic summary fallback")
        return fallback_summary(text)
    
    # Increased limits for handling larger documents
    max_input_length = 2048  # Increased from 1024 to handle larger chunks
    
    if len(text) <= max_input_length:
        try:
            result = run_generation_model(
                summarizer,
                text,
                max_new_tokens=150,
                min_length=40,
                do_sample=False
            )
            generated = extract_generated_text(result)
            return generated or fallback_summary(text)
        except Exception as e:
            print(f"Summarization failed, using fallback: {e}")
            return fallback_summary(text)
    else:
        # Process large documents in chunks with overlap for better context
        chunks = chunk_text_with_overlap(text, max_input_length, overlap=100)
        chunk_summaries = []
        
        print(f"[INFO] Processing {len(chunks)} chunks for large document")
        
        for i, chunk in enumerate(chunks):
            try:
                print(f"  Processing chunk {i+1}/{len(chunks)}...")
                result = run_generation_model(
                    summarizer,
                    chunk,
                    max_new_tokens=120,
                    min_length=30,
                    do_sample=False
                )
                generated = extract_generated_text(result)
                if generated:
                    chunk_summaries.append(generated)
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
                final_result = run_generation_model(
                    summarizer,
                    final_prompt,
                    max_new_tokens=200,
                    min_length=60,
                    do_sample=False
                )
                generated = extract_generated_text(final_result)
                if generated:
                    return generated
            except Exception as e:
                print(f"Final summarization failed: {e}")
                # Return a truncated version of combined summaries
                words = combined_summary.split()
                return ' '.join(words[:200]) + '...' if len(words) > 200 else combined_summary
        
        return combined_summary

def generate_flashcards_fallback(text: str, num_cards: int = 5) -> List[Dict[str, str]]:
    """Generate simple flashcards without ML models."""
    text = clean_text(text)
    if not text:
        return []
    sentences = extract_informative_sentences(text, max_items=max(num_cards * 2, 8))
    if not sentences:
        sentences = [sanitize_statement(s, max_words=24) for s in re.split(r'[.!?]\s+', text) if len(s.strip()) > 20]

    cards = []
    for i, sentence in enumerate(sentences[:num_cards]):
        answer = sanitize_statement(sentence, max_words=24)
        cards.append({
            "question": build_clear_question_from_content(answer, fallback_index=i + 1),
            "answer": answer
        })

    return cards[:num_cards]

def generate_flashcards(text: str, num_cards: int = 5) -> List[Dict[str, str]]:
    """Generate flashcards using the loaded model"""
    if not flashcard_generator:
        print("[WARN] Flashcard model unavailable, using heuristic flashcards")
        return generate_flashcards_fallback(text, num_cards)
    
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
            result = run_generation_model(
                flashcard_generator,
                prompt,
                max_new_tokens=50,
                temperature=0.8,
                do_sample=True
            )
            
            generated_question = sanitize_question(extract_generated_text(result))
            
            if not is_question_clear(generated_question):
                generated_question = build_clear_question_from_content(content, fallback_index=i + 1)
            
            # Use the original content as the answer, but make it more concise
            answer = sanitize_statement(content, max_words=24)
            if len(content) > 150:
                # Summarize long answers
                answer_prompt = f"Summarize this in one sentence: {content}"
                answer_result = run_generation_model(
                    flashcard_generator,
                    answer_prompt,
                    max_new_tokens=30,
                    temperature=0.3,
                    do_sample=False
                )
                answer = sanitize_statement(extract_generated_text(answer_result), max_words=24) or sanitize_statement(content, max_words=24)
            
            flashcards.append({
                "question": generated_question,
                "answer": answer
            })
            
        except Exception as e:
            print(f"Failed to generate flashcard {i}: {e}")
            # Create a simple fallback flashcard
            if content:
                flashcards.append({
                    "question": build_clear_question_from_content(content, fallback_index=i + 1),
                    "answer": sanitize_statement(content, max_words=24)
                })
    
    # Ensure we have the requested number of cards
    while len(flashcards) < num_cards and text:
        # Create additional simple flashcards from remaining content
        remaining_sentences = [s for s in sentences if s not in [fc["answer"] for fc in flashcards]]
        if remaining_sentences:
            sentence = remaining_sentences[0]
            flashcards.append({
                "question": build_clear_question_from_content(sentence, fallback_index=len(flashcards) + 1),
                "answer": sanitize_statement(sentence, max_words=24)
            })
        else:
            break

    deduped_flashcards = []
    seen_pairs = set()
    for card in flashcards:
        question = normalize_option_text(card.get("question", ""))
        answer = normalize_option_text(card.get("answer", ""))
        if not question or not answer:
            continue
        key = f"{question.lower()}|{answer.lower()}"
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        deduped_flashcards.append({"question": question, "answer": answer})
        if len(deduped_flashcards) >= num_cards:
            break

    return deduped_flashcards[:num_cards]

def dedupe_items(items: List[str], max_items: int = 8) -> List[str]:
    """Normalize and deduplicate short text items."""
    seen = set()
    unique_items = []

    for item in items:
        cleaned = re.sub(r'^\s*[-*•\d\.\)]\s*', '', item or '').strip()
        if not cleaned:
            continue
        key = re.sub(r'[^a-zA-Z0-9а-яА-ЯіїєґІЇЄҐ]+', '', cleaned.lower())
        if len(key) < 6:
            continue
        if key in seen:
            continue
        seen.add(key)
        unique_items.append(cleaned)
        if len(unique_items) >= max_items:
            break

    return unique_items

def generate_key_points(text: str, max_points: int = 8) -> List[str]:
    """Generate concise key points from text using model + robust fallback."""

    text = clean_text(text)
    if not text:
        return []

    prompt = (
        f"Extract {max_points} key learning points from this text. "
        "Return one point per line, concise and factual, without numbering:\n\n"
        f"{text[:3500]}"
    )

    if flashcard_generator:
        try:
            result = run_generation_model(
                flashcard_generator,
                prompt,
                max_new_tokens=220,
                temperature=0.2,
                do_sample=False
            )
            generated = extract_generated_text(result)
            raw_points = [line.strip() for line in re.split(r'[\n\r]+', generated) if line.strip()]
            points = dedupe_items(raw_points, max_points)
            if points:
                return points
        except Exception as e:
            print(f"Key points model generation failed, using fallback: {e}")
    else:
        print("[WARN] Key-points model unavailable, using heuristic fallback")

    # Fallback: extract informative sentences
    return extract_informative_sentences(text, max_items=max_points)

def normalize_option_text(value: str) -> str:
    cleaned = re.sub(r'\s+', ' ', (value or '').strip())
    return cleaned[:180]

def generate_quiz_questions(text: str, num_questions: int = 5) -> List[Dict[str, Union[str, int, List[str]]]]:
    """Generate multiple-choice quiz questions from flashcards."""
    text = clean_text(text)
    if not text:
        return []

    # Reuse flashcards as a stable source of QA pairs
    base_cards = generate_flashcards(text, max(6, num_questions + 2))
    if not base_cards:
        return []

    informative_pool = extract_informative_sentences(text, max_items=max(num_questions * 4, 12))
    answers_pool = dedupe_items(
        [normalize_option_text(card.get("answer", "")) for card in base_cards] + informative_pool,
        max_items=32
    )
    questions = []
    seen_questions = set()

    for card in base_cards:
        if len(questions) >= num_questions:
            break

        question_text = sanitize_question((card.get("question") or "").strip())
        correct_answer = normalize_option_text(card.get("answer") or "")

        if not question_text or not correct_answer:
            continue
        if not is_question_clear(question_text):
            question_text = build_clear_question_from_content(correct_answer, fallback_index=len(questions) + 1)

        question_key = question_text.lower()
        if question_key in seen_questions:
            continue
        seen_questions.add(question_key)

        distractors = [ans for ans in answers_pool if ans.lower() != correct_answer.lower()]
        random.shuffle(distractors)

        options = [correct_answer]
        for distractor in distractors:
            if len(options) >= 4:
                break
            if distractor.lower() not in [opt.lower() for opt in options]:
                options.append(distractor)

        fallback_distractors = [
            "A secondary detail that is not the main takeaway.",
            "An interpretation that is not supported by the source text.",
            "A claim that contradicts the core idea in the material.",
        ]
        for distractor in fallback_distractors:
            if len(options) >= 4:
                break
            if distractor.lower() not in [opt.lower() for opt in options]:
                options.append(distractor)

        random.shuffle(options)
        correct_index = options.index(correct_answer)

        questions.append({
            "question": question_text,
            "options": options,
            "correct_option": correct_index,
            "explanation": correct_answer
        })

    return questions[:num_questions]

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
        except HTTPException:
            raise
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
    
    print(f"[OK] Successfully processed document: {word_count} words, {char_count} characters")
    
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
    except HTTPException:
        raise
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Flashcard generation failed: {str(e)}")

@app.post("/key-points", response_model=KeyPointsResponse)
async def create_key_points(input_data: TextInput, max_points: int = 8):
    """Generate key points from text"""
    if not input_data.text or not input_data.text.strip():
        raise HTTPException(status_code=400, detail="Text content is required")

    if max_points < 3 or max_points > 12:
        raise HTTPException(status_code=400, detail="max_points must be between 3 and 12")

    try:
        key_points = generate_key_points(input_data.text, max_points=max_points)
        return KeyPointsResponse(
            key_points=key_points,
            total_count=len(key_points)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Key points generation failed: {str(e)}")
@app.get("/ollama/models")
async def get_ollama_models():
    """List locally available Ollama models for high-quality quiz mode."""
    models = list_ollama_models()
    return {
        "available": len(models) > 0,
        "models": models,
        "default_model": OLLAMA_QUIZ_MODEL,
    }

@app.post("/quiz", response_model=QuizResponse)
async def create_quiz(
    input_data: TextInput,
    num_questions: int = 5,
    mode: str = "fast",
    ollama_model: Optional[str] = None,
):
    """Generate multiple-choice quiz from text"""
    if not input_data.text or not input_data.text.strip():
        raise HTTPException(status_code=400, detail="Text content is required")

    if num_questions < 3 or num_questions > 12:
        raise HTTPException(status_code=400, detail="Number of questions must be between 3 and 12")

    mode = (mode or "fast").lower()
    if mode not in {"fast", "high_quality"}:
        raise HTTPException(status_code=400, detail="mode must be 'fast' or 'high_quality'")

    try:
        questions_data = []
        provider = "local"
        used_model = None
        fallback_used = False
        generation_mode = mode

        if mode == "high_quality":
            try:
                ollama_result = generate_quiz_questions_ollama(
                    input_data.text,
                    num_questions=num_questions,
                    model_name=ollama_model,
                )
                questions_data = ollama_result.get("questions", [])
                used_model = ollama_result.get("model")
                provider = "ollama"
                if not questions_data:
                    raise ValueError("Ollama returned empty question set")
                if len(questions_data) < num_questions:
                    fallback_needed = num_questions - len(questions_data)
                    fallback_used = True
                    fallback_candidates = generate_quiz_questions(input_data.text, num_questions=fallback_needed + 2)
                    existing = {q.get("question", "").strip().lower() for q in questions_data}
                    for candidate in fallback_candidates:
                        key = candidate.get("question", "").strip().lower()
                        if not key or key in existing:
                            continue
                        questions_data.append(candidate)
                        existing.add(key)
                        if len(questions_data) >= num_questions:
                            break
            except Exception as ollama_error:
                print(f"[WARN] High-quality Ollama quiz failed, using fast fallback: {ollama_error}")
                questions_data = generate_quiz_questions(input_data.text, num_questions=num_questions)
                provider = "local-fallback"
                used_model = (ollama_model or OLLAMA_QUIZ_MODEL)
                fallback_used = True
                generation_mode = "fast"
        else:
            questions_data = generate_quiz_questions(input_data.text, num_questions=num_questions)
        questions = [QuizQuestion(**question) for question in questions_data]
        return QuizResponse(
            questions=questions,
            total_count=len(questions),
            generation_mode=generation_mode,
            provider=provider,
            model=used_model,
            fallback_used=fallback_used,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Quiz generation failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
