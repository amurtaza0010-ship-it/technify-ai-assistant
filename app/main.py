"""
Technify Academic AI Assistant (TAIA)
=====================================
FastAPI Application Entry Point

This is the main entry point for the AI Assistant microservice.
Run with: uvicorn app.main:app --reload
"""

from dotenv import load_dotenv

load_dotenv()

import json
import logging
import os
import re
import time
import traceback

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

logger = logging.getLogger("taia.main")

from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Request, HTTPException, Query, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

# Import the RoleChecker from our custom authorization module
from app.auth.rbac import RoleChecker  
# Import our new JWT handler
from app.auth.jwt_handler import verify_user_access
from app.services.llm import check_llm_api_key
from app.services.knowledge_base import warmup_knowledge_base, vector_store_status

CODE_BUILD_TAG = "kb-singleton-v3"


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("=" * 50)
    print("Technify Academic AI Assistant (TAIA)")
    print(f"Build: {CODE_BUILD_TAG} | pid={os.getpid()}")
    print("Service is starting...")
    print(f"Docs available at: http://localhost:{os.getenv('APP_PORT', 8000)}/docs")
    check_llm_api_key()
    warmup_knowledge_base()
    from app.services.rag_service import warmup_admin_rag
    warmup_admin_rag()
    print("=" * 50)
    yield

# Initialize FastAPI application
app = FastAPI(
    title="Technify Academic AI Assistant (TAIA)",
    description="AI-powered academic assistant integrated with Technify University ERP",
    version="0.1.0",
    docs_url="/docs",          # Swagger UI path
    redoc_url="/redoc",        # ReDoc path,
    lifespan=lifespan,
)

# CORS — set CORS_ALLOW_ALL=false and CORS_ORIGINS for explicit origins in production
def _parse_cors_origins() -> list[str]:
    if os.getenv("CORS_ALLOW_ALL", "true").lower() in ("1", "true", "yes"):
        return ["*"]
    raw = os.getenv(
        "CORS_ORIGINS",
        "http://127.0.0.1:5000,http://localhost:5000,http://127.0.0.1:3000,http://localhost:3000",
    )
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================================
# SYSTEM SECURITY RULES (Defining Access Control for Student, Faculty, & Admin)
# =========================================================================
allow_student_and_admin = RoleChecker(["Student", "Admin"])
allow_only_faculty = RoleChecker(["Faculty"])
allow_only_admin = RoleChecker(["Admin"])


# ========== Health Check Endpoints ==========

@app.get("/", tags=["Health"])
async def root():
    # Verify if the application service gateway is up and running
    return {
        "service": "Technify Academic AI Assistant (TAIA)",
        "status": "running",
        "version": "0.1.0",
    }


@app.get("/health", tags=["Health"])
async def health_check():
    kb = vector_store_status()
    return {
        "status": "healthy",
        "build": CODE_BUILD_TAG,
        "pid": os.getpid(),
        "components": {
            "api": "up",
            "llm": "configured",
            "vector_db": "warm" if kb["ready"] else "cold",
            "vector_db_warmup_s": kb.get("warmup_seconds"),
            "erp_api": "not_configured",
        },
    }


# ========== Academic & Security Test Endpoints ==========

# 1. Student Route (Accessible by Students and Admins)
@app.get("/api/v1/student/attendance", tags=["Student Features"], dependencies=[Depends(allow_student_and_admin)])
async def get_attendance():
    return {
        "course": "Web Engineering (CS-301)",
        "attendance": "78%",
        "classes_attended": "25 out of 32"
    }


# 2. Faculty Route (Restricted strictly to Faculty members)
@app.get("/api/v1/faculty/at-risk-students", tags=["Faculty Features"], dependencies=[Depends(allow_only_faculty)])
async def get_at_risk_students():
    # Test route to check faculty tracking features
    return {
        "department": "Information Technology",
        "at_risk_count": 4,
        "students": [
            {"id": "STU-0091", "name": "Ali", "attendance": "54%", "reason": "Low Attendance"},
            {"id": "STU-0142", "name": "Sana", "attendance": "62%", "reason": "Ungraded Assignments"}
        ]
    }


