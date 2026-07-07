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

ADMIN_COMPRESS_INTENTS = frozenset({
    "admin_at_risk",
    "admin_finance_pending",
})

STUDENT_COMPRESS_INTENTS = frozenset({
    "results",
    "timetable",
    "assignments",
    "student_grade_calculation",
    "student_instructors",
})

TOP_STUDENTS = 8
TOP_ASSIGNMENTS = 8
TOP_COURSE_LOW = 5
TOP_STUDENT_COURSES = 15

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
    "assignments": {"assignments": 8, "assignments_due_this_week": 8, "upcoming": 8},
    "attendance": {"courses": 10, "records": 20},
    "admin_at_risk": {"at_risk_students": 8},
    "admin_finance_pending": {"pending_fees": 8},
    "courses": {"courses": 8},
    "student_instructors": {"courses": 15},
    "results": {"results": 10, "exams": 10},
    "timetable": {"timetable": 15},
    "faculty_courses": {"courses": 8},
    "faculty_teaching": {"courses": 8, "subjects": 8},
    "admin_departments": {"departments": 10},
    "admin_finance_department": {"departments": 10},
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
    result["_compressed_for_llm"] = True

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
    """Summarize per-course attendance to only the top-N critical courses/students."""
    courses = data.get("attendance_by_course", [])
    course_summaries = []
    top_lowest = []
    total_students = 0
    total_below_75 = 0

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
                "reason": "Low attendance",
                "warning_flag": student.get("warning_flag", _attendance_pct(student) < 75),
            })

    top_lowest.sort(key=lambda row: row["attendance_percentage"])
    course_summaries.sort(key=lambda row: row.get("average_attendance") if row.get("average_attendance") is not None else 100)

    result = {
        "faculty_id": data.get("faculty_id"),
        "_compressed_for_llm": True,
        "summary": {
            "total_courses": len(course_summaries),
            "total_students": total_students,
            "students_below_75_total": total_below_75,
            "course_summaries": course_summaries[:TOP_COURSE_LOW],
            "courses_shown": min(len(course_summaries), TOP_COURSE_LOW),
            "top_low_attendance_students": top_lowest[:TOP_STUDENTS],
        },
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


def _compact_at_risk_student(student: dict, course_id: str | None, course_name: str | None) -> dict:
    """Return the minimal at-risk student record the LLM needs to answer questions."""
    reason = (
        student.get("reason", "")
        or student.get("remarks", "")
        or ""
    )
    return {
        "student_id": student.get("student_id"),
        "student_name": _student_name(student),
        "course_id": course_id or student.get("course_id"),
        "course_name": course_name or student.get("course_name", ""),
        "reason": reason,
        "attendance_percentage": student.get("attendance_percentage"),
        "GPA": student.get("GPA") or student.get("gpa"),
        "avg_percentage": student.get("avg_percentage", student.get("total")),
        "current_grade": student.get("current_grade"),
    }


def _compress_faculty_at_risk(data: dict) -> dict:
    courses = data.get("at_risk_by_course", [])
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

        for student in at_risk:
            if not isinstance(student, dict):
                continue
            top_at_risk.append(
                _compact_at_risk_student(student, course.get("course_id"), course.get("course_name"))
            )

    if not top_at_risk and data.get("top_at_risk_students"):
        for stu in data["top_at_risk_students"]:
            if isinstance(stu, dict):
                top_at_risk.append(_compact_at_risk_student(stu, None, None))
        total_at_risk = total_at_risk or data.get("total_at_risk", len(top_at_risk))

    top_at_risk.sort(
        key=lambda row: (
            row.get("avg_percentage")
            if row.get("avg_percentage") is not None
            else (row.get("GPA") or 0)
        ),
    )

    return {
        "faculty_id": data.get("faculty_id"),
        "_compressed_for_llm": True,
        "summary": {
            "total_at_risk": total_at_risk,
            "top_at_risk_students": top_at_risk[:TOP_STUDENTS],
        },
    }


def _compact_assignment(row: dict) -> dict:
    """Keep only the 5 fields the LLM actually needs; strip ERP-internal IDs."""
    return {
        "assignment_name": row.get("assignment_name", row.get("assignment_title")),
        "course": row.get("course", row.get("course_name")),
        "student_name": row.get("student_name"),
        "due_date": row.get("due_date"),
        "status": row.get("status"),
    }


def _compress_faculty_ungraded(data: dict) -> dict:
    ungraded = [row for row in data.get("ungraded_assignments", []) if isinstance(row, dict)]
    overdue = [row for row in data.get("overdue_assignments", []) if isinstance(row, dict)]
    overdue_sorted = sorted(overdue, key=lambda row: row.get("due_date") or "")

    return {
        "_compressed_for_llm": True,
        "summary": {
            "total_ungraded": data.get("total_ungraded", len(ungraded)),
            "total_overdue": data.get("total_overdue", len(overdue)),
            "top_ungraded_assignments": [_compact_assignment(row) for row in ungraded[:TOP_ASSIGNMENTS]],
            "top_overdue_assignments": [_compact_assignment(row) for row in overdue_sorted[:TOP_ASSIGNMENTS]],
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


# ── Admin compressors ──────────────────────────────────────────────────────────

def _compress_admin_at_risk(data: dict) -> dict:
    """Cap to TOP_STUDENTS, strip internal fields the LLM doesn't need."""
    students = [s for s in data.get("at_risk_students", []) if isinstance(s, dict)]
    compact = [
        {
            "student_id": s.get("student_id"),
            "name": _student_name(s),                             # now uses both student_name/name
            "course_name": s.get("course_name", ""),
            "reason": s.get("reason", "") or s.get("remarks", ""),
            "attendance_percentage": s.get("attendance_percentage") or s.get("attendance"),
            "GPA": s.get("GPA") or s.get("gpa"),
        }
        for s in students[:TOP_STUDENTS]
    ]
    return {
        "_compressed_for_llm": True,
        "summary": {
            "total_at_risk": len(students),
            "at_risk_students": compact,
        },
    }


def _compress_admin_finance_pending(data: dict) -> dict:
    """Cap to TOP_STUDENTS, keep only essential payment fields."""
    pending = [p for p in data.get("pending_fees", []) if isinstance(p, dict)]
    compact = [
        {
            "student_id": p.get("student_id"),
            "name": p.get("name", ""),
            "amount": p.get("due_amount") or p.get("amount") or p.get("fee_amount"),
            "due_date": p.get("due_date"),
        }
        for p in pending[:TOP_STUDENTS]
    ]
    return {
        "_compressed_for_llm": True,
        "summary": {
            "total_pending": len(pending),
            "pending_fees": compact,
        },
    }


# ── Student compressors ────────────────────────────────────────────────────────

def _compress_student_results(data: dict) -> dict:
    """Strip per-record ERP noise (IDs, codes) and cap to 10 most recent exams."""
    results = [r for r in data.get("results", []) if isinstance(r, dict)]
    compact = [
        {
            "course_name": r.get("course_name", ""),
            "exam_type": r.get("exam_type", ""),
            "marks_obtained": r.get("marks_obtained"),
            "total_marks": r.get("total_marks"),
            "percentage": r.get("percentage"),
            "grade": r.get("grade") or r.get("current_grade", ""),
        }
        for r in results[:10]
    ]
    return {
        "_compressed_for_llm": True,
        "student_id": data.get("student_id"),
        "results": compact,
        "total_exams": len(results),
    }


_TIMETABLE_KEEP = frozenset({"course", "code", "day", "days", "time", "time_slot", "room", "faculty"})


def _compress_student_timetable(data: dict) -> dict:
    """Keep only schedule-relevant timetable fields, cap to 15 entries."""
    entries = [e for e in data.get("timetable", []) if isinstance(e, dict)]
    compact = [
        {k: v for k, v in e.items() if k in _TIMETABLE_KEEP}
        for e in entries[:15]
    ]
    return {
        "_compressed_for_llm": True,
        "student_id": data.get("student_id"),
        "timetable": compact,
        "total_entries": len(entries),
    }


def _compress_student_assignments(data: dict, message: str | None = None) -> dict:
    """Unify both assignment key variants; strip ERP-internal fields; cap to TOP_ASSIGNMENTS."""
    raw = (
        [a for a in data.get("assignments", []) if isinstance(a, dict)]
        or [a for a in data.get("assignments_due_this_week", []) if isinstance(a, dict)]
    )

    if message and "pending" in message.lower():
        pending_only = [a for a in raw if str(a.get("status", "")).strip().lower() == "pending"]
        if pending_only:
            raw = pending_only

    compact = [
        {
            "course": a.get("course") or a.get("course_name", ""),
            "assignment": (
                a.get("assignment")
                or a.get("assignment_title")
                or a.get("title", "")
            ),
            "status": a.get("status", ""),
            "due_date": a.get("due_date", ""),
            "marks": a.get("marks") or a.get("marks_obtained"),
        }
        for a in raw[:TOP_ASSIGNMENTS]
    ]
    payload_key = "assignments_due_this_week" if data.get("assignments_due_this_week") else "assignments"
    return {
        "_compressed_for_llm": True,
        "student_id": data.get("student_id"),
        payload_key: compact,
        "total": len(raw),
    }


def _compress_student_instructors(data: dict) -> dict:
    """Keep instructor rows aligned with the courses intent list; cap at TOP_STUDENT_COURSES."""
    courses = [c for c in data.get("courses", []) if isinstance(c, dict)]
    compact = [
        {
            "course_id": c.get("course_id"),
            "course_name": c.get("course_name", ""),
            "instructor": c.get("instructor") or c.get("faculty_name", ""),
        }
        for c in courses[:TOP_STUDENT_COURSES]
    ]
    return {
        "_compressed_for_llm": True,
        "student_id": data.get("student_id"),
        "courses": compact,
        "total_courses": len(courses),
        "courses_shown": len(compact),
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
    """Reduce ERP payloads before they are embedded in LLM prompts."""
    if not isinstance(data, dict):
        return _legacy_trim_erp_payload(data, intent)

    if data.get("_compressed_for_llm"):
        return data

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

    if intent_key in ADMIN_COMPRESS_INTENTS:
        admin_compressors: dict[str, Callable[[dict], dict]] = {
            "admin_at_risk": _compress_admin_at_risk,
            "admin_finance_pending": _compress_admin_finance_pending,
        }
        return admin_compressors[intent_key](data)

    if intent_key == "assignments":
        return _compress_student_assignments(data, message)

    if intent_key in STUDENT_COMPRESS_INTENTS:
        student_compressors: dict[str, Callable[[dict], dict]] = {
            "results": _compress_student_results,
            "timetable": _compress_student_timetable,
            "student_grade_calculation": _compress_student_results,
            "student_instructors": _compress_student_instructors,
        }
        return student_compressors[intent_key](data)

    return _legacy_trim_erp_payload(data, intent)