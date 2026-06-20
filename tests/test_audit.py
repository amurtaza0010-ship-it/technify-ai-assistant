import importlib


def test_audit_logger_creates_sqlite_parent_directory(tmp_path, monkeypatch):
    db_file = tmp_path / "nested" / "audit.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")

    import app.services.audit_logger as audit_logger

    importlib.reload(audit_logger)

    assert db_file.parent.exists()
    assert db_file.exists()