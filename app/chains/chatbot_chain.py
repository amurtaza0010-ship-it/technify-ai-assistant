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
    TAIA_FACULTY_SYSTEM,
    TAIA_ADMIN_SYSTEM,
    _estimate_tokens,
    ainvoke_llm_with_fallback,
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

ADMIN_AT_RISK_PROMPT = """University at-risk student data is provided below.
The list of students lives inside "summary" → "at_risk_students".

Data:
{admin_data}

Question: {question}

Instructions:
- State the total count from "summary.total_at_risk", then list every student as a \
numbered entry: name, course, reason (write "Reason not specified" if blank), \
attendance% and GPA where present.
- Never say "no information" or "no data" when student records are present.

Response:"""

ADMIN_FINANCE_PENDING_PROMPT = """Pending fee records are provided below.
The list lives inside "summary" → "pending_fees".

Data:
{admin_data}

Question: {question}

Instructions:
- State the total from "summary.total_pending", then list every entry as a numbered row: \
student name, amount due, due date.
- Never say "no information" or "no data" when records are present.

Response:"""

FACULTY_PROMPT = """Based on the following faculty data, answer the question clearly and accurately.
Faculty Data:
{faculty_data}

Question: {question}

Response:"""

FACULTY_TEACHING_PROMPT = """The following JSON lists the courses taught by this faculty member.
Look inside "courses" for the list (each entry has course_id, course_name, instructor).

Faculty Data:
{faculty_data}

Question: {question}

Instructions:
- Answer directly, e.g. "You teach the following course(s): <course_id> <course_name>, ...".
- List every course in the "courses" array — do not omit any.
- If "courses" is empty, say "You are not currently assigned to teach any courses."
- Never say "you can only access data related to your courses and students" — that phrase \
does not apply to this question.

Response:"""

ASSIGNMENTS_PROMPT = """Based on the following assignment data for student {student_id}, \
answer their question clearly.

Assignment Data:
{course_data}

Question: {question}

Instructions:
- List every assignment in the data as a numbered entry: course, assignment name, status, \
due date (if present).
- If the question asks about "pending" assignments, only mention entries with status \
"Pending". If none are present in the data, say "You have no pending assignments."
- Never invent assignments that are not present in the data.

Response:"""

STUDENT_INSTRUCTORS_PROMPT = """Based on the following enrolled-course and instructor data for student \
{student_id}, answer their question clearly.

Instructor Data:
{instructor_data}

Question: {question}

Instructions:
- The "courses" list is the student's complete enrolled course list — the same data shown for \
"Show my registered courses". Only use courses from this list.
- When asked "who teaches me?" (or similar), list every course with its instructor as a \
numbered entry: course name, instructor name.
- When asked about a specific course (e.g. "who teaches me English?"), match the requested name \
case-insensitively with partial match (e.g. "English" matches "English I"). If found, give the \
instructor. If not found in this list, say "You are not enrolled in a course called <name>."
- Never list courses or instructors that are not in the provided data.

Response:"""

FACULTY_AT_RISK_PROMPT = """The following JSON contains at-risk student data for a faculty member.
Look inside "summary" → "top_at_risk_students" for the list of students.

Faculty Data:
{faculty_data}

Question: {question}

Instructions:
- List EVERY student in "top_at_risk_students" as a numbered entry: name, course, reason \
(or "Reason not specified" if blank), GPA / avg% if present.
- State the total from "summary.total_at_risk" at the top.
- Never say "there is no information" when student records are present.
- End with a one-line total count.

Response:"""

FACULTY_ATTENDANCE_PROMPT = """The following JSON contains low-attendance data for a faculty member.
Look inside "summary" → "top_low_attendance_students" for the list of students.

Faculty Data:
{faculty_data}

Question: {question}

Instructions:
- List EVERY student in "top_low_attendance_students" as a numbered entry: name, course, \
attendance% (required), and "Low attendance" as the reason.
- If that list is empty but "global_fallback" exists, list those students instead.
- Never say "there is no information" when student records are present.
- End with a one-line total count.

Response:"""

FACULTY_UNGRADED_PROMPT = """The following JSON contains ungraded-assignment data for a faculty member.
Look inside "summary" → "top_ungraded_assignments" for the list.

Faculty Data:
{faculty_data}

Question: {question}

Instructions:
- List EVERY entry in "top_ungraded_assignments" as a numbered item: student name, \
assignment name, course, due date (if present), status.
- Never say "there is no information" when assignment records are present.
- End with total_ungraded count.

Response:"""

