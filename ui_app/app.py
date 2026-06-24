import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, render_template, request

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

app = Flask(__name__)

ERP_API_BASE_URL = os.getenv("ERP_API_BASE_URL", "http://127.0.0.1:8801/api/v1").rstrip("/")


@app.context_processor
def inject_taia_config():
    return {
        "taia_ai_url": os.getenv("TAIA_API_URL", "http://127.0.0.1:8000"),
        "taia_erp_url": os.getenv("ERP_PUBLIC_URL", "http://127.0.0.1:8801"),
    }


@app.route("/api/v1/auth/login", methods=["POST"])
def proxy_auth_login():
    """Proxy login to the mock ERP so the browser uses same-origin requests (no CORS)."""
    erp_url = f"{ERP_API_BASE_URL}/auth/login"
    proxy_request = urllib.request.Request(
        erp_url,
        data=request.get_data(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(proxy_request, timeout=30) as erp_response:
            body = erp_response.read()
            content_type = erp_response.headers.get_content_type() or "application/json"
            return Response(body, status=erp_response.status, content_type=content_type)
    except urllib.error.HTTPError as exc:
        body = exc.read()
        content_type = exc.headers.get_content_type() if exc.headers else "application/json"
        return Response(body, status=exc.code, content_type=content_type)
    except urllib.error.URLError:
        return Response(
            json.dumps({"detail": "Cannot reach ERP server"}),
            status=502,
            content_type="application/json",
        )


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/admin")
def admin():
    return render_template("admin.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
