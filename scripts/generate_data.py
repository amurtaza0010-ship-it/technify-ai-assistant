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
from collections import defaultdict
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
NUM_AT_RISK = 150
REFERENCE_DATE = datetime(2026, 6, 21)

DEMO_FACULTY_ID = "FAC-0001"
FEATURED_COURSE_NAMES = [
    "Artificial Intelligence",
    "Technical Writing",
    "Database Systems",
    "Operating Systems",
    "Software Engineering",
    "Machine Learning",
    "Business Intelligence",
    "Marketing Management",
    "Fluid Mechanics",
    "Communication Skills",
]
FEATURED_COURSE_CODES = {
    "Artificial Intelligence": "AI-401",
    "Technical Writing": "CS-210",
    "Database Systems": "CS-302",
    "Operating Systems": "CS-304",
    "Software Engineering": "SE-401",
    "Machine Learning": "AI-402",
    "Business Intelligence": "DS-350",
    "Marketing Management": "BA-310",
    "Fluid Mechanics": "ME-320",
    "Communication Skills": "HU-105",
}
STUDENTS_PER_FEATURED_COURSE = 45

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
    demo_faculty = next(
        (f for f in faculty_list if f["faculty_id"] == DEMO_FACULTY_ID),
        faculty_list[0],
    )
    course_index = 1

    for course_name in FEATURED_COURSE_NAMES:
        used_names.add(course_name)
        courses.append({
            "course_id": f"CRS-{course_index:04d}",
            "course_name": course_name,
            "course_code": FEATURED_COURSE_CODES[course_name],
            "credit_hours": 3,
            "department": demo_faculty["department"],
            "semester": random.randint(3, 6),
            "faculty_id": demo_faculty["faculty_id"],
            "faculty_name": demo_faculty["name"],
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
            "total_classes": random.randint(32, 40),
            "max_students": 50,
        })
        course_index += 1

    while course_index <= NUM_COURSES:
        course_name = random.choice(COURSE_NAMES)
        while course_name in used_names and len(used_names) < len(COURSE_NAMES):
            course_name = random.choice(COURSE_NAMES)
        used_names.add(course_name)

        assigned_faculty = random.choice(faculty_list)
        credit_hours = random.choice([2, 3, 3, 3, 4])

        courses.append({
            "course_id": f"CRS-{course_index:04d}",
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
        course_index += 1
    return courses


def build_course_enrollment_map(students, courses):
    """Map each course to enrolled students (linked, not random)."""
    print("[ENROLLMENTS] Building course enrollment map...")
    featured_ids = {
        c["course_id"] for c in courses if c["course_name"] in FEATURED_COURSE_NAMES
    }
    enrollment_map = {}

    for course in courses:
        eligible = [
            s for s in students
            if s["department"] == course["department"] and s["semester"] >= course["semester"]
        ]
        if len(eligible) < 20:
            eligible = [s for s in students if s["semester"] >= course["semester"]]
        if len(eligible) < 20:
            eligible = students

        target_size = (
            STUDENTS_PER_FEATURED_COURSE
            if course["course_id"] in featured_ids
            else random.randint(28, 38)
        )
        target_size = min(target_size, len(eligible))
        enrolled = random.sample(eligible, target_size)
        enrollment_map[course["course_id"]] = enrolled

        for student in enrolled:
            enrollment_entry = {
                "course_id": course["course_id"],
                "course_name": course["course_name"],
                "course_code": course["course_code"],
                "credit_hours": course["credit_hours"],
                "grade": "IP",
                "grade_points": 0.0,
                "percentage": 0.0,
            }
            existing_ids = {e["course_id"] for e in student["enrollments"]}
            if course["course_id"] not in existing_ids:
                student["enrollments"].append(enrollment_entry)

    return enrollment_map


def _attendance_counts_for_target(total_classes, target_pct):
    """Return present, absent, late counts matching target attendance percentage."""
    target_pct = max(40.0, min(98.0, target_pct))
    attended_equiv = round(total_classes * target_pct / 100)
    late = min(random.randint(0, 4), attended_equiv)
    present = max(0, attended_equiv - late)
    absent = max(0, total_classes - present - late)
    while present + late * 0.5 + absent > total_classes:
        absent -= 1
    while present + late * 0.5 < attended_equiv and present + late + absent < total_classes:
        present += 1
    return present, absent, late


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


def generate_attendance(students, courses, enrollment_map):
    print(f"[ATTENDANCE] Generating attendance records from course enrollments...")
    attendance = []
    summaries = []
    start_date = datetime(2026, 1, 15)
    record_index = 1

    for course in courses:
        enrolled = enrollment_map.get(course["course_id"], [])
        total_classes = course["total_classes"]

        for student in enrolled:
            if random.random() < 0.28:
                target_pct = random.uniform(45, 74.5)
            else:
                target_pct = random.uniform(75, 97)
            present, absent, late = _attendance_counts_for_target(total_classes, target_pct)

            statuses = ["Present"] * present + ["Absent"] * absent + ["Late"] * late
            random.shuffle(statuses)

            for class_num, status in enumerate(statuses):
                record_date = start_date + timedelta(days=class_num * 2)
                while record_date.weekday() >= 5:
                    record_date += timedelta(days=1)

                attendance.append({
                    "record_id": f"ATT-{record_index:06d}",
                    "student_id": student["student_id"],
                    "student_name": student["name"],
                    "course_id": course["course_id"],
                    "course_code": course["course_code"],
                    "course_name": course["course_name"],
                    "date": record_date.strftime("%Y-%m-%d"),
                    "status": status,
                    "marked_by": course["faculty_id"],
                })
                record_index += 1

            attended_classes = present + late
            attendance_pct = round((present + late * 0.5) / max(total_classes, 1) * 100, 1)
            summaries.append({
                "student_id": student["student_id"],
                "student_name": student["name"],
                "course_id": course["course_id"],
                "course_code": course["course_code"],
                "course_name": course["course_name"],
                "attendance_percentage": attendance_pct,
                "total_classes": total_classes,
                "attended_classes": attended_classes,
                "absent_classes": absent,
                "late_count": late,
                "warning_flag": attendance_pct < 75,
            })

    return attendance, summaries


def generate_exams(students, courses, enrollment_map):
    print(f"[EXAMS] Generating exam records from course enrollments...")
    exams = []
    performance = []
    record_index = 1

    exam_templates = [
        {"type": "Quiz 1", "total_marks": 10, "weight": 0.10},
        {"type": "Quiz 2", "total_marks": 10, "weight": 0.10},
        {"type": "Quiz 3", "total_marks": 10, "weight": 0.10},
        {"type": "Midterm", "total_marks": 30, "weight": 0.30},
        {"type": "Final", "total_marks": 50, "weight": 0.40},
    ]

    for course in courses:
        enrolled = enrollment_map.get(course["course_id"], [])
        course_percentages = []

        for student in enrolled:
            if random.random() < 0.18:
                base_pct = random.uniform(35, 49)
            elif random.random() < 0.25:
                base_pct = random.uniform(50, 69)
            else:
                base_pct = random.uniform(70, 95)

            quiz_scores = []
            midterm_score = None
            final_score = None

            for template in exam_templates:
                pct = max(20, min(100, random.gauss(base_pct, 8)))
                marks = round(template["total_marks"] * pct / 100, 1)
                grade = percentage_to_grade(pct)
                exam_date = f"2026-{random.choice(['02', '03', '04', '05'])}-{random.randint(1, 28):02d}"

                exams.append({
                    "record_id": f"EXM-{record_index:06d}",
                    "student_id": student["student_id"],
                    "student_name": student["name"],
                    "course_id": course["course_id"],
                    "course_code": course["course_code"],
                    "course_name": course["course_name"],
                    "exam_type": template["type"],
                    "marks_obtained": marks,
                    "total_marks": template["total_marks"],
                    "percentage": round(pct, 1),
                    "grade": grade,
                    "date": exam_date,
                })
                record_index += 1

                if template["type"].startswith("Quiz"):
                    quiz_scores.append(round(pct, 1))
                elif template["type"] == "Midterm":
                    midterm_score = round(pct, 1)
                elif template["type"] == "Final":
                    final_score = round(pct, 1)

            total_pct = round(
                sum(q * 0.10 for q in quiz_scores)
                + (midterm_score or 0) * 0.30
                + (final_score or 0) * 0.40,
                1,
            )
            course_percentages.append(total_pct)
            gpa = round(max(0, (total_pct / 100) * 4.0), 2)
            if gpa > 4.0:
                gpa = 4.0

            performance.append({
                "student_id": student["student_id"],
                "student_name": student["name"],
                "course_id": course["course_id"],
                "course_code": course["course_code"],
                "course": course["course_name"],
                "quizzes": quiz_scores,
                "midterm": midterm_score,
                "final": final_score,
                "total": total_pct,
                "GPA": gpa,
                "current_grade": percentage_to_grade(total_pct),
                "class_average": 0.0,
                "at_risk": total_pct < 50 or gpa < 2.5,
                "remarks": (
                    "Needs improvement — attendance and assessment scores below threshold"
                    if total_pct < 50 or gpa < 2.5
                    else "On track"
                ),
            })

        if course_percentages:
            avg = round(sum(course_percentages) / len(course_percentages), 1)
            for row in performance:
                if row["course_id"] == course["course_id"]:
                    row["class_average"] = avg

    return exams, performance


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


def generate_assignments(students, courses, enrollment_map):
    print(f"[ASSIGNMENTS] Generating assignment records from course enrollments...")
    assignments = []
    assignment_index = 1
    assignment_titles = [
        "Lab Report 1",
        "Lab Report 2",
        "Project Proposal",
        "Midterm Assignment",
        "Final Project",
    ]

    for course in courses:
        enrolled = enrollment_map.get(course["course_id"], [])
        for student in enrolled:
            for title in assignment_titles:
                due_offset = random.randint(-25, 45)
                due_date = REFERENCE_DATE + timedelta(days=due_offset)
                roll = random.random()

                if roll < 0.12:
                    status = "Missing"
                    submitted = False
                    graded = False
                    pending_grading = False
                    missing_submission = True
                    marks_obtained = None
                    submitted_date = None
                elif roll < 0.22:
                    status = "Pending"
                    submitted = False
                    graded = False
                    pending_grading = False
                    missing_submission = False
                    marks_obtained = None
                    submitted_date = None
                elif roll < 0.35:
                    status = "Submitted"
                    submitted = True
                    graded = False
                    pending_grading = True
                    missing_submission = False
                    marks_obtained = None
                    submitted_date = (due_date - timedelta(days=random.randint(0, 2))).strftime("%Y-%m-%d")
                elif roll < 0.42:
                    status = "Late"
                    submitted = True
                    graded = True
                    pending_grading = False
                    missing_submission = False
                    marks_obtained = round(random.uniform(4, 12), 1)
                    submitted_date = (due_date + timedelta(days=random.randint(1, 4))).strftime("%Y-%m-%d")
                else:
                    status = "Submitted"
                    submitted = True
                    graded = True
                    pending_grading = False
                    missing_submission = False
                    marks_obtained = round(random.uniform(8, 15), 1)
                    submitted_date = (due_date - timedelta(days=random.randint(0, 3))).strftime("%Y-%m-%d")

                assignments.append({
                    "assignment_id": f"ASN-{assignment_index:06d}",
                    "assignment_name": f"{title} - {course['course_name']}",
                    "student_id": student["student_id"],
                    "student_name": student["name"],
                    "course_id": course["course_id"],
                    "course_code": course["course_code"],
                    "course": course["course_name"],
                    "course_name": course["course_name"],
                    "assignment_title": f"{title} - {course['course_name']}",
                    "total_marks": 15,
                    "average_marks": marks_obtained,
                    "marks_obtained": marks_obtained,
                    "due_date": due_date.strftime("%Y-%m-%d"),
                    "submitted_date": submitted_date,
                    "submitted": submitted,
                    "graded": graded,
                    "pending_grading": pending_grading,
                    "missing_submission": missing_submission,
                    "status": status,
                    "faculty_id": course["faculty_id"],
                })
                assignment_index += 1

    return assignments


def compute_course_attendance_pct(attendance_records):
    if not attendance_records:
        return 0.0
    present = sum(1 for r in attendance_records if r["status"] == "Present")
    late = sum(1 for r in attendance_records if r["status"] == "Late")
    total = len(attendance_records)
    return round((present + late * 0.5) / max(total, 1) * 100, 1)


def generate_at_risk_students(students, courses, attendance_summaries, student_performance):
    print(f"[AT-RISK] Generating at-risk student records...")
    at_risk = []
    seen = set()

    for summary in attendance_summaries:
        if not summary["warning_flag"]:
            continue
        key = (summary["student_id"], summary["course_id"])
        if key in seen:
            continue
        seen.add(key)
        at_risk.append({
            "student_id": summary["student_id"],
            "name": summary["student_name"],
            "course_id": summary["course_id"],
            "course_name": summary["course_name"],
            "attendance_percentage": summary["attendance_percentage"],
            "reason": "Attendance below 75%",
        })

    for perf in student_performance:
        if not perf["at_risk"]:
            continue
        key = (perf["student_id"], perf["course_id"])
        if key in seen:
            continue
        seen.add(key)
        at_risk.append({
            "student_id": perf["student_id"],
            "name": perf["student_name"],
            "course_id": perf["course_id"],
            "course_name": perf["course"],
            "attendance_percentage": None,
            "GPA": perf["GPA"],
            "midterm": perf["midterm"],
            "reason": "Low academic performance (GPA below 2.5 or failing assessments)",
        })

    at_risk.sort(key=lambda x: (x.get("attendance_percentage") or 0, -(x.get("GPA") or 4)))
    if len(at_risk) < NUM_AT_RISK:
        for perf in student_performance:
            if len(at_risk) >= NUM_AT_RISK:
                break
            key = (perf["student_id"], perf["course_id"])
            if key in seen:
                continue
            seen.add(key)
            at_risk.append({
                "student_id": perf["student_id"],
                "name": perf["student_name"],
                "course_id": perf["course_id"],
                "course_name": perf["course"],
                "attendance_percentage": None,
                "GPA": perf["GPA"],
                "midterm": perf["midterm"],
                "reason": "Monitoring recommended",
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


def generate_course_performance(students, courses, exams, enrollment_map, attendance_summaries, assignments):
    print("[COURSE PERFORMANCE] Generating course performance and analytics metrics...")
    performance = []
    summary_by_course = defaultdict(list)
    for row in attendance_summaries:
        summary_by_course[row["course_id"]].append(row)

    assignments_by_course = defaultdict(list)
    for row in assignments:
        assignments_by_course[row["course_id"]].append(row)

    for course in courses:
        course_id = course["course_id"]
        course_exams = [e for e in exams if e["course_id"] == course_id]
        enrolled_students = enrollment_map.get(course_id, [])
        att_rows = summary_by_course.get(course_id, [])
        course_assignments = assignments_by_course.get(course_id, [])

        if course_exams:
            avg_pct = round(sum(e["percentage"] for e in course_exams) / len(course_exams), 1)
            pass_count = sum(1 for e in course_exams if e["percentage"] >= 50)
            pass_rate = round(pass_count / len(course_exams) * 100, 1)
            fail_rate = round(100 - pass_rate, 1)
        else:
            avg_pct = round(random.uniform(55, 85), 1)
            pass_rate = round(random.uniform(70, 95), 1)
            fail_rate = round(100 - pass_rate, 1)

        if att_rows:
            average_attendance = round(
                sum(r["attendance_percentage"] for r in att_rows) / len(att_rows), 1
            )
        else:
            average_attendance = round(random.uniform(72, 92), 1)

        if course_assignments:
            submitted_count = sum(1 for a in course_assignments if a.get("submitted"))
            assignment_completion = round(submitted_count / len(course_assignments) * 100, 1)
            graded_count = sum(
                1 for a in course_assignments
                if a.get("graded") and a.get("marks_obtained") is not None
            )
            grading_progress = round(graded_count / len(course_assignments) * 100, 1)
        else:
            assignment_completion = round(random.uniform(75, 95), 1)
            grading_progress = round(random.uniform(60, 90), 1)

        performance.append({
            "course_id": course_id,
            "course_name": course["course_name"],
            "course_code": course["course_code"],
            "faculty_id": course["faculty_id"],
            "average_grade": percentage_to_grade(avg_pct),
            "average_percentage": avg_pct,
            "pass_rate": pass_rate,
            "fail_rate": fail_rate,
            "total_students": len(enrolled_students),
            "enrollment": len(enrolled_students),
            "average_attendance": average_attendance,
            "assignment_completion": assignment_completion,
            "grading_progress": grading_progress,
        })

    return performance


def generate_faculty_dashboard(faculty_id, courses, assignments, at_risk_students, attendance_summaries):
    print("[FACULTY DASHBOARD] Generating faculty dashboard statistics...")
    faculty_courses = [c for c in courses if c["faculty_id"] == faculty_id]
    faculty_course_ids = {c["course_id"] for c in faculty_courses}
    faculty_assignments = [a for a in assignments if a.get("faculty_id") == faculty_id]
    faculty_attendance = [s for s in attendance_summaries if s["course_id"] in faculty_course_ids]

    pending_grading = sum(1 for a in faculty_assignments if a.get("pending_grading"))
    ungraded = sum(
        1 for a in faculty_assignments
        if not a.get("graded", True) or a.get("marks_obtained") is None
    )
    students_at_risk = len({
        (s["student_id"], s["course_id"])
        for s in at_risk_students
        if s["course_id"] in faculty_course_ids
    })
    attendance_alerts = sum(1 for s in faculty_attendance if s.get("warning_flag"))
    upcoming_deadlines = sum(
        1 for a in faculty_assignments
        if a.get("due_date")
        and REFERENCE_DATE <= datetime.strptime(a["due_date"], "%Y-%m-%d") <= REFERENCE_DATE + timedelta(days=14)
        and not a.get("submitted")
    )
    recent_submissions = sum(
        1 for a in faculty_assignments
        if a.get("submitted")
        and a.get("submitted_date")
        and datetime.strptime(a["submitted_date"], "%Y-%m-%d") >= REFERENCE_DATE - timedelta(days=7)
    )

    course_summaries = []
    for course in faculty_courses:
        cid = course["course_id"]
        course_assignments = [a for a in faculty_assignments if a["course_id"] == cid]
        course_attendance = [s for s in faculty_attendance if s["course_id"] == cid]
        course_summaries.append({
            "course_id": cid,
            "course_code": course["course_code"],
            "course_name": course["course_name"],
            "enrollment": len({a["student_id"] for a in course_assignments}),
            "average_attendance": round(
                sum(s["attendance_percentage"] for s in course_attendance) / max(len(course_attendance), 1),
                1,
            ),
            "pending_grading": sum(1 for a in course_assignments if a.get("pending_grading")),
            "students_at_risk": sum(
                1 for s in at_risk_students if s["course_id"] == cid
            ),
        })

    return {
        "faculty_id": faculty_id,
        "pending_grading": pending_grading,
        "students_at_risk": students_at_risk,
        "attendance_alerts": attendance_alerts,
        "upcoming_deadlines": upcoming_deadlines,
        "recent_submissions": recent_submissions,
        "total_ungraded": ungraded,
        "course_summaries": course_summaries,
    }


def sync_student_grades(students, student_performance):
    """Update enrollment grades and student GPA from generated performance records."""
    perf_by_key = {
        (p["student_id"], p["course_id"]): p for p in student_performance
    }
    for student in students:
        for enrollment in student["enrollments"]:
            perf = perf_by_key.get((student["student_id"], enrollment["course_id"]))
            if not perf:
                continue
            enrollment["percentage"] = perf["total"]
            enrollment["grade"] = perf["current_grade"]
            enrollment["grade_points"] = GRADE_POINTS.get(perf["current_grade"], 0.0)
        graded_enrollments = [e for e in student["enrollments"] if e.get("grade") != "IP"]
        gpa = calculate_weighted_gpa(graded_enrollments) if graded_enrollments else student.get("gpa", 3.0)
        gpa = max(2.0, min(4.0, gpa))
        student["gpa"] = gpa
        student["cgpa"] = gpa


def main():
    print("=" * 60)
    print("Technify University - Synthetic Data Generator")
    print("=" * 60)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    faculty = generate_faculty()
    courses = generate_courses(faculty)
    students = generate_students(courses)
    enrollment_map = build_course_enrollment_map(students, courses)
    attendance, attendance_summaries = generate_attendance(students, courses, enrollment_map)
    exams, student_performance = generate_exams(students, courses, enrollment_map)
    sync_student_grades(students, student_performance)
    upcoming_exams = generate_upcoming_exams(students, courses)
    timetable = generate_timetable(students, courses)
    assignments = generate_assignments(students, courses, enrollment_map)

    at_risk_students = generate_at_risk_students(
        students, courses, attendance_summaries, student_performance
    )
    admin_stats = generate_admin_stats()
    department_finance = generate_department_finance()
    pending_fees = generate_pending_fees(students)
    scholarship_stats = generate_scholarship_stats()
    financial_summary = generate_financial_summary(students)
    fee_stats = generate_fee_stats(students)
    course_performance = generate_course_performance(
        students, courses, exams, enrollment_map, attendance_summaries, assignments
    )
    faculty_dashboard = generate_faculty_dashboard(
        DEMO_FACULTY_ID, courses, assignments, at_risk_students, attendance_summaries
    )

    datasets = {
        "students": students,
        "faculty": faculty,
        "courses": courses,
        "attendance": attendance,
        "student_attendance_summary": attendance_summaries,
        "exams": exams,
        "student_performance": student_performance,
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
        "course_analytics": course_performance,
        "faculty_dashboard": faculty_dashboard,
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
        + len(attendance_summaries) + len(exams) + len(student_performance)
        + len(upcoming_exams) + len(timetable) + len(assignments)
        + len(at_risk_students) + len(pending_fees) + len(course_performance) + 7
    )

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"   Students:                  {len(students):>8,}")
    print(f"   Faculty:                   {len(faculty):>8,}")
    print(f"   Courses:                   {len(courses):>8,}")
    print(f"   Attendance Records:        {len(attendance):>8,}")
    print(f"   Attendance Summaries:      {len(attendance_summaries):>8,}")
    print(f"   Exam Records:              {len(exams):>8,}")
    print(f"   Student Performance:       {len(student_performance):>8,}")
    print(f"   Upcoming Exams:            {len(upcoming_exams):>8,}")
    print(f"   Timetable Records:         {len(timetable):>8,}")
    print(f"   Assignment Records:        {len(assignments):>8,}")
    print(f"   At-Risk Students:          {len(at_risk_students):>8,}")
    print(f"   Pending Fee Records:       {len(pending_fees):>8,}")
    print(f"   Course Performance:        {len(course_performance):>8,}")
    print(f"   Total Records:             {total_records:>8,}")
    print(f"\n   Output Directory: {os.path.abspath(OUTPUT_DIR)}")
    print("=" * 60)
    print("Data generation complete!")


if __name__ == "__main__":
    main()
