"""
TAIA Chatbot Chain — Phase 3
Member 3: Redis Persistent Conversation Memory

Replaces volatile Python dict (_memories = {}) with Redis so that
conversation history survives server restarts.

If Redis is not running, the code automatically falls back to in-memory
storage so the app never crashes.
"""

import os
import re
import logging
import time
from collections.abc import AsyncIterator
from typing import Optional

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from app.prompts.templates import ATTENDANCE_PROMPT, RESULTS_PROMPT, COURSE_PROMPT
from app.services.llm import (
    LLM_CONNECTION_ERROR,
    TAIA_IDENTITY_SYSTEM,
    ainvoke_llm_with_fallback,
    ainvoke_classifier_llm,
    astream_llm_with_fallback,
    get_llm,
    is_llm_auth_error,
)
from app.auth.chat_rbac import check_student_data_scope, normalize_role
from app.utils.fees_intent import is_fee_erp_intent, is_finance_department_fee_query, log_fee_routing
from app.utils.intent_routing import resolve_role_intent
from app.services.erp_connector import (
    format_user_context_for_prompt,
    install_fetch_erp_data_patch,
    is_access_denied_payload,
    is_cross_student_at_risk_query,
    is_erp_error_response,
    is_peers_gpa_query,
    is_department_stats_query,
    is_policy_or_rules_question,
    get_rbac_chain_denial_message,
    query_policy_documents_async,
    should_use_rag_for_exams,
)
from app.services.erp_data_trim import trim_erp_payload_for_llm

logger = logging.getLogger("taia.chatbot_chain")

GPA_PROMPT = """Based on the following GPA data for student {student_id}, answer their question clearly.
GPA Data:
{gpa_data}

Question: {question}

Response:"""

FEES_PROMPT = """Based on the following fee data for student {student_id}, answer their question clearly.
Fee Data:
{fee_data}

Question: {question}

Response:"""

ADMIN_PROMPT = """Based on the following administrative data, answer the question clearly and accurately.
Admin Data:
{admin_data}

Question: {question}

Response:"""

FACULTY_PROMPT = """Based on the following faculty data, answer the question clearly and accurately.
Faculty Data:
{faculty_data}

Question: {question}

Response:"""

PROFILE_PROMPT = """The user is asking about THEIR OWN identity or profile (not about you, TAIA).
Use ONLY the authenticated session details below — this is the logged-in user's JWT data.
Session User Data:
{profile_data}

Question: {question}

Rules:
1. The user is asking about themselves. Respond with THEIR name, ID, role, and department from session data.
2. If they ask for their name, respond with the exact name from session data (e.g. "Your name is Brian Howe.").
3. You are TAIA speaking to the user — do not say you are the user.

Response:"""

AI_IDENTITY_PROMPT = """The user is asking a simple question about YOU (TAIA) — NOT about themselves.
Do NOT use or mention the logged-in user's JWT profile, name, student ID, department, or email.

Question: {question}

Answer ONLY what was specifically asked:
- If asked your name → just say your name (e.g. "I'm TAIA.").
- If asked what university → just say "Technify University."
- If asked who built you → just say "Technify Software House."
- If asked what you can do → one short sentence listing key capabilities.

Keep it to 1-2 sentences max. Be friendly and conversational. Do NOT give a full introduction.

Response:"""

AI_IDENTITY_FULL_PROMPT = """The user explicitly wants a full introduction to YOU (TAIA) — NOT about themselves.
Do NOT use or mention the logged-in user's JWT profile, name, student ID, department, or email.

Question: {question}

Give a warm, concise introduction (one short paragraph max):
1. You are TAIA (Technify Academic AI Assistant), built by Technify Software House.
2. You help students, faculty, and admins with university ERP queries.
3. You are a bot, NOT the user.

Response:"""

GREETING_PROMPT = """The user sent a greeting or casual small talk.

Question: {question}

Reply with ONE friendly, conversational line. Examples:
- "Hi!" → "Hey! How can I help you today?"
- "How are you?" → "Doing great! What can I help you with today?"

Do NOT introduce yourself or explain what you do. Keep it to 1 sentence.

Response:"""

GENERAL_PROMPT = """Answer the user's question helpfully as TAIA.
You are NOT the user. Do not mention the user's name or profile unless they explicitly ask about themselves.
Match your response length to the question — simple questions get 1-2 sentences. Do not repeat your introduction.

Question: {question}

Response:"""

POLICY_PROMPT = """Based on the following university policy documents, answer the question clearly.
Be concise for simple questions; provide detail only when the question requires it.
Do NOT mention ERP errors, student IDs, or API failures. Use only the policy information provided.

Policy Information:
{policy_data}

Question: {question}

Response:"""

STUDENT_INTENTS = [
    'attendance', 'results', 'gpa', 'courses', 'timetable', 'fees',
    'assignments', 'exams', 'study_plan', 'policy', 'profile', 'name',
    'ai_identity', 'greeting', 'general',
]

FACULTY_INTENTS = [
    'faculty_attendance', 'faculty_ungraded', 'faculty_at_risk',
    'faculty_courses', 'faculty_performance', 'department_stats',
    'policy', 'profile', 'name',
    'ai_identity', 'greeting', 'general',
]

