import os
import io
import json
import re
import random
import copy
import time
import uuid
import asyncio
import hashlib
import threading
from collections import OrderedDict, Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib import error as urllib_error
from urllib import request as urllib_request

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import fitz  # PyMuPDF
import pdfplumber
from transformers import pipeline
import torch


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class InMemoryLRUCache:
    def __init__(self, max_items: int = 128):
        self.max_items = max_items
        self._store: OrderedDict[str, Any] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._store:
                return None
            value = self._store.pop(key)
            self._store[key] = value
            return copy.deepcopy(value)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if key in self._store:
                self._store.pop(key)
            self._store[key] = copy.deepcopy(value)
            while len(self._store) > self.max_items:
                self._store.popitem(last=False)

    def has(self, key: str) -> bool:
        with self._lock:
            return key in self._store

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                "size": len(self._store),
                "max_items": self.max_items,
            }


# App + CORS
app = FastAPI(
    title="PDF Flashcards API",
    description="Extract text from PDFs, generate summaries, grounded flashcards, quizzes and adaptive study signals",
    version="2.0.0",
)

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


# Runtime config
MAX_WORDS = int(os.getenv("MAX_WORDS", "30000"))
MAX_FLASHCARDS = int(os.getenv("MAX_FLASHCARDS", "20"))
MAX_QUIZ_QUESTIONS = int(os.getenv("MAX_QUIZ_QUESTIONS", "20"))
MAX_KEY_POINTS = int(os.getenv("MAX_KEY_POINTS", "20"))
CHUNK_WORDS = int(os.getenv("CHUNK_WORDS", "280"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_QUIZ_MODEL = os.getenv("OLLAMA_QUIZ_MODEL", "qwen2.5:7b")
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "240"))

DOCUMENT_CACHE = InMemoryLRUCache(max_items=128)
RESULT_CACHE = InMemoryLRUCache(max_items=512)

# async job state
JOB_STORE: Dict[str, Dict[str, Any]] = {}
JOB_LOCK = threading.Lock()
JOB_MAX_ITEMS = 200


# Global models
summarizer = None
flashcard_generator = None


@app.on_event("startup")
async def startup_event():
    global summarizer, flashcard_generator
    print("Loading models...")
    try:
        summarizer = pipeline(
            "summarization",
            model="facebook/bart-large-cnn",
            device=0 if torch.cuda.is_available() else -1,
        )
        print("[OK] Summarization model loaded: facebook/bart-large-cnn")
    except Exception as e:
        print(f"[WARN] BART load failed, fallback to flan-t5-base summarization: {e}")
        try:
            summarizer = pipeline(
                "summarization",
                model="google/flan-t5-base",
                device=0 if torch.cuda.is_available() else -1,
            )
            print("[OK] Fallback summarization model loaded: google/flan-t5-base")
        except Exception as fallback_error:
            print(f"[ERROR] Could not load summarization model: {fallback_error}")
            summarizer = None

    try:
        flashcard_generator = pipeline(
            "text2text-generation",
            model="google/flan-t5-base",
            device=0 if torch.cuda.is_available() else -1,
        )
        print("[OK] Flashcard generation model loaded: google/flan-t5-base")
    except Exception as e:
        print(f"[WARN] text2text load failed, fallback to distilgpt2: {e}")
        try:
            flashcard_generator = pipeline(
                "text-generation",
                model="distilgpt2",
                device=0 if torch.cuda.is_available() else -1,
            )
            print("[OK] Fallback flashcard model loaded: distilgpt2")
        except Exception as fallback_error:
            print(f"[ERROR] Could not load flashcard generation model: {fallback_error}")
            flashcard_generator = None


# Pydantic models
class TextInput(BaseModel):
    text: str


class SummaryResponse(BaseModel):
    summary: str
    original_length: int
    summary_length: int
    doc_hash: Optional[str] = None


class Flashcard(BaseModel):
    question: str
    answer: str
    mode: str = "qa"
    cloze_answer: Optional[str] = None
    source_excerpt: Optional[str] = None
    source_chunk_id: Optional[str] = None
    source_position: Optional[str] = None


class FlashcardsResponse(BaseModel):
    flashcards: List[Flashcard]
    total_count: int
    mode: str = "qa"


class KeyPointsResponse(BaseModel):
    key_points: List[str]
    total_count: int
    doc_hash: Optional[str] = None


class QuizQuestion(BaseModel):
    question: str
    options: List[str]
    correct_option: int
    explanation: str
    wrong_option_explanations: List[str] = Field(default_factory=list)
    source_excerpt: Optional[str] = None
    source_chunk_id: Optional[str] = None
    source_position: Optional[str] = None


class QuizResponse(BaseModel):
    questions: List[QuizQuestion]
    total_count: int
    generation_mode: str = "fast"
    provider: str = "local"
    model: Optional[str] = None
    fallback_used: bool = False
    doc_hash: Optional[str] = None


class UploadResponse(BaseModel):
    text: str
    word_count: int
    char_count: int
    doc_hash: str
    chunk_count: int


class StudyJobRequest(BaseModel):
    text: str
    num_cards: int = 6
    num_questions: int = 6
    flashcard_mode: str = "qa"
    quiz_mode: str = "fast"
    ollama_model: Optional[str] = None
    include_summary: bool = True
    include_key_points: bool = True


class StudyJobCreateResponse(BaseModel):
    job_id: str
    status: str
    stage: str
    progress: int


class StudyJobStatusResponse(BaseModel):
    job_id: str
    status: str
    stage: str
    progress: int
    message: str
    created_at: str
    updated_at: str
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


class QuizAttemptItem(BaseModel):
    question: str
    options: List[str]
    correct_option: int
    selected_option: Optional[int] = None
    explanation: Optional[str] = None
    wrong_option_explanations: Optional[List[str]] = None
    confidence: Optional[float] = None


class WeakTopicsRequest(BaseModel):
    attempts: List[QuizAttemptItem]


class WeakTopic(BaseModel):
    topic: str
    mistakes: int
    attempts: int
    accuracy: float
    recommendation: str


class WeakTopicsResponse(BaseModel):
    weak_topics: List[WeakTopic]
    overall_accuracy: float
    total_attempts: int


class AdaptiveReviewRequest(BaseModel):
    attempts: List[QuizAttemptItem]
    flashcards: Optional[List[Flashcard]] = None


class AdaptiveReviewItem(BaseModel):
    item_id: str
    prompt: str
    priority: int
    next_review_minutes: int
    reason: str


class AdaptiveReviewResponse(BaseModel):
    queue: List[AdaptiveReviewItem]
    generated_at: str


# Text processing
TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яІіЇїЄєҐґ0-9']+")
STOPWORDS = {
    "the",
    "and",
    "for",
    "from",
    "with",
    "this",
    "that",
    "into",
    "about",
    "your",
    "their",
    "have",
    "has",
    "was",
    "were",
    "will",
    "would",
    "could",
    "should",
    "not",
    "you",
    "they",
    "them",
    "our",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "how",
    "are",
    "is",
    "to",
    "of",
    "in",
    "on",
    "a",
    "an",
    "та",
    "або",
    "для",
    "про",
    "як",
    "що",
    "коли",
    "де",
    "який",
    "яка",
    "яке",
    "був",
    "була",
    "було",
    "також",
    "це",
    "ці",
    "той",
    "ця",
    "цієї",
    "його",
    "її",
    "їх",
    "у",
    "в",
    "на",
    "з",
    "до",
    "по",
    "і",
    "й",
    "чи",
    "не",
}

