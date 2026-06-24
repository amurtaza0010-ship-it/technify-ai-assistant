"""
Role-Based Access Control for TAIA chat intents and ERP data fetching.

Roles: student, faculty, admin, finance_officer, exam_officer.
"""
import logging
import re
from typing import FrozenSet, Optional, Tuple

from app.services.erp_connector import (
    get_rbac_chain_denial_message,
    is_department_stats_query,
)

logger = logging.getLogger("taia.rbac")

# Intents every role may use (non-sensitive / conversational)
UNIVERSAL_INTENTS: FrozenSet[str] = frozenset({
    "policy",
    "profile",
    "name",
    "ai_identity",
    "greeting",
    "general",
})

STUDENT_OWN_DATA_INTENTS: FrozenSet[str] = frozenset({
    "attendance",
    "results",
    "gpa",
    "fees",
    "courses",
    "timetable",
    "assignments",
    "exams",
    "study_plan",
})

ROLE_PERMISSIONS: dict[str, Optional[FrozenSet[str]]] = {
    "student": STUDENT_OWN_DATA_INTENTS | UNIVERSAL_INTENTS | {"study_plan"},
    "faculty": frozenset({
        "faculty_attendance",
        "faculty_ungraded",
        "faculty_at_risk",
        "faculty_courses",
        "faculty_performance",
        "department_stats",
    }) | UNIVERSAL_INTENTS,
    "admin": None,  # None = full access
    "finance_officer": frozenset({
        "admin_fees",
        "admin_finance_summary",
        "admin_finance_pending",
        "admin_finance_scholarship",
        "admin_finance_department",
    }) | UNIVERSAL_INTENTS,
    "exam_officer": frozenset({
        "exams",
        "faculty_performance",
        "admin_at_risk",
        "faculty_at_risk",
        "at_risk_students",
        "faculty_ungraded",
        "policy",
        "ai_identity",
        "greeting",
        "general",
        "profile",
        "name",
    }),
}

BLOCK_MESSAGES = {
    "student": (
        "As a student, you can only access your own academic information. "
        "Try asking: 'What is my attendance?' or 'Show my grades'."
    ),
    "faculty": (
        "As a faculty member, you can only access data related to your courses and students."
    ),
    "finance_officer": (
        "As a Finance Officer, you can only access financial and fee-related information."
    ),
    "exam_officer": (
        "That request is outside your Exam Officer access scope. "
        "You can ask about at-risk students, exam schedules, course performance, "
        "ungraded assignments, or examination policies."
    ),
}

_CROSS_STUDENT_KEYWORDS = (
    "which student",
    "which students",
    "who has low",
    "who has",
    "all students",
    "students with",
    "students have",
    "students are",
    "list of students",
    "list students",
    "other students",
    "how many students",
    "low attendance students",
    "failing students",
    "at risk students",
    "students failing",
    "0% attendance",
)

_OWN_DATA_KEYWORDS = (
    " my ",
    "my ",
    " mine",
    "meri ",
    "mera ",
    "mujhe ",
    "mujh",
    "do i ",
    "i have",
    "i am",
)

_OTHER_STUDENT_QUERY_PATTERNS = (
    r"\bwhich students?\b",
    r"\bwho has\b",
    r"\ball students\b",
    r"\bstudents with\b",
    r"\bstudents who\b",
    r"\bstudents have\b",
    r"\bstudents are\b",
    r"\blist of students\b",
    r"\blist students\b",
    r"\bevery student\b",
    r"\bother students?\b",
    r"\bhow many students\b",
    r"\bshow all student",
    r"\ball student grades\b",
    r"\blow attendance students?\b",
    r"\bfailing students?\b",
    r"\bat[- ]risk students?\b",
    r"\buniversity[- ]wide\b",
    r"\bentire university\b",
    r"\bacross the university\b",
    r"\b0%\s*attendance\b",
)

_STUDENT_ID_PATTERN = re.compile(r"\bSTU-\d+\b", re.IGNORECASE)


def normalize_role(role: str) -> str:
    r = role.lower().strip().replace(" ", "_")
    if r == "finance":
        return "finance_officer"
    return r


def is_admin_role(role: str) -> bool:
    return normalize_role(role) == "admin"


