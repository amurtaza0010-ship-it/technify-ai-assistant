# TAIA Setup & Deployment Guide

Welcome to the Technify Academic AI Assistant (TAIA) project! This guide contains everything your team members need to know to pull the code, install dependencies, and run the project in either **Development Mode** or **Production Mode**.

## 1. Prerequisites Installation

Before pulling the code, ensure your system has the following installed:

### Git & Python
- **Git:** Download and install from [git-scm.com](https://git-scm.com/)
- **Python 3.10+:** Download and install from [python.org](https://www.python.org/)

### Docker Desktop (For Production Mode)
- **Windows/Mac:** Download [Docker Desktop](https://www.docker.com/products/docker-desktop/) and run the installer.
- **Note:** Make sure WSL2 is enabled if you are on Windows.

### Redis (Optional for Dev, Required for Production)
- *Note: TAIA has an automatic in-memory fallback if Redis is not installed, so your app will never crash without it.*
- **Windows:** The easiest way to run Redis on Windows is via Docker (covered in Production mode). Alternatively, you can install Redis via WSL (Windows Subsystem for Linux) using `sudo apt install redis-server`.

---

## 2. Getting Started

### For New Members (Fresh Install)
Open your terminal and run the following commands to get the code and install the Python dependencies:

```bash
# 1. Clone the repository
git clone https://github.com/your-org/technify-ai-assistant.git
cd technify-ai-assistant

# 2. Create a virtual environment
python -m venv venv

# 3. Activate the virtual environment
# On Windows:
.\venv\Scripts\activate
# On Mac/Linux:
source venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Generate Mock Data & Vector Store
# Since data files are ignored by git, you must generate them locally:
python scripts/generate_data.py
python scripts/ingest_documents.py
```

### For Existing Members (Updating)
If you already have the code and just need to pull the latest updates (like the new Admin Dashboard), run:
```bash
git checkout main
git pull origin main
# Always re-run requirements in case new packages were added!
pip install -r requirements.txt
```

### Environment Variables (.env)
Create a `.env` file in the root directory with the following variables. (Your team can copy-paste exactly this, just replace the API key).
*(Note: You can leave `JWT_SECRET_KEY` exactly as it is for local testing. It only needs to be changed to a random string on a real production server).*
```env
LLM_API_KEY=sk-or-v1-your-openrouter-key-here
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=openrouter/free
APP_HOST=0.0.0.0
APP_PORT=8000
ERP_API_BASE_URL=http://localhost:8001/api/v1
CORS_ORIGINS=http://localhost:3000,http://localhost:5000,http://localhost:8080
JWT_SECRET_KEY=taia-super-secret-key-change-in-production
JWT_ALGORITHM=HS256
REDIS_URL=redis://localhost:6379/0
DATABASE_URL=sqlite:///./logs/audit.db
```

---

## 3. Running in Development Mode (Local Testing)

In development mode, we run the services directly on our machine without Docker. This is great for debugging and making quick code changes.

You will need **three separate terminal windows**. Make sure your virtual environment (`venv`) is activated in all three!

**Terminal 1 (Mock ERP API):**
```bash
uvicorn mock_erp.main:app --port 8001
```

**Terminal 2 (FastAPI AI Brain):**
```bash
python -m app.main
```

**Terminal 3 (Frontend UI):**
```bash
python ui_app/app.py
```

Once all three are running, open your browser and go to: `http://127.0.0.1:5000`

---

## 4. Running in Production Mode (Docker)

For the final production deployment, we use `docker-compose` to spin up everything simultaneously (including a dedicated Redis container).

1. Ensure **Docker Desktop** is open and running in the background.
2. Open a single terminal in the project directory.
3. Run the deployment command:
   ```bash
   docker-compose up --build -d
   ```
   *(Note: The `--build` flag only takes a long time the very first time it downloads Python and installs requirements. On future runs, Docker caches everything instantly. You can also drop the `--build` flag on future runs.)*
4. The system will pull the Redis image, build the FastAPI Gateway with Gunicorn, and start the Mock ERP.
5. **Database:** You do not need to manually create the `.audit.db` file. The FastAPI application will automatically create it in the `logs/` folder the moment you start the server!
6. You can view the live logs at any time by running:
   ```bash
   docker-compose logs -f
   ```
7. To shut down the production environment:
   ```bash
   docker-compose down
   ```

### 4.1. Fast Deployment using Pre-Built Docker Images (For Team Members)
If the project lead has pushed the images to a Docker Registry (like Docker Hub), you can skip building entirely!
This avoids downloading massive Python libraries on your machine.

**Steps:**
1. Clone the repository to your machine.
2. Make a copy of `.env.example` and rename it exactly to `.env`. Fill in the API keys.
3. Ensure Docker Desktop is running.
4. Run the following command in the project folder:
   ```bash
   docker-compose pull
   docker-compose up -d
   ```
*The `docker-compose.yml` file will safely read your local `.env` file on your computer and inject the variables into the containers in real-time. Your `.env` file is completely secure and is never uploaded anywhere!*

---

## 5. Using the UI & Authentication

When you open the UI, you will see two authentication options:

### Option A: The "Dev Fallback" (For Testing)
During local development, you don't need a real token. Simply use the dropdown menu to select your role (`Student`, `Faculty`, or `Admin`) and enter an ID (like `STU-0001`). This bypasses the security check for easy testing.

### Option B: The Production JWT Token
In a real-world scenario, the user would log into the University's main portal (SSO). The university portal would generate a **JSON Web Token (JWT)** and pass it to TAIA. 

To test this production flow locally, you can generate a real JWT using the built-in security handler. Run this quick python script in your terminal (with the venv activated):
```bash
python -c "from app.auth.jwt_handler import create_access_token; print(create_access_token({'sub': 'STU-0001', 'role': 'Student'}))"
```
Copy the long string it prints, paste it into the **"Paste JWT Bearer Token Here..."** field in the UI, and click **Save Token**.

---

## 6. Accessing the Admin Audit Logs

Member 5 implemented a persistent SQLite database (`.audit.db`) that tracks every question asked, the latency, and the user's role.

### How to view the logs:

We have built a dedicated **Admin Dashboard** directly into the frontend!

**To authenticate and view the dashboard:**
1. Open the Chat UI (`http://127.0.0.1:5000`).
2. Login to the main dashboard as an **Admin** using the sidebar (e.g., User ID: `ADM-0001`, Role: `Admin`).
3. Click the red **🛡️ Admin Dashboard** button.
4. The dashboard will automatically read your session token and display all queries securely in a professional UI!

*(If you are building external integrations, the raw JSON data is also fully accessible via `GET http://127.0.0.1:8000/api/v1/admin/audit-logs` by passing an Admin JWT or `x-user-role: Admin` header).*
