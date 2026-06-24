"""
Synthetic Data Generator for Technify Academic AI Assistant
==========================================================
Generates realistic fake university data for development and testing.

Generates:
- 1,000 Students (with enrollments, weighted GPA, fee status)
- 100 Faculty Members
- 150 Courses
- 10,000 Attendance Records
- 5,000 Exam Records
- 2,000 Timetable Records
- 5,000 Assignment Records
- Admin, finance, faculty performance, and at-risk datasets

Usage:
    python scripts/generate_data.py

Output:
    data/synthetic/*.json

Author: AI Team 1 - Data Engineer
"""

import json
import os
import random
from datetime import datetime, timedelta

try:
    from faker import Faker
    fake = Faker()
    USE_FAKER = True
except ImportError:
    USE_FAKER = False
    print("[WARNING] Faker not installed. Using basic random data.")
    print("          Install with: pip install faker")

# ============================================================
# Configuration
# ============================================================
NUM_STUDENTS = 1000
NUM_FACULTY = 100
NUM_COURSES = 150
NUM_ATTENDANCE_RECORDS = 10000
NUM_EXAM_RECORDS = 5000
NUM_TIMETABLE_RECORDS = 2000
NUM_ASSIGNMENT_RECORDS = 5000
NUM_PENDING_FEES = 20
NUM_AT_RISK = 10
REFERENCE_DATE = datetime(2026, 6, 21)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "synthetic")

DEPARTMENTS = [
    "Computer Science",
    "Information Technology",
    "Software Engineering",
    "Artificial Intelligence",
    "Data Science",
    "Electrical Engineering",
    "Mechanical Engineering",
    "Business Administration",
    "Mathematics",
    "Physics",
]

FINANCE_DEPARTMENTS = [
    {"department": "CS", "collected_percentage": 95, "total_collected_amount": 95000000},
    {"department": "Business", "collected_percentage": 82, "total_collected_amount": 65600000},
    {"department": "Engineering", "collected_percentage": 88, "total_collected_amount": 88000000},
    {"department": "Arts", "collected_percentage": 70, "total_collected_amount": 42000000},
    {"department": "Medicine", "collected_percentage": 60, "total_collected_amount": 120000000},
]

COURSE_NAMES = [
    "Programming Fundamentals", "Object Oriented Programming", "Data Structures",
    "Algorithms", "Database Systems", "Web Engineering", "Software Engineering",
    "Operating Systems", "Computer Networks", "Artificial Intelligence",
    "Machine Learning", "Deep Learning", "Natural Language Processing",
    "Computer Vision", "Data Mining", "Cloud Computing", "Cyber Security",
    "Mobile App Development", "Digital Logic Design", "Discrete Mathematics",
    "Linear Algebra", "Probability & Statistics", "Calculus I", "Calculus II",
    "Physics I", "Physics II", "Technical Writing", "Professional Ethics",
    "Project Management", "Software Testing", "Human Computer Interaction",
    "Information Security", "Compiler Construction", "Theory of Automata",
    "Numerical Methods", "Parallel Computing", "Distributed Systems",
    "Internet of Things", "Blockchain Technology", "DevOps Engineering",
    "Big Data Analytics", "Data Warehousing", "Business Intelligence",
    "Entrepreneurship", "Communication Skills", "Islamic Studies",
    "Pakistan Studies", "English I", "English II", "Accounting",
    "Microeconomics", "Macroeconomics", "Financial Accounting",
    "Marketing Management", "Organizational Behavior", "Business Law",
    "Thermodynamics", "Fluid Mechanics", "Control Systems",
    "Digital Signal Processing", "Power Electronics", "Structural Analysis",
    "Anatomy", "Physiology", "Biochemistry", "Pathology",
    "Pharmacology", "Clinical Medicine", "Medical Ethics",
    "Graphic Design", "Fine Arts", "Art History", "Creative Writing",
    "Research Methods", "Technical Report Writing", "Seminar",
]