# 3. Admin Route (Restricted exclusively to Admin role)
@app.get("/api/v1/admin/fee-report", tags=["Admin Reports"], dependencies=[Depends(allow_only_admin)])
async def get_fee_report():
    return {
        "total_expected": "PKR 425M",
        "collected": "PKR 382.5M",
        "percentage": "90%"
    }


from app.chains.chatbot_chain import (
    generate_chat_response,
    generate_chat_response_stream,
    generate_contextual_response,
    generate_contextual_response_stream,
    generate_access_denied_response,
    classify_intent_async,
)
from app.services.erp_connector import fetch_erp_data
from app.services.study_planner import generate_study_plan
from app.services.knowledge_base import query_knowledge_base
from app.services.audit_logger import log_request
from app.auth.chat_rbac import check_chat_access, get_denial_message
from app.utils.fees_intent import is_fee_erp_intent, is_finance_department_fee_query, log_fee_routing
from app.utils.intent_routing import resolve_role_intent
from app.services.erp_connector import get_student_results, format_user_context_for_prompt
from app.services.erp_connector import is_department_stats_query
from app.services.chat_history import (
    register_session,
    list_user_sessions,
    get_session_messages,
    session_belongs_to_user,
)
from app.services.perf_timer import RequestTimer

# ========== Chat Endpoint ==========

async def _prepare_chat_turn(request: Request, message: dict, user_data: dict, timer: RequestTimer):
    """Shared intent classification, RBAC, and ERP fetch for chat endpoints."""
    timer.mark("Auth (verified)")
    uid = user_data.get('user_id', 'STU-0001')
    role = user_data.get('role', 'Student')
    session = (
        request.headers.get('x-session-id')
        or message.get('session_id')
        or uid
    )
    user_msg = message.get('message', '')

    if not user_msg:
        return None, {'response': 'Please provide a message.'}

    start = time.time()
    intent = await classify_intent_async(session, user_msg, role, user_context=user_data)
    timer.mark(f"Router/Intent → {intent}")
    resolved = resolve_role_intent(role, intent, user_msg)
    if is_department_stats_query(user_msg) and not is_finance_department_fee_query(user_msg):
        resolved = 'department_stats'
    log_fee_routing(
        "prepare_chat_turn",
        message=user_msg,
        role=role,
        detected_intent=intent,
        resolved_intent=resolved,
        handler=f"fetch_erp_data({resolved})" if resolved not in ('policy', 'general', 'greeting', 'ai_identity', 'profile', 'name') else resolved,
    )

    allowed, denial_msg = check_chat_access(role, intent, user_msg, uid, resolved_intent=resolved)
    timer.mark("RBAC")
    if not allowed:
        elapsed = round(time.time() - start, 2)
        log_request(uid, role, user_msg, resolved, elapsed)
        return None, {'response': denial_msg, 'intent': resolved, 'time': f'{elapsed}s'}

    intent = resolved

    erp_data = ''
    access_denied = False
    immediate_response = None

    try:
        if intent == 'study_plan':
            results = await get_student_results(uid)
            immediate_response = generate_study_plan(results)
        elif intent == 'policy':
            erp_data = query_knowledge_base(user_msg, timer=timer)
        elif intent in ('profile', 'name'):
            if is_department_stats_query(user_msg):
                erp_data, access_denied = await fetch_erp_data(
                    'department_stats', uid, role, user_msg
                )
            else:
                erp_data = format_user_context_for_prompt(user_data)
        elif intent in ('ai_identity', 'general', 'greeting'):
            erp_data = '__prompt_only__'
        else:
            erp_data, access_denied = await fetch_erp_data(intent, uid, role, user_msg)
        timer.mark(f"ERP/RAG fetch ({intent})")
    except Exception as e:
        erp_data = f'Error: {e}'

    return {
        'uid': uid,
        'role': role,
        'session': session,
        'user_msg': user_msg,
        'intent': intent,
        'start': start,
        'erp_data': erp_data,
        'access_denied': access_denied,
        'immediate_response': immediate_response,
        'user_data': user_data,
        'timer': timer,
    }, None


