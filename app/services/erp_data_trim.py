"""
Trim large ERP payloads before they are embedded in LLM prompts.
Prevents Groq TPM / request-size errors (e.g. 413 on 8b-instant).
"""
from __future__ import annotations

import re
from typing import Any, Callable

FACULTY_COMPRESS_INTENTS = frozenset({
    "faculty_attendance",
    "faculty_at_risk",
    "faculty_ungraded",
    "faculty_performance",
})

TOP_STUDENTS = 20
TOP_ASSIGNMENTS = 20
TOP_COURSE_LOW = 10

_ANALYTICAL_MARKERS = (
    r"\bwhich students?\b",
    r"\bshow (all|attendance statistics|course analytics|pending grading)\b",
    r"\blist (of )?students?\b",
    r"\bhow many students?\b",
    r"\blow attendance\b",
    r"\bbelow 75\b",
    r"\bat[- ]risk\b",
    r"\bungraded\b",
    r"\bpending grading\b",
    r"\bcourse analytics\b",
    r"\battendance statistics\b",
    r"\bgrading progress\b",
    r"\bclass performance\b",
)

# Per-field list caps when trimming nested dict payloads (non-faculty / specific lookups)
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


def _extract_student_name_hint(message: str) -> str | None:
    lower = message.lower().strip()
    patterns = (
        r"\bshow\s+(.+?)\s+(?:attendance|grades|gpa|performance|marks)\b",
        r"\b(.+?)(?:'s|\s+)attendance\b",
        r"\battendance (?:for|of)\s+(.+?)\.?$",
        r"\b(?:student|for)\s+(.+?)\s+(?:attendance|grades|gpa|performance|marks)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, lower)
        if not match:
            continue
        hint = re.sub(r"\b(the|my|their|please)\b", "", match.group(1)).strip()
        if hint and not re.search(r"\b(all|which|every|students?)\b", hint):
            return hint
    return None


def _is_specific_student_lookup(message: str | None) -> bool:
    if not message:
        return False
    if re.search(r"\bSTU-\d+\b", message, re.I):
        return True
    hint = _extract_student_name_hint(message)
    if not hint:
        return False
    lower = message.lower()
    if any(re.search(pattern, lower) for pattern in _ANALYTICAL_MARKERS):
        return False
    return len(hint.split()) <= 4


def _student_name(record: dict) -> str:
    return str(record.get("student_name") or record.get("name") or "")


def _attendance_pct(record: dict) -> float:
    for key in ("attendance_percentage", "percentage"):
        value = record.get(key)
        if value is not None:
            return float(value)
    return 100.0


def _student_matches_hint(record: dict, hint: str) -> bool:
    hint_lower = hint.lower().strip()
    if not hint_lower:
        return False
    if hint_lower in _student_name(record).lower():
        return True
    student_id = str(record.get("student_id") or "").lower()
    return hint_lower in student_id


def _filter_student_rows(rows: list, hint: str) -> list:
    return [row for row in rows if isinstance(row, dict) and _student_matches_hint(row, hint)]


def _filter_faculty_payload_by_name(data: dict, intent: str, name_hint: str) -> dict:
    """Keep complete matching student rows for a named lookup."""
    result = {key: value for key, value in data.items() if key not in (
        "attendance_by_course", "at_risk_by_course", "students", "all_students",
    )}
    result["_student_lookup"] = name_hint

    if intent == "faculty_attendance":
        filtered_courses = []
        for course in data.get("attendance_by_course", []):
            if not isinstance(course, dict):
                continue
            all_students = _filter_student_rows(course.get("all_students", []), name_hint)
            low_students = _filter_student_rows(course.get("low_attendance_students", []), name_hint)
            if not all_students and not low_students:
                continue
            filtered_courses.append({
                **{k: v for k, v in course.items() if k not in ("all_students", "low_attendance_students")},
                "all_students": all_students,
                "low_attendance_students": low_students or all_students,
                "total_students": len(all_students),
            })
        result["attendance_by_course"] = filtered_courses
    elif intent == "faculty_at_risk":
        filtered_courses = []
        for course in data.get("at_risk_by_course", []):
            if not isinstance(course, dict):
                continue
            students = _filter_student_rows(course.get("students", []), name_hint)
            at_risk = _filter_student_rows(course.get("at_risk_students", []), name_hint) or [
                s for s in students if s.get("at_risk")
            ]
            if not students and not at_risk:
                continue
            filtered_courses.append({
                **{k: v for k, v in course.items() if k not in ("students", "at_risk_students")},
                "students": students,
                "at_risk_students": at_risk,
                "total_students": len(students),
            })
        result["at_risk_by_course"] = filtered_courses
    elif intent == "faculty_ungraded":
        result["ungraded_assignments"] = [
            row for row in data.get("ungraded_assignments", [])
            if isinstance(row, dict) and (
                _student_matches_hint(row, name_hint)
                or name_hint in str(row.get("assignment_name", "")).lower()
            )
        ]
        result["overdue_assignments"] = [
            row for row in data.get("overdue_assignments", [])
            if isinstance(row, dict) and _student_matches_hint(row, name_hint)
        ]
        for key in ("total_ungraded", "total_overdue", "by_course", "dashboard"):
            if key in data:
                result[key] = data[key]
    elif intent == "faculty_performance":
        result["courses"] = [
            course for course in data.get("courses", [])
            if isinstance(course, dict) and name_hint in str(course.get("course_name", "")).lower()
        ]
        if "faculty_dashboard" in data:
            result["faculty_dashboard"] = data["faculty_dashboard"]

    return result


def _compress_faculty_attendance(data: dict) -> dict:
    courses = data.get("attendance_by_course", [])
    course_summaries = []
    top_lowest = []
    total_students = 0
    total_below_75 = 0
    compressed_courses = []

    for course in courses:
        if not isinstance(course, dict):
            continue
        all_students = course.get("all_students", [])
        low_students = course.get("low_attendance_students", [])
        if not low_students and all_students:
            low_students = [s for s in all_students if _attendance_pct(s) < 75]

        course_total = course.get("total_students", len(all_students))
        total_students += course_total
        total_below_75 += len(low_students)

        percentages = [_attendance_pct(s) for s in all_students if isinstance(s, dict)]
        average_attendance = round(sum(percentages) / len(percentages), 1) if percentages else None

        course_summaries.append({
            "course_id": course.get("course_id"),
            "course_name": course.get("course_name"),
            "total_students": course_total,
            "students_below_75": len(low_students),
            "average_attendance": average_attendance,
        })

        for student in low_students:
            if not isinstance(student, dict):
                continue
            top_lowest.append({
                "student_id": student.get("student_id"),
                "student_name": _student_name(student),
                "course_id": course.get("course_id"),
                "course_name": course.get("course_name"),
                "attendance_percentage": _attendance_pct(student),
                "warning_flag": student.get("warning_flag", _attendance_pct(student) < 75),
            })

        compressed_courses.append({
            "course_id": course.get("course_id"),
            "course_name": course.get("course_name"),
            "total_students": course_total,
            "students_below_75": len(low_students),
            "average_attendance": average_attendance,
        })

    top_lowest.sort(key=lambda row: row["attendance_percentage"])

    result = {
        "faculty_id": data.get("faculty_id"),
        "_compressed_for_llm": True,
        "summary": {
            "total_courses": len(compressed_courses),
            "total_students": total_students,
            "students_below_75_total": total_below_75,
            "course_summaries": course_summaries,
            "top_20_lowest_attendance": top_lowest[:TOP_STUDENTS],
        },
        "attendance_by_course": compressed_courses,
    }

    if "global_fallback" in data and isinstance(data["global_fallback"], dict):
        fallback = data["global_fallback"]
        fallback_rows = fallback.get("low_attendance_students", [])
        result["global_fallback"] = {
            "source": fallback.get("source"),
            "total_low_attendance": fallback.get("total_low_attendance", len(fallback_rows)),
            "low_attendance_students": fallback_rows[:TOP_STUDENTS],
        }
    return result


def _compress_faculty_at_risk(data: dict) -> dict:
    courses = data.get("at_risk_by_course", [])
    grouped_by_course = []
    top_at_risk = []
    total_at_risk = 0

    for course in courses:
        if not isinstance(course, dict):
            continue
        students = course.get("students", [])
        at_risk = course.get("at_risk_students", [])
        if not at_risk and students:
            at_risk = [s for s in students if s.get("at_risk")]

        total_at_risk += len(at_risk)
        grouped_by_course.append({
            "course_id": course.get("course_id"),
            "course_name": course.get("course_name"),
            "total_students": course.get("total_students", len(students)),
            "at_risk_count": len(at_risk),
        })

        for student in at_risk:
            if not isinstance(student, dict):
                continue
            top_at_risk.append({
                "student_id": student.get("student_id"),
                "student_name": _student_name(student),
                "course_id": course.get("course_id"),
                "course_name": course.get("course_name"),
                "GPA": student.get("GPA"),
                "midterm": student.get("midterm"),
                "final": student.get("final"),
                "avg_percentage": student.get("avg_percentage", student.get("total")),
                "current_grade": student.get("current_grade"),
                "remarks": student.get("remarks"),
            })

    top_at_risk.sort(
        key=lambda row: row.get("avg_percentage") if row.get("avg_percentage") is not None else row.get("GPA", 0) or 0,
    )

    result = {
        "faculty_id": data.get("faculty_id"),
        "_compressed_for_llm": True,
        "summary": {
            "total_at_risk": total_at_risk,
            "grouped_by_course": grouped_by_course,
            "top_at_risk_students": top_at_risk[:TOP_STUDENTS],
        },
    }

    if "global_fallback" in data and isinstance(data["global_fallback"], dict):
        fallback = data["global_fallback"]
        fallback_rows = fallback.get("at_risk_students", [])
        result["global_fallback"] = {
            "source": fallback.get("source"),
            "total_at_risk": fallback.get("total_at_risk", len(fallback_rows)),
            "at_risk_students": fallback_rows[:TOP_STUDENTS],
        }
    return result


def _compact_assignment(row: dict) -> dict:
    return {
        "assignment_id": row.get("assignment_id"),
        "assignment_name": row.get("assignment_name", row.get("assignment_title")),
        "course": row.get("course", row.get("course_name")),
        "course_id": row.get("course_id"),
        "student_id": row.get("student_id"),
        "student_name": row.get("student_name"),
        "due_date": row.get("due_date"),
        "submitted": row.get("submitted"),
        "graded": row.get("graded"),
        "pending_grading": row.get("pending_grading"),
        "missing_submission": row.get("missing_submission"),
        "status": row.get("status"),
    }


def _compress_faculty_ungraded(data: dict) -> dict:
    ungraded = [row for row in data.get("ungraded_assignments", []) if isinstance(row, dict)]
    overdue = [row for row in data.get("overdue_assignments", []) if isinstance(row, dict)]
    by_course = [
        row for row in data.get("by_course", [])
        if isinstance(row, dict)
    ]
    by_course.sort(key=lambda row: row.get("ungraded_count", 0), reverse=True)
    dashboard = data.get("dashboard") if isinstance(data.get("dashboard"), dict) else {}

    overdue_sorted = sorted(overdue, key=lambda row: row.get("due_date") or "")

    return {
        "_compressed_for_llm": True,
        "summary": {
            "total_ungraded": data.get("total_ungraded", len(ungraded)),
            "total_overdue": data.get("total_overdue", len(overdue)),
            "assignment_counts_by_course": by_course[:TOP_COURSE_LOW],
            "top_ungraded_assignments": [_compact_assignment(row) for row in ungraded[:TOP_ASSIGNMENTS]],
            "top_overdue_assignments": [_compact_assignment(row) for row in overdue_sorted[:TOP_ASSIGNMENTS]],
            "pending_grading": dashboard.get("pending_grading"),
            "upcoming_deadlines": dashboard.get("upcoming_deadlines"),
            "recent_submissions": dashboard.get("recent_submissions"),
            "course_summaries": (dashboard.get("course_summaries") or [])[:TOP_COURSE_LOW],
        },
    }


def _average_field(rows: list, field: str) -> float | None:
    values = [row.get(field) for row in rows if isinstance(row, dict) and row.get(field) is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _compress_faculty_performance(data: dict) -> dict:
    courses = [row for row in data.get("courses", []) if isinstance(row, dict)]
    dashboard = data.get("faculty_dashboard") if isinstance(data.get("faculty_dashboard"), dict) else {}
    dashboard_courses = {
        row.get("course_id"): row
        for row in (dashboard.get("course_summaries") or [])
        if isinstance(row, dict)
    }

    if dashboard_courses:
        selected = [
            course for course in courses
            if course.get("course_id") in dashboard_courses
        ]
    else:
        selected = sorted(
            courses,
            key=lambda row: row.get("grading_progress", 0),
        )[:TOP_COURSE_LOW]

    compact_courses = [
        {
            "course_id": course.get("course_id"),
            "course_name": course.get("course_name"),
            "course_code": course.get("course_code"),
            "enrollment": course.get("enrollment", course.get("total_students")),
            "pass_rate": course.get("pass_rate"),
            "fail_rate": course.get("fail_rate"),
            "average_attendance": course.get("average_attendance"),
            "assignment_completion": course.get("assignment_completion"),
            "grading_progress": course.get("grading_progress"),
            "average_grade": course.get("average_grade"),
            "average_percentage": course.get("average_percentage"),
        }
        for course in selected
    ]

    return {
        "_compressed_for_llm": True,
        "summary": {
            "total_courses": len(courses),
            "courses_in_context": len(compact_courses),
            "average_pass_rate": _average_field(courses, "pass_rate"),
            "average_fail_rate": _average_field(courses, "fail_rate"),
            "average_attendance": _average_field(courses, "average_attendance"),
            "average_grading_progress": _average_field(courses, "grading_progress"),
            "average_assignment_completion": _average_field(courses, "assignment_completion"),
            "average_percentage": _average_field(courses, "average_percentage"),
            "pending_grading": dashboard.get("pending_grading"),
            "students_at_risk": dashboard.get("students_at_risk"),
            "attendance_alerts": dashboard.get("attendance_alerts"),
        },
        "courses": compact_courses,
    }


def _trim_list(key: str, items: list, intent: str | None) -> tuple[list, bool]:
    limits = INTENT_LIST_LIMITS.get(intent or "", {})
    cap = limits.get(key, DEFAULT_LIST_LIMIT)
    if key in ("low_attendance_students", "all_students", "at_risk_students"):
        cap = limits.get(key, 20 if "attendance" in key else 15)
    if len(items) > cap:
        return items[:cap], True
    return items, False


def _legacy_trim_erp_payload(data: Any, intent: str | None = None) -> Any:
    """Recursively trim lists inside ERP response dicts/lists."""
    if isinstance(data, list):
        trimmed, was_trimmed = _trim_list("_root", data, intent)
        if was_trimmed:
            return {
                "items": trimmed,
                "_truncated": True,
                "_total_records": len(data),
                "_shown_records": len(trimmed),
            }
        return [_legacy_trim_erp_payload(item, intent) for item in trimmed]

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
                    _legacy_trim_erp_payload(item, intent) if isinstance(item, dict) else item
                    for item in trimmed
                ]
                result[f"_{key}_total"] = len(value)
            else:
                result[key] = [
                    _legacy_trim_erp_payload(item, intent) if isinstance(item, dict) else item
                    for item in trimmed
                ]
        elif isinstance(value, dict):
            result[key] = _legacy_trim_erp_payload(value, intent)
        else:
            result[key] = value

    if any_trimmed and "_truncated" not in result:
        result["_truncated"] = True
        result["_note"] = "Large dataset trimmed for LLM context limits."

    return result


def trim_erp_payload_for_llm(
    data: Any,
    intent: str | None = None,
    message: str | None = None,
) -> Any:
    """
    Reduce ERP payloads before they are embedded in LLM prompts.
    Faculty analytical intents are summarized; named student lookups are filtered, not summarized.
    """
    if not isinstance(data, dict):
        return _legacy_trim_erp_payload(data, intent)

    intent_key = (intent or "").lower().strip()
    if intent_key in FACULTY_COMPRESS_INTENTS and message:
        if _is_specific_student_lookup(message):
            name_hint = _extract_student_name_hint(message) or message
            return _filter_faculty_payload_by_name(data, intent_key, name_hint)

        compressors: dict[str, Callable[[dict], dict]] = {
            "faculty_attendance": _compress_faculty_attendance,
            "faculty_at_risk": _compress_faculty_at_risk,
            "faculty_ungraded": _compress_faculty_ungraded,
            "faculty_performance": _compress_faculty_performance,
        }
        return compressors[intent_key](data)

    if isinstance(data, dict) and data.get("_compressed_for_llm"):
        return data

    return _legacy_trim_erp_payload(data, intent)
