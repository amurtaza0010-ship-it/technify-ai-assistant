"""Mock ERP API routes — serves synthetic data as if it were the real Laravel ERP."""
import json
import logging
import os
import random
import time
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException

logger = logging.getLogger("taia.mock_erp")

router = APIRouter()
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "synthetic")

_cache: dict = {}
_indexes: dict = {}
_indexes_built = False

_DATA_FILES = (
    "students",
    "faculty",
    "courses",
    "attendance",
    "student_attendance_summary",
    "exams",
    "student_performance",
    "timetable",
    "assignments",
    "course_performance",
    "course_analytics",
    "faculty_dashboard",
    "fee_stats",
    "at_risk_students",
    "upcoming_exams",
)


def _load(name):
    path = os.path.join(DATA_DIR, f"{name}.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_data(name):
    if name not in _cache:
        _cache[name] = _load(name)
    return _cache[name]


def _build_indexes():
    global _indexes_built
    if _indexes_built:
        return
    t0 = time.perf_counter()
    students = get_data("students")
    _indexes["students_by_id"] = {s["student_id"]: s for s in students}
    faculty = get_data("faculty")
    _indexes["faculty_by_id"] = {f["faculty_id"]: f for f in faculty}

    attendance = get_data("attendance")
    by_student_att = defaultdict(list)
    by_course_att = defaultdict(list)
    for record in attendance:
        by_student_att[record["student_id"]].append(record)
        by_course_att[record["course_id"]].append(record)
    _indexes["attendance_by_student"] = dict(by_student_att)
    _indexes["attendance_by_course"] = dict(by_course_att)

    exams = get_data("exams")
    by_student_exams = defaultdict(list)
    by_course_exams = defaultdict(list)
    for exam in exams:
        by_student_exams[exam["student_id"]].append(exam)
        by_course_exams[exam["course_id"]].append(exam)
    _indexes["exams_by_student"] = dict(by_student_exams)
    _indexes["exams_by_course"] = dict(by_course_exams)

    courses = get_data("courses")
    by_faculty_courses = defaultdict(list)
    for course in courses:
        by_faculty_courses[course["faculty_id"]].append(course)
    _indexes["courses_by_faculty"] = dict(by_faculty_courses)

    timetable = get_data("timetable")
    by_student_tt = defaultdict(list)
    for entry in timetable:
        by_student_tt[entry["student_id"]].append(entry)
    _indexes["timetable_by_student"] = dict(by_student_tt)

    assignments = get_data("assignments")
    by_faculty_assignments = defaultdict(list)
    for assignment in assignments:
        by_faculty_assignments[assignment.get("faculty_id", "")].append(assignment)
    _indexes["assignments_by_faculty"] = dict(by_faculty_assignments)

    attendance_summary = get_data("student_attendance_summary")
    by_course_summary = defaultdict(list)
    for row in attendance_summary:
        by_course_summary[row["course_id"]].append(row)
    _indexes["attendance_summary_by_course"] = dict(by_course_summary)

    student_performance = get_data("student_performance")
    by_course_performance = defaultdict(list)
    for row in student_performance:
        by_course_performance[row["course_id"]].append(row)
    _indexes["performance_by_course"] = dict(by_course_performance)

    _indexes_built = True
    logger.info("Mock ERP indexes built in %.0fms", (time.perf_counter() - t0) * 1000)


def warmup_cache():
    """Preload JSON datasets and indexes at startup for sub-200ms responses."""
    t0 = time.perf_counter()
    for name in _DATA_FILES:
        get_data(name)
    _build_indexes()
    logger.info("Mock ERP cache warmed in %.0fms", (time.perf_counter() - t0) * 1000)


_EXTENDED_DATA_FILES = ("salaries", "late_fees", "exam_attendance", "admin_stats")
_extended_indexes_built = False


def _build_extended_indexes():
    """Build supplemental indexes for new ERP endpoints (additive only)."""
    global _extended_indexes_built
    if _extended_indexes_built:
        return

    for name in _EXTENDED_DATA_FILES:
        get_data(name)

    salaries = get_data("salaries")
    if isinstance(salaries, list):
        _indexes["salaries_unpaid"] = [
            row for row in salaries
            if isinstance(row, dict) and not row.get("collected")
        ]
    else:
        _indexes["salaries_unpaid"] = []

    exam_attendance = get_data("exam_attendance")
    if isinstance(exam_attendance, dict):
        _indexes["exam_attendance_by_course"] = exam_attendance
    else:
        _indexes["exam_attendance_by_course"] = {}

    course_performance = get_data("course_performance")
    if isinstance(course_performance, list):
        _indexes["course_performance_by_course"] = {
            row["course_id"]: row
            for row in course_performance
            if isinstance(row, dict) and row.get("course_id")
        }
    else:
        _indexes["course_performance_by_course"] = {}

    _extended_indexes_built = True
    logger.info("Mock ERP extended indexes built.")


def warmup_extended_cache():
    """Preload extended datasets and supplemental indexes."""
    t0 = time.perf_counter()
    for name in _EXTENDED_DATA_FILES:
        get_data(name)
    _build_extended_indexes()
    logger.info("Mock ERP extended cache warmed in %.0fms", (time.perf_counter() - t0) * 1000)

# ──────────────── AUTH ────────────────
from app.auth.jwt_handler import create_token

@router.post("/auth/login")
def login(body: dict):
    """Issue a JWT token for testing. Send: {user_id, role}"""
    _build_indexes()
    uid = body.get("user_id", "STU-0001")
    role = body.get("role", "student")
    name, dept, email = "", "", ""
    if role == "student":
        s = _indexes["students_by_id"].get(uid)
        if s:
            name, dept, email = s["name"], s["department"], s["email"]
    elif role == "faculty":
        f = _indexes["faculty_by_id"].get(uid)
        if f:
            name, dept, email = f["name"], f["department"], f["email"]
    else:
        name = "Admin User"
    token = create_token(uid, role, name, dept, email)
    return {"token": token, "user_id": uid, "role": role, "name": name}

# ──────────────── STUDENT ENDPOINTS ────────────────
@router.get("/student/{student_id}")
def get_student(student_id: str):
    _build_indexes()
    s = _indexes["students_by_id"].get(student_id)
    if not s:
        raise HTTPException(404, "Student not found")
    return s

@router.get("/student/{student_id}/attendance")
def get_student_attendance(student_id: str):
    _build_indexes()
    records = _indexes["attendance_by_student"].get(student_id, [])
    if not records:
        return {"student_id": student_id, "overall_percentage": 0, "courses": []}
    # Group by course
    courses = {}
    for r in records:
        cid = r["course_id"]
        if cid not in courses:
            courses[cid] = {"course_id": cid, "course_name": r["course_name"], "present": 0, "absent": 0, "late": 0, "total": 0}
        courses[cid]["total"] += 1
        if r["status"] == "Present":
            courses[cid]["present"] += 1
        elif r["status"] == "Absent":
            courses[cid]["absent"] += 1
        else:
            courses[cid]["late"] += 1
    course_list = []
    for c in courses.values():
        pct = round((c["present"] + c["late"] * 0.5) / max(c["total"], 1) * 100, 1)
        c["percentage"] = pct
        course_list.append(c)
    total_p = sum(c["present"] for c in courses.values())
    total_l = sum(c["late"] for c in courses.values())
    total_all = sum(c["total"] for c in courses.values())
    overall = round((total_p + total_l * 0.5) / max(total_all, 1) * 100, 1)
    return {"student_id": student_id, "overall_percentage": overall, "courses": course_list}

@router.get("/student/{student_id}/results")
def get_student_results(student_id: str):
    _build_indexes()
    records = _indexes["exams_by_student"].get(student_id, [])
    return {"student_id": student_id, "results": records}

@router.get("/student/{student_id}/gpa")
def get_student_gpa(student_id: str):
    _build_indexes()
    s = _indexes["students_by_id"].get(student_id)
    if not s:
        raise HTTPException(404, "Student not found")
    return {"gpa": s.get("gpa", s.get("cgpa", 0.0))}

@router.get("/student/{student_id}/courses")
def get_student_courses(student_id: str):
    _build_indexes()
    s = _indexes["students_by_id"].get(student_id)
    if not s:
        raise HTTPException(404, "Student not found")
    all_courses = get_data("courses")
    dept_courses = [c for c in all_courses if c["department"] == s["department"] and c["semester"] <= s["semester"]]
    return {"student_id": student_id, "courses": dept_courses[:6]}

@router.get("/student/{student_id}/timetable")
def get_student_timetable(student_id: str):
    _build_indexes()
    s = _indexes["students_by_id"].get(student_id)
    if not s:
        raise HTTPException(404, "Student not found")
    records = _indexes["timetable_by_student"].get(student_id, [])
    if not records:
        all_courses = get_data("courses")
        dept_courses = [c for c in all_courses if c["department"] == s["department"] and c["semester"] <= s["semester"]][:6]
        timetable = []
        for c in dept_courses:
            timetable.append({"course": c["course_name"], "code": c["course_code"], "days": c["schedule"]["days"], "time": c["schedule"]["time"], "room": c["schedule"]["room"], "faculty": c["faculty_name"]})
        return {"student_id": student_id, "timetable": timetable}
    seen = set()
    timetable = []
    for t in records:
        key = (t["course_id"], t["day"], t["time_slot"])
        if key in seen:
            continue
        seen.add(key)
        timetable.append({
            "course": t["course_name"],
            "code": t["course_code"],
            "day": t["day"],
            "time": t["time_slot"],
            "room": t["room"],
            "faculty": t["faculty_name"],
        })
    return {"student_id": student_id, "timetable": timetable}

@router.get("/student/{student_id}/timetable/day/{day}")
def get_student_timetable_by_day(student_id: str, day: str):
    s = next((s for s in get_data("students") if s["student_id"] == student_id), None)
    if not s:
        raise HTTPException(404, "Student not found")
    day_normalized = day.strip().capitalize()
    records = [
        t for t in get_data("timetable")
        if t["student_id"] == student_id and t["day"].lower() == day_normalized.lower()
    ]
    classes = [{
        "course": t["course_name"],
        "code": t["course_code"],
        "time": t["time_slot"],
        "room": t["room"],
        "faculty": t["faculty_name"],
        "day": t["day"],
    } for t in records]
    return {"student_id": student_id, "day": day_normalized, "classes": classes}

@router.get("/student/{student_id}/exams/upcoming")
def get_student_upcoming_exams(student_id: str):
    s = next((s for s in get_data("students") if s["student_id"] == student_id), None)
    if not s:
        raise HTTPException(404, "Student not found")
    today = datetime.now().strftime("%Y-%m-%d")
    upcoming = [
        e for e in get_data("upcoming_exams")
        if e["student_id"] == student_id and e["date"] >= today
    ]
    if not upcoming:
        raise HTTPException(404, "No upcoming exams found")
    upcoming.sort(key=lambda x: x["date"])
    nearest = upcoming[0]
    return {
        "student_id": student_id,
        "subject": nearest["subject"],
        "course_code": nearest["course_code"],
        "exam_type": nearest["exam_type"],
        "date": nearest["date"],
        "time": nearest.get("time"),
        "room": nearest.get("room"),
    }

@router.get("/student/{student_id}/assignments/upcoming")
def get_student_upcoming_assignments(student_id: str):
    s = next((s for s in get_data("students") if s["student_id"] == student_id), None)
    if not s:
        raise HTTPException(404, "Student not found")
    today = datetime.now()
    week_end = today + timedelta(days=7)
    upcoming = []
    for a in get_data("assignments"):
        if a["student_id"] != student_id:
            continue
        due = datetime.strptime(a["due_date"], "%Y-%m-%d")
        if today.date() <= due.date() <= week_end.date():
            upcoming.append({
                "assignment_id": a["assignment_id"],
                "course": a["course_name"],
                "title": a["assignment_title"],
                "due_date": a["due_date"],
                "status": a["status"],
            })
    upcoming.sort(key=lambda x: x["due_date"])
    return {"student_id": student_id, "assignments_due_this_week": upcoming}

@router.get("/student/{student_id}/assignments")
def get_student_assignments(student_id: str):
    exams = [r for r in get_data("exams") if r["student_id"] == student_id and "Assignment" in r["exam_type"]]
    pending = [{"course": e["course_name"], "assignment": e["exam_type"], "status": "Submitted", "marks": e["marks_obtained"], "total": e["total_marks"]} for e in exams]
    # Add some fake pending ones
    pending.append({"course": "Web Engineering", "assignment": "Assignment 3", "status": "Pending", "due_date": (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")})
    pending.append({"course": "Database Systems", "assignment": "Project Proposal", "status": "Pending", "due_date": (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d")})
    return {"student_id": student_id, "assignments": pending}

@router.get("/student/{student_id}/fees")
def get_student_fees(student_id: str):
    _build_indexes()
    s = _indexes["students_by_id"].get(student_id)
    if not s:
        raise HTTPException(404, "Student not found")
    return {"student_id": student_id, "fee_status": s["fee_status"], "fee_amount": s["fee_amount"], "due_date": s["fee_due_date"], "program": s["department"]}

# ──────────────── FACULTY ENDPOINTS ────────────────
@router.get("/faculty/{faculty_id}/courses")
def get_faculty_courses(faculty_id: str):
    _build_indexes()
    courses = _indexes["courses_by_faculty"].get(faculty_id, [])
    return {"faculty_id": faculty_id, "courses": courses}

@router.get("/faculty/{faculty_id}/course/{course_id}/attendance")
def get_course_attendance(faculty_id: str, course_id: str):
    _build_indexes()
    summary_rows = _indexes["attendance_summary_by_course"].get(course_id, [])
    if summary_rows:
        result = []
        for row in summary_rows:
            result.append({
                "student_id": row["student_id"],
                "student_name": row["student_name"],
                "course_code": row.get("course_code", ""),
                "course_name": row.get("course_name", ""),
                "attendance_percentage": row["attendance_percentage"],
                "total_classes": row["total_classes"],
                "attended_classes": row["attended_classes"],
                "absent_classes": row["absent_classes"],
                "late_count": row["late_count"],
                "warning_flag": row["warning_flag"],
                "present": row["attended_classes"] - row["late_count"],
                "absent": row["absent_classes"],
                "late": row["late_count"],
                "total": row["total_classes"],
                "percentage": row["attendance_percentage"],
            })
        low = [s for s in result if s["percentage"] < 75]
        return {
            "course_id": course_id,
            "total_students": len(result),
            "low_attendance_students": low,
            "all_students": result,
        }

    records = _indexes["attendance_by_course"].get(course_id, [])
    students_att = {}
    for r in records:
        sid = r["student_id"]
        if sid not in students_att:
            students_att[sid] = {"student_id": sid, "student_name": r["student_name"], "present": 0, "absent": 0, "late": 0, "total": 0}
        students_att[sid]["total"] += 1
        if r["status"] == "Present":
            students_att[sid]["present"] += 1
        elif r["status"] == "Absent":
            students_att[sid]["absent"] += 1
        else:
            students_att[sid]["late"] += 1
    result = []
    for sa in students_att.values():
        sa["percentage"] = round((sa["present"] + sa["late"]*0.5) / max(sa["total"],1) * 100, 1)
        sa["attendance_percentage"] = sa["percentage"]
        sa["warning_flag"] = sa["percentage"] < 75
        result.append(sa)
    low = [s for s in result if s["percentage"] < 75]
    return {"course_id": course_id, "total_students": len(result), "low_attendance_students": low, "all_students": result}

@router.get("/faculty/{faculty_id}/assignments")
def get_faculty_assignments(faculty_id: str):
    _build_indexes()
    courses = _indexes["courses_by_faculty"].get(faculty_id, [])
    ungraded = []
    for c in courses:
        ungraded.append({"course": c["course_name"], "assignment": "Assignment 2", "submissions": random.randint(30, 50), "graded": 0})
    return {"faculty_id": faculty_id, "ungraded_assignments": ungraded}

@router.get("/faculty/course-performance")
def get_course_performance():
    performance = get_data("course_performance")
    if not performance:
        performance = get_data("course_analytics")
    if not performance:
        raise HTTPException(404, "Course performance data not found")
    dashboard = get_data("faculty_dashboard")
    attendance_summary = get_data("student_attendance_summary")
    course_attendance = {}
    for row in attendance_summary:
        cid = row["course_id"]
        if cid not in course_attendance:
            course_attendance[cid] = []
        course_attendance[cid].append(row["attendance_percentage"])
    enriched = []
    for course in performance:
        cid = course["course_id"]
        row = dict(course)
        if cid in course_attendance and "average_attendance" not in row:
            row["average_attendance"] = round(
                sum(course_attendance[cid]) / len(course_attendance[cid]), 1
            )
        enriched.append(row)
    payload = {"courses": enriched}
    if isinstance(dashboard, dict) and dashboard:
        payload["faculty_dashboard"] = dashboard
    return payload

@router.get("/faculty/ungraded")
def get_ungraded_count():
    assignments = get_data("assignments")
    today = datetime.now().date()
    ungraded = [
        a for a in assignments
        if not a.get("graded", True) or a.get("marks_obtained") is None or a.get("pending_grading")
    ]
    overdue = [
        a for a in assignments
        if not a.get("submitted")
        and a.get("due_date")
        and datetime.strptime(a["due_date"], "%Y-%m-%d").date() < today
    ]
    by_course = {}
    for a in ungraded:
        key = a["course_id"]
        if key not in by_course:
            by_course[key] = {
                "course_id": a["course_id"],
                "course_name": a["course_name"],
                "ungraded_count": 0,
            }
        by_course[key]["ungraded_count"] += 1
    ungraded_assignments = [
        {
            "assignment_id": a["assignment_id"],
            "assignment_name": a.get("assignment_name", a.get("assignment_title", "")),
            "course": a.get("course", a.get("course_name", "")),
            "course_id": a["course_id"],
            "student_id": a["student_id"],
            "student_name": a["student_name"],
            "due_date": a.get("due_date"),
            "submitted": a.get("submitted", False),
            "graded": a.get("graded", False),
            "pending_grading": a.get("pending_grading", False),
            "missing_submission": a.get("missing_submission", False),
            "average_marks": a.get("average_marks"),
            "status": a.get("status"),
        }
        for a in ungraded[:200]
    ]
    dashboard = get_data("faculty_dashboard")
    payload = {
        "total_ungraded": len(ungraded),
        "total_overdue": len(overdue),
        "by_course": list(by_course.values()),
        "ungraded_assignments": ungraded_assignments,
        "overdue_assignments": [
            {
                "assignment_id": a["assignment_id"],
                "assignment_name": a.get("assignment_name", a.get("assignment_title", "")),
                "course": a.get("course", a.get("course_name", "")),
                "student_name": a["student_name"],
                "due_date": a.get("due_date"),
                "status": a.get("status"),
            }
            for a in overdue[:100]
        ],
    }
    if isinstance(dashboard, dict) and dashboard:
        payload["dashboard"] = dashboard
    return payload

@router.get("/faculty/{faculty_id}/course/{course_id}/students")
def get_course_students(faculty_id: str, course_id: str):
    _build_indexes()
    performance_rows = _indexes["performance_by_course"].get(course_id, [])
    if performance_rows:
        result = []
        at_risk = []
        for row in performance_rows:
            entry = {
                "student_id": row["student_id"],
                "student_name": row["student_name"],
                "quizzes": row.get("quizzes", []),
                "midterm": row.get("midterm"),
                "final": row.get("final"),
                "total": row.get("total"),
                "GPA": row.get("GPA"),
                "current_grade": row.get("current_grade"),
                "class_average": row.get("class_average"),
                "avg_percentage": row.get("total"),
                "at_risk": row.get("at_risk", False),
                "remarks": row.get("remarks", ""),
            }
            result.append(entry)
            if entry["at_risk"]:
                at_risk.append(entry)
        return {
            "course_id": course_id,
            "total_students": len(result),
            "at_risk_students": at_risk,
            "students": result,
        }

    course_exams = _indexes["exams_by_course"].get(course_id, [])
    students = {}
    for e in course_exams:
        sid = e["student_id"]
        if sid not in students:
            students[sid] = {"student_id": sid, "student_name": e["student_name"], "avg_marks": 0, "count": 0, "total_pct": 0}
        students[sid]["count"] += 1
        students[sid]["total_pct"] += e["percentage"]
    result = []
    for s in students.values():
        s["avg_percentage"] = round(s["total_pct"] / max(s["count"], 1), 1)
        s["at_risk"] = s["avg_percentage"] < 50
        result.append(s)
    at_risk = [s for s in result if s["at_risk"]]
    return {"course_id": course_id, "total_students": len(result), "at_risk_students": at_risk}

# ──────────────── ADMIN ENDPOINTS ────────────────
@router.get("/admin/statistics/students")
def admin_students():
    students = get_data("students")
    depts = {}
    for s in students:
        d = s["department"]
        depts[d] = depts.get(d, 0) + 1
    return {"total_students": len(students), "by_department": depts, "active": sum(1 for s in students if s["status"] == "Active")}

@router.get("/admin/statistics/admissions")
def admin_admissions():
    students = get_data("students")
    by_year = {}
    for s in students:
        y = str(s["enrollment_year"])
        by_year[y] = by_year.get(y, 0) + 1
    return {"total_enrolled": len(students), "by_year": by_year}

@router.get("/admin/statistics/fees")
def admin_fees():
    students = get_data("students")
    paid = sum(1 for s in students if s["fee_status"] == "Paid")
    pending = sum(1 for s in students if s["fee_status"] == "Pending")
    unpaid = sum(1 for s in students if s["fee_status"] == "Unpaid")
    total_amount = sum(s["fee_amount"] for s in students)
    collected = sum(s["fee_amount"] for s in students if s["fee_status"] == "Paid")
    return {"total_students": len(students), "paid": paid, "pending": pending, "unpaid": unpaid, "total_expected": total_amount, "total_collected": collected, "collection_rate": round(collected/max(total_amount,1)*100, 1)}

@router.get("/admin/statistics/departments")
def admin_departments():
    students = get_data("students")
    depts = {}
    for s in students:
        d = s["department"]
        if d not in depts:
            depts[d] = {"students": 0, "total_cgpa": 0}
        depts[d]["students"] += 1
        depts[d]["total_cgpa"] += s["cgpa"]
    result = []
    for name, data in depts.items():
        result.append({"department": name, "students": data["students"], "avg_cgpa": round(data["total_cgpa"]/max(data["students"],1), 2)})
    result.sort(key=lambda x: x["avg_cgpa"], reverse=True)
    return {"departments": result}

@router.get("/admin/fee-stats")
def admin_fee_stats():
    stats = get_data("fee_stats")
    if isinstance(stats, list) or not stats:
        students = get_data("students")
        total_expected = sum(s["fee_amount"] for s in students)
        collected = sum(s["fee_amount"] for s in students if s["fee_status"] == "Paid")
        percentage = round(collected / max(total_expected, 1) * 100, 1)
        return {"total_expected": total_expected, "collected": collected, "percentage": percentage}
    return stats

@router.get("/admin/at-risk")
def admin_at_risk():
    at_risk = get_data("at_risk_students")
    if not at_risk:
        raise HTTPException(404, "At-risk student data not found")
    return {"at_risk_students": at_risk}

@router.get("/admin/exams/upcoming")
def admin_upcoming_exams():
    exams = get_data("upcoming_exams")
    if not exams:
        raise HTTPException(404, "Upcoming exam data not found")
    return {
        "total_upcoming": len(exams),
        "upcoming_exams": exams[:100],
        "by_department": _group_exams_by_department(exams),
    }

def _group_exams_by_department(exams: list) -> dict:
    by_dept: dict = {}
    for exam in exams:
        dept = exam.get("department", exam.get("course_name", "General"))
        if dept not in by_dept:
            by_dept[dept] = 0
        by_dept[dept] += 1
    return by_dept

@router.get("/admin/overall-stats")
def admin_overall_stats():
    stats = get_data("admin_stats")
    if isinstance(stats, list) or not stats:
        return {
            "total_enrollment": len(get_data("students")),
            "total_faculty": len(get_data("faculty")),
        }
    return {
        "total_enrollment": stats.get("total_enrollment", 1000),
        "total_faculty": stats.get("total_faculty", 100),
        "total_departments": stats.get("total_departments", 10),
    }

@router.get("/admin/finance/department-stats")
def admin_finance_department_stats():
    data = get_data("department_finance")
    if isinstance(data, list) or not data:
        raise HTTPException(404, "Department finance data not found")
    return data

@router.get("/admin/finance/pending-fees")
def admin_finance_pending_fees():
    pending = get_data("pending_fees")
    if not pending:
        raise HTTPException(404, "Pending fees data not found")
    return {"pending_fees": pending}

@router.get("/admin/finance/scholarship-stats")
def admin_finance_scholarship_stats():
    stats = get_data("scholarship_stats")
    if isinstance(stats, list) or not stats:
        raise HTTPException(404, "Scholarship stats not found")
    return stats

@router.get("/admin/finance/summary")
def admin_finance_summary():
    summary = get_data("financial_summary")
    if isinstance(summary, list) or not summary:
        raise HTTPException(404, "Financial summary not found")
    return summary


@router.get("/admin/salary-unpaid")
def admin_salary_unpaid():
    _build_extended_indexes()
    return _indexes.get("salaries_unpaid", [])


@router.get("/admin/finance/late-fees-total")
def admin_late_fees_total():
    stats = get_data("admin_stats")
    if not isinstance(stats, dict):
        raise HTTPException(404, "Admin stats not found")
    return {"total_late_fees_collected": stats.get("total_late_fees_collected", 0)}


@router.get("/faculty/{faculty_id}/course/{course_id}/average-grade")
def faculty_course_average_grade(faculty_id: str, course_id: str):
    _build_indexes()
    _build_extended_indexes()
    course_row = _indexes.get("course_performance_by_course", {}).get(course_id)
    if course_row and course_row.get("average_grade"):
        return {
            "course_id": course_id,
            "average_grade": course_row["average_grade"],
            "average_percentage": course_row.get("average_percentage"),
        }

    performance_rows = _indexes["performance_by_course"].get(course_id, [])
    if not performance_rows:
        raise HTTPException(404, "Course performance not found")
    totals = [row.get("total", 0) for row in performance_rows if row.get("total") is not None]
    if not totals:
        raise HTTPException(404, "No grade data for course")
    avg_pct = round(sum(totals) / len(totals), 1)
    return {"course_id": course_id, "average_grade": _percentage_to_letter(avg_pct), "average_percentage": avg_pct}


def _percentage_to_letter(pct: float) -> str:
    if pct >= 90:
        return "A"
    if pct >= 85:
        return "A-"
    if pct >= 80:
        return "B+"
    if pct >= 75:
        return "B"
    if pct >= 70:
        return "B-"
    if pct >= 65:
        return "C+"
    if pct >= 60:
        return "C"
    if pct >= 55:
        return "C-"
    if pct >= 50:
        return "D"
    return "F"


@router.get("/faculty/{faculty_id}/course/{course_id}/missed-midterm")
def faculty_missed_midterm(faculty_id: str, course_id: str):
    _build_indexes()
    _build_extended_indexes()
    att = _indexes.get("exam_attendance_by_course", {}).get(course_id)
    if not att:
        raise HTTPException(404, "Midterm attendance data not found for course")

    attended = set(att.get("attended_students", []))
    all_students = att.get("all_students", [])
    missed_ids = [sid for sid in all_students if sid not in attended]

    students_by_id = _indexes.get("students_by_id", {})
    missed = []
    for sid in missed_ids:
        student = students_by_id.get(sid, {})
        missed.append({
            "student_id": sid,
            "student_name": student.get("name", ""),
        })

    return {
        "course_id": course_id,
        "exam_type": att.get("exam_type", "Midterm"),
        "missed_count": len(missed),
        "missed_students": missed,
    }


@router.get("/faculty/{faculty_id}/course/{course_id}/low-attendance")
def faculty_course_low_attendance(faculty_id: str, course_id: str):
    _build_indexes()
    summary_rows = _indexes["attendance_summary_by_course"].get(course_id, [])
    if summary_rows:
        low = [
            {
                "student_id": row["student_id"],
                "student_name": row["student_name"],
                "attendance_percentage": row["attendance_percentage"],
            }
            for row in summary_rows
            if row.get("attendance_percentage", 100) < 75
        ]
        return {
            "course_id": course_id,
            "threshold": 75,
            "low_attendance_count": len(low),
            "students": low,
        }

    records = _indexes["attendance_by_course"].get(course_id, [])
    students_att = {}
    for record in records:
        sid = record["student_id"]
        if sid not in students_att:
            students_att[sid] = {
                "student_id": sid,
                "student_name": record["student_name"],
                "present": 0,
                "absent": 0,
                "late": 0,
                "total": 0,
            }
        students_att[sid]["total"] += 1
        if record["status"] == "Present":
            students_att[sid]["present"] += 1
        elif record["status"] == "Absent":
            students_att[sid]["absent"] += 1
        else:
            students_att[sid]["late"] += 1

    low = []
    for row in students_att.values():
        pct = round((row["present"] + row["late"] * 0.5) / max(row["total"], 1) * 100, 1)
        if pct < 75:
            low.append({
                "student_id": row["student_id"],
                "student_name": row["student_name"],
                "attendance_percentage": pct,
            })

    return {
        "course_id": course_id,
        "threshold": 75,
        "low_attendance_count": len(low),
        "students": low,
    }


@router.get("/faculty/{faculty_id}/course/{course_id}/top-marks")
def faculty_course_top_marks(faculty_id: str, course_id: str):
    _build_indexes()
    performance_rows = _indexes["performance_by_course"].get(course_id, [])
    if not performance_rows:
        raise HTTPException(404, "No student performance data for course")

    ranked = sorted(
        performance_rows,
        key=lambda row: row.get("total", 0) or 0,
        reverse=True,
    )[:5]
    top = [
        {
            "student_id": row.get("student_id"),
            "student_name": row.get("student_name"),
            "total_marks": row.get("total"),
            "current_grade": row.get("current_grade"),
            "GPA": row.get("GPA"),
        }
        for row in ranked
    ]
    return {"course_id": course_id, "top_count": len(top), "top_students": top}