async def _resolve_chat_response(turn: dict) -> str:
    """Generate a complete chat response from a prepared turn."""
    timer: RequestTimer | None = turn.get('timer')
    if turn['immediate_response'] is not None:
        return turn['immediate_response']

    if turn['access_denied']:
        return turn['erp_data'] if turn['erp_data'] else get_denial_message(
            turn['role'], turn['intent']
        )
    if turn['erp_data']:
        result = await generate_contextual_response(
            turn['session'],
            turn['user_msg'],
            turn['erp_data'],
            turn['intent'],
            user_context=turn['user_data'],
        )
        if timer:
            timer.mark("Groq generation (contextual)")
        return result
    result = await generate_chat_response(turn['session'], turn['user_msg'])
    if timer:
        timer.mark("Groq generation")
    return result


async def _stream_chat_response(turn: dict):
    """Yield text chunks for a prepared chat turn."""
    timer: RequestTimer | None = turn.get('timer')
    if timer:
        timer.mark("Streaming setup")
    if turn['immediate_response'] is not None:
        yield turn['immediate_response']
        return

    if turn['access_denied']:
        yield turn['erp_data'] if turn['erp_data'] else get_denial_message(
            turn['role'], turn['intent']
        )
        return

    if turn['erp_data']:
        async for chunk in generate_contextual_response_stream(
            turn['session'],
            turn['user_msg'],
            turn['erp_data'],
            turn['intent'],
            user_context=turn['user_data'],
        ):
            yield chunk
        if timer:
            timer.mark("Groq streaming (contextual)")
        return

    async for chunk in generate_chat_response_stream(
        turn['session'], turn['user_msg']
    ):
        yield chunk
    if timer:
        timer.mark("Groq streaming")


@app.post('/api/v1/chat', tags=['Chat'])
async def chat(request: Request, message: dict, user_data: dict = Depends(verify_user_access)):
    timer = RequestTimer("chat")
    turn, early = await _prepare_chat_turn(request, message, user_data, timer)
    if early is not None:
        perf = timer.finish()
        early['perf'] = perf
        return early

    ai = await _resolve_chat_response(turn)
    elapsed = round(time.time() - turn['start'], 2)
    log_request(turn['uid'], turn['role'], turn['user_msg'], turn['intent'], elapsed)
    register_session(turn['uid'], turn['session'], turn['user_msg'])
    perf = timer.finish()
    return {'response': ai, 'intent': turn['intent'], 'time': f'{elapsed}s', 'perf': perf}


@app.post('/api/v1/chat/stream', tags=['Chat'])
async def chat_stream(
    request: Request,
    message: dict,
    user_data: dict = Depends(verify_user_access),
):
    timer = RequestTimer("chat-stream")
    turn, early = await _prepare_chat_turn(request, message, user_data, timer)

    async def generate():
        if early is not None:
            perf = timer.finish()
            yield f"data: {json.dumps({'text': early['response']})}\n\n"
            if 'intent' in early:
                yield f"data: {json.dumps({'meta': {'intent': early['intent'], 'time': early.get('time', ''), 'perf': perf}})}\n\n"
            yield "data: [DONE]\n\n"
            return

        yield f"data: {json.dumps({'meta': {'intent': turn['intent']}})}\n\n"

        async for chunk in _stream_chat_response(turn):
            if chunk:
                yield f"data: {json.dumps({'text': chunk})}\n\n"

        elapsed = round(time.time() - turn['start'], 2)
        log_request(
            turn['uid'], turn['role'], turn['user_msg'], turn['intent'], elapsed
        )
        register_session(turn['uid'], turn['session'], turn['user_msg'])
        perf = timer.finish()
        yield f"data: {json.dumps({'meta': {'intent': turn['intent'], 'time': f'{elapsed}s', 'perf': perf}})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ========== Chat History Endpoints ==========

@app.get('/api/v1/chat/history/list/{user_id}', tags=['Chat'])
async def chat_history_list(
    user_id: str,
    user_data: dict = Depends(verify_user_access),
):
    """List chat sessions for a user (newest first)."""
    if user_data.get('user_id') != user_id:
        raise HTTPException(status_code=403, detail="Cannot access another user's history.")

    sessions = list_user_sessions(user_id)
    return {'sessions': sessions}


