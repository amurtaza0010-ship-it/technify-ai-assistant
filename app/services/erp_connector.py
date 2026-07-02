"""ERP Connector — calls the ERP (mock or real) REST APIs using httpx."""
import asyncio
import json
import logging
import re
import time
from typing import Callable, Optional, Tuple

import httpx
from app.config import get_settings
from app.utils.fees_intent import (
    FEE_ERP_INTENTS,
    is_fee_erp_intent,
    is_finance_department_fee_query,
    log_fee_routing,
)
from app.utils.intent_routing import is_exam_schedule_query, resolve_role_intent

logger = logging.getLogger("taia.erp_connector")

settings = get_settings()
BASE = settings.ERP_API_BASE_URL
if not BASE.endswith("/api/v1") and not BASE.endswith("/api/v1/"):
    BASE = BASE.rstrip("/") + "/api/v1"

# ── RBAC endpoint categories ──

STUDENT_ONLY_ENDPOINTS = frozenset({
    "student_only",
})

FACULTY_ONLY_ENDPOINTS = frozenset({
    "faculty_only",
})

ADMIN_ONLY_ENDPOINTS = frozenset({
    "admin_only",
})

INTENT_TO_ENDPOINT_TYPE: dict[str, str] = {
    # student_only
    "gpa": "student_only",
    "attendance": "student_only",
    "fees": "student_only",
    "timetable": "student_only",
    "exams": "student_only",
    "assignments": "student_only",
    "courses": "student_only",
    "results": "student_only",
    "study_plan": "student_only",
    # faculty_only
    "faculty_attendance": "faculty_only",
    "faculty_at_risk": "faculty_only",
    "at_risk_students": "faculty_only",
    "peers_gpa": "faculty_only",
    "faculty_ungraded": "faculty_only",
    "faculty_performance": "faculty_only",
    "faculty_courses": "faculty_only",
    "course_performance": "faculty_only",
    "ungraded_assignments": "faculty_only",
    # admin_only
    "admin_fees": "admin_only",
    "admin_finance_summary": "admin_only",
    "admin_finance_pending": "admin_only",
    "admin_finance_scholarship": "admin_only",
    "admin_finance_department": "admin_only",
    "global_fee_stats": "admin_only",
    "pending_fees_list": "admin_only",
    "scholarship_stats": "admin_only",
    "global_finance": "admin_only",
    "admin_students": "admin_only",
    "admin_admissions": "admin_only",
    "admin_departments": "admin_only",
    "department_stats": "faculty_only",
    "admin_at_risk": "faculty_only",
    "admin_overall": "admin_only",
}

_CROSS_STUDENT_AT_RISK_PATTERNS = (
    r"\bwhich students?\b",
    r"\bstudents? (are )?(in danger|at risk|failing|in trouble)\b",
    r"\bwhich students? (are )?(in danger|at risk|failing)\b",
    r"\bwho (has|have) low attendance\b",
    r"\blist (of )?students?\b",
    r"\bhow many students?\b",
    r"\bstudents? with\b",
    r"\bat[- ]risk students?\b",
    r"\bfailing students?\b",
    r"\bin danger\b",
)

_PEERS_GPA_PATTERNS = (
    r"\bother students?('?s?)? gpa\b",
    r"\bother students?('?s?)? grades?\b",
    r"\btell me other students\b",
    r"\bpeers? gpa\b",
    r"\bstudents? gpa\b",
    r"\bstudents? grades?\b",
    r"\bother students? marks\b",
)

_DEPARTMENT_STATS_PATTERNS = (
    r"department[- ]?wise",
    r"department[- ]?wise students?",
    r"students? department[- ]?wise",
    r"students? (per|by|across|in each|in) department",
    r"department[- ]?wise stats?",
    r"department statistics",
    r"department[- ]?wise student count",
    r"student count (by|per|across) department",
    r"stats? (per|by|across) department",
    r"how many students? (per|in|by|across) department",
    r"enrollment by department",
    r"department[- ]?wise enrollment",
    r"show department[- ]?wise",
    r"department stats?",
    r"department list",
    r"list of departments?",
    r"other students? in (dept|department)s?",
    r"tell me about students? department",
    r"about students? department",
    r"students? in (each )?departments?",
    r"breakdown (by|per) department",
)

_DEPARTMENT_STATS_PHRASES = (
    "department wise students",
    "students department wise",
    "department list",
    "other students in dept",
    "other students in department",
    "students departmentwise",
)