ADMIN_INTENTS = [
    'admin_students', 'admin_admissions', 'admin_fees', 'admin_departments',
    'department_stats', 'admin_at_risk', 'admin_overall', 'admin_finance_department',
    'admin_finance_pending', 'admin_finance_scholarship', 'admin_finance_summary',
    'policy', 'profile', 'name', 'ai_identity', 'greeting', 'general',
]

FINANCE_OFFICER_INTENTS = [
    'admin_fees', 'admin_finance_department', 'admin_finance_pending',
    'admin_finance_scholarship', 'admin_finance_summary',
    'policy', 'profile', 'name', 'ai_identity', 'greeting', 'general',
]

EXAM_OFFICER_INTENTS = [
    'exams', 'faculty_performance', 'admin_at_risk', 'faculty_at_risk',
    'at_risk_students', 'faculty_ungraded',
    'policy', 'profile', 'name', 'ai_identity', 'greeting', 'general',
]

PROFILE_INTENTS = frozenset({'profile', 'name'})

_AI_FULL_INTRO_PATTERNS = (
    r"who are you",
    r"what are you",
    r"tell me about yourself",
    r"tell me about you",
    r"introduce yourself",
    r"about yourself",
)

_AI_BRIEF_PATTERNS = (
    r"what is your name",
    r"what's your name",
    r"your name",
    r"what can you do",
    r"what do you do",
    r"name of your university",
    r"name of the university",
    r"what university",
    r"which university",
    r"who (built|made|created) you",
    r"who are you built by",
)

_GREETING_PATTERNS = (
    r"^hi\b",
    r"^hello\b",
    r"^hey\b",
    r"^good (morning|afternoon|evening)\b",
    r"how are you",
    r"how's it going",
    r"what's up",
    r"^greetings\b",
)

_USER_PROFILE_PATTERNS = (
    r"who am i",
    r"what is my name",
    r"what's my name",
    r"my profile",
    r"what is my profile",
)


def _is_greeting(message: str) -> bool:
    lower = message.lower().strip()
    return any(re.search(p, lower) for p in _GREETING_PATTERNS)


def _is_ai_identity_question(message: str) -> bool:
    lower = message.lower().strip()
    return any(
        re.search(p, lower)
        for p in _AI_FULL_INTRO_PATTERNS + _AI_BRIEF_PATTERNS
    )


def _get_ai_identity_mode(message: str) -> str:
    """Return 'full' for explicit intro requests, 'brief' for simple factual bot questions."""
    lower = message.lower().strip()
    if any(re.search(p, lower) for p in _AI_FULL_INTRO_PATTERNS):
        return "full"
    return "brief"


def _at_risk_intent_for_role(role: str) -> str:
    """Map at-risk queries to the intent each role is permitted to use."""
    role_norm = normalize_role(role)
    if role_norm in ("admin", "exam_officer"):
        return "admin_at_risk"
    if role_norm == "faculty":
        return "faculty_at_risk"
    return "at_risk_students"


_KEYWORD_INTENT_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("faculty_at_risk", (r"at[- ]risk students?", r"students? at risk", r"my students at risk")),
    ("faculty_ungraded", (r"ungraded", r"not graded", r"pending grading")),
    ("faculty_performance", (
        r"course performance",
        r"performance statistics",
        r"pass rate",
        r"average grade",
    )),
    ("exams", (
        r"exam schedule",
        r"upcoming exam",
        r"examination schedule",
        r"\bmy exams?\b",
        r"next exam",
    )),
    ("attendance", (r"\battendance\b", r"\bpresent\b", r"\babsent\b", r"how many classes")),
    ("gpa", (r"\bgpa\b", r"\bcgpa\b", r"grade point")),
    ("admin_finance_pending", (r"pending fees?", r"unpaid fees?", r"students with pending fees?")),
    ("admin_finance_scholarship", (r"scholarship stats?", r"scholarship statistics?", r"scholarship report")),
    ("admin_finance_department", (
        r"department[- ]wise fees?",
        r"department[- ]wise fee",
        r"fees? by department",
        r"department[- ]wise fee stats?",
    )),
    ("admin_finance_summary", (r"financial summary", r"revenue report", r"finance summary")),
    ("admin_fees", (r"fee collection", r"collected fees?", r"fee report", r"collection rate")),
    ("fees", (
        r"\bmy fees?\b",
        r"\bmy tuition\b",
        r"fee status",
        r"fee collection",
        r"how much.*\bfee",
        r"\btuition\b",
        r"fee amount",
        r"fee due",
        r"due date",
    )),
    ("timetable", (r"\btimetable\b", r"class schedule", r"\bschedule\b.*\bclass")),
    ("assignments", (r"\bmy assignments?\b", r"\bhomework\b", r"due this week")),
    ("courses", (r"\bmy courses?\b", r"registered subjects", r"\benrolled\b")),
    ("results", (r"\bgrades?\b", r"\bmarks?\b", r"\bresults?\b", r"transcript")),
    ("study_plan", (r"study plan", r"study schedule", r"how (should|do) i study")),
    ("admin_overall", (r"overall (university )?statistics", r"total enrollment", r"university stats")),
]