@app.get('/api/v1/chat/history/{user_id}', tags=['Chat'])
async def chat_history(
    user_id: str,
    session_id: str = Query(None, description="Load messages for a specific session"),
    user_data: dict = Depends(verify_user_access),
):
    """Return messages for a specific session when session_id is provided."""
    if user_data.get('user_id') != user_id:
        raise HTTPException(status_code=403, detail="Cannot access another user's history.")

    if not session_id:
        return {'sessions': list_user_sessions(user_id)}

    if not session_belongs_to_user(session_id, user_id):
        raise HTTPException(status_code=404, detail="Session not found.")

    return {
        'session_id': session_id,
        'messages': get_session_messages(session_id),
    }


# ========== Audit Logs & Usage Stats Endpoints ==========

from app.services.audit_logger import get_recent_logs, get_stats as get_audit_stats

@app.get('/api/v1/admin/audit-logs', tags=['Admin Reports'], dependencies=[Depends(allow_only_admin)])
async def audit_logs(limit: int = 50):
    """Return recent audit log entries from the database."""
    return get_recent_logs(limit=limit)

@app.get('/api/v1/admin/usage-stats', tags=['Admin Reports'], dependencies=[Depends(allow_only_admin)])
async def usage_stats():
    """Return overall usage statistics."""
    return get_audit_stats()


# ========== Admin RAG (hybrid search over uploaded ERP data) ==========

from app.services.rag_service import (
    ingest_documents,
    hybrid_retrieve,
    get_rag_index_status,
    MAX_UPLOAD_BYTES,
)
from app.services.llm import build_rag_prompt, astream_llm_with_fallback
from langchain_core.messages import HumanMessage
from app.chains import chatbot_chain


# ── Abbreviation expansion (simple replace, no named groups) ──
_ABBREVIATION_PATTERNS = [
    (re.compile(r'\bvc\b', re.IGNORECASE), 'vice chancellor'),
    (re.compile(r'\bdc\b', re.IGNORECASE), 'deputy commissioner'),
    (re.compile(r'\bprofs?\b', re.IGNORECASE), 'professor'),
    (re.compile(r'\bdept\b', re.IGNORECASE), 'department'),
    (re.compile(r'\buni\b', re.IGNORECASE), 'university'),
]

def _expand_abbreviations(query: str) -> str:
    for pattern, replacement in _ABBREVIATION_PATTERNS:
        query = pattern.sub(replacement, query)
    return query


# ── Misspelling correction ──
_MISSPELLING_PATTERNS = [
    (re.compile(r'\bunivesity\b', re.IGNORECASE), 'university'),
    (re.compile(r'\buniversty\b', re.IGNORECASE), 'university'),
    (re.compile(r'\bv\.c\b', re.IGNORECASE), 'vice chancellor'),
]

def _correct_spelling(query: str) -> str:
    for pattern, replacement in _MISSPELLING_PATTERNS:
        query = pattern.sub(replacement, query)
    return query


_IDENTITY_QUERY_RE = re.compile(
    r"\b(who\s+is|who'?s|who\s+(?:are|was|were)|tell\s+me\s+about|what\s+is\s+the\s+name\s+of)\b",
    re.IGNORECASE,
)
_NAME_PATTERN_RE = re.compile(
    r"\b(?:Prof\.\s*Dr\.|Prof\.|Dr\.|Mr\.|Mrs\.|Ms\.)\s+[A-Z][a-z]+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b"
)

_IDENTITY_FILLER_PREFIXES = (
    "tell me about ",
    "what do you know about ",
    "information about ",
    "info about ",
    "describe ",
    "explain ",
)


def _canonicalize_identity_query(query: str) -> str:
    """Convert identity-seeking questions to a simple 'who is ...' form."""
    lower = query.lower().strip()
    for prefix in _IDENTITY_FILLER_PREFIXES:
        if lower.startswith(prefix):
            core = query[len(prefix):].strip()
            return f"who is {core}"
    return query


def _boost_identity_chunks(query: str, chunks: list) -> list:
    """
    If the query asks for a person's identity, move chunks that contain
    a person's name to the front, preserving others in order.
    """
    if not _IDENTITY_QUERY_RE.search(query):
        return chunks
    named = [c for c in chunks if _NAME_PATTERN_RE.search(c.page_content)]
    others = [c for c in chunks if not _NAME_PATTERN_RE.search(c.page_content)]
    return named + others