RBAC_ACCESS_DENIED_MESSAGE = (
    "You do not have permission to view this data. "
    "This feature is restricted to faculty and admin users."
)

RBAC_CHAIN_USER_MESSAGE = (
    "I apologize, I cannot provide that information because it involves "
    "other students' academic data, which is restricted to faculty members."
)

async def _get(path: str) -> dict:
    url = f"{BASE.rstrip('/')}{path}"
    t0 = time.perf_counter()
    status = "error"
    try:
        client = _get_erp_client()
        r = await client.get(url)
        r.raise_for_status()
        status = str(r.status_code)
        return r.json()
    except Exception:
        raise
    finally:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("ERP API GET %s → %.0fms (status=%s)", path, elapsed_ms, status)


_erp_client: httpx.AsyncClient | None = None


def _get_erp_client() -> httpx.AsyncClient:
    global _erp_client
    if _erp_client is None:
        _erp_client = httpx.AsyncClient(timeout=60.0)
    return _erp_client


# ── Policy / RAG routing ──

_POLICY_QUESTION_PATTERNS = (
    r"examination\s+rules?",
    r"exam\s+rules?",
    r"rules?\s+for\s+exams?",
    r"what\s+are\s+the\s+.*rules?",
    r"university\s+polic",
    r"academic\s+integrit",
    r"late\s+submission",
    r"leave\s+polic",
    r"regulations?",
    r"exam\s+conduct",
    r"cheating\s+polic",
    r"grading\s+polic",
)

RAG_POLICY_ROLES = frozenset({"admin", "faculty", "exam_officer"})

_ORIGINAL_FETCH_ERP_DATA: Optional[Callable] = None


def normalize_role(role: str) -> str:
    r = role.lower().strip().replace(" ", "_")
    if r == "finance":
        return "finance_officer"
    return r


def is_cross_student_at_risk_query(message: str) -> bool:
    from app.utils.fees_intent import is_pending_fee_query

    if is_pending_fee_query(message):
        return False

    lower = message.lower().strip()
    if any(re.search(p, lower) for p in _CROSS_STUDENT_AT_RISK_PATTERNS):
        if re.search(r"\bmy\b", lower) and not re.search(r"\b(which|other|all|how many) students?\b", lower):
            return False
        return True
    return False


def is_peers_gpa_query(message: str) -> bool:
    lower = message.lower().strip()
    if re.search(r"\bmy\b", lower) and "other" not in lower:
        return False
    return any(re.search(p, lower) for p in _PEERS_GPA_PATTERNS)


def is_department_stats_query(message: str) -> bool:
    """Detect university-wide department student/statistics queries (not own profile)."""
    if is_finance_department_fee_query(message):
        return False
    lower = message.lower().strip()
    if any(phrase in lower for phrase in _DEPARTMENT_STATS_PHRASES):
        return True
    if re.search(r"\bmy department\b", lower) and not re.search(
        r"\b(wise|stats?|statistics|count|students? per|by department|department wise)\b",
        lower,
    ):
        return False
    if re.search(r"\bmy\b", lower) and re.search(r"\bdepartment\b", lower):
        if not re.search(
            r"\b(wise|stats?|statistics|per department|by department|across department|department wise|students? department)\b",
            lower,
        ):
            return False
    if re.search(r"\bstudents?\b", lower) and re.search(r"\bdepartment\b", lower):
        if re.search(r"\b(wise|list|stats?|statistics|per|by|across|count)\b", lower):
            return True
    return any(re.search(p, lower) for p in _DEPARTMENT_STATS_PATTERNS)


def intent_to_endpoint_type(intent: str, message: str = "") -> Optional[str]:
    """Map intent (and message heuristics) to an RBAC endpoint category."""
    intent_lower = (intent or "").lower().strip()
    # Pending-fee lists are admin/finance data — not faculty-only academic queries.
    if intent_lower == "admin_finance_pending":
        return INTENT_TO_ENDPOINT_TYPE.get(intent_lower)
    if is_department_stats_query(message):
        return "faculty_only"
    if is_cross_student_at_risk_query(message):
        return "faculty_only"
    if is_peers_gpa_query(message):
        return "faculty_only"
    return INTENT_TO_ENDPOINT_TYPE.get(intent_lower)


