"""ERP handlers for TAIA chains — async HTTP calls to the Mock ERP API."""
import asyncio
import json
import logging
import re
import time
from typing import Optional, Tuple

import httpx
from app.auth.chat_rbac import (
    check_chat_access,
    check_student_data_scope,
    normalize_role,
    resolve_query_user_id,
)
from app.utils.intent_routing import resolve_role_intent
from app.config import get_settings
from app.services.erp_data_trim import trim_erp_payload_for_llm

logger = logging.getLogger("taia.erp_handlers")


def _is_valid_student_id(user_id: str) -> bool:
    return bool(user_id) and user_id.upper().startswith("STU-")

settings = get_settings()
BASE = settings.ERP_API_BASE_URL
if not BASE.endswith("/api/v1") and not BASE.endswith("/api/v1/"):
    BASE = BASE.rstrip("/") + "/api/v1"

_erp_client: httpx.AsyncClient | None = None


def _get_erp_client() -> httpx.AsyncClient:
    global _erp_client
    if _erp_client is None:
        _erp_client = httpx.AsyncClient(timeout=30.0)
    return _erp_client


async def _get(path: str) -> dict:
    t0 = time.perf_counter()
    client = _get_erp_client()
    url = f"{BASE}{path}"
    if "/fees" in path:
        logger.info("[FEES DEBUG] ERP GET %s", url)
    response = await client.get(url)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info("ERP handler GET %s → %.0fms", path, elapsed_ms)
    if "/fees" in path:
        logger.info(
            "[FEES DEBUG] ERP response status=%s body=%s",
            response.status_code,
            response.text[:500],
        )
    response.raise_for_status()
    return response.json()


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


async def get_student_timetable_by_day(student_id: str, day: str) -> dict:
    return await _get(f"/student/{student_id}/timetable/day/{day}")


async def get_student_upcoming_exams(student_id: str) -> dict:
    return await _get(f"/student/{student_id}/exams/upcoming")


async def get_student_upcoming_assignments(student_id: str) -> dict:
    return await _get(f"/student/{student_id}/assignments/upcoming")


async def get_student_assignments(student_id: str) -> dict:
    return await _get(f"/student/{student_id}/assignments")


async def get_student_fees(student_id: str) -> dict:
    return await _get(f"/student/{student_id}/fees")


# ── Faculty APIs ──
async def get_faculty_courses(faculty_id: str) -> dict:
    return await _get(f"/faculty/{faculty_id}/courses")


async def get_course_attendance(faculty_id: str, course_id: str) -> dict:
    return await _get(f"/faculty/{faculty_id}/course/{course_id}/attendance")


async def get_faculty_assignments(faculty_id: str) -> dict:
    return await _get(f"/faculty/{faculty_id}/assignments")


async def get_course_students(faculty_id: str, course_id: str) -> dict:
    return await _get(f"/faculty/{faculty_id}/course/{course_id}/students")


async def get_course_performance() -> dict:
    return await _get("/faculty/course-performance")


async def get_faculty_ungraded() -> dict:
    data = await _get("/faculty/ungraded")
    if not isinstance(data, dict):
        return data if data else {}

    # Ensure we have the best list under 'top_ungraded_assignments'
    summary = data.get("summary")
    if isinstance(summary, dict):
        if "top_ungraded_assignments" not in data and summary.get("top_ungraded_assignments"):
            data["top_ungraded_assignments"] = summary["top_ungraded_assignments"]
        if data.get("total_ungraded") is None and summary.get("total_ungraded") is not None:
            data["total_ungraded"] = summary["total_ungraded"]

    if "top_ungraded_assignments" not in data:
        if data.get("ungraded_assignments"):
            data["top_ungraded_assignments"] = data["ungraded_assignments"]
        elif data.get("assignments"):
            data["top_ungraded_assignments"] = data["assignments"]

    # Trim to at most 10 to keep prompt small and latency low
    assignments = data.get("top_ungraded_assignments", [])
    if assignments:
        data["top_ungraded_assignments"] = assignments[:10]
        data["total_ungraded"] = len(assignments)  # show actual total but send only top 10

    return data