def _keyword_intent(message: str, role: str) -> Optional[str]:
    """Fast keyword router — avoids LLM classifier for common ERP queries."""
    lower = message.lower().strip()
    role_norm = normalize_role(role)
    for intent, patterns in _KEYWORD_INTENT_PATTERNS:
        if any(re.search(p, lower) for p in patterns):
            if role_norm == "student" and intent.startswith(("faculty_", "admin_")):
                continue
            if role_norm == "faculty" and intent.startswith("admin_"):
                continue
            return intent
    if role_norm in ("admin", "finance_officer") and re.search(r"\bfees?\b", lower):
        if not re.search(r"\bSTU-\d+\b", message, re.I):
            return resolve_role_intent(role, "fees", message)
    return None


def _heuristic_intent(message: str, role: str = "Student") -> Optional[str]:
    """Fast path for identity, greeting, policy, and RBAC-sensitive queries."""
    lower = message.lower().strip()
    if is_policy_or_rules_question(message):
        return "policy"
    kw = _keyword_intent(message, role)
    if kw:
        return kw
    if is_department_stats_query(message) and not is_finance_department_fee_query(message):
        return "department_stats"
    if any(re.search(p, lower) for p in _USER_PROFILE_PATTERNS):
        if is_department_stats_query(message):
            return "department_stats"
        return "profile" if "name" not in lower else "name"
    # RBAC: cross-student queries → faculty_only intents (blocked for students)
    if is_peers_gpa_query(message):
        return "peers_gpa"
    if is_cross_student_at_risk_query(message):
        return _at_risk_intent_for_role(role)
    if _is_greeting(lower):
        return "greeting"
    if _is_ai_identity_question(lower):
        return "ai_identity"
    return None


def _resolve_intent_for_role(intent: str, role: str, message: str) -> str:
    """Re-route intents based on role and cross-student query detection."""
    if is_finance_department_fee_query(message) or (
        normalize_role(role) in ("admin", "finance_officer")
        and "scholarship" in message.lower()
    ):
        return resolve_role_intent(role, intent, message)
    if is_department_stats_query(message):
        return "department_stats"
    if is_cross_student_at_risk_query(message):
        return _at_risk_intent_for_role(role)
    if is_peers_gpa_query(message):
        return "peers_gpa"
    if is_policy_or_rules_question(message):
        return "policy"
    if intent in ("exams", "examination", "rules"):
        if should_use_rag_for_exams(role, message):
            return "policy"
    if normalize_role(role) == "student" and intent in (
        "faculty_at_risk", "admin_at_risk", "gpa", "results", "attendance",
        "profile", "name",
    ):
        if is_department_stats_query(message):
            return "department_stats"
        if is_cross_student_at_risk_query(message):
            return _at_risk_intent_for_role(role)
        if is_peers_gpa_query(message):
            return "peers_gpa"
    if intent in ("at_risk_students", "faculty_at_risk", "admin_at_risk") and is_cross_student_at_risk_query(message):
        return _at_risk_intent_for_role(role)
    return resolve_role_intent(role, intent, message)
# ── Step 1: Try to connect to Redis. Fall back to in-memory if unavailable. ──

_use_redis = False
_memories = {}  # fallback in-memory store


def _get_redis_url() -> str:
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        return redis_url
    host = os.getenv("REDIS_HOST", "localhost")
    port = os.getenv("REDIS_PORT", "6379")
    db = os.getenv("REDIS_DB", "0")
    return f"redis://{host}:{port}/{db}"


try:
    import redis
    from langchain_community.chat_message_histories import RedisChatMessageHistory

    _redis_url = _get_redis_url()
    _redis_client = redis.from_url(
        _redis_url,
        decode_responses=True,
        socket_connect_timeout=2   # fail fast if Redis is not reachable
    )
    _redis_client.ping()           # raises ConnectionError if Redis is down
    _use_redis = True
    print("[TAIA] Redis connected. Using persistent session memory.")

except Exception as e:
    print(f"[TAIA] Redis not available ({e}). Using in-memory fallback.")


def _build_system_message(
    session_id: Optional[str] = None,
    user_context: Optional[dict] = None,
) -> str:
    """Return TAIA identity system prompt. JWT user data is never injected here."""
    prompt = TAIA_IDENTITY_SYSTEM
    if user_context:
        role = user_context.get("role", "")
        uid = user_context.get("user_id", "")
        role_norm = normalize_role(role)
        if role_norm == "student" and uid:
            prompt += (
                f"\n\nSTUDENT DATA SCOPE: You are assisting a STUDENT. "
                f"You must ONLY provide information about THIS student (ID: {uid}). "
                "NEVER reveal data about other students, even if asked. "
                "If asked about other students, politely redirect them to ask about their own data."
            )
        elif role and uid:
            prompt += (
                f"\n\nACTIVE SESSION: User is logged in as {role} ({uid}). "
                "Enforce role-based access: students may only see their own records; "
                "faculty may only see their own courses and enrolled students; "
                "admins have full access. Never reveal another user's private data."
            )
    if session_id and _has_prior_turns(session_id):
        prompt += (
            "\n\nCONVERSATION CONTEXT: This is an ongoing conversation. "
            "Do NOT repeat your introduction or explain what you are unless "
            "the user explicitly asks again."
        )
    return prompt


