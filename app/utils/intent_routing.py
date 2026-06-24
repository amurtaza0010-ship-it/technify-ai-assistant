"""Role-aware intent correction — prevents keyword collisions (e.g. 'course' vs 'course performance')."""
import re

_STAFF_ROLES = frozenset({"faculty", "exam_officer", "admin"})


def _normalize_role(role: str) -> str:
    r = role.lower().strip().replace(" ", "_")
    if r == "finance":
        return "finance_officer"
    return r

_COURSE_PERFORMANCE_PATTERN = re.compile(
    r"course performance|performance statistics|pass rate|average grade",
    re.IGNORECASE,
)
_UNGRADED_PATTERN = re.compile(
    r"ungraded|not graded|pending grading",
    re.IGNORECASE,
)
_AT_RISK_PATTERN = re.compile(
    r"at[- ]risk|students? at risk|my students at risk",
    re.IGNORECASE,
)
_EXAM_SCHEDULE_PATTERN = re.compile(
    r"exam schedule|upcoming exam|examination schedule|exam dates?|when are (the )?exams",
    re.IGNORECASE,
)


def is_exam_schedule_query(message: str) -> bool:
    return bool(_EXAM_SCHEDULE_PATTERN.search(message or ""))


def is_course_performance_query(message: str) -> bool:
    return bool(_COURSE_PERFORMANCE_PATTERN.search(message or ""))


def is_ungraded_query(message: str) -> bool:
    return bool(_UNGRADED_PATTERN.search(message or ""))


def _at_risk_intent_for_role(role_norm: str) -> str:
    if role_norm in ("admin", "exam_officer"):
        return "admin_at_risk"
    if role_norm == "faculty":
        return "faculty_at_risk"
    return "at_risk_students"


def resolve_staff_intent(role: str, intent: str, message: str) -> str:
    """
    Correct intents misclassified by broad keyword patterns.
    E.g. 'course performance' must not become student 'courses'.
    """
    role_norm = _normalize_role(role)
    intent_lower = (intent or "").lower().strip()
    lower = (message or "").lower()

    if role_norm in _STAFF_ROLES:
        if is_course_performance_query(message):
            return "faculty_performance"
        if is_ungraded_query(message):
            return "faculty_ungraded"

    if role_norm in ("faculty", "admin", "exam_officer"):
        if _AT_RISK_PATTERN.search(lower):
            return _at_risk_intent_for_role(role_norm)

    if role_norm == "exam_officer" and is_exam_schedule_query(message):
        return "exams"

    if intent_lower == "courses" and role_norm in _STAFF_ROLES and is_course_performance_query(message):
        return "faculty_performance"
    if intent_lower == "assignments" and role_norm in _STAFF_ROLES and is_ungraded_query(message):
        return "faculty_ungraded"

    return intent


def resolve_role_intent(role: str, intent: str, message: str) -> str:
    """Full role-aware intent resolution (finance + staff corrections)."""
    from app.utils.fees_intent import resolve_finance_intent

    intent = resolve_finance_intent(role, intent, message)
    return resolve_staff_intent(role, intent, message)
