""" 
TAIA Security Tests — Phase 3 
Tests JWT validation, RBAC enforcement, and data privacy. 
""" 
import httpx 
import pytest 
 
BASE = "http://localhost:8000" 
ERP  = "http://localhost:8001" 
 
# ── Helper: get a real JWT token ────────────────────────────────
async def get_token(user_id: str, role: str) -> str: 
    async with httpx.AsyncClient() as c: 
        r = await c.post(f"{ERP}/api/v1/auth/login", 
                         json={"user_id": user_id, "role": role}) 
        return r.json()["token"] 
 
 
# ── 1. No credentials → 401 ──────────────────────────────────── 
@pytest.mark.asyncio 
async def test_no_auth_rejected(): 
    async with httpx.AsyncClient() as c: 
        r = await c.post(f"{BASE}/api/v1/chat", 
                         json={"message": "What is my attendance?"}) 
    assert r.status_code == 401 
 
 
# ── 2. Invalid JWT → 401 ───────────────────────────────────────── 
@pytest.mark.asyncio 
async def test_invalid_jwt_rejected(): 
    async with httpx.AsyncClient() as c: 
        r = await c.post(f"{BASE}/api/v1/chat", 
                         json={"message": "What is my attendance?"}, 
                         headers={"Authorization": "Bearer totally-fake-token"}) 
    assert r.status_code == 401 
 
 
# ── 3. Valid JWT token → 200 ───────────────────────────────────────── 
@pytest.mark.asyncio 
async def test_valid_jwt_accepted(): 
    token = await get_token("STU-0001", "student") 
    async with httpx.AsyncClient() as c: 
        r = await c.post(f"{BASE}/api/v1/chat", 
                         json={"message": "What is my attendance?"}, 
                         headers={"Authorization": f"Bearer {token}"}) 
    assert r.status_code == 200 
    assert "response" in r.json() 
 
 
# ── 4. Student cannot access Faculty route ───────────────────────── 
@pytest.mark.asyncio 
async def test_student_cannot_access_faculty_route(): 
    async with httpx.AsyncClient() as c: 
        r = await c.get(f"{BASE}/api/v1/faculty/at-risk-students", 
                        headers={"x-user-role": "Student", 
                                 "x-user-id": "STU-0001"}) 
    assert r.status_code == 403 
 
 
# ── 5. Faculty can access faculty route ──────────────────────────────── 
@pytest.mark.asyncio 
async def test_faculty_can_access_faculty_route(): 
    async with httpx.AsyncClient() as c: 
        r = await c.get(f"{BASE}/api/v1/faculty/at-risk-students", 
                        headers={"x-user-role": "Faculty", 
                                 "x-user-id": "FAC-0001"}) 
    assert r.status_code == 200 
 
 
# ── 6. Empty message → rejected gracefully ──────────────────────── 
@pytest.mark.asyncio
async def test_empty_message_rejected(): 
    async with httpx.AsyncClient() as c: 
        r = await c.post(f"{BASE}/api/v1/chat", 
                         json={"message": ""}, 
                         headers={"x-user-role": "Student", 
                                  "x-user-id": "STU-0001"}) 
    assert r.status_code == 200 
    assert "Please provide" in r.json()["response"] 
 
 
# ── 7. Audit log endpoint accessible ────────────────────────────────── 
@pytest.mark.asyncio 
async def test_audit_logs_endpoint(): 
    async with httpx.AsyncClient() as c: 
        r = await c.get(f"{BASE}/api/v1/admin/audit-logs") 
    assert r.status_code == 200 
    assert "logs" in r.json() 
 
 
# ── 8. Health check ───────────────────────────────────────────────── 
@pytest.mark.asyncio 
async def test_health(): 
    async with httpx.AsyncClient() as c: 
        r = await c.get(f"{BASE}/health") 
    assert r.json()["status"] == "healthy"