async def get_faculty_teaching(faculty_id: str) -> dict:
    return await _get(f"/faculty/{faculty_id}/teaching")


async def get_student_instructors(student_id: str) -> dict:
    return await _get(f"/student/{student_id}/instructors")


async def get_admin_salary_unpaid() -> list:
    return await _get("/admin/salary-unpaid")


async def get_admin_late_fees_total() -> dict:
    return await _get("/admin/finance/late-fees-total")


async def get_course_average_grade(faculty_id: str, course_id: str) -> dict:
    return await _get(f"/faculty/{faculty_id}/course/{course_id}/average-grade")


async def get_missed_midterm_students(faculty_id: str, course_id: str) -> dict:
    return await _get(f"/faculty/{faculty_id}/course/{course_id}/missed-midterm")


async def get_course_low_attendance(faculty_id: str, course_id: str) -> dict:
    return await _get(f"/faculty/{faculty_id}/course/{course_id}/low-attendance")


async def get_course_top_marks(faculty_id: str, course_id: str) -> dict:
    return await _get(f"/faculty/{faculty_id}/course/{course_id}/top-marks")


_COURSE_ID_PATTERN = re.compile(r"[A-Z]{2,4}-\d+", re.I)


def extract_course_id_from_message(message: str) -> Optional[str]:
    match = _COURSE_ID_PATTERN.search(message)
    return match.group(0).upper() if match else None


async def get_all_faculty_attendance(faculty_id: str) -> dict:
    courses_data = await get_faculty_courses(faculty_id)
    courses = courses_data.get("courses", [])
    if not courses:
        return {"faculty_id": faculty_id, "attendance_by_course": []}

    async def _fetch(course: dict) -> dict:
        course_key = course.get("course_id") or course.get("course_code")
        if not course_key:
            return {}
        att = await get_course_attendance(faculty_id, course_key)
        att["course_name"] = course.get("course_name", "")
        return att

    results = await asyncio.gather(*[_fetch(course) for course in courses])
    all_attendance = [item for item in results if item]
    return {"faculty_id": faculty_id, "attendance_by_course": all_attendance}


async def get_all_faculty_at_risk(faculty_id: str) -> dict:
    courses_data = await get_faculty_courses(faculty_id)
    courses = courses_data.get("courses", [])
    if not courses:
        return {"faculty_id": faculty_id, "at_risk_by_course": [], "total_at_risk": 0}

    async def _fetch(course: dict) -> dict | None:
        course_key = course.get("course_id") or course.get("course_code")
        if not course_key:
            return None
        risk = await get_course_students(faculty_id, course_key)
        course_id = risk.get("course_id") or course_key
        course_name = course.get("course_name", "") or risk.get("course_name", "")

        at_risk = risk.get("at_risk_students")
        if at_risk:
            source_students = at_risk
        else:
            all_students = risk.get("students", [])
            source_students = [
                student for student in all_students
                if isinstance(student, dict) and student.get("at_risk")
            ]

        compact_students = []
        for student in source_students:
            if isinstance(student, dict) and student.get("student_id"):
                reason = student.get("reason", "")
                # Determine if it's low attendance based on available fields
                if student.get("attendance_percentage", 100) < 75:
                    reason = reason or "Low attendance"
                elif student.get("gpa", 4.0) < 2.5:
                    reason = reason or "Academic performance (GPA)"
                compact_students.append({
                    "student_id": student["student_id"],
                    "student_name": student.get("student_name") or student.get("name", ""),
                    "reason": reason
                })

        if not compact_students:
            return None

        return {
            "course_id": course_id,
            "course_name": course_name,
            "at_risk_students": compact_students,
        }

    results = await asyncio.gather(*[_fetch(course) for course in courses])
    at_risk_by_course = [item for item in results if item]
    total_at_risk = sum(len(course.get("at_risk_students", [])) for course in at_risk_by_course)
    # Build a flat top-10 list for the prompt
    top_at_risk = []
    for course in at_risk_by_course:
        for stu in course["at_risk_students"]:
            top_at_risk.append({
                "student_id": stu["student_id"],
                "student_name": stu["student_name"],
                "reason": stu.get("reason", ""),
                "course_name": course["course_name"]
            })
    top_at_risk = top_at_risk[:10]
    return {
        "faculty_id": faculty_id,
        "at_risk_by_course": at_risk_by_course,
        "total_at_risk": total_at_risk,
        "top_at_risk_students": top_at_risk,
    }