def is_role_allowed_for_endpoint(
    user_role: str, endpoint_type: str, intent: str = "", message: str = ""
) -> bool:
    """
    Return True if user_role may access endpoint_type.

    student_only  → students only (+ exam_officer for university exam schedules)
    faculty_only  → faculty, admin, exam_officer
    admin_only    → admin, finance_officer
    """
    role = normalize_role(user_role)

    if role == "admin":
        return True

    if (
        intent == "exams"
        and role == "exam_officer"
        and is_exam_schedule_query(message)
    ):
        return True

    if endpoint_type == "student_only":
        return role == "student"

    if endpoint_type == "faculty_only":
        return role in ("faculty", "exam_officer")

    if endpoint_type == "admin_only":
        return role == "finance_officer"

    return True


def build_access_denied_response() -> dict:
    return {"error": "access_denied", "message": RBAC_ACCESS_DENIED_MESSAGE}


def is_access_denied_payload(data: str) -> bool:
    if not data or not isinstance(data, str):
        return False
    try:
        parsed = json.loads(data)
        return isinstance(parsed, dict) and parsed.get("error") == "access_denied"
    except (json.JSONDecodeError, TypeError):
        return False


def get_rbac_chain_denial_message() -> str:
    return RBAC_CHAIN_USER_MESSAGE


def guard_erp_endpoint_access(role: str, intent: str, message: str) -> Optional[dict]:
    """Return access_denied dict if role may not call this endpoint; else None."""
    endpoint_type = intent_to_endpoint_type(intent, message)
    if endpoint_type is None:
        return None
    if not is_role_allowed_for_endpoint(role, endpoint_type, intent, message):
        msg = (
            RBAC_CHAIN_USER_MESSAGE
            if normalize_role(role) == "student"
            else RBAC_ACCESS_DENIED_MESSAGE
        )
        return {"error": "access_denied", "message": msg}
    return None


def map_intent_for_erp_fetch(intent: str, role: str = "", message: str = "") -> str:
    """Map RBAC / heuristic intents to ERP handler intent names."""
    intent = resolve_role_intent(role, intent, message)
    role_norm = normalize_role(role)
    if intent == "at_risk_students":
        if role_norm in ("admin", "exam_officer"):
            return "admin_at_risk"
        return "faculty_at_risk"
    mapping = {
        "peers_gpa": "faculty_performance",
        "course_performance": "faculty_performance",
        "ungraded_assignments": "faculty_ungraded",
    }
    return mapping.get(intent, intent)

def is_valid_student_id(user_id: str) -> bool:
    """Only STU-* IDs may be used for student ERP endpoints."""
    return bool(user_id) and user_id.upper().startswith("STU-")


def is_policy_or_rules_question(message: str) -> bool:
    """Detect questions about university rules/policies (not personal exam schedules)."""
    lower = message.lower().strip()
    if any(re.search(p, lower) for p in _POLICY_QUESTION_PATTERNS):
        return True
    if re.search(r"\brules?\b", lower) and re.search(r"\b(exam|examination|university|academic)\b", lower):
        return True
    return False


def should_use_rag_for_exams(role: str, message: str) -> bool:
    """Non-students and rule/policy questions must use RAG, not student ERP APIs."""
    if is_policy_or_rules_question(message):
        return True
    role_norm = normalize_role(role)
    if role_norm == "exam_officer":
        return not is_exam_schedule_query(message)
    return role_norm in RAG_POLICY_ROLES


def is_erp_not_found_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
        return True
    message = str(exc).lower()
    return "404" in message or "not found" in message


def is_erp_error_response(data: str) -> bool:
    """True only for explicit ERP error strings — not JSON payloads containing '404' in amounts."""
    if not data or not isinstance(data, str):
        return False
    stripped = data.strip()
    lower = stripped.lower()
    if lower.startswith("error:"):
        return True
    if lower.startswith("client error") or lower.startswith("server error"):
        return True
    if "httpstatuserror" in lower:
        return True
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict) and parsed.get("error"):
                return True
        except (json.JSONDecodeError, TypeError):
            pass
        return False
    return "not found for url" in lower or "not found" in lower and "student" in lower


def query_policy_documents(query: str) -> str:
    """Query the RAG vector store for university policy documents (sync)."""
    from app.services.knowledge_base import query_knowledge_base

    result = query_knowledge_base(query)
    if result == "Knowledge base not initialized.":
        return (
            "University examination rules: students need 75% attendance to sit finals, "
            "must carry ID, and electronic devices are prohibited during exams. "
            "See examination_rules.md for full details."
        )
    return result