def remove_pdf_artifacts(value: str) -> str:
    if not value:
        return ""
    cleaned = value
    cleaned = re.sub(r"\(cid:\d+\)", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"cid:\d+", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[\u0000-\u001f\u007f-\u009f]", " ", cleaned)
    cleaned = cleaned.replace("�", " ")
    cleaned = cleaned.replace("\ufeff", " ")
    cleaned = re.sub(r"[•●■◆►▪]", " ", cleaned)
    cleaned = re.sub(r"[`´]+", "'", cleaned)
    cleaned = re.sub(r"[“”]", "\"", cleaned)
    cleaned = re.sub(r"[’]", "'", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def normalize_content_fragment(value: str) -> str:
    cleaned = remove_pdf_artifacts(value or "")
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"([,;:]){2,}", r"\1", cleaned)
    cleaned = cleaned.strip(" \"'`")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def is_readable_fragment(value: str, min_words: int = 3) -> bool:
    text = normalize_content_fragment(value)
    if not text:
        return False
    if re.search(r"cid:\d+", text, flags=re.IGNORECASE):
        return False

    tokens = [t for t in text.split() if t]
    if len(tokens) < min_words:
        return False

    non_space = len(re.sub(r"\s+", "", text))
    if non_space <= 0:
        return False

    letters = len(re.findall(r"[A-Za-zА-Яа-яІіЇїЄєҐґ]", text))
    symbols = len(re.findall(r"[^\w\s]", text, flags=re.UNICODE))
    if letters / max(1, non_space) < 0.4:
        return False
    if symbols / max(1, non_space) > 0.38 and letters / max(1, non_space) < 0.58:
        return False

    bad_tokens = 0
    single_letter_tokens = 0
    comma_glued_tokens = 0
    for token in tokens:
        stripped = token.strip(".,;:!?()[]{}\"'`")
        if not stripped:
            bad_tokens += 1
            continue
        if re.fullmatch(r"[A-Za-zА-Яа-яІіЇїЄєҐґ]", stripped):
            single_letter_tokens += 1
        if re.search(r"[A-Za-zА-Яа-яІіЇїЄєҐґ]{1,4},[A-Za-zА-Яа-яІіЇїЄєҐґ]{1,4}", stripped):
            comma_glued_tokens += 1
        letter_count = len(re.findall(r"[A-Za-zА-Яа-яІіЇїЄєҐґ]", stripped))
        punct_count = len(re.findall(r"[^A-Za-zА-Яа-яІіЇїЄєҐґ0-9_\-]", stripped))
        if len(stripped) >= 7 and letter_count / max(1, len(stripped)) < 0.35:
            bad_tokens += 1
        elif punct_count >= 3:
            bad_tokens += 1
        elif "cid:" in stripped.lower():
            bad_tokens += 1
    if bad_tokens / max(1, len(tokens)) > 0.32:
        return False
    if single_letter_tokens / max(1, len(tokens)) > 0.18:
        return False
    if comma_glued_tokens / max(1, len(tokens)) > 0.1:
        return False
    return True


def extract_readable_document_text(text: str) -> str:
    normalized = clean_text(text)
    raw_sentences = [normalize_content_fragment(s) for s in re.split(r"(?<=[.!?])\s+|\n+", normalized) if s.strip()]
    if not raw_sentences:
        return normalized

    readable_sentences = [s for s in raw_sentences if is_readable_fragment(s, min_words=4)]
    if not readable_sentences:
        return normalized

    original_words = len(normalized.split())
    readable_words = sum(len(s.split()) for s in readable_sentences)
    if readable_words >= max(120, int(original_words * 0.35)) or len(readable_sentences) >= 10:
        return " ".join(readable_sentences)
    return normalized


def clean_text(text: str) -> str:
    text = remove_pdf_artifacts(text or "")
    text = re.sub(r"\s+", " ", text.strip())
    return text


def tokenize(text: str) -> List[str]:
    return [t.lower() for t in TOKEN_RE.findall(text or "") if len(t) >= 3]


def normalize_option_text(value: str, max_len: int = 180) -> str:
    cleaned = normalize_content_fragment(value)
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip(" ,;:") + "..."
    return cleaned


def sanitize_statement(value: str, max_words: int = 28) -> str:
    cleaned = normalize_content_fragment(value)
    cleaned = re.sub(r"^[\-\*\•\d\.\)\(]+\s*", "", cleaned)
    cleaned = cleaned.strip(" \"'`")
    words = cleaned.split()
    if len(words) > max_words:
        cleaned = " ".join(words[:max_words]).rstrip(",;:") + "..."
    if cleaned and not is_readable_fragment(cleaned, min_words=2):
        return ""
    return cleaned


def sanitize_question(question: str) -> str:
    cleaned = normalize_content_fragment(question)
    cleaned = re.sub(r"^(question|q)\s*[:\-\)]\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"^(create|generate|write|ask)\s+(a\s+)?(question|quiz\s+question)\s*(about|for)?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = cleaned.strip(" \"'`")
    if cleaned and not is_readable_fragment(cleaned, min_words=3):
        return ""
    if cleaned and not cleaned.endswith("?"):
        cleaned += "?"
    return cleaned


def split_definition_sentence(sentence: str) -> Optional[Tuple[str, str]]:
    patterns = [
        " is defined as ",
        " can be defined as ",
        " refers to ",
        " is ",
        " are ",
        " means ",
        " — це ",
        " це ",
        " означає ",
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
        if len(subject) <= 90:
            return f"What is {subject}?"
    if len(statement.split()) >= 6:
        topic = " ".join(statement.split()[:6]).strip(" ,;:.")
        return f"What key idea is emphasized about {topic}?"
    return f"What is the key point number {fallback_index}?"


def is_question_clear(question: str) -> bool:
    if not question:
        return False
    q = question.strip()
    if len(q) < 12 or len(q) > 180:
        return False
    if any(token in q.lower() for token in ["create a question", "generate a question", "ask about this"]):
        return False
    return q.endswith("?")


def dedupe_items(items: List[str], max_items: int = 8) -> List[str]:
    seen = set()
    unique_items = []
    for item in items:
        cleaned = re.sub(r"^\s*[-*•\d\.\)]\s*", "", normalize_content_fragment(item or "")).strip()
        if not cleaned:
            continue
        if not is_readable_fragment(cleaned, min_words=2):
            continue
        key = re.sub(r"[^a-zA-Z0-9а-яА-ЯіїєґІЇЄҐ]+", "", cleaned.lower())
        if len(key) < 6:
            continue
        if key in seen:
            continue
        seen.add(key)
        unique_items.append(cleaned)
        if len(unique_items) >= max_items:
            break
    return unique_items


def extract_informative_sentences(text: str, max_items: int = 8) -> List[str]:
    raw_sentences = [sanitize_statement(s, max_words=34) for s in re.split(r"[.!?]\s+", clean_text(text))]
    candidates = [s for s in raw_sentences if len(s.split()) >= 6 and is_readable_fragment(s, min_words=6)]

    def score(sentence: str) -> int:
        words = len(sentence.split())
        length_score = 30 - abs(18 - min(words, 30))
        bonus = 0
        if re.search(r"\d", sentence):
            bonus += 3
        if any(k in sentence.lower() for k in ["because", "therefore", "important", "key", "main", "defined", "critical"]):
            bonus += 2
        return length_score + bonus

    ranked = sorted(candidates, key=score, reverse=True)
    return dedupe_items(ranked, max_items=max_items)


def chunk_text_with_overlap(text: str, max_words: int = CHUNK_WORDS, overlap: int = CHUNK_OVERLAP) -> List[Dict[str, Any]]:
    words = text.split()
    if not words:
        return []
    overlap = max(0, min(overlap, max_words - 1))
    step = max_words - overlap
    chunks = []
    chunk_index = 0
    for start in range(0, len(words), step):
        end = min(start + max_words, len(words))
        chunk_words = words[start:end]
        chunk_text = " ".join(chunk_words)
        token_list = [t for t in tokenize(chunk_text) if t not in STOPWORDS]
        token_counter = Counter(token_list)
        keywords = [k for k, _ in token_counter.most_common(14)]
        chunk_index += 1
        chunks.append(
            {
                "chunk_id": f"chunk-{chunk_index}",
                "source_position": f"words {start + 1}-{end}",
                "start_word": start + 1,
                "end_word": end,
                "text": chunk_text,
                "token_set": list(set(token_list)),
                "keywords": keywords,
            }
        )
        if end >= len(words):
            break
    return chunks


def validate_text_size(text: str, max_words: int = MAX_WORDS) -> bool:
    return len((text or "").split()) <= max_words


def document_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def build_cache_key(doc_hash: str, kind: str, params: Dict[str, Any]) -> str:
    packed = json.dumps(params, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"{kind}:{doc_hash}:{packed}"


def get_document_analysis(text: str) -> Dict[str, Any]:
    cleaned = extract_readable_document_text(text)
    if not cleaned:
        raise HTTPException(status_code=400, detail="Text content is required")
    doc_hash = document_hash(cleaned)
    key = f"analysis:{doc_hash}:v3"
    cached = DOCUMENT_CACHE.get(key)
    if cached:
        return cached

    chunks = chunk_text_with_overlap(cleaned, max_words=CHUNK_WORDS, overlap=CHUNK_OVERLAP)
    analysis = {
        "doc_hash": doc_hash,
        "text": cleaned,
        "word_count": len(cleaned.split()),
        "chunk_count": len(chunks),
        "chunks": chunks,
        "created_at": utc_now_iso(),
    }
    DOCUMENT_CACHE.set(key, analysis)
    return analysis


def score_chunk_relevance(chunk: Dict[str, Any], query: str) -> float:
    q_tokens = [t for t in tokenize(query) if t not in STOPWORDS]
    if not q_tokens:
        return 0.0
    q_set = set(q_tokens)
    c_set = set(chunk.get("token_set") or [])
    overlap = len(q_set.intersection(c_set))
    score = overlap / max(1, len(q_set))
    text_low = (chunk.get("text") or "").lower()
    query_low = (query or "").lower()
    if query_low and query_low in text_low:
        score += 0.45
    for keyword in chunk.get("keywords", []):
        if keyword in q_set:
            score += 0.05
    return score


def retrieve_best_chunk(chunks: List[Dict[str, Any]], query: str) -> Optional[Dict[str, Any]]:
    if not chunks:
        return None
    scored = sorted(chunks, key=lambda c: score_chunk_relevance(c, query), reverse=True)
    return scored[0]


def source_excerpt(chunk: Optional[Dict[str, Any]], max_chars: int = 220) -> Optional[str]:
    if not chunk:
        return None
    chunk_text = clean_text(chunk.get("text", ""))
    candidate_sentences = [
        sanitize_statement(sentence, max_words=34)
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", chunk_text)
        if sentence.strip()
    ]
    readable = [s for s in candidate_sentences if s and is_readable_fragment(s, min_words=4)]
    text = readable[0] if readable else sanitize_statement(chunk_text, max_words=42)
    if not text:
        return None
    if len(text) > max_chars:
        return text[:max_chars].rstrip() + "..."
    return text


def extract_generated_text(result: Union[List[Dict[str, str]], Dict[str, str], str]) -> str:
    if isinstance(result, str):
        return result.strip()
    if isinstance(result, dict):
        return (result.get("summary_text") or result.get("generated_text") or "").strip()
    if isinstance(result, list):
        if not result:
            return ""
        item = result[0]
        if isinstance(item, dict):
            return (item.get("summary_text") or item.get("generated_text") or "").strip()
    return ""


def run_generation_model(
    model_pipeline,
    prompt: str,
    max_new_tokens: int,
    min_length: Optional[int] = None,
    temperature: float = 0.7,
    do_sample: bool = True,
) -> Any:
    params: Dict[str, Any] = {
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


def run_generation_model_batch(
    model_pipeline,
    prompts: List[str],
    max_new_tokens: int,
    min_length: Optional[int] = None,
    temperature: float = 0.7,
    do_sample: bool = True,
) -> List[Any]:
    if not prompts:
        return []
    params: Dict[str, Any] = {
        "max_new_tokens": max_new_tokens,
        "do_sample": do_sample,
        "batch_size": min(8, len(prompts)),
    }
    if min_length is not None:
        params["min_length"] = min_length
    if do_sample:
        params["temperature"] = temperature
    tokenizer = getattr(model_pipeline, "tokenizer", None)
    eos_token_id = getattr(tokenizer, "eos_token_id", None) if tokenizer else None
    if eos_token_id is not None:
        params["pad_token_id"] = eos_token_id
    result = model_pipeline(prompts, **params)
    return result if isinstance(result, list) else [result]


def fallback_summary(text: str, max_sentences: int = 5, max_words: int = 220) -> str:
    sentences = [s.strip() for s in re.split(r"[.!?]\s+", clean_text(text)) if s.strip()]
    if not sentences:
        return ""
    candidate = ". ".join(sentences[:max_sentences]).strip()
    if candidate and not candidate.endswith("."):
        candidate += "."
    words = candidate.split()
    if len(words) > max_words:
        return " ".join(words[:max_words]) + "..."
    return candidate


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
    req = urllib_request.Request(
        url,
        data=json.dumps(request_payload).encode("utf-8"),
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
        raise RuntimeError("Cannot connect to Ollama. Start it with: ollama serve") from network_error


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
    if len(context) > 14000:
        prioritized = extract_informative_sentences(context, max_items=30)
        context = ". ".join(prioritized)
    return (
        "You generate high-quality multiple-choice quiz questions from study material.\n"
        "Requirements:\n"
        "- Use the same language as the source text.\n"
        f"- Return exactly {num_questions} questions.\n"
        "- Each question must be clear, specific, and directly answerable from context.\n"
        "- Each question must have exactly 4 options.\n"
        "- correct_option must be an index 0..3.\n"
        "- explanation must be concise (one sentence).\n"
        "- wrong_option_explanations must be an array of 4 concise strings explaining each option.\n"
        "Return strict JSON only in this schema:\n"
        "{\"questions\":[{\"question\":\"...\",\"options\":[\"...\",\"...\",\"...\",\"...\"],\"correct_option\":0,"
        "\"explanation\":\"...\",\"wrong_option_explanations\":[\"...\",\"...\",\"...\",\"...\"]}]}\n\n"
        f"Context:\n{context}"
    )


def build_wrong_option_explanations(options: List[str], correct_idx: int, correct_answer: str, question: str) -> List[str]:
    explanations = []
    for idx, option in enumerate(options):
        if idx == correct_idx:
            explanations.append("This is the correct option supported by the source material.")
        else:
            explanations.append(
                sanitize_statement(
                    f"This option is incorrect because the source supports '{correct_answer}' for the question '{question}'.",
                    max_words=28,
                )
            )
    return explanations


def normalize_quiz_item(item: Dict[str, Any], index: int) -> Optional[Dict[str, Union[str, int, List[str]]]]:
    question = sanitize_question(str((item or {}).get("question", "")))
    explanation = sanitize_statement(str((item or {}).get("explanation", "")), max_words=28)
    raw_options = (item or {}).get("options", [])
    if not isinstance(raw_options, list):
        raw_options = []
    options = []
    for opt in raw_options:
        cleaned = sanitize_statement(str(opt), max_words=20)
        if cleaned and is_readable_fragment(cleaned, min_words=1):
            options.append(cleaned)

    unique_options = []
    seen_opts = set()
    for opt in options:
        key = opt.lower()
        if key in seen_opts:
            continue
        seen_opts.add(key)
        unique_options.append(opt)
    options = unique_options[:4]

    try:
        correct_option = int((item or {}).get("correct_option", 0))
    except Exception:
        correct_option = 0

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
    options = options[:4]
    if correct_option < 0 or correct_option >= len(options):
        correct_option = 0
    if not is_question_clear(question) or not is_readable_fragment(question, min_words=4):
        source = explanation or (options[0] if options else f"topic {index + 1}")
        question = build_clear_question_from_content(source, fallback_index=index + 1)
    if not question or not is_readable_fragment(question, min_words=4):
        return None
    wrongs_raw = (item or {}).get("wrong_option_explanations")
    wrongs: List[str] = []
    if isinstance(wrongs_raw, list):
        for raw in wrongs_raw[:4]:
            wrongs.append(sanitize_statement(str(raw), max_words=26))
    while len(wrongs) < len(options):
        wrongs.append("")
    if len(wrongs) != len(options) or not any(wrongs):
        wrongs = build_wrong_option_explanations(options, correct_option, options[correct_option], question)
    if not question or len(options) < 4:
        return None
    safe_explanation = explanation or options[correct_option]
    if not is_readable_fragment(safe_explanation, min_words=2):
        safe_explanation = options[correct_option]
    return {
        "question": question,
        "options": options,
        "correct_option": correct_option,
        "explanation": safe_explanation,
        "wrong_option_explanations": wrongs,
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


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    text = ""
    try:
        pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
        for page_num in range(pdf_document.page_count):
            page = pdf_document.get_page(page_num)
            page_text = page.get_text()
            if page_text:
                text += page_text + "\n"
        pdf_document.close()
        if text.strip():
            return text
    except Exception as e:
        print(f"PyMuPDF extraction failed: {e}")

    try:
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


def generate_summary(text: str) -> str:
    analysis = get_document_analysis(text)
    cache_key = build_cache_key(analysis["doc_hash"], "summary", {"v": 2})
    cached = RESULT_CACHE.get(cache_key)
    if cached:
        return str(cached)

    source_text = analysis["text"]
    word_count = analysis["word_count"]
    print(f"[INFO] Summarizing {word_count} words")

    if not summarizer:
        summary = fallback_summary(source_text)
        RESULT_CACHE.set(cache_key, summary)
        return summary

    max_chunk_chars = 2300
    if len(source_text) <= max_chunk_chars:
        try:
            result = run_generation_model(
                summarizer,
                source_text,
                max_new_tokens=180,
                min_length=45,
                do_sample=False,
            )
            summary = extract_generated_text(result) or fallback_summary(source_text)
            RESULT_CACHE.set(cache_key, summary)
            return summary
        except Exception as e:
            print(f"[WARN] Single-pass summary failed: {e}")
            summary = fallback_summary(source_text)
            RESULT_CACHE.set(cache_key, summary)
            return summary

    chunk_inputs = []
    for chunk in analysis["chunks"]:
        chunk_text = chunk.get("text", "")
        if chunk_text:
            chunk_inputs.append(chunk_text[:max_chunk_chars])

    chunk_summaries: List[str] = []
    try:
        batch_results = run_generation_model_batch(
            summarizer,
            chunk_inputs,
            max_new_tokens=110,
            min_length=28,
            do_sample=False,
        )
        for item in batch_results:
            text_piece = extract_generated_text(item)
            if text_piece:
                chunk_summaries.append(text_piece)
    except Exception as e:
        print(f"[WARN] Batch chunk summarization failed, using loop fallback: {e}")
        for chunk_input in chunk_inputs:
            try:
                result = run_generation_model(
                    summarizer,
                    chunk_input,
                    max_new_tokens=110,
                    min_length=28,
                    do_sample=False,
                )
                generated = extract_generated_text(result)
                if generated:
                    chunk_summaries.append(generated)
            except Exception:
                pass

    if not chunk_summaries:
        summary = fallback_summary(source_text)
        RESULT_CACHE.set(cache_key, summary)
        return summary

    combined = " ".join(chunk_summaries)
    if len(combined.split()) > 260:
        try:
            final_prompt = f"Create a compact study summary from these points: {combined[:3000]}"
            final_result = run_generation_model(
                summarizer,
                final_prompt,
                max_new_tokens=200,
                min_length=60,
                do_sample=False,
            )
            combined = extract_generated_text(final_result) or combined
        except Exception as e:
            print(f"[WARN] Final summary compression failed: {e}")
            combined = fallback_summary(combined, max_sentences=6, max_words=220)

    RESULT_CACHE.set(cache_key, combined)
    return combined


def extract_claim_candidates(text: str, max_claims: int = 20) -> List[str]:
    candidates = []
    informative = extract_informative_sentences(text, max_items=max(max_claims * 2, 30))
    candidates.extend(informative)

    for sentence in informative:
        definition = split_definition_sentence(sentence)
        if definition:
            subject, predicate = definition
            candidates.append(f"{subject} is {predicate}")

    if len(candidates) < max_claims:
        fallback = [sanitize_statement(s, max_words=30) for s in re.split(r"[.!?]\s+", clean_text(text))]
        fallback = [s for s in fallback if len(s.split()) >= 6 and is_readable_fragment(s, min_words=6)]
        candidates.extend(fallback)
    readable = [c for c in candidates if is_readable_fragment(c, min_words=5)]
    return dedupe_items(readable, max_items=max_claims)


def create_cloze_from_statement(statement: str) -> Tuple[str, str]:
    normalized = sanitize_statement(statement, max_words=30)
    if not normalized:
        normalized = normalize_option_text(statement, max_len=120)
    if not normalized:
        return "Fill in the blank: key concept ____", "concept"
    tokens = TOKEN_RE.findall(normalized)
    candidates = [t for t in tokens if len(t) >= 4 and t.lower() not in STOPWORDS]
    if not candidates:
        candidates = [t for t in tokens if len(t) >= 3]
    if not candidates:
        return f"Fill in the blank: {normalized}", normalize_option_text(normalized)

    target = max(candidates, key=len)
    pattern = re.compile(rf"\b{re.escape(target)}\b", re.IGNORECASE)
    question_body = pattern.sub("____", normalized, count=1)
    if question_body == normalized:
        question_body = normalized.replace(target, "____", 1)
    if question_body == normalized:
        question_body = f"{normalized} ____"
    question = f"Fill in the blank: {question_body}"
    return question, target


def dedupe_flashcards(cards: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    deduped = []
    seen = set()
    for card in cards:
        question = normalize_option_text(card.get("question", ""))
        answer = normalize_option_text(card.get("answer", ""))
        if not question or not answer:
            continue
        key = f"{question.lower()}|{answer.lower()}|{card.get('mode','qa')}"
        if key in seen:
            continue
        seen.add(key)
        cleaned = {
            "question": question,
            "answer": answer,
            "mode": card.get("mode", "qa"),
            "cloze_answer": card.get("cloze_answer"),
            "source_excerpt": card.get("source_excerpt"),
            "source_chunk_id": card.get("source_chunk_id"),
            "source_position": card.get("source_position"),
        }
        deduped.append(cleaned)
        if len(deduped) >= limit:
            break
    return deduped


def build_grounded_flashcard(
    question: str,
    answer: str,
    mode: str,
    chunk: Optional[Dict[str, Any]],
    cloze_answer: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "question": question,
        "answer": answer,
        "mode": mode,
        "cloze_answer": cloze_answer,
        "source_excerpt": source_excerpt(chunk),
        "source_chunk_id": (chunk or {}).get("chunk_id"),
        "source_position": (chunk or {}).get("source_position"),
    }


def generate_flashcards_fallback(text: str, num_cards: int = 5, mode: str = "qa", chunks: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    sentences = extract_informative_sentences(text, max_items=max(num_cards * 3, 15))
    cards = []
    for i, sentence in enumerate(sentences[:num_cards * 2]):
        if not is_readable_fragment(sentence, min_words=5):
            continue
        chunk = retrieve_best_chunk(chunks or [], sentence)
        if mode == "cloze":
            question, cloze_answer = create_cloze_from_statement(sentence)
            answer = sanitize_statement(sentence, max_words=28)
            if not question or not answer or not cloze_answer:
                continue
            if not is_readable_fragment(question, min_words=4):
                continue
            cards.append(build_grounded_flashcard(question, answer, "cloze", chunk, cloze_answer=cloze_answer))
        else:
            answer = sanitize_statement(sentence, max_words=24)
            if not answer or not is_readable_fragment(answer, min_words=4):
                continue
            question = build_clear_question_from_content(answer, fallback_index=i + 1)
            if not question or not is_readable_fragment(question, min_words=4):
                continue
            cards.append(build_grounded_flashcard(question, answer, "qa", chunk))
    return dedupe_flashcards(cards, num_cards)


def generate_flashcards_qa_batch(claims: List[str], chunks: List[Dict[str, Any]], num_cards: int) -> List[Dict[str, Any]]:
    cards = []
    usable_claims = [claim for claim in claims if is_readable_fragment(claim, min_words=5)]
    if flashcard_generator and usable_claims:
        prompts = [
            "Write one concise study question answerable from this statement. "
            "Return only the question.\n"
            f"Statement: {claim}\nQuestion:"
            for claim in usable_claims
        ]
        try:
            results = run_generation_model_batch(
                flashcard_generator,
                prompts,
                max_new_tokens=52,
                temperature=0.35,
                do_sample=True,
            )
            for idx, claim in enumerate(usable_claims):
                generated = ""
                if idx < len(results):
                    generated = extract_generated_text(results[idx])
                question = sanitize_question(generated)
                if not question or not is_question_clear(question):
                    question = build_clear_question_from_content(claim, fallback_index=idx + 1)
                if not question or not is_readable_fragment(question, min_words=4):
                    continue
                answer = sanitize_statement(claim, max_words=28)
                if not answer or not is_readable_fragment(answer, min_words=4):
                    continue
                chunk = retrieve_best_chunk(chunks, f"{question} {answer}")
                cards.append(build_grounded_flashcard(question, answer, "qa", chunk))
                if len(cards) >= num_cards:
                    break
        except Exception as e:
            print(f"[WARN] Batch QA generation failed: {e}")

    if len(cards) < num_cards:
        fallback_cards = generate_flashcards_fallback(
            ". ".join(usable_claims) if usable_claims else "",
            num_cards=num_cards,
            mode="qa",
            chunks=chunks,
        )
        cards.extend(fallback_cards)
    if len(cards) < num_cards and usable_claims:
        for idx, claim in enumerate(usable_claims):
            answer = sanitize_statement(claim, max_words=24)
            if not answer or not is_readable_fragment(answer, min_words=4):
                continue
            base_question = build_clear_question_from_content(answer, fallback_index=idx + 1)
            if base_question.endswith("?"):
                question = f"{base_question[:-1]} ({idx + 1})?"
            else:
                question = f"{base_question} ({idx + 1})?"
            if not is_readable_fragment(question, min_words=4):
                continue
            chunk = retrieve_best_chunk(chunks, f"{question} {answer}")
            cards.append(build_grounded_flashcard(question, answer, "qa", chunk))
            if len(cards) >= num_cards:
                break
    return dedupe_flashcards(cards, num_cards)


def generate_flashcards(text: str, num_cards: int = 5, mode: str = "qa") -> List[Dict[str, Any]]:
    mode = (mode or "qa").lower().strip()
    if mode not in {"qa", "cloze"}:
        mode = "qa"
    analysis = get_document_analysis(text)
    cache_key = build_cache_key(
        analysis["doc_hash"],
        "flashcards",
        {
            "v": 4,
            "num_cards": num_cards,
            "mode": mode,
        },
    )
    cached = RESULT_CACHE.get(cache_key)
    if cached:
        return cached

    claims = extract_claim_candidates(analysis["text"], max_claims=max(num_cards * 3, 18))
    if not claims:
        claims = extract_informative_sentences(analysis["text"], max_items=max(num_cards * 3, 18))
    chunks = analysis["chunks"]
    cards: List[Dict[str, Any]] = []

    if mode == "cloze":
        for idx, claim in enumerate(claims):
            if not is_readable_fragment(claim, min_words=5):
                continue
            question, cloze_answer = create_cloze_from_statement(claim)
            answer = sanitize_statement(claim, max_words=28)
            if not question or not answer or not cloze_answer:
                continue
            if not is_readable_fragment(question, min_words=4):
                continue
            chunk = retrieve_best_chunk(chunks, f"{claim} {cloze_answer}")
            cards.append(build_grounded_flashcard(question, answer, "cloze", chunk, cloze_answer=cloze_answer))
            if len(cards) >= num_cards:
                break
        if len(cards) < num_cards:
            cards.extend(generate_flashcards_fallback(analysis["text"], num_cards=num_cards, mode="cloze", chunks=chunks))
        cards = dedupe_flashcards(cards, num_cards)
    else:
        cards = generate_flashcards_qa_batch(claims, chunks, num_cards=num_cards)

    RESULT_CACHE.set(cache_key, cards[:num_cards])
    return cards[:num_cards]


def generate_key_points(text: str, max_points: int = 8) -> List[str]:
    analysis = get_document_analysis(text)
    cache_key = build_cache_key(
        analysis["doc_hash"],
        "key_points",
        {"v": 2, "max_points": max_points},
    )
    cached = RESULT_CACHE.get(cache_key)
    if cached:
        return cached

    source_text = analysis["text"]
    prompt = (
        f"Extract {max_points} key learning points from this text. "
        "Return one point per line, concise and factual, without numbering:\n\n"
        f"{source_text[:5000]}"
    )
    points: List[str] = []
    if flashcard_generator:
        try:
            result = run_generation_model(
                flashcard_generator,
                prompt,
                max_new_tokens=240,
                temperature=0.2,
                do_sample=False,
            )
            generated = extract_generated_text(result)
            raw_points = [line.strip() for line in re.split(r"[\n\r]+", generated) if line.strip()]
            points = dedupe_items(raw_points, max_points)
        except Exception as e:
            print(f"[WARN] Key points generation failed, using fallback: {e}")
    if not points:
        points = extract_informative_sentences(source_text, max_items=max_points)
    RESULT_CACHE.set(cache_key, points[:max_points])
    return points[:max_points]


def generate_quiz_questions(text: str, num_questions: int = 5) -> List[Dict[str, Union[str, int, List[str]]]]:
    analysis = get_document_analysis(text)
    cache_key = build_cache_key(
        analysis["doc_hash"],
        "quiz_fast",
        {"v": 4, "num_questions": num_questions},
    )
    cached = RESULT_CACHE.get(cache_key)
    if cached:
        return cached

    source_text = analysis["text"]
    chunks = analysis["chunks"]
    base_cards = generate_flashcards(source_text, max(8, num_questions + 3), mode="qa")
    base_cards = [
        card for card in base_cards
        if is_readable_fragment(card.get("question", ""), min_words=4)
        and is_readable_fragment(card.get("answer", ""), min_words=3)
    ]
    if not base_cards:
        return []

    informative_pool = extract_informative_sentences(source_text, max_items=max(num_questions * 4, 18))
    answers_pool = dedupe_items(
        [normalize_option_text(card.get("answer", "")) for card in base_cards] + informative_pool,
        max_items=40,
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
        if not is_question_clear(question_text) or not is_readable_fragment(question_text, min_words=4):
            question_text = build_clear_question_from_content(correct_answer, fallback_index=len(questions) + 1)
        if not question_text or not is_readable_fragment(question_text, min_words=4):
            continue
        question_key = question_text.lower()
        if question_key in seen_questions:
            continue
        seen_questions.add(question_key)

        distractors = [
            ans for ans in answers_pool
            if ans.lower() != correct_answer.lower() and is_readable_fragment(ans, min_words=2)
        ]
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
        options = [opt for opt in options if is_readable_fragment(opt, min_words=2)]
        options = options[:4]
        if len(options) < 4:
            continue
        options = options[:4]
        random.shuffle(options)
        correct_index = options.index(correct_answer)
        wrongs = build_wrong_option_explanations(options, correct_index, correct_answer, question_text)
        chunk = retrieve_best_chunk(chunks, f"{question_text} {correct_answer}")
        questions.append(
            {
                "question": question_text,
                "options": options,
                "correct_option": correct_index,
                "explanation": correct_answer,
                "wrong_option_explanations": wrongs,
                "source_excerpt": source_excerpt(chunk),
                "source_chunk_id": (chunk or {}).get("chunk_id"),
                "source_position": (chunk or {}).get("source_position"),
            }
        )

    if len(questions) < num_questions:
        for idx, sentence in enumerate(informative_pool):
            if len(questions) >= num_questions:
                break

            answer = sanitize_statement(sentence, max_words=22)
            if not answer or not is_readable_fragment(answer, min_words=4):
                continue
            question_text = build_clear_question_from_content(answer, fallback_index=len(questions) + 1)
            if question_text.lower() in seen_questions:
                if question_text.endswith("?"):
                    question_text = f"{question_text[:-1]} ({idx + 1})?"
                else:
                    question_text = f"{question_text} ({idx + 1})?"
            if question_text.lower() in seen_questions:
                continue
            if not is_readable_fragment(question_text, min_words=4):
                continue
            seen_questions.add(question_text.lower())

            options = [answer]
            distractors = [ans for ans in answers_pool if ans.lower() != answer.lower()]
            random.shuffle(distractors)
            for distractor in distractors:
                if len(options) >= 4:
                    break
                if distractor.lower() not in [opt.lower() for opt in options]:
                    options.append(distractor)
            while len(options) < 4:
                fallback_option = "A claim not supported by the source material."
                if fallback_option.lower() not in [opt.lower() for opt in options]:
                    options.append(fallback_option)
                else:
                    options.append(f"{fallback_option} ({len(options) + 1})")

            options = options[:4]
            options = [opt for opt in options if is_readable_fragment(opt, min_words=2)]
            if len(options) < 4:
                continue
            random.shuffle(options)
            correct_index = options.index(answer)
            wrongs = build_wrong_option_explanations(options, correct_index, answer, question_text)
            chunk = retrieve_best_chunk(chunks, f"{question_text} {answer}")
            questions.append(
                {
                    "question": question_text,
                    "options": options,
                    "correct_option": correct_index,
                    "explanation": answer,
                    "wrong_option_explanations": wrongs,
                    "source_excerpt": source_excerpt(chunk),
                    "source_chunk_id": (chunk or {}).get("chunk_id"),
                    "source_position": (chunk or {}).get("source_position"),
                }
            )

    RESULT_CACHE.set(cache_key, questions[:num_questions])
    return questions[:num_questions]


def enrich_quiz_questions_with_grounding(questions: List[Dict[str, Any]], chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    enriched = []
    for item in questions:
        question = item.get("question", "")
        explanation = item.get("explanation", "")
        chunk = retrieve_best_chunk(chunks, f"{question} {explanation}")
        options = item.get("options", [])
        correct_idx = int(item.get("correct_option", 0)) if options else 0
        if correct_idx < 0 or correct_idx >= len(options):
            correct_idx = 0
        wrongs = item.get("wrong_option_explanations") or []
        if not isinstance(wrongs, list) or len(wrongs) != len(options):
            correct_answer = options[correct_idx] if options else explanation
            wrongs = build_wrong_option_explanations(options, correct_idx, correct_answer, question)
        enriched.append(
            {
                **item,
                "wrong_option_explanations": wrongs,
                "source_excerpt": item.get("source_excerpt") or source_excerpt(chunk),
                "source_chunk_id": item.get("source_chunk_id") or (chunk or {}).get("chunk_id"),
                "source_position": item.get("source_position") or (chunk or {}).get("source_position"),
            }
        )
    return enriched


def topic_label_from_question(question: str) -> str:
    cleaned = re.sub(r"[^A-Za-zА-Яа-яІіЇїЄєҐґ0-9\s]", " ", (question or "").lower())
    tokens = [t for t in cleaned.split() if len(t) >= 4 and t not in STOPWORDS]
    if not tokens:
        return "General"
    return " ".join(tokens[:2]).title()


def compute_weak_topics(attempts: List[QuizAttemptItem]) -> WeakTopicsResponse:
    total = len(attempts)
    if total == 0:
        return WeakTopicsResponse(weak_topics=[], overall_accuracy=0.0, total_attempts=0)

    topic_stats = defaultdict(lambda: {"attempts": 0, "mistakes": 0})
    correct_total = 0
    for attempt in attempts:
        topic = topic_label_from_question(attempt.question)
        topic_stats[topic]["attempts"] += 1
        is_correct = attempt.selected_option is not None and attempt.selected_option == attempt.correct_option
        if is_correct:
            correct_total += 1
        else:
            topic_stats[topic]["mistakes"] += 1

    weak_topics: List[WeakTopic] = []
    for topic, stats in topic_stats.items():
        attempts_count = stats["attempts"]
        mistakes = stats["mistakes"]
        accuracy = round((attempts_count - mistakes) / max(1, attempts_count), 3)
        if mistakes == 0 and attempts_count < 2:
            continue
        recommendation = (
            "Review source excerpts for this topic and schedule 2 short recall sessions."
            if mistakes >= 2
            else "Do one focused review pass and retry similar quiz items."
        )
        weak_topics.append(
            WeakTopic(
                topic=topic,
                mistakes=mistakes,
                attempts=attempts_count,
                accuracy=accuracy,
                recommendation=recommendation,
            )
        )

    weak_topics = sorted(weak_topics, key=lambda x: (x.mistakes, -x.accuracy), reverse=True)
    overall_accuracy = round(correct_total / max(1, total), 3)
    return WeakTopicsResponse(
        weak_topics=weak_topics[:8],
        overall_accuracy=overall_accuracy,
        total_attempts=total,
    )


def compute_adaptive_review_queue(attempts: List[QuizAttemptItem], flashcards: Optional[List[Flashcard]] = None) -> AdaptiveReviewResponse:
    queue: List[AdaptiveReviewItem] = []
    for idx, attempt in enumerate(attempts):
        selected = attempt.selected_option
        is_correct = selected is not None and selected == attempt.correct_option
        confidence = attempt.confidence if attempt.confidence is not None else 0.55
        confidence = max(0.0, min(1.0, confidence))

        if not is_correct:
            next_minutes = 15
            reason = "Incorrect answer: immediate reinforcement needed."
            base_priority = 95
        elif confidence < 0.6:
            next_minutes = 180
            reason = "Correct but low confidence: short-term reinforcement recommended."
            base_priority = 70
        elif confidence < 0.8:
            next_minutes = 720
            reason = "Correct with moderate confidence: medium interval review."
            base_priority = 45
        else:
            next_minutes = 1440
            reason = "Correct with high confidence: long interval review."
            base_priority = 25

        question_prompt = sanitize_statement(attempt.question, max_words=20)
        item_id = f"quiz-{idx + 1}"
        queue.append(
            AdaptiveReviewItem(
                item_id=item_id,
                prompt=question_prompt,
                priority=base_priority,
                next_review_minutes=next_minutes,
                reason=reason,
            )
        )

    if flashcards:
        for idx, card in enumerate(flashcards[:20]):
            queue.append(
                AdaptiveReviewItem(
                    item_id=f"card-{idx + 1}",
                    prompt=sanitize_statement(card.question, max_words=20),
                    priority=20,
                    next_review_minutes=1440,
                    reason="Baseline daily review for retention stabilization.",
                )
            )

    deduped = []
    seen_prompts = set()
    for item in sorted(queue, key=lambda x: x.priority, reverse=True):
        key = item.prompt.lower()
        if key in seen_prompts:
            continue
        seen_prompts.add(key)
        deduped.append(item)
        if len(deduped) >= 30:
            break
    return AdaptiveReviewResponse(queue=deduped, generated_at=utc_now_iso())


# Job orchestration
def create_job(payload: Dict[str, Any]) -> Dict[str, Any]:
    job_id = str(uuid.uuid4())
    now = utc_now_iso()
    job = {
        "job_id": job_id,
        "status": "queued",
        "stage": "queued",
        "progress": 0,
        "message": "Job queued",
        "created_at": now,
        "updated_at": now,
        "error": None,
        "result": None,
        "payload": payload,
    }
    with JOB_LOCK:
        JOB_STORE[job_id] = job
        if len(JOB_STORE) > JOB_MAX_ITEMS:
            oldest_key = sorted(JOB_STORE.keys(), key=lambda k: JOB_STORE[k].get("created_at", ""))[0]
            JOB_STORE.pop(oldest_key, None)
    return copy.deepcopy(job)


def update_job(job_id: str, **changes) -> Optional[Dict[str, Any]]:
    with JOB_LOCK:
        job = JOB_STORE.get(job_id)
        if not job:
            return None
        for k, v in changes.items():
            job[k] = v
        job["updated_at"] = utc_now_iso()
        return copy.deepcopy(job)


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with JOB_LOCK:
        job = JOB_STORE.get(job_id)
        return copy.deepcopy(job) if job else None


async def process_study_job(job_id: str, request_data: StudyJobRequest) -> None:
    try:
        update_job(job_id, status="running", stage="analyzing", progress=8, message="Analyzing document structure")
        analysis = await asyncio.to_thread(get_document_analysis, request_data.text)

        summary = None
        key_points = None
        flashcards = None
        quiz_payload = None

        if request_data.include_summary:
            update_job(job_id, stage="summarizing", progress=24, message="Generating summary")
            summary = await asyncio.to_thread(generate_summary, request_data.text)

        if request_data.include_key_points:
            update_job(job_id, stage="key_points", progress=42, message="Extracting key points")
            key_points = await asyncio.to_thread(generate_key_points, request_data.text, min(10, MAX_KEY_POINTS))

        update_job(job_id, stage="flashcards", progress=63, message="Generating grounded flashcards")
        flashcards = await asyncio.to_thread(
            generate_flashcards,
            request_data.text,
            max(1, min(request_data.num_cards, MAX_FLASHCARDS)),
            request_data.flashcard_mode,
        )

        update_job(job_id, stage="quiz", progress=82, message="Generating quiz")
        quiz_questions: List[Dict[str, Any]] = []
        provider = "local"
        used_model = None
        fallback_used = False
        generation_mode = request_data.quiz_mode

        if request_data.quiz_mode == "high_quality":
            try:
                ollama_result = await asyncio.to_thread(
                    generate_quiz_questions_ollama,
                    request_data.text,
                    max(3, min(request_data.num_questions, MAX_QUIZ_QUESTIONS)),
                    request_data.ollama_model,
                )
                quiz_questions = ollama_result.get("questions", [])
                used_model = ollama_result.get("model")
                provider = "ollama"
                if len(quiz_questions) < request_data.num_questions:
                    fallback_used = True
                    fallback_candidates = await asyncio.to_thread(
                        generate_quiz_questions,
                        request_data.text,
                        request_data.num_questions,
                    )
                    existing = {q.get("question", "").strip().lower() for q in quiz_questions}
                    for candidate in fallback_candidates:
                        key = candidate.get("question", "").strip().lower()
                        if not key or key in existing:
                            continue
                        quiz_questions.append(candidate)
                        existing.add(key)
                        if len(quiz_questions) >= request_data.num_questions:
                            break
            except Exception as ollama_error:
                print(f"[WARN] Job high_quality quiz failed, fallback to fast: {ollama_error}")
                quiz_questions = await asyncio.to_thread(
                    generate_quiz_questions,
                    request_data.text,
                    request_data.num_questions,
                )
                provider = "local-fallback"
                used_model = request_data.ollama_model or OLLAMA_QUIZ_MODEL
                fallback_used = True
                generation_mode = "fast"
        else:
            quiz_questions = await asyncio.to_thread(
                generate_quiz_questions,
                request_data.text,
                request_data.num_questions,
            )

        quiz_questions = enrich_quiz_questions_with_grounding(quiz_questions, analysis["chunks"])
        quiz_payload = {
            "questions": quiz_questions,
            "total_count": len(quiz_questions),
            "generation_mode": generation_mode,
            "provider": provider,
            "model": used_model,
            "fallback_used": fallback_used,
            "doc_hash": analysis["doc_hash"],
        }

        result = {
            "summary": summary,
            "key_points": key_points,
            "flashcards": flashcards,
            "quiz": quiz_payload,
            "document": {
                "doc_hash": analysis["doc_hash"],
                "word_count": analysis["word_count"],
                "chunk_count": analysis["chunk_count"],
            },
        }
        update_job(job_id, status="completed", stage="completed", progress=100, message="Job completed", result=result)
    except Exception as e:
        update_job(job_id, status="failed", stage="failed", progress=100, message="Job failed", error=str(e))


# API Endpoints
@app.get("/")
async def root():
    return {"message": "PDF Flashcards API is running", "version": "2.0.0"}


@app.get("/system/cache")
async def cache_stats():
    return {
        "document_cache": DOCUMENT_CACHE.stats(),
        "result_cache": RESULT_CACHE.stats(),
        "job_store_size": len(JOB_STORE),
    }


@app.post("/upload", response_model=UploadResponse)
async def upload_file(
    file: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
):
    if not file and not text:
        raise HTTPException(status_code=400, detail="Either file or text must be provided")

    extracted_text = ""
    if file:
        if file.content_type != "application/pdf":
            raise HTTPException(status_code=400, detail="Only PDF files are allowed")
        try:
            pdf_bytes = await file.read()
            extracted_text = extract_text_from_pdf(pdf_bytes)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error processing PDF: {str(e)}")
    else:
        extracted_text = text or ""

    if not extracted_text.strip():
        raise HTTPException(status_code=400, detail="No text content found")
    if not validate_text_size(extracted_text, max_words=MAX_WORDS):
        word_count = len(extracted_text.split())
        raise HTTPException(
            status_code=413,
            detail=f"Text is too large. Maximum {MAX_WORDS} words allowed, but received {word_count} words.",
        )

    analysis = get_document_analysis(extracted_text)
    print(
        f"[OK] Processed document: {analysis['word_count']} words, "
        f"{len(extracted_text)} chars, {analysis['chunk_count']} chunks"
    )
    return UploadResponse(
        text=analysis["text"],
        word_count=analysis["word_count"],
        char_count=len(analysis["text"]),
        doc_hash=analysis["doc_hash"],
        chunk_count=analysis["chunk_count"],
    )


@app.post("/summarize", response_model=SummaryResponse)
async def create_summary(input_data: TextInput):
    if not input_data.text or not input_data.text.strip():
        raise HTTPException(status_code=400, detail="Text content is required")
    if not validate_text_size(input_data.text, max_words=MAX_WORDS):
        raise HTTPException(status_code=413, detail=f"Text exceeds max limit of {MAX_WORDS} words")
    try:
        analysis = get_document_analysis(input_data.text)
        summary = generate_summary(input_data.text)
        return SummaryResponse(
            summary=summary,
            original_length=analysis["word_count"],
            summary_length=len(summary.split()),
            doc_hash=analysis["doc_hash"],
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Summary generation failed: {str(e)}")


@app.post("/flashcards", response_model=FlashcardsResponse)
async def create_flashcards(input_data: TextInput, num_cards: int = 6, mode: str = "qa"):
    if not input_data.text or not input_data.text.strip():
        raise HTTPException(status_code=400, detail="Text content is required")
    if not validate_text_size(input_data.text, max_words=MAX_WORDS):
        raise HTTPException(status_code=413, detail=f"Text exceeds max limit of {MAX_WORDS} words")
    if num_cards < 1 or num_cards > MAX_FLASHCARDS:
        raise HTTPException(status_code=400, detail=f"Number of cards must be between 1 and {MAX_FLASHCARDS}")
    mode = (mode or "qa").lower()
    if mode not in {"qa", "cloze"}:
        raise HTTPException(status_code=400, detail="mode must be 'qa' or 'cloze'")
    try:
        flashcards_data = generate_flashcards(input_data.text, num_cards, mode=mode)
        flashcards = [Flashcard(**card) for card in flashcards_data]
        return FlashcardsResponse(flashcards=flashcards, total_count=len(flashcards), mode=mode)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Flashcard generation failed: {str(e)}")


@app.post("/key-points", response_model=KeyPointsResponse)
async def create_key_points(input_data: TextInput, max_points: int = 8):
    if not input_data.text or not input_data.text.strip():
        raise HTTPException(status_code=400, detail="Text content is required")
    if not validate_text_size(input_data.text, max_words=MAX_WORDS):
        raise HTTPException(status_code=413, detail=f"Text exceeds max limit of {MAX_WORDS} words")
    if max_points < 3 or max_points > MAX_KEY_POINTS:
        raise HTTPException(status_code=400, detail=f"max_points must be between 3 and {MAX_KEY_POINTS}")
    try:
        analysis = get_document_analysis(input_data.text)
        key_points = generate_key_points(input_data.text, max_points=max_points)
        return KeyPointsResponse(
            key_points=key_points,
            total_count=len(key_points),
            doc_hash=analysis["doc_hash"],
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Key points generation failed: {str(e)}")


@app.get("/ollama/models")
async def get_ollama_models():
    models = list_ollama_models()
    return {
        "available": len(models) > 0,
        "models": models,
        "default_model": OLLAMA_QUIZ_MODEL,
    }


@app.post("/quiz", response_model=QuizResponse)
async def create_quiz(
    input_data: TextInput,
    num_questions: int = 6,
    mode: str = "fast",
    ollama_model: Optional[str] = None,
):
    if not input_data.text or not input_data.text.strip():
        raise HTTPException(status_code=400, detail="Text content is required")
    if not validate_text_size(input_data.text, max_words=MAX_WORDS):
        raise HTTPException(status_code=413, detail=f"Text exceeds max limit of {MAX_WORDS} words")
    if num_questions < 3 or num_questions > MAX_QUIZ_QUESTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Number of questions must be between 3 and {MAX_QUIZ_QUESTIONS}",
        )

    mode = (mode or "fast").lower()
    if mode not in {"fast", "high_quality"}:
        raise HTTPException(status_code=400, detail="mode must be 'fast' or 'high_quality'")

    try:
        analysis = get_document_analysis(input_data.text)
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
                    fallback_used = True
                    fallback_candidates = generate_quiz_questions(input_data.text, num_questions=num_questions + 2)
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
                used_model = ollama_model or OLLAMA_QUIZ_MODEL
                fallback_used = True
                generation_mode = "fast"
        else:
            questions_data = generate_quiz_questions(input_data.text, num_questions=num_questions)

        questions_data = enrich_quiz_questions_with_grounding(questions_data, analysis["chunks"])
        questions = [QuizQuestion(**question) for question in questions_data]
        return QuizResponse(
            questions=questions,
            total_count=len(questions),
            generation_mode=generation_mode,
            provider=provider,
            model=used_model,
            fallback_used=fallback_used,
            doc_hash=analysis["doc_hash"],
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Quiz generation failed: {str(e)}")


@app.post("/quiz/insights", response_model=WeakTopicsResponse)
async def create_quiz_insights(payload: WeakTopicsRequest):
    if not payload.attempts:
        raise HTTPException(status_code=400, detail="At least one attempt is required")
    try:
        return compute_weak_topics(payload.attempts)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Weak topics analysis failed: {str(e)}")


@app.post("/review/adaptive", response_model=AdaptiveReviewResponse)
async def create_adaptive_review(payload: AdaptiveReviewRequest):
    if not payload.attempts and not payload.flashcards:
        raise HTTPException(status_code=400, detail="Provide attempts or flashcards")
    try:
        return compute_adaptive_review_queue(payload.attempts or [], payload.flashcards or [])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Adaptive review generation failed: {str(e)}")


@app.post("/jobs/study", response_model=StudyJobCreateResponse)
async def create_study_job(payload: StudyJobRequest):
    if not payload.text or not payload.text.strip():
        raise HTTPException(status_code=400, detail="Text content is required")
    if not validate_text_size(payload.text, max_words=MAX_WORDS):
        word_count = len(payload.text.split())
        raise HTTPException(
            status_code=413,
            detail=f"Text is too large. Maximum {MAX_WORDS} words allowed, but received {word_count} words.",
        )
    if payload.flashcard_mode not in {"qa", "cloze"}:
        raise HTTPException(status_code=400, detail="flashcard_mode must be 'qa' or 'cloze'")
    if payload.quiz_mode not in {"fast", "high_quality"}:
        raise HTTPException(status_code=400, detail="quiz_mode must be 'fast' or 'high_quality'")
    if payload.num_cards < 1 or payload.num_cards > MAX_FLASHCARDS:
        raise HTTPException(status_code=400, detail=f"num_cards must be between 1 and {MAX_FLASHCARDS}")
    if payload.num_questions < 3 or payload.num_questions > MAX_QUIZ_QUESTIONS:
        raise HTTPException(status_code=400, detail=f"num_questions must be between 3 and {MAX_QUIZ_QUESTIONS}")

    created = create_job(payload.model_dump())
    asyncio.create_task(process_study_job(created["job_id"], payload))
    return StudyJobCreateResponse(
        job_id=created["job_id"],
        status=created["status"],
        stage=created["stage"],
        progress=created["progress"],
    )


@app.get("/jobs/study/{job_id}", response_model=StudyJobStatusResponse)
async def get_study_job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return StudyJobStatusResponse(
        job_id=job["job_id"],
        status=job["status"],
        stage=job["stage"],
        progress=job["progress"],
        message=job["message"],
        created_at=job["created_at"],
        updated_at=job["updated_at"],
        error=job.get("error"),
        result=job.get("result"),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
