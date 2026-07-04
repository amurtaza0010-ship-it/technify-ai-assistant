"""
Mock ERP data helpers — instructor mapping and FAC-0001 demo enrichment.

Runs the base synthetic generator (scripts/generate_data.py) when executed
directly, then enriches courses and faculty demo datasets for testing.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from datetime import datetime, timedelta

try:
    from faker import Faker

    _fake = Faker()
    _USE_FAKER = True
except ImportError:
    _USE_FAKER = False

DEMO_FACULTY_ID = "FAC-0001"
DEMO_INSTRUCTOR = "Prof. Alex Carter"
REFERENCE_DATE = datetime(2026, 6, 21)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "synthetic")

_FIRST_NAMES_MALE = ["James", "John", "Robert", "Michael", "David", "Ali", "Ahmed", "Hassan"]
_FIRST_NAMES_FEMALE = ["Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Aisha", "Fatima", "Sana"]
_LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Khan", "Ali", "Hassan", "Malik"]


def _generate_instructor_name() -> str:
    """Return a realistic instructor display name."""
    if _USE_FAKER:
        return f"Prof. {_fake.name()}"
    gender = random.choice(["M", "F"])
    first = random.choice(_FIRST_NAMES_MALE if gender == "M" else _FIRST_NAMES_FEMALE)
    last = random.choice(_LAST_NAMES)
    return f"Prof. {first} {last}"


def assign_instructors(courses: list[dict]) -> list[dict]:
    """
    Add an instructor field to every course.

    Demo faculty FAC-0001 courses use DEMO_INSTRUCTOR (10 featured courses,
    satisfying the 3–5 minimum). Other faculties share one name per faculty_id.
    """
    faculty_instructor: dict[str, str] = {}

    for course in courses:
        faculty_id = course.get("faculty_id", "")

        if faculty_id == DEMO_FACULTY_ID:
            course["instructor"] = DEMO_INSTRUCTOR
            continue

        if faculty_id not in faculty_instructor:
            faculty_instructor[faculty_id] = _generate_instructor_name()

        course["instructor"] = faculty_instructor[faculty_id]

    return courses


def _data_path(name: str) -> str:
    return os.path.join(DATA_DIR, f"{name}.json")


def _load_json(name: str):
    path = _data_path(name)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _save_json(name: str, data) -> None:
    with open(_data_path(name), "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)


def _demo_courses(courses: list[dict]) -> list[dict]:
    return [
        course for course in courses
        if course.get("faculty_id") == DEMO_FACULTY_ID
        or course.get("instructor") == DEMO_INSTRUCTOR
    ]


def _rebuild_faculty_dashboard(
    demo_courses: list[dict],
    assignments: list[dict],
    at_risk_students: list[dict],
    attendance_summaries: list[dict],
    demo_course_ids: set[str],
) -> dict:
    """Rebuild faculty_dashboard.json stats for FAC-0001 from enriched data."""
    faculty_assignments = [
        row for row in assignments
        if row.get("faculty_id") == DEMO_FACULTY_ID or row.get("course_id") in demo_course_ids
    ]
    faculty_attendance = [
        row for row in attendance_summaries
        if row.get("course_id") in demo_course_ids
    ]

    pending_grading = sum(1 for row in faculty_assignments if row.get("pending_grading"))
    ungraded = sum(
        1 for row in faculty_assignments
        if not row.get("graded", True) or row.get("marks_obtained") is None
    )
    students_at_risk = len({
        (row["student_id"], row["course_id"])
        for row in at_risk_students
        if row.get("course_id") in demo_course_ids
    })
    attendance_alerts = sum(1 for row in faculty_attendance if row.get("warning_flag"))
    upcoming_deadlines = sum(
        1 for row in faculty_assignments
        if row.get("due_date")
        and REFERENCE_DATE <= datetime.strptime(row["due_date"], "%Y-%m-%d") <= REFERENCE_DATE + timedelta(days=14)
        and not row.get("submitted")
    )
    recent_submissions = sum(
        1 for row in faculty_assignments
        if row.get("submitted")
        and row.get("submitted_date")
        and datetime.strptime(row["submitted_date"], "%Y-%m-%d") >= REFERENCE_DATE - timedelta(days=7)
    )

    course_summaries = []
    for course in demo_courses:
        course_id = course["course_id"]
        course_assignments = [
            row for row in faculty_assignments if row.get("course_id") == course_id
        ]
        course_attendance = [
            row for row in faculty_attendance if row.get("course_id") == course_id
        ]
        course_summaries.append({
            "course_id": course_id,
            "course_code": course.get("course_code", ""),
            "course_name": course.get("course_name", ""),
            "enrollment": len({row["student_id"] for row in course_assignments}),
            "average_attendance": round(
                sum(row["attendance_percentage"] for row in course_attendance)
                / max(len(course_attendance), 1),
                1,
            ),
            "pending_grading": sum(1 for row in course_assignments if row.get("pending_grading")),
            "students_at_risk": sum(
                1 for row in at_risk_students if row.get("course_id") == course_id
            ),
        })

    return {
        "faculty_id": DEMO_FACULTY_ID,
        "pending_grading": pending_grading,
        "students_at_risk": students_at_risk,
        "attendance_alerts": attendance_alerts,
        "upcoming_deadlines": upcoming_deadlines,
        "recent_submissions": recent_submissions,
        "total_ungraded": ungraded,
        "course_summaries": course_summaries,
    }


def _upsert_at_risk_record(
    at_risk_students: list[dict],
    seen: set[tuple[str, str]],
    *,
    student_id: str,
    student_name: str,
    course_id: str,
    course_name: str,
    reason: str,
    attendance_percentage: float | None = None,
    gpa: float | None = None,
    midterm: float | None = None,
) -> None:
    key = (student_id, course_id)
    if key in seen:
        for row in at_risk_students:
            if (row.get("student_id"), row.get("course_id")) != key:
                continue
            row["reason"] = reason
            if attendance_percentage is not None:
                row["attendance_percentage"] = attendance_percentage
            if gpa is not None:
                row["GPA"] = gpa
            if midterm is not None:
                row["midterm"] = midterm
        return

    record = {
        "student_id": student_id,
        "name": student_name,
        "course_id": course_id,
        "course_name": course_name,
        "reason": reason,
    }
    if attendance_percentage is not None:
        record["attendance_percentage"] = attendance_percentage
    if gpa is not None:
        record["GPA"] = gpa
    if midterm is not None:
        record["midterm"] = midterm

    at_risk_students.append(record)
    seen.add(key)


def enrich_demo_faculty_data() -> None:
    """
    Enrich FAC-0001 courses with low-attendance at-risk students, ungraded
    assignments, and failing-risk performance records for faculty ERP intents.
    """
    courses = _load_json("courses")
    performance = _load_json("student_performance")
    summaries = _load_json("student_attendance_summary")
    assignments = _load_json("assignments")
    at_risk_students = _load_json("at_risk_students")

    if not isinstance(courses, list) or not courses:
        return
    if not isinstance(performance, list) or not performance:
        return
    if not isinstance(summaries, list):
        summaries = []
    if not isinstance(assignments, list):
        assignments = []
    if not isinstance(at_risk_students, list):
        at_risk_students = []

    demo_courses = _demo_courses(courses)
    if not demo_courses:
        print("[DEMO FACULTY] No FAC-0001 courses found; skipping enrichment.")
        return

    demo_course_ids = {course["course_id"] for course in demo_courses}
    course_name_by_id = {course["course_id"]: course.get("course_name", "") for course in demo_courses}

    summary_by_key = {
        (row["student_id"], row["course_id"]): row
        for row in summaries
        if isinstance(row, dict)
    }
    demo_perf = [
        row for row in performance
        if isinstance(row, dict) and row.get("course_id") in demo_course_ids
    ]
    if not demo_perf:
        print("[DEMO FACULTY] No student_performance rows for FAC-0001 courses; skipping.")
        return

    seen_at_risk = {
        (row.get("student_id"), row.get("course_id"))
        for row in at_risk_students
        if isinstance(row, dict)
    }

    n_low = min(random.randint(5, 10), len(demo_perf))
    low_att_selected = random.sample(demo_perf, n_low)
    low_att_keys: set[tuple[str, str]] = set()

    for perf in low_att_selected:
        key = (perf["student_id"], perf["course_id"])
        low_att_keys.add(key)
        perf["at_risk"] = True
        perf["remarks"] = "Needs improvement — attendance below threshold"

        pct = round(random.uniform(45, 74), 1)
        summary = summary_by_key.get(key)
        if summary is None:
            summary = {
                "student_id": perf["student_id"],
                "student_name": perf.get("student_name", ""),
                "course_id": perf["course_id"],
                "course_code": perf.get("course_code", ""),
                "course_name": perf.get("course") or course_name_by_id.get(perf["course_id"], ""),
                "total_classes": 36,
                "late_count": 1,
            }
            summaries.append(summary)
            summary_by_key[key] = summary

        total_classes = summary.get("total_classes", 36)
        attended_equiv = max(0, round(total_classes * pct / 100))
        summary["attendance_percentage"] = pct
        summary["warning_flag"] = True
        summary["attended_classes"] = attended_equiv
        summary["absent_classes"] = max(0, total_classes - attended_equiv)

        _upsert_at_risk_record(
            at_risk_students,
            seen_at_risk,
            student_id=perf["student_id"],
            student_name=perf.get("student_name", ""),
            course_id=perf["course_id"],
            course_name=perf.get("course") or course_name_by_id.get(perf["course_id"], ""),
            reason="Attendance below 75%",
            attendance_percentage=pct,
        )

    remaining_perf = [
        row for row in demo_perf
        if (row["student_id"], row["course_id"]) not in low_att_keys
    ]
    n_fail = min(random.randint(5, 10), len(remaining_perf))
    fail_selected = random.sample(remaining_perf, n_fail) if remaining_perf else []

    for perf in fail_selected:
        key = (perf["student_id"], perf["course_id"])
        gpa = round(random.uniform(1.0, 2.4), 2)
        total = round(random.uniform(35, 49), 1)
        midterm = round(random.uniform(30, 45), 1)
        final_score = round(random.uniform(30, 48), 1)

        perf["at_risk"] = True
        perf["GPA"] = gpa
        perf["total"] = total
        perf["midterm"] = midterm
        perf["final"] = final_score
        perf["current_grade"] = "F" if total < 45 else "D"
        perf["remarks"] = "At risk of failing — GPA and assessment scores below threshold"

        _upsert_at_risk_record(
            at_risk_students,
            seen_at_risk,
            student_id=perf["student_id"],
            student_name=perf.get("student_name", ""),
            course_id=perf["course_id"],
            course_name=perf.get("course") or course_name_by_id.get(perf["course_id"], ""),
            reason="Low academic performance (GPA below 2.5 or failing assessments)",
            gpa=gpa,
            midterm=midterm,
        )

    demo_assignments = [
        row for row in assignments
        if isinstance(row, dict)
        and (row.get("faculty_id") == DEMO_FACULTY_ID or row.get("course_id") in demo_course_ids)
    ]
    n_ungraded = min(random.randint(15, 20), len(demo_assignments))
    if demo_assignments and n_ungraded:
        for assignment in random.sample(demo_assignments, n_ungraded):
            assignment["graded"] = False
            assignment["pending_grading"] = True
            assignment["submitted"] = True
            assignment["missing_submission"] = False
            assignment["marks_obtained"] = None
            assignment["average_marks"] = None
            assignment["status"] = "Submitted"
            if not assignment.get("submitted_date"):
                assignment["submitted_date"] = "2026-06-15"

    dashboard = _rebuild_faculty_dashboard(
        demo_courses,
        assignments,
        at_risk_students,
        summaries,
        demo_course_ids,
    )

    _save_json("student_performance", performance)
    _save_json("student_attendance_summary", summaries)
    _save_json("assignments", assignments)
    _save_json("at_risk_students", at_risk_students)
    _save_json("faculty_dashboard", dashboard)

    print(
        "[DEMO FACULTY] Enriched FAC-0001: "
        f"{n_low} low-attendance at-risk, {n_fail} failing-risk, {n_ungraded} ungraded assignments."
    )


def apply_instructors_to_courses_file() -> None:
    """Load courses.json, assign instructors, and write back."""
    path = _data_path("courses")
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as handle:
        courses = json.load(handle)

    if not isinstance(courses, list) or not courses:
        return

    assign_instructors(courses)

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(courses, handle, indent=2, ensure_ascii=False)


def ensure_instructor_fields() -> None:
    """Ensure instructors exist, then enrich FAC-0001 demo faculty datasets."""
    path = _data_path("courses")
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as handle:
        courses = json.load(handle)

    if not isinstance(courses, list) or not courses:
        return

    if not all(isinstance(course, dict) and course.get("instructor") for course in courses):
        assign_instructors(courses)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(courses, handle, indent=2, ensure_ascii=False)
        print(f"[INSTRUCTORS] Updated {len(courses)} courses with instructor fields.")

    enrich_demo_faculty_data()
    generate_extended_synthetic_data()


def _percentage_to_grade(pct: float) -> str:
    """Map a percentage score to a letter grade."""
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


def fill_missing_instructors() -> None:
    """Ensure every course has a non-empty instructor name."""
    courses = _load_json("courses")
    if not isinstance(courses, list) or not courses:
        return

    changed = False
    for course in courses:
        if not isinstance(course, dict):
            continue
        instructor = course.get("instructor")
        if not instructor or not str(instructor).strip():
            course["instructor"] = _generate_instructor_name()
            changed = True

    if changed:
        _save_json("courses", courses)
        print(f"[INSTRUCTORS] Filled missing instructors on {len(courses)} courses.")


def generate_salaries_data() -> None:
    """Create faculty salary records with at least five unpaid entries."""
    faculty = _load_json("faculty")
    if not isinstance(faculty, list) or not faculty:
        return

    salaries = []
    for member in faculty:
        if not isinstance(member, dict):
            continue
        salaries.append({
            "faculty_id": member.get("faculty_id", ""),
            "name": member.get("name", ""),
            "amount": random.randint(80000, 150000),
            "collected": random.choice([True, False]),
        })

    unpaid_count = sum(1 for row in salaries if not row["collected"])
    while unpaid_count < 5 and salaries:
        row = random.choice(salaries)
        if not row["collected"]:
            break
        row["collected"] = False
        unpaid_count = sum(1 for r in salaries if not r["collected"])

    _save_json("salaries", salaries)
    print(f"[SALARIES] Generated {len(salaries)} salary records ({unpaid_count} unpaid).")


def generate_late_fees_data() -> None:
    """Create late-fee fine records and update admin_stats with collected total."""
    students = _load_json("students")
    if not isinstance(students, list) or not students:
        return

    sample_size = min(50, len(students))
    selected = random.sample(students, sample_size)
    late_fees = []
    for student in selected:
        if not isinstance(student, dict):
            continue
        late_fees.append({
            "student_id": student.get("student_id", ""),
            "amount": random.randint(500, 5000),
            "paid": random.choice([True, False]),
        })

    total_collected = sum(row["amount"] for row in late_fees if row.get("paid"))
    admin_stats = _load_json("admin_stats")
    if not isinstance(admin_stats, dict):
        admin_stats = {}
    admin_stats["total_late_fees_collected"] = total_collected

    _save_json("late_fees", late_fees)
    _save_json("admin_stats", admin_stats)
    print(
        f"[LATE FEES] Generated {len(late_fees)} late-fee records; "
        f"total collected: {total_collected}."
    )


def generate_exam_attendance_data() -> None:
    """Build per-course midterm attendance (~80% of enrolled students attended)."""
    exams = _load_json("exams")
    if not isinstance(exams, list) or not exams:
        return

    students_by_course: dict[str, set[str]] = {}
    for exam in exams:
        if not isinstance(exam, dict):
            continue
        if exam.get("exam_type") != "Midterm":
            continue
        course_id = exam.get("course_id")
        student_id = exam.get("student_id")
        if course_id and student_id:
            students_by_course.setdefault(course_id, set()).add(student_id)

    attendance: dict[str, dict] = {}
    for course_id, student_ids in students_by_course.items():
        enrolled = list(student_ids)
        attend_count = max(1, int(len(enrolled) * random.uniform(0.75, 0.85)))
        attended = random.sample(enrolled, min(attend_count, len(enrolled)))
        attendance[course_id] = {
            "exam_type": "Midterm",
            "all_students": enrolled,
            "attended_students": attended,
        }

    _save_json("exam_attendance", attendance)
    print(f"[EXAM ATTENDANCE] Generated midterm attendance for {len(attendance)} courses.")


def enrich_course_performance_average_grades() -> None:
    """
    Ensure every course has a course_performance entry with a computed
    average_grade — including courses missing from the base generator output
    (e.g. courses with no exam/attendance rows at generation time).
    """
    course_performance = _load_json("course_performance")
    performance = _load_json("student_performance")
    courses = _load_json("courses")

    if not isinstance(course_performance, list):
        course_performance = []
    if not isinstance(performance, list):
        performance = []
    if not isinstance(courses, list):
        courses = []

    totals_by_course: dict[str, list[float]] = {}
    for row in performance:
        if not isinstance(row, dict):
            continue
        course_id = row.get("course_id")
        total = row.get("total")
        if course_id is not None and total is not None:
            totals_by_course.setdefault(course_id, []).append(float(total))

    performance_by_course_id = {
        row.get("course_id"): row
        for row in course_performance
        if isinstance(row, dict) and row.get("course_id")
    }

    changed = False

    # Fill missing average_grade on existing entries.
    for course in course_performance:
        if not isinstance(course, dict):
            continue
        if course.get("average_grade"):
            continue
        totals = totals_by_course.get(course.get("course_id"), [])
        avg_pct = round(sum(totals) / len(totals), 1) if totals else 0.0
        course["average_percentage"] = avg_pct
        course["average_grade"] = _percentage_to_grade(avg_pct)
        changed = True

    # Ensure every course (e.g. CRS-0001) has a course_performance entry,
    # even if it was skipped by the base generator.
    for course in courses:
        if not isinstance(course, dict):
            continue
        course_id = course.get("course_id")
        if not course_id or course_id in performance_by_course_id:
            continue

        totals = totals_by_course.get(course_id, [])
        if totals:
            avg_pct = round(sum(totals) / len(totals), 1)
            pass_count = sum(1 for t in totals if t >= 50)
            pass_rate = round(pass_count / len(totals) * 100, 1)
        else:
            avg_pct = 0.0
            pass_rate = 0.0

        placeholder = {
            "course_id": course_id,
            "course_name": course.get("course_name", ""),
            "course_code": course.get("course_code", ""),
            "faculty_id": course.get("faculty_id", ""),
            "average_grade": _percentage_to_grade(avg_pct),
            "average_percentage": avg_pct,
            "pass_rate": pass_rate,
            "fail_rate": round(100 - pass_rate, 1),
            "total_students": len(totals),
            "enrollment": len(totals),
            "average_attendance": 0.0,
            "assignment_completion": 0.0,
            "grading_progress": 0.0,
        }
        course_performance.append(placeholder)
        performance_by_course_id[course_id] = placeholder
        changed = True

    if changed:
        _save_json("course_performance", course_performance)
        _save_json("course_analytics", course_performance)
        print(
            f"[COURSE PERFORMANCE] Ensured {len(course_performance)} course entries "
            "with average_grade populated."
        )


def generate_extended_synthetic_data() -> None:
    """Run all additive synthetic data generators after base generation."""
    fill_missing_instructors()
    generate_salaries_data()
    generate_late_fees_data()
    generate_exam_attendance_data()
    enrich_course_performance_average_grades()


def generate_all() -> None:
    """Run the base generator, then apply instructors and FAC-0001 enrichment."""
    project_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    script = os.path.join(project_root, "scripts", "generate_data.py")
    subprocess.run([sys.executable, script], cwd=project_root, check=True)
    apply_instructors_to_courses_file()
    enrich_demo_faculty_data()
    generate_extended_synthetic_data()
    print("[DEMO FACULTY] Course instructor mapping and FAC-0001 enrichment applied.")


if __name__ == "__main__":
    generate_all()