def _rag_history_session(request_session: str, uid: str) -> str:
    """Use a stable per-admin key when clients send ephemeral x-session-id values."""
    if request_session and request_session != uid:
        if not re.fullmatch(r"admin_rag_\d{10,}", request_session):
            return request_session
    return f"admin_rag_{uid}"


_SHORT_QUERY_MAX_WORDS = 15

_QUERY_FILLER_PREFIXES = (
    "can you tell me about",
    "could you tell me about",
    "tell me more about",
    "tell me about",
    "what do you know about",
    "what can you tell me about",
    "give me information about",
    "give me info about",
    "information about",
    "info about",
    "who is the",
    "who is",
    "what is the",
    "what is",
)

_CONTEXT_SENTENCE_RE = re.compile(
    r"(?:"
    r"\(Page\s+\d+\)|"
    r"\b(?:Prof\.|Dr\.|Mr\.|Mrs\.|Ms\.|University|College|Institute)\b|"
    r"\b[A-Z][a-z]+(?:\s+(?:[A-Z][a-z]+|Prof\.|Dr\.))+|"
    r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b"
    r")"
)

_RAG_REFERENCE_INSTRUCTION = (
    "\n\nIf the user asks for a reference, reply ONLY with the page number and the "
    'exact sentence from the excerpt. Example: "Page 9: Prof. Dr. Tauha Hussain Ali '
    'is the Vice-Chancellor."'
)


def _extract_relevant_context_sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return ""

    # NEVER use "Not found" messages as retrieval context
    if "not found" in text.lower():
        return ""

    sentences = re.split(r"(?<=[.!?])\s+", text)

    # First pass: look for a sentence with a name and a page citation (ideal anchor)
    for sentence in sentences:
        candidate = sentence.strip()
        if candidate and _NAME_PATTERN_RE.search(candidate) and "Page" in candidate:
            return candidate

    # Second pass: fall back to any sentence with a page citation
    for sentence in sentences:
        candidate = sentence.strip()
        if candidate and "Page" in candidate:
            return candidate

    # Final fallback: first sentence
    return sentences[0].strip() if sentences else text


def _enhance_short_query(query: str) -> str:
    """Return the query unchanged. (Previously added 'name profile details' to short queries, which diluted retrieval.)"""
    return query


def _build_rag_retrieval_query(user_msg: str, history_session: str) -> str:
    """Combine recent assistant context with the current user message for retrieval."""
    try:
        history = get_session_messages(history_session)
        if history:
            last_ai = next(
                (message for message in reversed(history[-6:]) if message.get("role") == "assistant"),
                None,
            )
            if last_ai:
                last_ai_content = (last_ai.get("content") or "").strip()
                if last_ai_content:
                    context_sentence = _extract_relevant_context_sentence(last_ai_content)
                    if context_sentence:
                        retrieval_query = f"Context: {context_sentence}. Query: {user_msg}"
                        logger.info("RAG retrieval query: %s", retrieval_query[:200])
                        return retrieval_query
    except Exception as exc:
        logger.warning("RAG retrieval context unavailable: %s", exc)
    logger.info("RAG retrieval query (no history): %s", user_msg[:200])
    return user_msg


def _save_rag_exchange(history_session: str, user_msg: str, ai_msg: str) -> None:
    """Persist admin RAG turns so follow-up retrieval can use conversation context."""
    if not ai_msg.strip():
        return
    try:
        _, redis_history = chatbot_chain._get_history(history_session)
        chatbot_chain._save_to_history(history_session, user_msg, ai_msg, redis_history)
    except Exception as exc:
        logger.warning("Failed to save admin RAG history: %s", exc)


@app.get('/api/v1/admin/rag/status', tags=['Admin RAG'])
async def admin_rag_status(user_data: dict = Depends(allow_only_admin)):
    """Return admin RAG index status (document count, readiness)."""
    return get_rag_index_status()