def _has_prior_turns(session_id: str) -> bool:
    """True if the session already has user/assistant messages (not first turn)."""
    if _use_redis:
        try:
            history = RedisChatMessageHistory(
                session_id=f"taia:{session_id}",
                url=_get_redis_url(),
            )
            return len(history.messages) > 0
        except Exception:
            return False
    if session_id in _memories:
        return any(
            isinstance(m, (HumanMessage, AIMessage))
            for m in _memories[session_id]
        )
    return False


# ── Step 2: Helper — get history for a session ────────────────────────────────


def _get_history(session_id: str, user_context: Optional[dict] = None):
    """
    Return (list_of_messages, redis_history_object_or_None) for a session.

    - If Redis is available: loads full conversation history from Redis.
    - If not: uses the in-memory dict as fallback.
    Always prepends the System Persona message so the LLM stays in character.
    """
    if _use_redis:
        history = RedisChatMessageHistory(
            session_id=f"taia:{session_id}",
            url=_get_redis_url(),
        )
        msgs = [SystemMessage(content=_build_system_message(session_id, user_context))]
        msgs.extend(history.messages)
        return msgs, history

    if session_id not in _memories:
        _memories[session_id] = [SystemMessage(content=_build_system_message(session_id, user_context))]
    else:
        _memories[session_id][0] = SystemMessage(content=_build_system_message(session_id, user_context))
    return _memories[session_id], None


def get_stored_messages(session_id: str) -> list:
    """Return Human/AI messages for a session (excludes system prompt)."""
    if _use_redis:
        try:
            history = RedisChatMessageHistory(
                session_id=f"taia:{session_id}",
                url=_get_redis_url(),
            )
            return [
                m for m in history.messages
                if isinstance(m, (HumanMessage, AIMessage))
            ]
        except Exception:
            return []
    if session_id in _memories:
        return [
            m for m in _memories[session_id]
            if isinstance(m, (HumanMessage, AIMessage))
        ]
    return []


# ── Step 3: Helper — save exchange to history ─────────────────────────────────

def _save_to_history(session_id: str, human_msg: str, ai_msg: str, redis_history):
    """
    Persist the latest human + AI message pair.

    - Redis mode: appends to the Redis list (survives restarts).
    - Fallback mode: appends to the in-memory dict (lost on restart).
    """
    if _use_redis and redis_history is not None:
        redis_history.add_user_message(human_msg)
        redis_history.add_ai_message(ai_msg)
    else:
        if session_id in _memories:
            _memories[session_id].append(HumanMessage(content=human_msg))
            _memories[session_id].append(AIMessage(content=ai_msg))



# ── Step 4: Build the LLM model ───────────────────────────────────────────────

def get_chatbot_chain(session_id: str):
    """
    Create and return the ChatOpenAI LLM instance using central config.
    """
    return get_llm()


# ── Step 5: Main chat entry point ─────────────────────────────────────────────

# --- ISKE NEECHAY WALA CODE (generate_chat_response waghera) WAISE HI REHNE DEIN ---

async def generate_chat_response(
    session_id: str,
    user_message: str,
    user_context: Optional[dict] = None,
    history_user_message: Optional[str] = None,
) -> str:
    """
    Send user_message to the LLM with full conversation history.
    Saves the exchange to Redis (or in-memory fallback) afterwards.
    """
    t0 = time.perf_counter()
    display_message = history_user_message or user_message
    try:
        messages, redis_history = _get_history(session_id, user_context)
        messages.append(HumanMessage(content=user_message))

        response = await ainvoke_llm_with_fallback(messages)
        ai_text = response.content

        _save_to_history(session_id, display_message, ai_text, redis_history)

        return ai_text

    except Exception as e:
        print(f"LangChain Error: {e}")
        if is_llm_auth_error(e):
            return LLM_CONNECTION_ERROR
        return f"I'm sorry, I encountered an error connecting to my AI brain. (Error: {e})"
    finally:
        logger.info(
            "Chain generate_chat_response → %.2fs",
            time.perf_counter() - t0,
        )


async def _stream_and_save(
    session_id: str,
    display_message: str,
    messages: list,
    redis_history,
) -> AsyncIterator[str]:
    """Stream LLM output and persist the full exchange to session history."""
    full_text = ""
    try:
        async for chunk in astream_llm_with_fallback(messages):
            full_text += chunk
            yield chunk
        _save_to_history(session_id, display_message, full_text, redis_history)
    except Exception as e:
        print(f"LangChain Stream Error: {e}")
        if is_llm_auth_error(e):
            yield LLM_CONNECTION_ERROR
        else:
            yield (
                f"I'm sorry, I encountered an error connecting to my AI brain. "
                f"(Error: {e})"
            )


async def generate_chat_response_stream(
    session_id: str,
    user_message: str,
    user_context: Optional[dict] = None,
    history_user_message: Optional[str] = None,
) -> AsyncIterator[str]:
    """Stream user_message to the LLM with full conversation history."""
    display_message = history_user_message or user_message
    messages, redis_history = _get_history(session_id, user_context)
    messages.append(HumanMessage(content=user_message))
    async for chunk in _stream_and_save(
        session_id, display_message, messages, redis_history
    ):
        yield chunk