def is_intent_allowed(role: str, intent: str) -> bool:
    role_norm = normalize_role(role)
    intent_lower = (intent or "").lower().strip()

    if role_norm == "admin":
        return True

    allowed = ROLE_PERMISSIONS.get(role_norm)
    if allowed is None:
        return False

    return intent_lower in allowed


def is_own_data_query(message: str) -> bool:
    """True when the message clearly asks about the user's own records."""
    lower = f" {message.lower().strip()} "
    if any(kw in lower for kw in _OWN_DATA_KEYWORDS):
        return True
    if re.search(r"\bmy\b", lower):
        return True
    return False


def requests_other_students_data(message: str, user_id: str) -> bool:
    """True when a student asks about data belonging to other or all students."""
    lower = message.lower().strip()

    if any(kw in lower for kw in _CROSS_STUDENT_KEYWORDS):
        return True

    if any(re.search(p, lower) for p in _OTHER_STUDENT_QUERY_PATTERNS):
        return True

    for match in _STUDENT_ID_PATTERN.findall(message):
        if match.upper() != (user_id or "").upper():
            return True

    # Plural/bulk attendance or grades without a clear "my/mine" scope
    if not is_own_data_query(message):
        if re.search(r"\b(attendance|grades?|gpa|marks?|results?)\b", lower):
            if re.search(r"\b(students?|class|course|department)\b", lower):
                if not re.search(r"\bmy\b", lower):
                    return True

    return False


def check_student_data_scope(intent: str, message: str, user_id: str) -> Tuple[bool, Optional[str]]:
    """
    Secondary RBAC for students: intent may be allowed but query targets other students.
    Returns (allowed, denial_message).
    """
    intent_lower = (intent or "").lower().strip()
    if intent_lower not in STUDENT_OWN_DATA_INTENTS:
        return True, None
    if requests_other_students_data(message, user_id):
        return False, get_denial_message("student")
    return True, None


def get_denial_message(role: str, intent: str = "") -> str:
    role_norm = normalize_role(role)
    return BLOCK_MESSAGES.get(
        role_norm,
        "I'm sorry, but I don't have permission to share that information with your account.",
    )


def log_rbac_debug(
    role: str,
    intent: str,
    resolved_intent: str,
    allowed: bool,
    reason: str,
) -> None:
    logger.info(
        "[RBAC DEBUG] role=%s intent=%s resolved_intent=%s allowed=%s reason=%s",
        role,
        intent,
        resolved_intent,
        allowed,
        reason,
    )


def check_chat_access(
    role: str,
    intent: str,
    message: str,
    user_id: str,
    resolved_intent: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Validate whether the authenticated user may execute this intent.

    Returns (allowed, denial_message). denial_message is set when allowed is False.
    """
    role_norm = normalize_role(role)
    intent_lower = (intent or "").lower().strip()
    effective_intent = (resolved_intent or intent_lower).lower().strip()

    if role_norm == "student" and (
        effective_intent == "department_stats" or is_department_stats_query(message)
    ):
        log_rbac_debug(
            role, intent_lower, effective_intent, False, "student_department_stats_blocked"
        )
        return False, get_rbac_chain_denial_message()

    if is_admin_role(role_norm):
        log_rbac_debug(role, intent_lower, effective_intent, True, "admin_full_access")
        return True, None

    if not is_intent_allowed(role_norm, effective_intent):
        log_rbac_debug(
            role,
            intent_lower,
            effective_intent,
            False,
            f"intent_not_in_role_permissions:{effective_intent}",
        )
        return False, get_denial_message(role_norm)

    if role_norm == "student":
        scope_ok, scope_denial = check_student_data_scope(
            effective_intent, message, user_id
        )
        if not scope_ok:
            log_rbac_debug(
                role, intent_lower, effective_intent, False, "student_scope_denied"
            )
            return False, scope_denial

    log_rbac_debug(role, intent_lower, effective_intent, True, "allowed")
    return True, None


def resolve_query_user_id(role: str, user_id: str, intent: str, message: str) -> str:
    """
    Return the user_id scoped for ERP queries.
    Students always use their own JWT user_id for personal data intents.
    Faculty use their faculty_id for faculty_* intents.
    """
    role_norm = normalize_role(role)
    if role_norm == "student" and intent.lower() in STUDENT_OWN_DATA_INTENTS:
        return user_id
    if intent.lower() == "fees":
        match = _STUDENT_ID_PATTERN.search(message)
        if match:
            return match.group(0).upper()
    return user_id
