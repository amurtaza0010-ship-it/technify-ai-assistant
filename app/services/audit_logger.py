"""
TAIA Audit Logger - Phase 3
Logs every request to a SQLite database.
"""
import os
from pathlib import Path
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, Text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# --- Database Setup
# Using hidden file in root directory to prevent uvicorn auto-reload bugs
DB_PATH = ".audit.db"
DB_URL  = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")


def _normalize_db_url(url: str) -> str:
    """Ensure SQLite database directories exist before the engine is created."""
    parsed = make_url(url)
    if parsed.drivername != "sqlite" or not parsed.database:
        return url

    db_path = Path(parsed.database)
    if not db_path.is_absolute():
        db_path = (Path.cwd() / db_path).resolve()
    else:
        db_path = db_path.resolve()

    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.as_posix()}"


DB_URL = _normalize_db_url(DB_URL)
engine = create_engine(DB_URL, echo=False, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

class AuditLog(Base):
    """Database model for audit logs."""
    __tablename__ = "audit_logs"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    timestamp     = Column(DateTime, default=datetime.utcnow, nullable=False)
    user_id       = Column(String(50), nullable=False)
    role          = Column(String(30), nullable=False)
    query         = Column(Text,       nullable=False)
    response_type = Column(String(50), nullable=False)
    response_time = Column(Float,      nullable=False)
    auth_mode     = Column(String(20), default="header")

# Create tables on startup
Base.metadata.create_all(bind=engine)

def log_request(user_id: str, role: str, query: str,
                response_type: str, response_time: float,
                auth_mode: str = "header") -> None:
    """
    Log a single chat request to the audit database.
    """
    db = SessionLocal()
    try:
        entry = AuditLog(
            user_id       = user_id,
            role          = role,
            query         = query[:500],      # cap at 500 chars
            response_type = response_type,
            response_time = round(response_time, 3),
            auth_mode     = auth_mode
        )
        db.add(entry)
        db.commit()
        print(f"[AUDIT] {user_id} ({role}): {response_type} in {response_time:.2f}s")
    except Exception as e:
        print(f"[AUDIT ERROR] Could not write log: {e}")
        db.rollback()
    finally:
        db.close()

def get_recent_logs(limit: int = 50) -> list:
    """
    Retrieve the most recent audit log entries.
    Used by the /api/v1/admin/audit-logs endpoint.
    """
    db = SessionLocal()
    try:
        rows = (db.query(AuditLog)
                .order_by(AuditLog.timestamp.desc())
                .limit(limit)
                .all())
        return [
            {
                "id":            r.id,
                "timestamp":     r.timestamp.isoformat(),
                "user_id":       r.user_id,
                "role":          r.role,
                "query":         r.query,
                "intent":        r.response_type,
                "latency":       r.response_time,
                "auth_mode":     r.auth_mode,
            }
            for r in rows
        ]
    finally:
        db.close()

def get_stats() -> dict:
    """
    Return high-level usage statistics.
    Used by the /api/v1/admin/stats endpoint.
    """
    db = SessionLocal()
    try:
        total   = db.query(AuditLog).count()
        by_role = {}
        for role in ["Student", "Faculty", "Admin"]:
            by_role[role] = db.query(AuditLog).filter(
                AuditLog.role == role).count()
        
        avg_time = db.query(AuditLog.response_time).all()
        avg = (sum([r[0] for r in avg_time]) / max(len(avg_time), 1)
               if avg_time else 0)
        
        return {
            "total_requests":     total,
            "by_role":            by_role,
            "avg_response_time_s": round(avg, 3)
        }
    finally:
        db.close()