async def _generate_ai_identity_response_stream(
    session_id: str, msg: str
) -> AsyncIterator[str]:
    mode = _get_ai_identity_mode(msg)
    prompt_template = (
        AI_IDENTITY_FULL_PROMPT if mode == "full" else AI_IDENTITY_PROMPT
    )
    try:
        system = _build_system_message(session_id)
        messages = [
            SystemMessage(content=system),
            HumanMessage(content=prompt_template.format(question=msg)),
        ]
        _, redis_history = _get_history(session_id)
        async for chunk in _stream_and_save(session_id, msg, messages, redis_history):
            yield chunk
    except Exception as e:
        print(f"AI Identity Stream Error: {e}")
        if is_llm_auth_error(e):
            yield LLM_CONNECTION_ERROR
        elif mode == "full":
            yield (
                "I'm TAIA (Technify Academic AI Assistant), built by Technify "
                "Software House. I help students, faculty, and admins with "
                "university ERP queries."
            )
        else:
            yield "I'm TAIA, your Technify University assistant!"


async def _generate_greeting_response_stream(
    session_id: str, msg: str
) -> AsyncIterator[str]:
    try:
        messages = [
            SystemMessage(content=_build_system_message(session_id)),
            HumanMessage(content=GREETING_PROMPT.format(question=msg)),
        ]
        _, redis_history = _get_history(session_id)
        async for chunk in _stream_and_save(session_id, msg, messages, redis_history):
            yield chunk
    except Exception as e:
        print(f"Greeting Stream Error: {e}")
        if is_llm_auth_error(e):
            yield LLM_CONNECTION_ERROR
        else:
            yield "Hey! How can I help you today?"


async def _generate_ai_identity_response(session_id: str, msg: str) -> str:
    """
    Answer bot-identity questions without full Redis history (avoids JWT/profile leakage).
    Uses brief vs full prompt based on what was specifically asked.
    """
    mode = _get_ai_identity_mode(msg)
    prompt_template = (
        AI_IDENTITY_FULL_PROMPT if mode == "full" else AI_IDENTITY_PROMPT
    )
    try:
        system = _build_system_message(session_id)
        messages = [
            SystemMessage(content=system),
            HumanMessage(content=prompt_template.format(question=msg)),
        ]
        response = await ainvoke_llm_with_fallback(messages)
        ai_text = response.content

        _, redis_history = _get_history(session_id)
        _save_to_history(session_id, msg, ai_text, redis_history)

        return ai_text
    except Exception as e:
        print(f"AI Identity Error: {e}")
        if is_llm_auth_error(e):
            return LLM_CONNECTION_ERROR
        if mode == "full":
            return (
                "I'm TAIA (Technify Academic AI Assistant), built by Technify Software House. "
                "I help students, faculty, and admins with university ERP queries."
            )
        return "I'm TAIA, your Technify University assistant!"


async def _generate_greeting_response(session_id: str, msg: str) -> str:
    """One-line friendly reply for greetings and small talk."""
    try:
        messages = [
            SystemMessage(content=_build_system_message(session_id)),
            HumanMessage(content=GREETING_PROMPT.format(question=msg)),
        ]
        response = await ainvoke_llm_with_fallback(messages)
        ai_text = response.content

        _, redis_history = _get_history(session_id)
        _save_to_history(session_id, msg, ai_text, redis_history)

        return ai_text
    except Exception as e:
        print(f"Greeting Error: {e}")
        if is_llm_auth_error(e):
            return LLM_CONNECTION_ERROR
        return "Hey! How can I help you today?"

# ── Step 6: Intent classifier ─────────────────────────────────────────────────