def _faculty_attendance_is_empty(data: dict) -> bool:
    courses = data.get("attendance_by_course", [])
    if not courses:
        return True
    total_low = sum(len(c.get("low_attendance_students", [])) for c in courses)
    return total_low == 0


def _faculty_at_risk_is_empty(data: dict) -> bool:
    courses = data.get("at_risk_by_course", [])
    if not courses:
        return True
    total = sum(len(c.get("at_risk_students", [])) for c in courses)
    return total == 0


def _faculty_ungraded_is_empty(data: dict) -> bool:
    total = data.get("total_ungraded", 0)
    by_course = data.get("by_course", [])
    return total == 0 and not by_course


async def get_global_low_attendance_summary() -> dict:
    """University-wide low-attendance students (faculty fallback)."""
    risk = await get_admin_at_risk()
    students = risk.get("at_risk_students", [])
    low = [
        s for s in students
        if "attendance" in str(s.get("reason", "")).lower()
    ]
    if not low:
        low = students
    return {
        "source": "global_fallback",
        "low_attendance_students": low,
        "total_low_attendance": len(low),
    }


async def get_global_at_risk_summary() -> dict:
    """University-wide at-risk students (faculty fallback)."""
    risk = await get_admin_at_risk()
    students = risk.get("at_risk_students", [])
    return {
        "source": "global_fallback",
        "at_risk_students": students,
        "total_at_risk": len(students),
    }


async def get_faculty_attendance_with_fallback(faculty_id: str) -> dict:
    data = await get_all_faculty_attendance(faculty_id)
    if _faculty_attendance_is_empty(data):
        global_data = await get_global_low_attendance_summary()
        return {
            "faculty_id": faculty_id,
            "attendance_by_course": [],
            "global_fallback": global_data,
        }
    return data


async def get_faculty_at_risk_with_fallback(faculty_id: str) -> dict:
    data = await get_all_faculty_at_risk(faculty_id)
    if _faculty_at_risk_is_empty(data):
        global_data = await get_global_at_risk_summary()
        return {
            "faculty_id": faculty_id,
            "at_risk_by_course": [],
            "global_fallback": global_data,
        }
    return data


async def get_faculty_ungraded_with_fallback(faculty_id: str) -> dict:
    data = await get_faculty_ungraded()
    if _faculty_ungraded_is_empty(data):
        return {
            "faculty_id": faculty_id,
            "source": "global_fallback",
            "total_ungraded": 0,
            "by_course": [],
            "message": "No ungraded assignments found in the system.",
        }
    return data


# ── Admin APIs ──
async def get_admin_student_stats() -> dict:
    return await _get("/admin/statistics/students")


async def get_admin_admission_stats() -> dict:
    return await _get("/admin/statistics/admissions")


async def get_admin_fee_stats() -> dict:
    return await _get("/admin/statistics/fees")


async def get_admin_department_stats() -> dict:
    return await _get("/admin/statistics/departments")


async def get_admin_at_risk() -> dict:
    return await _get("/admin/at-risk")


async def get_admin_overall_stats() -> dict:
    return await _get("/admin/overall-stats")


async def get_admin_finance_department_stats() -> dict:
    return await _get("/admin/finance/department-stats")


async def get_admin_finance_pending_fees() -> dict:
    return await _get("/admin/finance/pending-fees")


async def get_admin_finance_scholarship_stats() -> dict:
    return await _get("/admin/finance/scholarship-stats")


async def get_admin_finance_summary() -> dict:
    return await _get("/admin/finance/summary")


