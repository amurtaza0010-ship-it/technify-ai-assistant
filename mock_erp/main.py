"""Mock ERP Server — simulates the Laravel ERP backend for development.
Run with: uvicorn mock_erp.main:app --port 8801 --reload
"""
import json
import logging
import os
import time
from collections import defaultdict

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from mock_erp.routes import router

load_dotenv()

logger = logging.getLogger("taia.mock_erp.main")

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "synthetic")

_cache: dict = {}
_indexes: dict = {}
_indexes_built = False


def _parse_cors_origins() -> list[str]:
    if os.getenv("CORS_ALLOW_ALL", "true").lower() in ("1", "true", "yes"):
        return ["*"]
    raw = os.getenv(
        "CORS_ORIGINS",
        "http://127.0.0.1:5000,http://localhost:5000",
    )
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _load_data(name: str):
    path = os.path.join(DATA_DIR, f"{name}.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def get_data(name: str):
    if name not in _cache:
        _cache[name] = _load_data(name)
    return _cache[name]


def _build_indexes() -> None:
    """Build course/instructor indexes for teaching endpoints."""
    global _indexes_built
    if _indexes_built:
        return

    t0 = time.perf_counter()
    courses = get_data("courses")
    students = get_data("students")

    course_by_id = {}
    courses_by_faculty: dict[str, list] = defaultdict(list)
    instructor_index: dict[str, list] = defaultdict(list)
    faculty_instructor_map: dict[str, str] = {}

    for course in courses:
        if not isinstance(course, dict):
            continue
        course_id = course.get("course_id")
        if course_id:
            course_by_id[course_id] = course

        faculty_id = course.get("faculty_id", "")
        if faculty_id:
            courses_by_faculty[faculty_id].append(course)
            instructor = course.get("instructor", "")
            if instructor and faculty_id not in faculty_instructor_map:
                faculty_instructor_map[faculty_id] = instructor

        instructor = course.get("instructor", "")
        if instructor:
            instructor_index[instructor].append(course)

    _indexes["course_by_id"] = course_by_id
    _indexes["courses_by_faculty"] = dict(courses_by_faculty)
    _indexes["instructor_index"] = dict(instructor_index)
    _indexes["faculty_instructor_map"] = faculty_instructor_map
    _indexes["students_by_id"] = {
        s["student_id"]: s for s in students if isinstance(s, dict) and s.get("student_id")
    }

    _indexes_built = True
    logger.info("Teaching indexes built in %.0fms", (time.perf_counter() - t0) * 1000)


app = FastAPI(title="Mock Technify ERP", version="1.0.0", docs_url="/docs")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api/v1")


@app.on_event("startup")
def preload_mock_erp_data():
    from mock_erp.generate_data import ensure_instructor_fields
    from mock_erp.routes import warmup_cache, warmup_extended_cache
    import mock_erp.routes as erp_routes

    ensure_instructor_fields()

    _cache.clear()
    erp_routes._cache.clear()
    erp_routes._indexes_built = False
    erp_routes._indexes.clear()
    erp_routes._extended_indexes_built = False
    global _indexes_built
    _indexes_built = False
    _indexes.clear()

    warmup_cache()
    warmup_extended_cache()
    _build_indexes()

    logger.info("Mock ERP startup: demo data enriched and indexes rebuilt.")


@app.get("/")
def root():
    return {"service": "Mock Technify ERP", "status": "running"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/faculty/{faculty_id}/teaching")
def get_faculty_teaching(faculty_id: str):
    """Return courses taught by a faculty member with instructor names."""
    _build_indexes()
    courses = _indexes["courses_by_faculty"].get(faculty_id, [])
    return {
        "faculty_id": faculty_id,
        "courses": [
            {
                "course_id": course.get("course_id"),
                "course_name": course.get("course_name"),
                "instructor": course.get("instructor", ""),
            }
            for course in courses
            if isinstance(course, dict)
        ],
    }


@app.get("/api/v1/student/{student_id}/instructors")
def get_student_instructors(student_id: str):
    """Return enrolled courses and their instructors for a student."""
    _build_indexes()
    student = _indexes["students_by_id"].get(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    course_by_id = _indexes["course_by_id"]
    courses_out = []
    for enrollment in student.get("enrollments", []):
        if not isinstance(enrollment, dict):
            continue
        course = course_by_id.get(enrollment.get("course_id"))
        if not course:
            continue
        instructor = course.get("instructor", "")
        if not instructor:
            continue
        courses_out.append({
            "course_id": course.get("course_id"),
            "course_name": course.get("course_name"),
            "instructor": instructor,
        })

    return {"student_id": student_id, "courses": courses_out}