async def classify_intent_async(
    session_id: str,
    message: str,
    role: str = 'Student',
    user_context: Optional[dict] = None,
) -> str:
    """
    Use an LLM to classify the user's intent based on the message and conversation history.
    Used by main.py to decide which ERP endpoint to call before LLM.
    """
    t0 = time.perf_counter()
    heuristic = _heuristic_intent(message, role)
    if heuristic:
        resolved = _resolve_intent_for_role(heuristic, role, message)
        logger.info(
            "Chain classify_intent (heuristic=%s) → %.2fs",
            resolved,
            time.perf_counter() - t0,
        )
        return resolved

    try:
        messages, _ = _get_history(session_id)
        
        # Extract the last 3 user/AI exchanges to provide context
        recent_history = []
        for msg in messages[-6:]:
            if isinstance(msg, HumanMessage):
                recent_history.append(f"User: {msg.content}")
            elif isinstance(msg, AIMessage):
                recent_history.append(f"AI: {msg.content}")
                
        history_text = "\n".join(recent_history)
        
        # Define valid intents based on role
        role_lower = role.lower().replace(" ", "_")
        if role_lower == 'faculty':
            valid_list = FACULTY_INTENTS
        elif role_lower == 'admin':
            valid_list = ADMIN_INTENTS
        elif role_lower in ('finance', 'finance_officer'):
            valid_list = FINANCE_OFFICER_INTENTS
        elif role_lower == 'exam_officer':
            valid_list = EXAM_OFFICER_INTENTS
        else:
            valid_list = STUDENT_INTENTS
        
        prompt = f"""You are an Intent Classifier for a University ERP AI Assistant.
The user is a {role}.
Your task is to classify the user's latest message into EXACTLY ONE of the following intents:
{valid_list}

Recent Conversation History:
{history_text}

Latest User Message: {message}

Intent mapping guide:
- attendance: attendance percentage, present/absent, class attendance
- results: grades, marks, exam scores, transcript
- gpa: CGPA, GPA, grade point average
- courses: enrolled courses, registered subjects
- timetable: class schedule, which classes on a day (Monday, Tuesday, etc.)
- fees: own fee status, due amount (student's own fees only)
- assignments: homework, pending assignments, due this week
- exams: upcoming exams, next exam date, when is my exam (student's personal schedule ONLY)
- study_plan: study schedule, how to prepare
- policy: university rules, policies, regulations, examination rules, late submission, integrity, leave
- faculty_attendance: faculty viewing student attendance in their courses
- faculty_ungraded: ungraded assignments count
- faculty_at_risk / at_risk_students: which students are at risk, in danger, failing (faculty/admin only)
- peers_gpa: other students' GPA or grades (faculty/admin only)
- faculty_courses: courses taught by faculty
- faculty_performance: course performance, pass rate, average grade
- admin_students: total student count, enrollment statistics
- admin_admissions: admission statistics by year
- admin_fees: fee collection stats, total expected/collected
- admin_departments: department-wise student/CGPA stats
- department_stats: department-wise student counts or enrollment breakdown (faculty/admin only)
- admin_at_risk: university-wide at-risk students list
- admin_overall: total enrollment, total faculty
- admin_finance_department: department-wise fee collection (CS, Business, etc.)
- admin_finance_pending: students with pending fees
- admin_finance_scholarship: scholarship statistics
- admin_finance_summary: total revenue, pending revenue, expenses
- ai_identity: questions about TAIA the bot — name, university, who built you, what can you do, OR full intro ("who are you", "tell me about yourself")
- greeting: hi, hello, hey, how are you, good morning — casual small talk only
- profile: who am I, what is MY profile, my department, my email (questions about the logged-in user)
- name: what is MY name, tell me MY name (the user's name only)
- general: other unrelated questions (not greetings, bot identity, or user profile)

Rules:
1. Output ONLY the exact intent string from the list above. Do not output quotes or extra text.
2. "Hi" / "Hello" / "How are you?" → greeting (NOT ai_identity).
3. "What is your name?" / "What university?" / "Name of your university?" → ai_identity (brief bot question, NOT full intro).
4. "Tell me about yourself" / "Who are you?" / "Introduce yourself" → ai_identity (full intro request).
5. "Who am I?" / "What is my name?" / "my profile" → profile or name (about the user).
6. "What are the examination rules?" / "exam regulations" → policy (NOT exams).
7. exams intent is ONLY for students asking about THEIR upcoming exam schedule (dates/times).
8. Admin, Faculty, and Exam Officer asking about rules → policy.
9. If the user asks a follow-up about ERP data, use conversation history to pick the ERP intent.
10. Students asking about finance reports → admin_finance_summary (access will be denied).
11. "Department wise students" / "students per department" / "department statistics" → department_stats (NOT profile).
12. Students asking about other students or university-wide lists → admin_at_risk or faculty intents (access will be denied for students).
13. Faculty cannot access admin reports or individual student ERP records outside their courses.
14. If no intent matches, output 'general'.

Intent:"""

        response = await ainvoke_classifier_llm([HumanMessage(content=prompt)])
        intent = response.content.strip().strip("'\"").lower()
        if intent not in valid_list:
            intent = "general"
        resolved = _resolve_intent_for_role(intent, role, message)
        logger.info(
            "Chain classify_intent (llm=%s) → %.2fs",
            resolved,
            time.perf_counter() - t0,
        )
        return resolved
    except Exception as e:
        print(f"Intent Classification Error: {e}")
        if is_department_stats_query(message):
            return "department_stats"
        return 'general'


# ── Step 7: Contextual response with ERP data ─────────────────────────────────

async def generate_contextual_response(
    sid: str,
    msg: str,
    data: str,
    intent: str,
    user_context: Optional[dict] = None,
) -> str:
    """
    Format a structured prompt using live ERP data and send it to the LLM.
    Called by main.py after fetching data from the Mock ERP API.
    """
    t0 = time.perf_counter()
    try:
        return await _generate_contextual_response_inner(
            sid, msg, data, intent, user_context
        )
    finally:
        logger.info(
            "Chain generate_contextual_response intent=%s → %.2fs",
            intent,
            time.perf_counter() - t0,
        )


