"""RBAC + intent routing audit for TAIA."""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.auth.chat_rbac import ROLE_PERMISSIONS, check_chat_access, is_intent_allowed, normalize_role
from app.chains.chatbot_chain import _heuristic_intent, _resolve_intent_for_role
from app.services.erp_connector import (
    INTENT_TO_ENDPOINT_TYPE,
    guard_erp_endpoint_access,
    is_department_stats_query,
    map_intent_for_erp_fetch,
)
from app.utils.intent_routing import resolve_role_intent

TEST_PROMPTS = {
    "Exam Officer": [
        "Show course performance statistics",
        "Show ungraded assignments",
        "Show upcoming exam schedule",
        "Show at-risk students",
    ],
    "Finance Officer": [
        "Show fee collection status",
        "Show scholarship statistics",
        "Show department-wise fee stats",
        "Show pending fee statistics",
    ],
    "Faculty": [
        "Show my students at risk",
        "Show course performance",
    ],
    "Student": [
        "Show my fees",
        "Show my grades",
        "Show my attendance",
    ],
    "Admin": [
        "Show fee collection status",
        "Show course performance statistics",
        "Show department-wise student stats",
    ],
}

ROLE_UIDS = {
    "Student": "STU-0001",
    "Faculty": "FAC-0001",
    "Admin": "ADM-0001",
    "Finance Officer": "FIN-0001",
    "Exam Officer": "EXO-0001",
}

INTENT_ENDPOINTS = {
    "attendance": "/student/{id}/attendance",
    "results": "/student/{id}/results",
    "gpa": "/student/{id}/gpa",
    "fees": "/student/{id}/fees",
    "courses": "/student/{id}/courses",
    "timetable": "/student/{id}/timetable",
    "assignments": "/student/{id}/assignments",
    "exams": "/student/{id}/exams/upcoming",
    "faculty_attendance": "/faculty/{id}/courses+attendance",
    "faculty_ungraded": "/faculty/ungraded",
    "faculty_at_risk": "/faculty/{id}/courses+students",
    "faculty_courses": "/faculty/{id}/courses",
    "faculty_performance": "/faculty/course-performance",
    "admin_fees": "/admin/statistics/fees",
    "admin_finance_department": "/admin/finance/department-stats",
    "admin_finance_pending": "/admin/finance/pending-fees",
    "admin_finance_scholarship": "/admin/finance/scholarship-stats",
    "admin_finance_summary": "/admin/finance/summary",
    "admin_at_risk": "/admin/at-risk",
    "admin_students": "/admin/statistics/students",
    "admin_departments": "/admin/statistics/departments",
    "department_stats": "/admin/statistics/departments",
    "admin_overall": "/admin/overall-stats",
    "at_risk_students": "/admin/at-risk",
}


def route_prompt(role: str, message: str) -> dict:
    uid = ROLE_UIDS.get(role, "STU-0001")
    detected = _heuristic_intent(message, role)
    if detected is None:
        detected = "general"
    resolved = resolve_role_intent(
        role, _resolve_intent_for_role(detected, role, message), message
    )
    if is_department_stats_query(message) and resolved not in (
        "admin_finance_department",
    ):
        from app.utils.fees_intent import is_finance_department_fee_query
        if not is_finance_department_fee_query(message):
            resolved = "department_stats"
    allowed, denial = check_chat_access(
        role, detected, message, uid, resolved_intent=resolved
    )
    erp_intent = map_intent_for_erp_fetch(resolved, role, message)
    guard = guard_erp_endpoint_access(role, erp_intent, message)
    return {
        "role": role,
        "message": message,
        "detected_intent": detected,
        "resolved_intent": resolved,
        "erp_intent": erp_intent,
        "rbac_allowed": allowed,
        "denial": denial,
        "endpoint_guard": guard,
        "endpoint": INTENT_ENDPOINTS.get(erp_intent, "?"),
        "intent_in_role_permissions": is_intent_allowed(role, resolved),
    }


async def check_erp_data():
    import httpx
    base = os.getenv("ERP_API_BASE_URL", "http://localhost:8001/api/v1")
    endpoints = [
        "/student/STU-0001/attendance",
        "/student/STU-0001/results",
        "/student/STU-0001/fees",
        "/student/STU-0001/exams/upcoming",
        "/faculty/course-performance",
        "/faculty/ungraded",
        "/admin/at-risk",
        "/admin/statistics/fees",
        "/admin/finance/department-stats",
        "/admin/finance/pending-fees",
        "/admin/finance/scholarship-stats",
        "/admin/finance/summary",
        "/admin/statistics/departments",
        "/admin/overall-stats",
    ]
    results = {}
    async with httpx.AsyncClient(timeout=10.0) as client:
        for ep in endpoints:
            try:
                r = await client.get(f"{base}{ep}")
                body = r.json() if r.status_code == 200 else {"error": r.text[:200]}
                empty = False
                if isinstance(body, dict):
                    empty = len(body) == 0 or (
                        len(body) == 1 and list(body.values())[0] in ([], {}, None)
                    )
                elif isinstance(body, list):
                    empty = len(body) == 0
                results[ep] = {
                    "status": r.status_code,
                    "empty": empty,
                    "keys": list(body.keys())[:8] if isinstance(body, dict) else f"list[{len(body)}]",
                }
            except Exception as e:
                results[ep] = {"status": "error", "error": str(e)}
    return results


def main():
    print("=" * 70)
    print("PHASE 1 & 2: RBAC + INTENT ROUTING")
    print("=" * 70)
    for role, prompts in TEST_PROMPTS.items():
        print(f"\n--- {role} ---")
        perms = ROLE_PERMISSIONS.get(normalize_role(role))
        print(f"Allowed intents: {sorted(perms) if perms else 'ALL (admin)'}")
        for msg in prompts:
            r = route_prompt(role, msg)
            status = "ALLOW" if r["rbac_allowed"] and r["endpoint_guard"] is None else "DENY"
            print(f"  [{status}] {msg!r}")
            print(f"       detected={r['detected_intent']} resolved={r['resolved_intent']} erp={r['erp_intent']}")
            print(f"       rbac={r['rbac_allowed']} guard={r['endpoint_guard']} endpoint={r['endpoint']}")
            if r["denial"]:
                print(f"       denial={r['denial'][:80]}...")

    print("\n" + "=" * 70)
    print("PHASE 3: ERP DATA COVERAGE")
    print("=" * 70)
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "synthetic")
    if os.path.isdir(data_dir):
        for fn in sorted(os.listdir(data_dir)):
            if fn.endswith(".json"):
                path = os.path.join(data_dir, fn)
                with open(path, encoding="utf-8") as f:
                    d = json.load(f)
                n = len(d) if isinstance(d, list) else 1
                print(f"  {fn}: {n} records")
    else:
        print(f"  DATA GAP: {data_dir} missing — run scripts/generate_data.py")

    try:
        erp = asyncio.run(check_erp_data())
        for ep, info in erp.items():
            gap = " DATA GAP" if info.get("empty") or info.get("status") != 200 else ""
            print(f"  {ep}: {info}{gap}")
    except Exception as e:
        print(f"  ERP live check skipped: {e}")


if __name__ == "__main__":
    main()
