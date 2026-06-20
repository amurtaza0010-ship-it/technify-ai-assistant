from config.logging_config import setup_central_logger

# Initialize the central audit logger
audit_log = setup_central_logger("TAIA_AUDIT")

def log_security_event(user_id: str, role: str, action: str, status: str = "SUCCESS", details: str = ""):
    """Logs security, access, and RBAC-related events."""
    audit_log.info(f"User: {user_id} | Role: {role} | Action: {action} | Status: {status} | Details: {details}")

def log_data_access(user_id: str, endpoint: str, intent: str):
    """Logs when a user or AI accesses specific ERP data."""
    audit_log.info(f"DATA_ACCESS | User: {user_id} | Endpoint: {endpoint} | Intent: {intent}")

def log_request(user_id: str, role: str, message: str, intent: str, elapsed_time: float):
    """Compatible function for TAIA main.py chat endpoint."""
    audit_log.info(f"CHAT_LOG | User: {user_id} ({role}) | Intent: {intent} | Time: {elapsed_time}s")