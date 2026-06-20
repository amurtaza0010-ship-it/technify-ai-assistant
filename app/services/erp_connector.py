"""ERP Connector — calls the ERP (mock or real) REST APIs using httpx."""
import httpx
from app.config import get_settings

settings = get_settings()
BASE = settings.ERP_API_BASE_URL
if not BASE.endswith("/api/v1") and not BASE.endswith("/api/v1/"):
    BASE = BASE.rstrip("/") + "/api/v1"

async def _get(path: str) -> dict:
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(f"{BASE}{path}")
        r.raise_for_status()
        return r.json()

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
    all_attendance = []
    for c in courses:
        att = await get_course_attendance(faculty_id, c["course_code"])
        att["course_name"] = c["course_name"]
        all_attendance.append(att)
    return {"faculty_id": faculty_id, "attendance_by_course": all_attendance}

async def get_all_faculty_at_risk(faculty_id: str) -> dict:
    courses_data = await get_faculty_courses(faculty_id)
    courses = courses_data.get("courses", [])
    all_at_risk = []
    for c in courses:
        risk = await get_course_students(faculty_id, c["course_code"])
        risk["course_name"] = c["course_name"]
        all_at_risk.append(risk)
    return {"faculty_id": faculty_id, "at_risk_by_course": all_at_risk}

# ── Admin APIs ──
async def get_admin_student_stats() -> dict:
    return await _get("/admin/statistics/students")

async def get_admin_admission_stats() -> dict:
    return await _get("/admin/statistics/admissions")

async def get_admin_fee_stats() -> dict:
    return await _get("/admin/statistics/fees")

async def get_admin_department_stats() -> dict:
    return await _get("/admin/statistics/departments")