FINANCE_INTENTS = {
    "admin_fees",
    "admin_finance_department",
    "admin_finance_pending",
    "admin_finance_scholarship",
    "admin_finance_summary",
    "admin_teacher_salary",
    "admin_late_fees",
}

STUDENT_RESTRICTED_INTENTS = FINANCE_INTENTS | {
    "admin_students",
    "admin_admissions",
    "admin_departments",
    "department_stats",
    "admin_at_risk",
    "admin_overall",
    "faculty_attendance",
    "faculty_ungraded",
    "faculty_at_risk",
    "faculty_courses",
    "faculty_performance",
    "faculty_teaching",
    "faculty_course_low_attendance",
    "faculty_course_top_marks",
    "faculty_missed_midterm",
    "faculty_course_average_grade",
}

FACULTY_RESTRICTED_INTENTS = {
    "admin_students",
    "admin_admissions",
    "admin_departments",
    "admin_at_risk",
    "admin_overall",
    "admin_fees",
    "admin_finance_department",
    "admin_finance_pending",
    "admin_finance_scholarship",
    "admin_finance_summary",
    "admin_teacher_salary",        # ← added
    "admin_late_fees",             # ← added
    "attendance",
    "results",
    "gpa",
    "fees",
    "courses",
    "timetable",
    "assignments",
    "exams",
    "study_plan",
    "student_instructors",
    "student_current_semester",
    "student_grade_calculation",
}


def extract_day_from_message(message: str) -> Optional[str]:
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    lower = message.lower()
    for day in days:
        if day in lower:
            return day.capitalize()
    return None