async def query_policy_documents_async(query: str) -> str:
    """Run RAG retrieval off the event loop."""
    t0 = time.perf_counter()
    result = await asyncio.to_thread(query_policy_documents, query)
    logger.info("RAG policy query → %.0fms", (time.perf_counter() - t0) * 1000)
    return result


def install_fetch_erp_data_patch(original_fetch: Callable) -> None:
    """Preserve the original erp_handlers.fetch_erp_data for delegation."""
    global _ORIGINAL_FETCH_ERP_DATA
    _ORIGINAL_FETCH_ERP_DATA = original_fetch

# ── Student APIs ──
async def get_student_profile(student_id: str) -> dict:
    return await _get(f"/student/{student_id}")

async def get_student_attendance(student_id: str) -> dict:
    return await _get(f"/student/{student_id}/attendance")

async def get_student_results(student_id: str) -> dict:
    return await _get(f"/student/{student_id}/results")

async def get_student_gpa(student_id: str) -> dict:
    return await _get(f"/student/{student_id}/gpa")

async def get_student_courses(student_id: str) -> dict:
    return await _get(f"/student/{student_id}/courses")

async def get_student_timetable(student_id: str) -> dict:
    return await _get(f"/student/{student_id}/timetable")

async def get_student_assignments(student_id: str) -> dict:
    return await _get(f"/student/{student_id}/assignments")

async def get_student_fees(student_id: str) -> dict:
    return await _get(f"/student/{student_id}/fees")


async def get_student_upcoming_exams(student_id: str) -> dict:
    if not is_valid_student_id(student_id):
        raise ValueError(
            f"Refusing ERP exams lookup for non-student ID: {student_id}"
        )
    return await _get(f"/student/{student_id}/exams/upcoming")

# ── Faculty APIs ──
async def get_faculty_courses(faculty_id: str) -> dict:
    return await _get(f"/faculty/{faculty_id}/courses")

async def get_course_attendance(faculty_id: str, course_id: str) -> dict:
    return await _get(f"/faculty/{faculty_id}/course/{course_id}/attendance")

async def get_faculty_assignments(faculty_id: str) -> dict:
    return await _get(f"/faculty/{faculty_id}/assignments")

async def get_course_students(faculty_id: str, course_id: str) -> dict:
    return await _get(f"/faculty/{faculty_id}/course/{course_id}/students")

async def get_all_faculty_attendance(faculty_id: str) -> dict:
    courses_data = await get_faculty_courses(faculty_id)
    courses = courses_data.get("courses", [])
    if not courses:
        return {"faculty_id": faculty_id, "attendance_by_course": []}
    attendance_results = await asyncio.gather(
        *[get_course_attendance(faculty_id, c["course_code"]) for c in courses]
    )
    all_attendance = []
    for course, att in zip(courses, attendance_results):
        att["course_name"] = course["course_name"]
        all_attendance.append(att)
    return {"faculty_id": faculty_id, "attendance_by_course": all_attendance}

async def get_all_faculty_at_risk(faculty_id: str) -> dict:
    courses_data = await get_faculty_courses(faculty_id)
    courses = courses_data.get("courses", [])
    if not courses:
        return {"faculty_id": faculty_id, "at_risk_by_course": []}
    risk_results = await asyncio.gather(
        *[get_course_students(faculty_id, c["course_code"]) for c in courses]
    )
    all_at_risk = []
    for course, risk in zip(courses, risk_results):
        risk["course_name"] = course["course_name"]
        all_at_risk.append(risk)
    return {"faculty_id": faculty_id, "at_risk_by_course": all_at_risk}

# ── Admin APIs ──
async def get_admin_student_stats() -> dict:
    return await _get("/admin/statistics/students")

async def get_admin_admission_stats() -> dict:
    return await _get("/admin/statistics/admissions")

async def get_admin_fee_stats() -> dict:
    return await _get("/admin/statistics/fees")

async def get_admin_upcoming_exams() -> dict:
    return await _get("/admin/exams/upcoming")


async def get_admin_department_stats() -> dict:
    return await _get("/admin/statistics/departments")


