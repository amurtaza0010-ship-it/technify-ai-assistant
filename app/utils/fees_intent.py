"""Fees intent routing — shared by RBAC, ERP connector, and chat chain."""
import logging
import re

logger = logging.getLogger("taia.fees_intent")

_STUDENT_ID_PATTERN = re.compile(r"\bSTU-\d+\b", re.IGNORECASE)

FEE_ERP_INTENTS = frozenset({
    "fees",
    "admin_fees",
    "admin_finance_pending",
    "admin_finance_scholarship",
    "admin_finance_department",
    "admin_finance_summary",
})

FINANCE_OFFICER_INTENTS = frozenset({
    "admin_fees",
    "admin_finance_summary",
    "admin_finance_pending",
    "admin_finance_scholarship",
    "admin_finance_department",
}) | FEE_ERP_INTENTS

_FEE_COLLECTION_PATTERN = re.compile(
    r"fee collection|collected fees?|collection rate|fee report",
    re.IGNORECASE,
)

_FINANCE_DEPARTMENT_FEE_PATTERN = re.compile(
    r"department[- ]?wise fees?|fees? by department|department[- ]?wise fee",
    re.IGNORECASE,
)

_SCHOLARSHIP_QUERY_PATTERN = re.compile(
    r"\bscholarship\b",
    re.IGNORECASE,
)


def _normalize_role(role: str) -> str:
    r = role.lower().strip().replace(" ", "_")
    if r == "finance":
        return "finance_officer"
    return r


def is_finance_department_fee_query(message: str) -> bool:
    """True when the query is about department-wise fee/financial stats (not student enrollment)."""
    lower = (message or "").lower()
    if not re.search(r"\bdepartment\b", lower):
        return False
    if _FINANCE_DEPARTMENT_FEE_PATTERN.search(lower):
        return True
    return bool(
        re.search(r"department[- ]?wise", lower) and re.search(r"\bfee", lower)
    )


def is_finance_scholarship_query(message: str) -> bool:
    return bool(_SCHOLARSHIP_QUERY_PATTERN.search(message or ""))


def is_pending_fee_query(message: str) -> bool:
    """Finance/admin query listing students with pending or unpaid fees."""
    lower = (message or "").lower()
    return bool(re.search(r"pending fees?|unpaid fees?|students with pending", lower))


def is_fee_erp_intent(intent: str, role: str = "", message: str = "") -> bool:
    """True when the intent (after fees resolution) targets fee ERP data, not RAG policy."""
    from app.utils.intent_routing import resolve_role_intent

    resolved = resolve_role_intent(role, intent, message)
    return resolved in FEE_ERP_INTENTS


def resolve_fees_intent(role: str, intent: str, message: str) -> str:
    """
    Map generic 'fees' to the correct ERP intent for the user's role.
    Students keep 'fees'; admin/finance get aggregate stats unless a STU-* id is named.
    """
    intent_lower = (intent or "").lower().strip()
    role_norm = _normalize_role(role)
    lower = (message or "").lower()

    if intent_lower != "fees":
        if intent_lower in FEE_ERP_INTENTS:
            return intent_lower
        if _FEE_COLLECTION_PATTERN.search(lower):
            if role_norm == "student":
                return "fees"
            if role_norm in ("admin", "finance_officer"):
                return "admin_fees"
        return intent

    if role_norm == "student":
        return "fees"

    if role_norm in ("admin", "finance_officer"):
        if _STUDENT_ID_PATTERN.search(message):
            return "fees"
        if re.search(r"pending fees?|unpaid fees?|students with pending", lower):
            return "admin_finance_pending"
        if is_finance_scholarship_query(message):
            return "admin_finance_scholarship"
        if is_finance_department_fee_query(message):
            return "admin_finance_department"
        if re.search(r"financial summary|revenue|finance summary", lower):
            return "admin_finance_summary"
        return "admin_fees"

    return intent


def resolve_finance_intent(role: str, intent: str, message: str) -> str:
    """
    Resolve the ERP intent after role- and message-aware finance routing.
    Prevents finance fee queries from being misrouted to department_stats.
    """
    role_norm = _normalize_role(role)
    lower = (message or "").lower()

    if role_norm in ("admin", "finance_officer"):
        if is_finance_scholarship_query(message):
            return "admin_finance_scholarship"
        if is_finance_department_fee_query(message):
            return "admin_finance_department"
        if re.search(r"pending fees?|unpaid fees?|students with pending", lower):
            return "admin_finance_pending"
        if re.search(r"financial summary|revenue|finance summary", lower):
            return "admin_finance_summary"

    resolved = resolve_fees_intent(role, intent, message)

    if resolved == "department_stats" and is_finance_department_fee_query(message):
        return "admin_finance_department"
    if (
        role_norm in ("admin", "finance_officer")
        and resolved == "department_stats"
        and re.search(r"\bfee", lower)
    ):
        return "admin_finance_department"

    return resolved


def log_fee_routing(
    stage: str,
    *,
    message: str,
    role: str,
    detected_intent: str,
    resolved_intent: str,
    handler: str,
) -> None:
    logger.info(
        "[FEES ROUTING] stage=%s role=%s detected=%s resolved=%s handler=%s msg=%r",
        stage,
        role,
        detected_intent,
        resolved_intent,
        handler,
        message,
    )