DESIGNATIONS = ["Lecturer", "Assistant Professor", "Associate Professor", "Professor"]
FEE_STATUSES = ["Paid", "Paid", "Paid", "Pending", "Unpaid"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

GRADE_POINTS = {
    "A+": 4.0, "A": 4.0, "A-": 3.67,
    "B+": 3.33, "B": 3.00, "B-": 2.67,
    "C+": 2.33, "C": 2.00, "C-": 1.67,
    "D": 1.00, "F": 0.00,
}

FIRST_NAMES_MALE = [
    "Ahmed", "Ali", "Muhammad", "Hassan", "Usman", "Bilal", "Hamza", "Omar",
    "Saad", "Zain", "Fahad", "Rehan", "Kamran", "Imran", "Tariq", "Junaid",
    "Faisal", "Adeel", "Waqar", "Shahid", "Arslan", "Nabeel", "Kashif", "Sohail",
]

FIRST_NAMES_FEMALE = [
    "Ayesha", "Fatima", "Zainab", "Maryam", "Hira", "Sana", "Amna", "Noor",
    "Rabia", "Sumaya", "Kiran", "Mehwish", "Sadia", "Nimra", "Iqra", "Bushra",
    "Samina", "Tahira", "Uzma", "Asma", "Mahnoor", "Laiba", "Anum", "Mishal",
]

LAST_NAMES = [
    "Khan", "Ahmed", "Ali", "Hussain", "Shah", "Malik", "Butt", "Iqbal",
    "Raza", "Siddiqui", "Qureshi", "Sheikh", "Chaudhry", "Aslam", "Javed",
    "Nawaz", "Akram", "Saleem", "Farooq", "Rehman", "Umar", "Haider",
    "Zaidi", "Naqvi", "Abbasi", "Mirza", "Baig", "Mughal", "Awan", "Gill",
]

SCHOLARSHIP_PROGRAMS = [
    {"program": "Merit Scholarship (100%)", "students": 25, "amount_disbursed": 2375000},
    {"program": "Merit Scholarship (75%)", "students": 40, "amount_disbursed": 2850000},
    {"program": "Merit Scholarship (50%)", "students": 45, "amount_disbursed": 2137500},
    {"program": "Need-Based Financial Aid", "students": 30, "amount_disbursed": 4500000},
    {"program": "Sports Excellence Scholarship", "students": 10, "amount_disbursed": 950000},
]


def generate_name():
    if USE_FAKER:
        return fake.name()
    gender = random.choice(["M", "F"])
    first = random.choice(FIRST_NAMES_MALE if gender == "M" else FIRST_NAMES_FEMALE)
    last = random.choice(LAST_NAMES)
    return f"{first} {last}"


def generate_email(name, domain="technify.edu.pk"):
    clean = name.lower().replace(" ", ".").replace("'", "")
    rand_num = random.randint(1, 999)
    return f"{clean}{rand_num}@{domain}"


def generate_phone():
    return f"+92-3{random.randint(0, 4)}{random.randint(0, 9)}-{random.randint(1000000, 9999999)}"


def percentage_to_grade(percentage):
    if percentage >= 90:
        return "A+"
    if percentage >= 85:
        return "A"
    if percentage >= 80:
        return "A-"
    if percentage >= 75:
        return "B+"
    if percentage >= 70:
        return "B"
    if percentage >= 65:
        return "B-"
    if percentage >= 60:
        return "C+"
    if percentage >= 55:
        return "C"
    if percentage >= 50:
        return "C-"
    if percentage >= 45:
        return "D"
    return "F"


def calculate_weighted_gpa(enrollments):
    total_points = 0.0
    total_credits = 0
    for enrollment in enrollments:
        credits = enrollment["credit_hours"]
        points = enrollment["grade_points"]
        total_points += points * credits
        total_credits += credits
    if total_credits == 0:
        return 0.0
    return round(total_points / total_credits, 2)


def generate_faculty():
    print(f"[FACULTY] Generating {NUM_FACULTY} faculty members...")
    faculty = []
    for i in range(1, NUM_FACULTY + 1):
        name = generate_name()
        faculty.append({
            "faculty_id": f"FAC-{i:04d}",
            "name": name,
            "email": generate_email(name, "faculty.technify.edu.pk"),
            "phone": generate_phone(),
            "department": random.choice(DEPARTMENTS),
            "designation": random.choice(DESIGNATIONS),
            "qualification": random.choice(["PhD", "MS", "MPhil"]),
            "joining_year": random.randint(2015, 2025),
            "office": f"Room {random.choice(['A', 'B', 'C', 'D'])}-{random.randint(100, 499)}",
        })
    return faculty


def generate_courses(faculty_list):
    print(f"[COURSES] Generating {NUM_COURSES} courses...")
    courses = []
    used_names = set()

    for i in range(1, NUM_COURSES + 1):
        course_name = random.choice(COURSE_NAMES)
        while course_name in used_names and len(used_names) < len(COURSE_NAMES):
            course_name = random.choice(COURSE_NAMES)
        used_names.add(course_name)

        assigned_faculty = random.choice(faculty_list)
        credit_hours = random.choice([2, 3, 3, 3, 4])

        courses.append({
            "course_id": f"CRS-{i:04d}",
            "course_name": course_name,
            "course_code": f"{random.choice(['CS', 'IT', 'SE', 'AI', 'DS', 'EE', 'MT', 'PH', 'BA', 'MD', 'AR'])}-{random.randint(100, 499)}",
            "credit_hours": credit_hours,
            "department": assigned_faculty["department"],
            "semester": random.randint(1, 8),
            "faculty_id": assigned_faculty["faculty_id"],
            "faculty_name": assigned_faculty["name"],
            "schedule": {
                "days": random.choice([
                    ["Monday", "Wednesday"],
                    ["Tuesday", "Thursday"],
                    ["Monday", "Wednesday", "Friday"],
                ]),
                "time": random.choice([
                    "08:00-09:30", "09:30-11:00", "11:00-12:30",
                    "14:00-15:30", "15:30-17:00",
                ]),
                "room": f"Room {random.choice(['LH', 'CR', 'Lab'])}-{random.randint(1, 20)}",
            },
            "total_classes": random.randint(28, 45),
            "max_students": random.choice([30, 40, 50, 60]),
        })
    return courses


def build_student_enrollments(student, courses):
    eligible = [
        c for c in courses
        if c["department"] == student["department"] and c["semester"] <= student["semester"]
    ]
    if not eligible:
        eligible = random.sample(courses, min(5, len(courses)))
    selected = random.sample(eligible, min(random.randint(5, 7), len(eligible)))

    enrollments = []
    for course in selected:
        percentage = max(45, min(100, random.gauss(72, 12)))
        grade = percentage_to_grade(percentage)
        enrollments.append({
            "course_id": course["course_id"],
            "course_name": course["course_name"],
            "course_code": course["course_code"],
            "credit_hours": course["credit_hours"],
            "grade": grade,
            "grade_points": GRADE_POINTS[grade],
            "percentage": round(percentage, 1),
        })
    return enrollments


def generate_students(courses):
    print(f"[STUDENTS] Generating {NUM_STUDENTS} students...")
    students = []
    for i in range(1, NUM_STUDENTS + 1):
        name = generate_name()
        semester = random.randint(1, 8)
        student = {
            "student_id": f"STU-{i:04d}",
            "name": name,
            "email": generate_email(name, "student.technify.edu.pk"),
            "phone": generate_phone(),
            "department": random.choice(DEPARTMENTS),
            "semester": semester,
            "section": random.choice(["A", "B", "C"]),
            "enrollment_year": 2026 - (semester // 2) - 1,
            "status": random.choice(["Active"] * 9 + ["On Leave"]),
            "fee_status": random.choice(FEE_STATUSES),
            "fee_amount": random.choice([85000, 90000, 95000, 100000, 120000]),
            "fee_due_date": f"2026-07-{random.randint(1, 28):02d}",
        }
        enrollments = build_student_enrollments(student, courses)
        student["enrollments"] = enrollments
        gpa = calculate_weighted_gpa(enrollments)
        student["gpa"] = gpa
        student["cgpa"] = gpa
        students.append(student)
    return students


def generate_attendance(students, courses):
    print(f"[ATTENDANCE] Generating {NUM_ATTENDANCE_RECORDS} attendance records...")
    attendance = []
    start_date = datetime(2026, 1, 15)

    for i in range(1, NUM_ATTENDANCE_RECORDS + 1):
        student = random.choice(students)
        course = random.choice(courses)
        days_offset = random.randint(0, 120)
        record_date = start_date + timedelta(days=days_offset)

        while record_date.weekday() >= 5:
            record_date += timedelta(days=1)

        attendance.append({
            "record_id": f"ATT-{i:06d}",
            "student_id": student["student_id"],
            "student_name": student["name"],
            "course_id": course["course_id"],
            "course_name": course["course_name"],
            "date": record_date.strftime("%Y-%m-%d"),
            "status": random.choices(
                ["Present", "Absent", "Late"],
                weights=[75, 18, 7],
                k=1,
            )[0],
            "marked_by": course["faculty_id"],
        })

    return attendance


def generate_exams(students, courses):
    print(f"[EXAMS] Generating {NUM_EXAM_RECORDS} exam records...")
    exams = []

    exam_types = [
        {"type": "Quiz 1", "total_marks": 10},
        {"type": "Quiz 2", "total_marks": 10},
        {"type": "Quiz 3", "total_marks": 10},
        {"type": "Assignment 1", "total_marks": 15},
        {"type": "Assignment 2", "total_marks": 15},
        {"type": "Midterm", "total_marks": 30},
        {"type": "Final", "total_marks": 50},
    ]

    for i in range(1, NUM_EXAM_RECORDS + 1):
        student = random.choice(students)
        course = random.choice(courses)
        exam_type = random.choice(exam_types)
        total = exam_type["total_marks"]

        percentage = random.gauss(70, 15)
        percentage = max(10, min(100, percentage))
        marks = round(total * percentage / 100, 1)

        exams.append({
            "record_id": f"EXM-{i:06d}",
            "student_id": student["student_id"],
            "student_name": student["name"],
            "course_id": course["course_id"],
            "course_name": course["course_name"],
            "exam_type": exam_type["type"],
            "marks_obtained": marks,
            "total_marks": total,
            "percentage": round(percentage, 1),
            "grade": percentage_to_grade(percentage),
            "date": f"2026-{random.choice(['02', '03', '04', '05'])}-{random.randint(1, 28):02d}",
        })

    return exams


def generate_upcoming_exams(students, courses):
    print("[UPCOMING EXAMS] Generating scheduled upcoming exams...")
    upcoming = []
    exam_subjects = ["Midterm", "Final", "Quiz 4", "Practical Exam"]

    for student in students:
        enrolled_ids = {e["course_id"] for e in student["enrollments"]}
        student_courses = [c for c in courses if c["course_id"] in enrolled_ids]
        if not student_courses:
            student_courses = random.sample(courses, min(3, len(courses)))

        for course in random.sample(student_courses, min(3, len(student_courses))):
            days_ahead = random.randint(1, 45)
            exam_date = (REFERENCE_DATE + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
            upcoming.append({
                "student_id": student["student_id"],
                "course_id": course["course_id"],
                "subject": course["course_name"],
                "course_code": course["course_code"],
                "department": course.get("department", student["department"]),
                "exam_type": random.choice(exam_subjects),
                "date": exam_date,
                "time": random.choice(["09:00", "11:00", "14:00"]),
                "room": course["schedule"]["room"],
            })

    return upcoming


def generate_timetable(students, courses):
    print(f"[TIMETABLE] Generating {NUM_TIMETABLE_RECORDS} timetable records...")
    timetable = []

    time_slots = [
        "08:00-09:30", "09:30-11:00", "11:00-12:30",
        "13:00-14:30", "14:30-16:00", "16:00-17:30",
    ]

    for student in students:
        enrolled_ids = {e["course_id"] for e in student["enrollments"]}
        student_courses = [c for c in courses if c["course_id"] in enrolled_ids]
        for course in student_courses:
            for day in course["schedule"]["days"]:
                timetable.append({
                    "timetable_id": f"TT-{len(timetable) + 1:06d}",
                    "student_id": student["student_id"],
                    "student_name": student["name"],
                    "course_id": course["course_id"],
                    "course_name": course["course_name"],
                    "course_code": course["course_code"],
                    "faculty_name": course["faculty_name"],
                    "day": day,
                    "time_slot": course["schedule"]["time"],
                    "room": course["schedule"]["room"],
                    "semester": student["semester"],
                    "section": student["section"],
                })

    while len(timetable) < NUM_TIMETABLE_RECORDS:
        student = random.choice(students)
        course = random.choice(courses)
        timetable.append({
            "timetable_id": f"TT-{len(timetable) + 1:06d}",
            "student_id": student["student_id"],
            "student_name": student["name"],
            "course_id": course["course_id"],
            "course_name": course["course_name"],
            "course_code": course["course_code"],
            "faculty_name": course["faculty_name"],
            "day": random.choice(DAYS),
            "time_slot": random.choice(time_slots),
            "room": f"Room {random.choice(['LH', 'CR', 'Lab'])}-{random.randint(1, 20)}",
            "semester": student["semester"],
            "section": student["section"],
        })

    return timetable[:NUM_TIMETABLE_RECORDS]


def generate_assignments(students, courses):
    print(f"[ASSIGNMENTS] Generating {NUM_ASSIGNMENT_RECORDS} assignment records...")
    assignments = []

    statuses = ["Submitted", "Submitted", "Submitted", "Pending", "Late", "Missing", "Submitted"]

    for i in range(1, NUM_ASSIGNMENT_RECORDS + 1):
        student = random.choice(students)
        course = random.choice(courses)
        due_date = REFERENCE_DATE + timedelta(days=random.randint(-30, 60))
        status = random.choice(statuses)

        submitted_date = None
        marks_obtained = None
        graded = True

        if status == "Submitted":
            submitted_date = (due_date - timedelta(days=random.randint(0, 3))).strftime("%Y-%m-%d")
            if random.random() < 0.15:
                marks_obtained = None
                graded = False
            else:
                marks_obtained = round(random.uniform(7, 15), 1)
        elif status == "Late":
            submitted_date = (due_date + timedelta(days=random.randint(1, 5))).strftime("%Y-%m-%d")
            marks_obtained = round(random.uniform(3, 10), 1)
        elif status == "Pending":
            graded = False

        assignments.append({
            "assignment_id": f"ASN-{i:06d}",
            "student_id": student["student_id"],
            "student_name": student["name"],
            "course_id": course["course_id"],
            "course_name": course["course_name"],
            "assignment_title": f"Assignment {random.randint(1, 5)} - {course['course_name']}",
            "total_marks": 15,
            "marks_obtained": marks_obtained,
            "due_date": due_date.strftime("%Y-%m-%d"),
            "submitted_date": submitted_date,
            "status": status,
            "graded": graded,
            "faculty_id": course["faculty_id"],
        })

    return assignments


def compute_course_attendance_pct(attendance_records):
    if not attendance_records:
        return 0.0
    present = sum(1 for r in attendance_records if r["status"] == "Present")
    late = sum(1 for r in attendance_records if r["status"] == "Late")
    total = len(attendance_records)
    return round((present + late * 0.5) / max(total, 1) * 100, 1)


def generate_at_risk_students(students, courses, attendance):
    print(f"[AT-RISK] Generating {NUM_AT_RISK} at-risk students...")
    at_risk = []
    used_students = set()

    for student in students:
        if len(at_risk) >= NUM_AT_RISK:
            break
        if student["student_id"] in used_students:
            continue

        student_records = [r for r in attendance if r["student_id"] == student["student_id"]]
        if not student_records:
            continue

        course_ids = {r["course_id"] for r in student_records}
        for course_id in course_ids:
            course_records = [r for r in student_records if r["course_id"] == course_id]
            pct = compute_course_attendance_pct(course_records)
            if pct < 75:
                course = next((c for c in courses if c["course_id"] == course_id), None)
                at_risk.append({
                    "student_id": student["student_id"],
                    "name": student["name"],
                    "course_id": course_id,
                    "course_name": course["course_name"] if course else "Unknown Course",
                    "attendance_percentage": pct,
                    "reason": "Attendance below 75%",
                })
                used_students.add(student["student_id"])
                break

    while len(at_risk) < NUM_AT_RISK:
        student = students[len(at_risk)]
        course = random.choice(courses)
        at_risk.append({
            "student_id": student["student_id"],
            "name": student["name"],
            "course_id": course["course_id"],
            "course_name": course["course_name"],
            "attendance_percentage": round(random.uniform(45, 74.9), 1),
            "reason": "Attendance below 75%",
        })

    return at_risk[:NUM_AT_RISK]


def generate_admin_stats():
    return {
        "total_enrollment": NUM_STUDENTS,
        "total_faculty": NUM_FACULTY,
        "total_departments": len(DEPARTMENTS),
    }


def generate_department_finance():
    return {"departments": FINANCE_DEPARTMENTS}


def generate_pending_fees(students):
    print(f"[PENDING FEES] Generating {NUM_PENDING_FEES} pending fee records...")
    candidates = [s for s in students if s["fee_status"] in ("Unpaid", "Pending")]
    if len(candidates) < NUM_PENDING_FEES:
        candidates = students[:NUM_PENDING_FEES]

    pending = []
    for student in candidates[:NUM_PENDING_FEES]:
        pending.append({
            "student_id": student["student_id"],
            "name": student["name"],
            "due_amount": student["fee_amount"],
            "due_date": student["fee_due_date"],
        })
    return pending


def generate_scholarship_stats():
    return {
        "total_students_with_scholarship": 150,
        "total_scholarship_amount_disbursed": 15000000,
        "top_scholarship_programs": SCHOLARSHIP_PROGRAMS,
    }


def generate_financial_summary(students):
    total_expected = sum(s["fee_amount"] for s in students)
    total_collected = sum(s["fee_amount"] for s in students if s["fee_status"] == "Paid")
    total_pending = total_expected - total_collected
    total_expenses = round(total_collected * 0.72)

    return {
        "total_revenue": total_collected,
        "total_pending_revenue": total_pending,
        "total_expenses": total_expenses,
        "currency": "PKR",
    }


def generate_fee_stats(students):
    total_expected = sum(s["fee_amount"] for s in students)
    collected = sum(s["fee_amount"] for s in students if s["fee_status"] == "Paid")
    percentage = round(collected / max(total_expected, 1) * 100, 1)
    return {
        "total_expected": total_expected,
        "collected": collected,
        "percentage": percentage,
        "currency": "PKR",
    }


def generate_course_performance(students, courses, exams):
    print("[COURSE PERFORMANCE] Generating course performance metrics...")
    performance = []

    for course in courses:
        course_exams = [e for e in exams if e["course_id"] == course["course_id"]]
        enrolled_students = {
            s["student_id"]
            for s in students
            for e in s["enrollments"]
            if e["course_id"] == course["course_id"]
        }

        if course_exams:
            avg_pct = round(sum(e["percentage"] for e in course_exams) / len(course_exams), 1)
            pass_count = sum(1 for e in course_exams if e["percentage"] >= 50)
            pass_rate = round(pass_count / len(course_exams) * 100, 1)
        else:
            avg_pct = round(random.uniform(55, 85), 1)
            pass_rate = round(random.uniform(70, 95), 1)

        performance.append({
            "course_id": course["course_id"],
            "course_name": course["course_name"],
            "course_code": course["course_code"],
            "faculty_id": course["faculty_id"],
            "average_grade": percentage_to_grade(avg_pct),
            "average_percentage": avg_pct,
            "pass_rate": pass_rate,
            "total_students": len(enrolled_students) if enrolled_students else random.randint(20, 55),
        })

    return performance


def main():
    print("=" * 60)
    print("Technify University - Synthetic Data Generator")
    print("=" * 60)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    faculty = generate_faculty()
    courses = generate_courses(faculty)
    students = generate_students(courses)
    attendance = generate_attendance(students, courses)
    exams = generate_exams(students, courses)
    upcoming_exams = generate_upcoming_exams(students, courses)
    timetable = generate_timetable(students, courses)
    assignments = generate_assignments(students, courses)

    at_risk_students = generate_at_risk_students(students, courses, attendance)
    admin_stats = generate_admin_stats()
    department_finance = generate_department_finance()
    pending_fees = generate_pending_fees(students)
    scholarship_stats = generate_scholarship_stats()
    financial_summary = generate_financial_summary(students)
    fee_stats = generate_fee_stats(students)
    course_performance = generate_course_performance(students, courses, exams)

    datasets = {
        "students": students,
        "faculty": faculty,
        "courses": courses,
        "attendance": attendance,
        "exams": exams,
        "upcoming_exams": upcoming_exams,
        "timetable": timetable,
        "assignments": assignments,
        "admin_stats": admin_stats,
        "at_risk_students": at_risk_students,
        "department_finance": department_finance,
        "pending_fees": pending_fees,
        "scholarship_stats": scholarship_stats,
        "financial_summary": financial_summary,
        "fee_stats": fee_stats,
        "course_performance": course_performance,
    }

    print("\nSaving data...")
    for name, data in datasets.items():
        filepath = os.path.join(OUTPUT_DIR, f"{name}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        count = len(data) if isinstance(data, list) else 1
        print(f"   [OK] {name}.json ({count:,} records)")

    total_records = (
        len(students) + len(faculty) + len(courses) + len(attendance)
        + len(exams) + len(upcoming_exams) + len(timetable) + len(assignments)
        + len(at_risk_students) + len(pending_fees) + len(course_performance) + 6
    )

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"   Students:              {len(students):>8,}")
    print(f"   Faculty:               {len(faculty):>8,}")
    print(f"   Courses:               {len(courses):>8,}")
    print(f"   Attendance Records:    {len(attendance):>8,}")
    print(f"   Exam Records:          {len(exams):>8,}")
    print(f"   Upcoming Exams:        {len(upcoming_exams):>8,}")
    print(f"   Timetable Records:     {len(timetable):>8,}")
    print(f"   Assignment Records:    {len(assignments):>8,}")
    print(f"   At-Risk Students:      {len(at_risk_students):>8,}")
    print(f"   Pending Fee Records:   {len(pending_fees):>8,}")
    print(f"   Course Performance:    {len(course_performance):>8,}")
    print(f"   Total Records:         {total_records:>8,}")
    print(f"\n   Output Directory: {os.path.abspath(OUTPUT_DIR)}")
    print("=" * 60)
    print("Data generation complete!")


if __name__ == "__main__":
    main()