@app.post('/api/v1/admin/rag/upload', tags=['Admin RAG'])
async def admin_rag_upload(
    file: UploadFile = File(...),
    mode: str = Form("replace"),
    user_data: dict = Depends(allow_only_admin),
):
    """Upload CSV/Excel/JSON ERP data and index for hybrid RAG (admin only)."""
    filename = file.filename or "upload.csv"
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext not in ("csv", "xlsx", "xls", "json", "pdf", "docx"):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Upload .csv, .xlsx, .json, .pdf, or .docx",
        )

    try:
        logger.info(f"RAG upload requested: filename={file.filename}, size={file.size}, mode={mode}")
        contents = await file.read()
        if len(contents) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"File exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
            )
        if not contents:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        result = ingest_documents(contents, filename, mode=mode)
        return result
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as e:
        logger.error(f"RAG upload failed: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post('/api/v1/chat/rag', tags=['Admin RAG'])
async def chat_rag(
    request: Request,
    message: dict,
    user_data: dict = Depends(allow_only_admin),
):
    """
    Admin-only RAG chat over uploaded ERP data (hybrid BM25 + vector retrieval).
    Does not affect normal mock-ERP chat flows.
    """
    timer = RequestTimer("chat-rag")
    user_msg = (message.get("message") or "").strip()
    if not user_msg:
        return {"response": "Please provide a message.", "intent": "admin_rag"}

    # ── Expand abbreviations so "vc" → "vice chancellor" ──
    user_msg = _expand_abbreviations(user_msg)
    user_msg = _correct_spelling(user_msg)
    # Normalise "who X" → "who is X" so identity patterns catch them
    if re.match(r"who\s+(?!is\b|are\b|was\b|were\b)", user_msg, re.IGNORECASE):
        user_msg = re.sub(r"who\b", "who is", user_msg, count=1, flags=re.IGNORECASE)
    if _IDENTITY_QUERY_RE.search(user_msg):
        user_msg = _canonicalize_identity_query(user_msg)

    uid = user_data.get("user_id", "ADM-0001")
    session = request.headers.get("x-session-id") or message.get("session_id") or uid
    history_session = _rag_history_session(session, uid)
    start = time.time()

    # ── Safe default ──
    chunks: list = []

    retrieval_query = _build_rag_retrieval_query(user_msg, history_session)
    if not retrieval_query.startswith("Context:") and not _IDENTITY_QUERY_RE.search(user_msg):
        retrieval_query = _enhance_short_query(retrieval_query)

    # ── Debug logging after enhancement ──
    logger.info("Final retrieval query: %s", retrieval_query[:200])

    # ── Enumeration detection: increase top_k for list/count queries ──
    # Uses word-boundary regex matching so words like "Overall", "Hall", "small"
    # don't falsely trigger on the substring "all". Only standalone enumeration
    # keywords count.
    lower_msg = user_msg.lower()
    _ENUM_KEYWORDS_RE = re.compile(r"\b(?:all|list|how many|every)\b")
    is_enum_query = bool(_ENUM_KEYWORDS_RE.search(lower_msg))
    top_k_val = 20 if is_enum_query else 10

    chunks = hybrid_retrieve(retrieval_query, top_k=top_k_val)
    chunks = _boost_identity_chunks(user_msg, chunks)
    timer.mark(f"Hybrid RAG retrieve ({len(chunks)} chunks)")

    prompt = build_rag_prompt(user_msg, chunks) + _RAG_REFERENCE_INSTRUCTION
    messages = [HumanMessage(content=prompt)]

    async def generate():
        full_text = ""
        yield f"data: {json.dumps({'meta': {'intent': 'admin_rag', 'chunks': len(chunks)}})}\n\n"
        async for chunk in astream_llm_with_fallback(messages):
            if chunk:
                full_text += chunk
                yield f"data: {json.dumps({'text': chunk})}\n\n"
        elapsed = round(time.time() - start, 2)
        log_request(uid, "admin", user_msg, "admin_rag", elapsed)
        _save_rag_exchange(history_session, user_msg, full_text)
        perf = timer.finish()
        yield f"data: {json.dumps({'meta': {'intent': 'admin_rag', 'time': f'{elapsed}s', 'perf': perf}})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=os.getenv("APP_HOST", "0.0.0.0"),
        port=int(os.getenv("APP_PORT", 8000)),
        reload=False,
    )