async def _generate_contextual_response_inner(
    sid: str,
    msg: str,
    data: str,
    intent: str,
    user_context: Optional[dict] = None,
) -> str:
    # RBAC hard stop — never send restricted data to LLM or RAG
    if data and is_access_denied_payload(data):
        return get_rbac_chain_denial_message()

    profile_data = format_user_context_for_prompt(user_context or {}) if intent in PROFILE_INTENTS else ""

    if user_context:
        role = user_context.get("role", "Student")
        uid = user_context.get("user_id", sid)
        if normalize_role(role) == "student":
            if is_cross_student_at_risk_query(msg) or is_peers_gpa_query(msg):
                return get_rbac_chain_denial_message()
            scope_ok, scope_denial = check_student_data_scope(intent, msg, uid)
            if not scope_ok:
                return scope_denial or get_rbac_chain_denial_message()

    role = (user_context or {}).get("role", "Student")
    resolved_intent = resolve_role_intent(role, intent, msg)
    log_fee_routing(
        "generate_contextual_response",
        message=msg,
        role=role,
        detected_intent=intent,
        resolved_intent=resolved_intent,
        handler=(
            "ADMIN_PROMPT/FEES_PROMPT"
            if is_fee_erp_intent(intent, role, msg)
            else ("POLICY_PROMPT" if intent == "policy" else "contextual_prompt")
        ),
    )

    use_policy = (
        intent == "policy"
        or is_policy_or_rules_question(msg)
        or (intent == "exams" and should_use_rag_for_exams(role, msg))
    )
    # Never RAG-fallback for faculty-only / cross-student / fee ERP intents
    if intent in ("at_risk_students", "peers_gpa", "faculty_at_risk", "admin_at_risk"):
        use_policy = False
    if is_fee_erp_intent(intent, role, msg):
        use_policy = False
    if is_erp_error_response(data) and not use_policy:
        if is_cross_student_at_risk_query(msg) or is_peers_gpa_query(msg):
            return get_rbac_chain_denial_message()
    if is_erp_error_response(data) and use_policy and not is_fee_erp_intent(intent, role, msg):
        data = await query_policy_documents_async(msg)
        use_policy = True

    if not use_policy and data and isinstance(data, str):
        try:
            import json as _json
            if data.strip().startswith(("{", "[")):
                parsed = _json.loads(data)
                data = _json.dumps(trim_erp_payload_for_llm(parsed, intent, msg))
        except (ValueError, TypeError):
            pass

    if intent == 'ai_identity':
        return await _generate_ai_identity_response(sid, msg)
    elif intent == 'greeting':
        return await _generate_greeting_response(sid, msg)
    elif use_policy:
        prompt = POLICY_PROMPT.format(policy_data=data, question=msg)
    elif intent in PROFILE_INTENTS:
        prompt = PROFILE_PROMPT.format(profile_data=profile_data, question=msg)
    elif intent == 'general':
        prompt = GENERAL_PROMPT.format(question=msg)
    elif intent == 'attendance':
        prompt = ATTENDANCE_PROMPT.format(
            student_id=sid, attendance_data=data, question=msg)
    elif intent in ('results', 'exams'):
        prompt = RESULTS_PROMPT.format(
            student_id=sid, results_data=data, question=msg)
    elif intent == 'gpa':
        prompt = GPA_PROMPT.format(
            student_id=sid, gpa_data=data, question=msg)
    elif intent == 'fees':
        logger.info("[FEES DEBUG] Raw fee data: %s", data)
        logger.info(
            "[FEES DEBUG] Data type: %s, Length: %s",
            type(data),
            len(str(data)) if data is not None else 0,
        )
        prompt = FEES_PROMPT.format(
            student_id=sid, fee_data=data, question=msg)
    elif intent.startswith('admin_') and 'fee' in intent:
        logger.info("[FEES DEBUG] Raw admin fee data: %s", data)
        logger.info(
            "[FEES DEBUG] Data type: %s, Length: %s",
            type(data),
            len(str(data)) if data is not None else 0,
        )
        prompt = ADMIN_PROMPT.format(admin_data=data, question=msg)
    elif intent in ('courses', 'timetable', 'assignments'):
        prompt = COURSE_PROMPT.format(
            student_id=sid, course_data=data, question=msg)
    elif intent.startswith('admin_') or intent == 'department_stats':
        prompt = ADMIN_PROMPT.format(admin_data=data, question=msg)
    elif intent.startswith('faculty_') or intent in ('at_risk_students', 'peers_gpa'):
        prompt = FACULTY_PROMPT.format(faculty_data=data, question=msg)
    else:
        prompt = f'Data: {data}\nQuestion: {msg}'

    # Pass user_context so student-scoped system prompt is applied
    ctx_for_history = user_context
    return await generate_chat_response(
        sid, prompt, user_context=ctx_for_history, history_user_message=msg,
    )