def build_session_user_context(user_data: dict) -> dict:
    """Build identity context from the authenticated JWT/login session."""
    return {
        "user_id": user_data.get("user_id", ""),
        "name": user_data.get("name", ""),
        "role": user_data.get("role", ""),
        "department": user_data.get("department", ""),
        "email": user_data.get("email", ""),
        "source": "jwt_session",
    }


def format_user_context_for_prompt(user_data: dict) -> str:
    """Format JWT session identity for LLM prompts (general/profile/name intents)."""
    import json
    context = build_session_user_context(user_data)
    return json.dumps(context)


async def get_session_user_profile(user_data: dict) -> dict:
    """Return the logged-in user's identity from the JWT session (not synthetic ERP lookup)."""
    return build_session_user_context(user_data)


async def fetch_erp_data(
    intent: str, uid: str, role: str, message: str
) -> Tuple[str, bool]:
    """
    Fetch ERP data with role-aware routing for exams/rules and RAG fallback on 404.
    Delegates all other intents to the original erp_handlers implementation.
    """
    t0 = time.perf_counter()
    intent_lower = intent.lower().strip()

    denied = guard_erp_endpoint_access(role, intent_lower, message)
    if denied is not None:
        return json.dumps(denied), False

    if intent_lower in ("policy", "rules", "examination") or is_policy_or_rules_question(message):
        return await query_policy_documents_async(message), False

    if intent_lower == "exams":
        role_norm = normalize_role(role)
        if role_norm == "exam_officer" and is_exam_schedule_query(message):
            try:
                data = await get_admin_upcoming_exams()
                return json.dumps(data), False
            except Exception as exc:
                if is_erp_not_found_error(exc):
                    return await query_policy_documents_async(message), False
                return f"Error: {exc}", False

        if should_use_rag_for_exams(role, message):
            return await query_policy_documents_async(message), False

        role_norm = normalize_role(role)
        if role_norm != "student":
            return await query_policy_documents_async(message), False

        if not is_valid_student_id(uid):
            return await query_policy_documents_async(message), False

        try:
            data = await get_student_upcoming_exams(uid)
            return json.dumps(data), False
        except Exception as exc:
            if is_erp_not_found_error(exc):
                return await query_policy_documents_async(message), False
            return f"Error: {exc}", False

    erp_intent = map_intent_for_erp_fetch(intent_lower, role, message)
    fee_query = is_fee_erp_intent(intent_lower, role, message)
    handler = (
        f"erp_handlers.fetch_erp_data({erp_intent})"
        if fee_query or erp_intent not in ("policy", "rules", "examination")
        else "query_policy_documents"
    )
    log_fee_routing(
        "fetch_erp_data",
        message=message,
        role=role,
        detected_intent=intent_lower,
        resolved_intent=erp_intent,
        handler=handler,
    )

    if _ORIGINAL_FETCH_ERP_DATA is not None:
        try:
            data, access_denied = await _ORIGINAL_FETCH_ERP_DATA(
                erp_intent, uid, role, message
            )
            if access_denied or is_access_denied_payload(data):
                return json.dumps(build_access_denied_response()), False
            if (
                is_erp_error_response(data)
                and not fee_query
                and erp_intent not in FEE_ERP_INTENTS
                and (
                    is_policy_or_rules_question(message)
                    or intent_lower in ("exams", "examination", "rules", "policy")
                    or normalize_role(role) in RAG_POLICY_ROLES
                )
            ):
                # Do not RAG-fallback for faculty-only cross-student queries
                if intent_to_endpoint_type(intent_lower, message) == "faculty_only":
                    return json.dumps(build_access_denied_response()), False
                return await query_policy_documents_async(message), False
            return data, False
        except Exception as exc:
            if (
                is_erp_not_found_error(exc)
                and not fee_query
                and erp_intent not in FEE_ERP_INTENTS
                and (
                    is_policy_or_rules_question(message)
                    or intent_lower in ("exams", "examination", "rules", "policy")
                    or normalize_role(role) in RAG_POLICY_ROLES
                )
            ):
                if intent_to_endpoint_type(intent_lower, message) == "faculty_only":
                    return json.dumps(build_access_denied_response()), True
                return await query_policy_documents_async(message), False
            logger.error(
                "[FEES] ERP fetch exception intent=%s erp_intent=%s: %s",
                intent_lower,
                erp_intent,
                exc,
                exc_info=True,
            )
            return f"Error: {exc}", False

    return "", False