GRADE_CALCULATION_PROMPT = """You have the student's current grades and the university's grading policy.
Calculate the required marks and explain your reasoning.

Student Results:
{results_data}

Grading Policy:
{policy_data}

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

MAX_PROMPT_TOKENS = 5000
_RAG_DOC_TRUNCATE_CHARS = 1500

STUDENT_INTENTS = [
    'attendance', 'results', 'gpa', 'courses', 'timetable', 'fees',
    'assignments', 'exams', 'study_plan', 'student_instructors',
    'student_current_semester', 'student_grade_calculation',
    'policy', 'profile', 'name',
    'ai_identity', 'greeting', 'general',
]

FACULTY_INTENTS = [
    'faculty_attendance', 'faculty_ungraded', 'faculty_at_risk',
    'faculty_courses', 'faculty_performance', 'faculty_teaching',
    'faculty_course_low_attendance', 'faculty_course_top_marks',
    'faculty_missed_midterm', 'faculty_course_average_grade',
    'department_stats',
    'policy', 'profile', 'name',
    'ai_identity', 'greeting', 'general',
]

ADMIN_INTENTS = [
    'admin_students', 'admin_admissions', 'admin_fees', 'admin_departments',
    'department_stats', 'admin_at_risk', 'admin_overall', 'admin_finance_department',
    'admin_finance_pending', 'admin_finance_scholarship', 'admin_finance_summary',
    'admin_teacher_salary', 'admin_late_fees',
    'policy', 'profile', 'name', 'ai_identity', 'greeting', 'general',
]

FINANCE_OFFICER_INTENTS = [
    'admin_fees', 'admin_finance_department', 'admin_finance_pending',
    'admin_finance_scholarship', 'admin_finance_summary',
    'admin_teacher_salary', 'admin_late_fees',
    'policy', 'profile', 'name', 'ai_identity', 'greeting', 'general',
]

EXAM_OFFICER_INTENTS = [
    'exams', 'faculty_performance', 'admin_at_risk', 'faculty_at_risk',
    'at_risk_students', 'faculty_ungraded',
    'policy', 'profile', 'name', 'ai_identity', 'greeting', 'general',
]

PROFILE_INTENTS = frozenset({'profile', 'name'})

# Faculty analytical intents that pull large ERP datasets (10 courses x many students).
# These use a condensed system prompt (TAIA_FACULTY_SYSTEM) to save tokens; every other
# intent (student, admin, etc.) keeps the full TAIA_IDENTITY_SYSTEM persona unchanged.
FACULTY_SHORT_SYSTEM_INTENTS = frozenset({
    'faculty_attendance', 'faculty_at_risk', 'faculty_ungraded', 'faculty_performance',
})

# Admin analytical intents that embed a student/fee list in the human message.
# Use TAIA_ADMIN_SYSTEM instead of the full TAIA_IDENTITY_SYSTEM to stay under TPM.
ADMIN_SHORT_SYSTEM_INTENTS = frozenset({
    'admin_at_risk', 'admin_finance_pending',
})

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

_EXTENDED_POLICY_PHRASES = (
    "re-take a midterm",
    "re-take the midterm",
    "retake a midterm",
    "medical leave",
    "fee waiver",
    "children of faculty",
    "tuition waiver",
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
    # ── FACULTY ATTENDANCE (must come before generic attendance) ──
    ("faculty_attendance", (
        r"attendance of my courses",
        r"attendance in CRS-\d+",
        r"attendance for CRS-\d+",
        r"course attendance",
        r"faculty attendance",
        r"my course attendance",
        r"attendance for my courses",
        r"how is the attendance",
        r"what is the attendance",
        r"show attendance",
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
    ("assignments", (
        r"\bmy assignments?\b",
        r"\bhomework\b",
        r"due this week",
        r"\b(what|show|list|my|pending)\s*(my\s*)?(pending\s*)?assignments\b",
        r"\bassignments\s+(are\s+)?pending\b",
        r"\bwhat\s+assignments\s+do\s+i\s+have\b",
        r"\bpending\s+(assignments|work)\b",
    )),
    ("courses", (
        r"\bmy courses?\b",
        r"registered subjects?",
        r"\benrolled\b",
        r"\bmy subjects?\b",
        r"what (are|were) (my|the) (subjects?|courses?)",
        r"what (am i|i am) (taking|studying|enrolled in)",
        r"which (subjects?|courses?) (am i|do i|i)",
    )),
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
            # "courses" is the student's own-enrollment intent; a faculty member's
            # course/subject question must go through faculty_teaching instead, or
            # this would trigger the FACULTY_RESTRICTED_INTENTS access-denied path.
            if role_norm == "faculty" and intent == "courses":
                continue
            if role_norm == "faculty" and intent.startswith("admin_"):
                continue
            return intent
    if role_norm in ("admin", "finance_officer") and re.search(r"\bfees?\b", lower):
        if not re.search(r"\bSTU-\d+\b", message, re.I):
            return resolve_role_intent(role, "fees", message)
    return None


_FACULTY_TEACHING_PATTERNS = (
    r"\b(which|what)\s+(subjects?|courses?)\s+(do\s+)?i\s+teach\b",
    r"\bmy teaching subjects?\b",
    r"\bwhat do i teach\b",
)


def _heuristic_intent(message: str, role: str = "Student") -> Optional[str]:
    """Fast path for identity, greeting, policy, and RBAC-sensitive queries."""
    lower = message.lower().strip()
    role_norm = normalize_role(role)
    if role_norm == "faculty" and any(
        re.search(p, lower) for p in _FACULTY_TEACHING_PATTERNS
    ):
        return "faculty_teaching"
    if role_norm == "student" and any(
        phrase in lower
        for phrase in (
            "who teaches me",
            "my instructors",
            "who is my teacher",
            "my teachers",
        )
    ):
        return "student_instructors"
    if "salary" in lower and ("teacher" in lower or "faculty" in lower):
        return "admin_teacher_salary"
    if "late fee" in lower and (
        "total" in lower or "collected" in lower or "amount" in lower
    ):
        return "admin_late_fees"
    if role_norm == "faculty":
        if any(
            phrase in lower
            for phrase in (
                "students with least attendance in my course",
                "low attendance in",
            )
        ):
            return "faculty_course_low_attendance"
        if any(
            phrase in lower
            for phrase in (
                "highest marks in their previous courses",
                "top students in course",
                "top marks in",
            )
        ):
            return "faculty_course_top_marks"
        if any(
            phrase in lower
            for phrase in (
                "missed the midterm exam",
                "missed exam last week",
                "missed the midterm",
            )
        ):
            return "faculty_missed_midterm"
        if "average grade for the" in lower and "course" in lower:
            return "faculty_course_average_grade"
        # Catch-all for any faculty attendance query not captured by keyword patterns
        if "attendance" in lower:
            return "faculty_attendance"
    if role_norm == "student":
        if any(
            phrase in lower
            for phrase in ("current semester", "which semester", "what semester")
        ):
            return "student_current_semester"
        if any(
            phrase in lower
            for phrase in (
                "how many marks do i need",
                "maximum grade",
                "fail the midterm",
                "get a b+",
            )
        ):
            return "student_grade_calculation"
    if role_norm in ("admin", "finance_officer") and (
        "department wise fee" in lower
        or "department-wise fee" in lower
        or "department fee stats" in lower
    ):
        return "admin_finance_department"
    if is_policy_or_rules_question(message) or any(
        phrase in lower for phrase in _EXTENDED_POLICY_PHRASES
    ):
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
    if role_norm == "student" and "registered courses" in lower:
        return "courses"
    if role_norm == "student" and any(
        phrase in lower
        for phrase in (
            "my subjects",
            "what subjects",
            "which subjects",
            "what am i studying",
            "what i am studying",
            "what courses am i",
            "which courses am i",
        )
    ):
        return "courses"
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
    intent: Optional[str] = None,
) -> str:
    """Return TAIA identity system prompt. JWT user data is never injected here.

    Faculty analytical intents (see FACULTY_SHORT_SYSTEM_INTENTS) use a condensed
    persona (TAIA_FACULTY_SYSTEM) to reduce prompt token size, since those requests
    already embed a large ERP data summary in the human message. All other intents
    are unaffected and keep the full TAIA_IDENTITY_SYSTEM text.
    """
    use_short_prompt = intent in FACULTY_SHORT_SYSTEM_INTENTS
    if intent in FACULTY_SHORT_SYSTEM_INTENTS:
        prompt = TAIA_FACULTY_SYSTEM
    elif intent in ADMIN_SHORT_SYSTEM_INTENTS:
        prompt = TAIA_ADMIN_SYSTEM
    else:
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


def _estimate_rag_prompt_tokens(
    policy_data: str,
    question: str,
    session_id: str = "",
    user_context: Optional[dict] = None,
) -> int:
    """Estimate tokens for system prompt + RAG policy prompt sent to Groq."""
    prompt = POLICY_PROMPT.format(policy_data=policy_data, question=question)
    messages = [
        SystemMessage(content=_build_system_message(session_id, user_context)),
        HumanMessage(content=prompt),
    ]
    return _estimate_tokens(messages)


def _trim_rag_policy_data(
    policy_data: str,
    question: str,
    session_id: str = "",
    user_context: Optional[dict] = None,
) -> str:
    """Trim retrieved policy documents to stay within MAX_PROMPT_TOKENS."""
    if not policy_data or not str(policy_data).strip():
        return policy_data

    original_docs = [doc for doc in str(policy_data).split("\n\n") if doc.strip()]
    if not original_docs:
        return policy_data

    original_count = len(original_docs)
    docs = list(original_docs)

    while (
        len(docs) > 1
        and _estimate_rag_prompt_tokens("\n\n".join(docs), question, session_id, user_context)
        > MAX_PROMPT_TOKENS
    ):
        docs.pop()

    trimmed = "\n\n".join(docs)
    if (
        _estimate_rag_prompt_tokens(trimmed, question, session_id, user_context)
        > MAX_PROMPT_TOKENS
    ):
        docs = [doc[:_RAG_DOC_TRUNCATE_CHARS] for doc in docs]
        trimmed = "\n\n".join(docs)
        while (
            docs
            and _estimate_rag_prompt_tokens(trimmed, question, session_id, user_context)
            > MAX_PROMPT_TOKENS
        ):
            if len(docs) == 1:
                docs[0] = docs[0][: max(200, len(docs[0]) - 300)]
            else:
                docs = [doc[: max(200, len(doc) - 300)] for doc in docs]
            trimmed = "\n\n".join(docs)

    final_count = len(docs)
    if final_count < original_count or trimmed != "\n\n".join(original_docs):
        logger.info(
            "RAG context trimmed from %s to %s documents to stay within token limit",
            original_count,
            final_count,
        )

    return trimmed


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


def _get_history(session_id: str, user_context: Optional[dict] = None, intent: Optional[str] = None):
    """
    Return (list_of_messages, redis_history_object_or_None) for a session.

    - If Redis is available: loads full conversation history from Redis.
    - If not: uses the in-memory dict as fallback.
    Always prepends the System Persona message so the LLM stays in character.
    `intent` is only used to pick a condensed system prompt for faculty analytical
    intents (see FACULTY_SHORT_SYSTEM_INTENTS); defaults to the full persona.
    """
    if _use_redis:
        history = RedisChatMessageHistory(
            session_id=f"taia:{session_id}",
            url=_get_redis_url(),
        )
        msgs = [SystemMessage(content=_build_system_message(session_id, user_context, intent))]
        msgs.extend(history.messages)
        return msgs, history

    if session_id not in _memories:
        _memories[session_id] = [SystemMessage(content=_build_system_message(session_id, user_context, intent))]
    else:
        _memories[session_id][0] = SystemMessage(content=_build_system_message(session_id, user_context, intent))
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
    intent: Optional[str] = None,
) -> str:
    """
    Send user_message to the LLM with full conversation history.
    Saves the exchange to Redis (or in-memory fallback) afterwards.
    `intent` only affects which system prompt is selected (see FACULTY_SHORT_SYSTEM_INTENTS).
    """
    t0 = time.perf_counter()
    display_message = history_user_message or user_message
    try:
        messages, redis_history = _get_history(session_id, user_context, intent)
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
    intent: Optional[str] = None,
) -> AsyncIterator[str]:
    """Stream user_message to the LLM with full conversation history.
    `intent` only affects which system prompt is selected (see FACULTY_SHORT_SYSTEM_INTENTS).
    """
    display_message = history_user_message or user_message
    messages, redis_history = _get_history(session_id, user_context, intent)
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
    Classify intent using heuristic/keyword routing only (no LLM).
    Used by main.py to decide which ERP endpoint to call before response generation.
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

    resolved = _resolve_intent_for_role("general", role, message)
    logger.info(
        "Chain classify_intent (heuristic=miss → %s) → %.2fs",
        resolved,
        time.perf_counter() - t0,
    )
    return resolved


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
        data = _trim_rag_policy_data(data, msg, sid, user_context)
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
    elif intent == 'admin_at_risk':
        prompt = ADMIN_AT_RISK_PROMPT.format(admin_data=data, question=msg)
    elif intent == 'admin_finance_pending':
        prompt = ADMIN_FINANCE_PENDING_PROMPT.format(admin_data=data, question=msg)
    elif intent == 'assignments':
        prompt = ASSIGNMENTS_PROMPT.format(
            student_id=sid, course_data=data, question=msg)
    elif intent == 'student_instructors':
        prompt = STUDENT_INSTRUCTORS_PROMPT.format(
            student_id=sid, instructor_data=data, question=msg)
    elif intent in ('courses', 'timetable'):
        prompt = COURSE_PROMPT.format(
            student_id=sid, course_data=data, question=msg)
    elif intent.startswith('admin_') or intent == 'department_stats':
        prompt = ADMIN_PROMPT.format(admin_data=data, question=msg)
    elif intent == 'faculty_at_risk':
        prompt = FACULTY_AT_RISK_PROMPT.format(faculty_data=data, question=msg)
    elif intent == 'faculty_attendance':
        prompt = FACULTY_ATTENDANCE_PROMPT.format(faculty_data=data, question=msg)
    elif intent == 'faculty_ungraded':
        prompt = FACULTY_UNGRADED_PROMPT.format(faculty_data=data, question=msg)
    elif intent == 'faculty_teaching':
        prompt = FACULTY_TEACHING_PROMPT.format(faculty_data=data, question=msg)
    elif intent.startswith('faculty_') or intent in ('at_risk_students', 'peers_gpa'):
        prompt = FACULTY_PROMPT.format(faculty_data=data, question=msg)
    else:
        prompt = f'Data: {data}\nQuestion: {msg}'

    # Pass user_context so student-scoped system prompt is applied
    ctx_for_history = user_context
    return await generate_chat_response(
        sid, prompt, user_context=ctx_for_history, history_user_message=msg, intent=intent,
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
        data = _trim_rag_policy_data(data, msg, sid, user_context)
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
    elif intent == "admin_at_risk":
        prompt = ADMIN_AT_RISK_PROMPT.format(admin_data=data, question=msg)
    elif intent == "admin_finance_pending":
        prompt = ADMIN_FINANCE_PENDING_PROMPT.format(admin_data=data, question=msg)
    elif intent == "assignments":
        prompt = ASSIGNMENTS_PROMPT.format(
            student_id=sid, course_data=data, question=msg
        )
    elif intent == "student_instructors":
        prompt = STUDENT_INSTRUCTORS_PROMPT.format(
            student_id=sid, instructor_data=data, question=msg
        )
    elif intent in ("courses", "timetable"):
        prompt = COURSE_PROMPT.format(
            student_id=sid, course_data=data, question=msg
        )
    elif intent.startswith("admin_") or intent == "department_stats":
        prompt = ADMIN_PROMPT.format(admin_data=data, question=msg)
    elif intent == "faculty_at_risk":
        prompt = FACULTY_AT_RISK_PROMPT.format(faculty_data=data, question=msg)
    elif intent == "faculty_attendance":
        prompt = FACULTY_ATTENDANCE_PROMPT.format(faculty_data=data, question=msg)
    elif intent == "faculty_ungraded":
        prompt = FACULTY_UNGRADED_PROMPT.format(faculty_data=data, question=msg)
    elif intent == "faculty_teaching":
        prompt = FACULTY_TEACHING_PROMPT.format(faculty_data=data, question=msg)
    elif intent.startswith("faculty_") or intent in (
        "at_risk_students",
        "peers_gpa",
    ):
        prompt = FACULTY_PROMPT.format(faculty_data=data, question=msg)
    elif intent == "student_grade_calculation":
        policy_data = await query_policy_documents_async(msg)
        policy_data = _trim_rag_policy_data(policy_data, msg, sid, user_context)
        prompt = GRADE_CALCULATION_PROMPT.format(
            results_data=data,
            policy_data=policy_data,
            question=msg,
        )
    else:
        prompt = f"Data: {data}\nQuestion: {msg}"

    ctx_for_history = user_context
    async for chunk in generate_chat_response_stream(
        sid, prompt, user_context=ctx_for_history, history_user_message=msg, intent=intent
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