"""
Technify Academic AI Assistant (TAIA)
=====================================
FastAPI Application Entry Point

This is the main entry point for the AI Assistant microservice.
Run with: uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os
import json
import time

# Import the RoleChecker from our custom authorization module
from app.auth.rbac import RoleChecker  
# Import our new JWT handler
from app.auth.jwt_handler import verify_user_access

# Load environment variables from .env file
load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("=" * 50)
    print("Technify Academic AI Assistant (TAIA)")
    print("Service is starting...")
    print(f"Docs available at: http://localhost:{os.getenv('APP_PORT', 8000)}/docs")
    print("=" * 50)
    yield

# Initialize FastAPI application
app = FastAPI(
    title="Technify Academic AI Assistant (TAIA)",
    description="AI-powered academic assistant integrated with Technify University ERP",
    version="0.1.0",
    docs_url="/docs",          # Swagger UI path
    redoc_url="/redoc",        # ReDoc path,
    lifespan=lifespan,
)

# CORS Middleware configuration to allow the ERP frontend to make requests
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5000,http://localhost:8080").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================================
# SYSTEM SECURITY RULES (Defining Access Control for Student, Faculty, & Admin)
# =========================================================================
allow_student_and_admin = RoleChecker(["Student", "Admin"])
allow_only_faculty = RoleChecker(["Faculty"])
allow_only_admin = RoleChecker(["Admin"])


# ========== Health Check Endpoints ==========

@app.get("/", tags=["Health"])
async def root():
    # Verify if the application service gateway is up and running
    return {
        "service": "Technify Academic AI Assistant (TAIA)",
        "status": "running",
        "version": "0.1.0",
    }


@app.get("/health", tags=["Health"])
async def health_check():
    # System health status monitoring endpoint
    return {
        "status": "healthy",
        "components": {
            "api": "up",
            "llm": "not_configured",       # TODO: Check LLM connection
            "vector_db": "not_configured",  # TODO: Check ChromaDB connection
            "erp_api": "not_configured",    # TODO: Check ERP API connection
        },
    }


# ========== Academic & Security Test Endpoints ==========

# 1. Student Route (Accessible by Students and Admins)
@app.get("/api/v1/student/attendance", tags=["Student Features"], dependencies=[Depends(allow_student_and_admin)])
async def get_attendance():
    return {
        "course": "Web Engineering (CS-301)",
        "attendance": "78%",
        "classes_attended": "25 out of 32"
    }


# 2. Faculty Route (Restricted strictly to Faculty members)
@app.get("/api/v1/faculty/at-risk-students", tags=["Faculty Features"], dependencies=[Depends(allow_only_faculty)])
async def get_at_risk_students():
    # Test route to check faculty tracking features
    return {
        "department": "Information Technology",
        "at_risk_count": 4,
        "students": [
            {"id": "STU-0091", "name": "Ali", "attendance": "54%", "reason": "Low Attendance"},
            {"id": "STU-0142", "name": "Sana", "attendance": "62%", "reason": "Ungraded Assignments"}
        ]
    }


# 3. Admin Route (Restricted exclusively to Admin role)
@app.get("/api/v1/admin/fee-report", tags=["Admin Reports"], dependencies=[Depends(allow_only_admin)])
async def get_fee_report():
    return {
        "total_expected": "PKR 425M",
        "collected": "PKR 382.5M",
        "percentage": "90%"
    }


from app.chains.chatbot_chain import (
    generate_chat_response, generate_contextual_response, classify_intent_async)
from app.services.erp_connector import *
from app.services.study_planner import generate_study_plan
from app.services.knowledge_base import query_knowledge_base
from app.services.audit_logger import log_request

# ========== Chat Endpoint ==========

@app.post('/api/v1/chat', tags=['Chat'])
async def chat(request: Request, message: dict, user_data: dict = Depends(verify_user_access)):
    # Extract user information from the validated token/headers
    uid      = user_data.get('user_id', 'STU-0001')
    role     = user_data.get('role', 'Student')
    session  = request.headers.get('x-session-id', uid)
    user_msg = message.get('message', '')
    
    if not user_msg: return {'response': 'Please provide a message.'}
    start    = time.time()
    intent   = await classify_intent_async(session, user_msg, role)
    erp_data = ''
    
    try:
        # ■■ Student intents ■■
        if   intent == 'attendance' : erp_data = json.dumps(await get_student_attendance(uid))
        elif intent == 'results'    : erp_data = json.dumps(await get_student_results(uid))
        elif intent == 'fees'       : erp_data = json.dumps(await get_student_fees(uid))
        elif intent == 'courses'    : erp_data = json.dumps(await get_student_courses(uid))
        elif intent == 'timetable'  : erp_data = json.dumps(await get_student_timetable(uid))
        elif intent == 'assignments': erp_data = json.dumps(await get_student_assignments(uid))
        elif intent == 'exams'      : erp_data = json.dumps(await get_student_results(uid))
        elif intent == 'study_plan' :
            results = await get_student_results(uid)
            return {'response': generate_study_plan(results), 'intent': intent}
        elif intent == 'policy'     : erp_data = query_knowledge_base(user_msg)
        
        # ■■ Faculty intents ■■
        elif intent == 'faculty_attendance': erp_data = json.dumps(await get_all_faculty_attendance(uid))
        elif intent == 'faculty_ungraded'  : erp_data = json.dumps(await get_faculty_assignments(uid))
        elif intent == 'faculty_at_risk'   : erp_data = json.dumps(await get_all_faculty_at_risk(uid))
        
        # ■■ Admin intents — use actual erp_connector function names ■■
        elif intent == 'admin_students'   : erp_data = json.dumps(await get_admin_student_stats())
        elif intent == 'admin_admissions' : erp_data = json.dumps(await get_admin_admission_stats())
        elif intent == 'admin_fees'       : erp_data = json.dumps(await get_admin_fee_stats())
        elif intent == 'admin_departments': erp_data = json.dumps(await get_admin_department_stats())
    except Exception as e:
        erp_data = f'Error: {e}'
        
    if erp_data:
        ai = await generate_contextual_response(session, user_msg, erp_data, intent)
    else:
        ai = await generate_chat_response(session, user_msg)
        
    elapsed = round(time.time() - start, 2)
    log_request(uid, role, user_msg, intent, elapsed)
    return {'response': ai, 'intent': intent, 'time': f'{elapsed}s'}


# ========== Audit Logs & Usage Stats Endpoints ==========

from app.services.audit_logger import get_recent_logs, get_stats as get_audit_stats

@app.get('/api/v1/admin/audit-logs', tags=['Admin Reports'], dependencies=[Depends(allow_only_admin)])
async def audit_logs(limit: int = 50):
    """Return recent audit log entries from the database."""
    return get_recent_logs(limit=limit)

@app.get('/api/v1/admin/usage-stats', tags=['Admin Reports'], dependencies=[Depends(allow_only_admin)])
async def usage_stats():
    """Return overall usage statistics."""
    return get_audit_stats()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=os.getenv("APP_HOST", "0.0.0.0"),
        port=int(os.getenv("APP_PORT", 8000)),
        reload=False,
    )