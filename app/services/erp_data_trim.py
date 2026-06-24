"""
Trim large ERP payloads before they are embedded in LLM prompts.
Prevents Groq TPM / request-size errors (e.g. 413 on 8b-instant).
"""
from __future__ import annotations

from typing import Any

# Per-field list caps when trimming nested dict payloads
INTENT_LIST_LIMITS: dict[str, dict[str, int]] = {
    "faculty_performance": {"courses": 10},
    "faculty_attendance": {
        "attendance_by_course": 5,
        "low_attendance_students": 20,
        "all_students": 20,
    },
    "faculty_at_risk": {
        "at_risk_by_course": 5,
        "at_risk_students": 15,
    },
    "faculty_ungraded": {"by_course": 15, "ungraded_assignments": 15},
    "assignments": {"assignments": 15, "upcoming": 15},
    "attendance": {"courses": 10, "records": 20},
    "admin_at_risk": {"at_risk_students": 15},
    "courses": {"courses": 15},
    "results": {"results": 15, "exams": 15},
}

DEFAULT_LIST_LIMIT = 10


def trim_data_for_llm(data: Any, max_records: int = DEFAULT_LIST_LIMIT) -> Any:
    """Cap a list to max_records; pass through other types unchanged."""
    if isinstance(data, list) and len(data) > max_records:
        return data[:max_records]
    return data


def _trim_list(key: str, items: list, intent: str | None) -> tuple[list, bool]:
    limits = INTENT_LIST_LIMITS.get(intent or "", {})
    cap = limits.get(key, DEFAULT_LIST_LIMIT)
    if key in ("low_attendance_students", "all_students", "at_risk_students"):
        cap = limits.get(key, 20 if "attendance" in key else 15)
    if len(items) > cap:
        return items[:cap], True
    return items, False


def trim_erp_payload_for_llm(data: Any, intent: str | None = None) -> Any:
    """
    Recursively trim lists inside ERP response dicts/lists.
    Adds metadata keys when truncation occurs.
    """
    if isinstance(data, list):
        trimmed, was_trimmed = _trim_list("_root", data, intent)
        if was_trimmed:
            return {
                "items": trimmed,
                "_truncated": True,
                "_total_records": len(data),
                "_shown_records": len(trimmed),
            }
        return [trim_erp_payload_for_llm(item, intent) for item in trimmed]

    if not isinstance(data, dict):
        return data

    result: dict[str, Any] = {}
    any_trimmed = False

    for key, value in data.items():
        if isinstance(value, list):
            trimmed, was_trimmed = _trim_list(key, value, intent)
            if was_trimmed:
                any_trimmed = True
                result[key] = [
                    trim_erp_payload_for_llm(item, intent) if isinstance(item, dict) else item
                    for item in trimmed
                ]
                result[f"_{key}_total"] = len(value)
            else:
                result[key] = [
                    trim_erp_payload_for_llm(item, intent) if isinstance(item, dict) else item
                    for item in trimmed
                ]
        elif isinstance(value, dict):
            result[key] = trim_erp_payload_for_llm(value, intent)
        else:
            result[key] = value

    if any_trimmed and "_truncated" not in result:
        result["_truncated"] = True
        result["_note"] = "Large dataset trimmed for LLM context limits."

    return result