async def generate_contextual_response_stream(
    sid: str,
    msg: str,
    data: str,
    intent: str,
    user_context: Optional[dict] = None,
) -> AsyncIterator[str]:
    """Stream a contextual response using live ERP or policy data."""
    t0 = time.perf_counter()
    if data and is_access_denied_payload(data):
        yield get_rbac_chain_denial_message()
        return

    profile_data = (
        format_user_context_for_prompt(user_context or {})
        if intent in PROFILE_INTENTS
        else ""
    )

    if user_context:
        role = user_context.get("role", "Student")
        uid = user_context.get("user_id", sid)
        if normalize_role(role) == "student":
            if is_cross_student_at_risk_query(msg) or is_peers_gpa_query(msg):
                yield get_rbac_chain_denial_message()
                return
            scope_ok, scope_denial = check_student_data_scope(intent, msg, uid)
            if not scope_ok:
                yield scope_denial or get_rbac_chain_denial_message()
                return

    role = (user_context or {}).get("role", "Student")
    resolved_intent = resolve_role_intent(role, intent, msg)
    log_fee_routing(
        "generate_contextual_response_stream",
        message=msg,
        role=role,
        detected_intent=intent,
        resolved_intent=resolved_intent,
        handler=(
            "ADMIN_PROMPT/FEES_PROMPT"
            if is_fee_erp_intent(intent, role, msg)
            else ("POLICY_PROMPT" if intent == "policy" else "contextual_prompt")
        ),
    )

    use_policy = (
        intent == "policy"
        or is_policy_or_rules_question(msg)
        or (intent == "exams" and should_use_rag_for_exams(role, msg))
    )
    if intent in ("at_risk_students", "peers_gpa", "faculty_at_risk", "admin_at_risk"):
        use_policy = False
    if is_fee_erp_intent(intent, role, msg):
        use_policy = False
    if is_erp_error_response(data) and not use_policy:
        if is_cross_student_at_risk_query(msg) or is_peers_gpa_query(msg):
            yield get_rbac_chain_denial_message()
            return
    if is_erp_error_response(data) and use_policy and not is_fee_erp_intent(intent, role, msg):
        data = await query_policy_documents_async(msg)
        use_policy = True

    if not use_policy and data and isinstance(data, str):
        try:
            import json as _json
            if data.strip().startswith(("{", "[")):
                parsed = _json.loads(data)
                data = _json.dumps(trim_erp_payload_for_llm(parsed, intent, msg))
        except (ValueError, TypeError):
            pass

    if intent == "ai_identity":
        async for chunk in _generate_ai_identity_response_stream(sid, msg):
            yield chunk
        logger.info(
            "Chain generate_contextual_response_stream intent=%s → %.2fs",
            intent,
            time.perf_counter() - t0,
        )
        return
    if intent == "greeting":
        async for chunk in _generate_greeting_response_stream(sid, msg):
            yield chunk
        return
    if use_policy:
        prompt = POLICY_PROMPT.format(policy_data=data, question=msg)
    elif intent in PROFILE_INTENTS:
        prompt = PROFILE_PROMPT.format(profile_data=profile_data, question=msg)
    elif intent == "general":
        prompt = GENERAL_PROMPT.format(question=msg)
    elif intent == "attendance":
        prompt = ATTENDANCE_PROMPT.format(
            student_id=sid, attendance_data=data, question=msg
        )
    elif intent in ("results", "exams"):
        prompt = RESULTS_PROMPT.format(
            student_id=sid, results_data=data, question=msg
        )
    elif intent == "gpa":
        prompt = GPA_PROMPT.format(student_id=sid, gpa_data=data, question=msg)
    elif intent == "fees":
        logger.info("[FEES DEBUG] Raw fee data: %s", data)
        logger.info(
            "[FEES DEBUG] Data type: %s, Length: %s",
            type(data),
            len(str(data)) if data is not None else 0,
        )
        prompt = FEES_PROMPT.format(student_id=sid, fee_data=data, question=msg)
    elif intent.startswith("admin_") and "fee" in intent:
        logger.info("[FEES DEBUG] Raw admin fee data: %s", data)
        logger.info(
            "[FEES DEBUG] Data type: %s, Length: %s",
            type(data),
            len(str(data)) if data is not None else 0,
        )
        prompt = ADMIN_PROMPT.format(admin_data=data, question=msg)
    elif intent in ("courses", "timetable", "assignments"):
        prompt = COURSE_PROMPT.format(
            student_id=sid, course_data=data, question=msg
        )
    elif intent.startswith("admin_") or intent == "department_stats":
        prompt = ADMIN_PROMPT.format(admin_data=data, question=msg)
    elif intent.startswith("faculty_") or intent in (
        "at_risk_students",
        "peers_gpa",
    ):
        prompt = FACULTY_PROMPT.format(faculty_data=data, question=msg)
    else:
        prompt = f"Data: {data}\nQuestion: {msg}"

    ctx_for_history = user_context
    async for chunk in generate_chat_response_stream(
        sid, prompt, user_context=ctx_for_history, history_user_message=msg
    ):
        yield chunk
    logger.info(
        "Chain generate_contextual_response_stream intent=%s → %.2fs",
        intent,
        time.perf_counter() - t0,
    )


ACCESS_DENIED_RESPONSE = (
    "I'm sorry, but I don't have permission to share that information with your account. "
    "Please contact your department administrator if you need assistance."
)


async def generate_access_denied_response(
    session_id: str,
    role: str = "Student",
    intent: str = "",
) -> str:
    from app.auth.chat_rbac import get_denial_message
    return get_denial_message(role, intent)


# Wire role-aware ERP fetch with RAG fallback into erp_handlers (used by main.py).
import app.chains.erp_handlers as _erp_handlers_module
from app.services.erp_connector import fetch_erp_data as _connector_fetch_erp_data

install_fetch_erp_data_patch(_erp_handlers_module.fetch_erp_data)
_erp_handlers_module.fetch_erp_data = _connector_fetch_erp_data