async def fetch_erp_data(intent: str, uid: str, role: str, message: str) -> Tuple[str, bool]:
    """
    Fetch ERP data for a classified intent.
    Returns (erp_data_json_or_message, access_denied).
    """
    intent = resolve_role_intent(role, intent, message)

    allowed, denial_msg = check_chat_access(role, intent, message, uid)
    if not allowed:
        return denial_msg or "Access denied.", True

    role_lower = normalize_role(role)
    query_uid = resolve_query_user_id(role, uid, intent, message)

    if role_lower == "student":
        scope_ok, scope_denial = check_student_data_scope(intent, message, uid)
        if not scope_ok:
            return scope_denial or "Access denied.", True

    if role_lower == "student" and intent in STUDENT_RESTRICTED_INTENTS:
        return (
            "Access denied: Finance and administrative data is restricted to authorized staff only.",
            True,
        )

    if role_lower == "faculty" and intent in FACULTY_RESTRICTED_INTENTS:
        return (
            "Access denied: As a faculty member, you can only access data related to your courses and students.",
            True,
        )

    if role_lower == "faculty" and intent in FINANCE_INTENTS:
        return (
            "Access denied: Financial reports are restricted to Admin and Finance Officer roles.",
            True,
        )

    try:
        if intent == "attendance":
            data = await get_student_attendance(query_uid)
        elif intent == "results":
            data = await get_student_results(query_uid)
        elif intent == "gpa":
            data = await get_student_gpa(query_uid)
        elif intent == "fees":
            if not _is_valid_student_id(query_uid):
                logger.error(
                    "[FEES] Invalid student ID for fees lookup: %r (role=%s)",
                    query_uid,
                    role_lower,
                )
                return (
                    f"Error: Cannot fetch student fees for ID '{query_uid}'. "
                    "Student fee records require a valid STU-* student ID.",
                    False,
                )
            data = await get_student_fees(query_uid)
            logger.info("[FEES DEBUG] Raw fee data: %s", data)
            logger.info(
                "[FEES DEBUG] Data type: %s, Length: %s",
                type(data),
                len(str(data)),
            )
        elif intent == "courses":
            data = await get_student_courses(query_uid)
        elif intent == "timetable":
            day = extract_day_from_message(message)
            if day:
                data = await get_student_timetable_by_day(query_uid, day)
            else:
                data = await get_student_timetable(query_uid)
        elif intent == "assignments":
            if re.search(r"this week|upcoming|due", message, re.I):
                data = await get_student_upcoming_assignments(query_uid)
            else:
                data = await get_student_assignments(query_uid)
        elif intent == "exams":
            data = await get_student_upcoming_exams(query_uid)
        elif intent == "faculty_attendance":
            data = await get_faculty_attendance_with_fallback(query_uid)
        elif intent == "faculty_ungraded":
            data = await get_faculty_ungraded_with_fallback(query_uid)
        elif intent == "faculty_at_risk":
            data = await get_faculty_at_risk_with_fallback(query_uid)
        elif intent == "faculty_courses":
            data = await get_faculty_courses(query_uid)
        elif intent == "faculty_performance":
            data = await get_course_performance()
        elif intent == "faculty_teaching":
            data = await get_faculty_teaching(query_uid)
        elif intent == "student_instructors":
            data = await get_student_instructors(query_uid)
        elif intent == "admin_students":
            data = await get_admin_student_stats()
        elif intent == "admin_admissions":
            data = await get_admin_admission_stats()
        elif intent == "admin_fees":
            data = await get_admin_fee_stats()
            logger.info("[FEES DEBUG] Raw admin fee data: %s", data)
            logger.info(
                "[FEES DEBUG] Data type: %s, Length: %s",
                type(data),
                len(str(data)),
            )
        elif intent == "admin_departments":
            data = await get_admin_department_stats()
        elif intent == "department_stats":
            data = await get_admin_department_stats()
        elif intent == "admin_at_risk":
            data = await get_admin_at_risk()
        elif intent == "admin_overall":
            data = await get_admin_overall_stats()
        elif intent == "admin_finance_department":
            data = await get_admin_finance_department_stats()
        elif intent == "admin_finance_pending":
            data = await get_admin_finance_pending_fees()
        elif intent == "admin_finance_scholarship":
            data = await get_admin_finance_scholarship_stats()
        elif intent == "admin_finance_summary":
            data = await get_admin_finance_summary()
        elif intent == "student_current_semester":
            profile = await get_student_profile(query_uid)
            semester = profile.get("current_semester") or profile.get("semester")
            data = {"current_semester": semester, "student_id": query_uid}
        elif intent == "student_grade_calculation":
            data = await get_student_results(query_uid)
        elif intent == "faculty_course_low_attendance":
            course_id = extract_course_id_from_message(message)
            if course_id:
                data = await get_course_low_attendance(query_uid, course_id)
            else:
                data = await get_faculty_at_risk_with_fallback(query_uid)
        elif intent == "faculty_course_top_marks":
            course_id = extract_course_id_from_message(message)
            if course_id:
                data = await get_course_top_marks(query_uid, course_id)
            else:
                data = {"error": "Course ID not found in message. Include a code like CS-302."}
        elif intent == "faculty_course_average_grade":
            course_id = extract_course_id_from_message(message)
            if course_id:
                data = await get_course_average_grade(query_uid, course_id)
            else:
                data = {"error": "Course ID not found in message. Include a code like CS-302."}
        elif intent == "faculty_missed_midterm":
            course_id = extract_course_id_from_message(message)
            if course_id:
                data = await get_missed_midterm_students(query_uid, course_id)
            else:
                data = {"error": "Course ID not found in message. Include a code like CS-302."}
        elif intent == "admin_teacher_salary":
            data = await get_admin_salary_unpaid()
        elif intent == "admin_late_fees":
            data = await get_admin_late_fees_total()
        else:
            return "", False

        # For faculty_at_risk and faculty_ungraded, skip trim because we already formatted cleanly
        if intent in ("faculty_at_risk", "faculty_ungraded"):
            return json.dumps(data), False

        data = trim_erp_payload_for_llm(data, intent, message)
        return json.dumps(data), False
    except Exception as exc:
        logger.error(
            "[FEES] ERP fetch failed for intent=%s uid=%s: %s",
            intent,
            query_uid,
            exc,
            exc_info=True,
        )
        return f"Error: {exc}", False