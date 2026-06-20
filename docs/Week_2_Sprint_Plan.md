# Week 2 Sprint Plan: Full Integration & Flask UI 🚀

**Goal:** Achieve 100% system integration by connecting the FastAPI backend (with LangChain & Mock ERP) to a brand new **Flask-based Web UI**.

Since our team is moving at lightning speed and already finished the foundation, we are advancing directly to full system integration. We have expanded our task force to **9 Members**.

---

## 🏗️ 1. Team Lead & Architect (You)
**Responsibilities:**
- Review and merge Pull Requests from all 8 team members.
- Define the API contract (JSON structure) between the new Flask UI and the FastAPI backend.
- **Deliverable:** Oversee the final connection where the Flask Frontend successfully displays an AI response from FastAPI.

---

## 🌐 2. Frontend Developer 1: Flask Architecture
**Responsibilities:**
- Initialize a completely new `ui_app/` folder for the Flask frontend.
- Setup `app.py` with Flask routing (`@app.route('/')`).
- Configure Jinja2 templates directory and static assets (CSS/JS) folder.
- **Deliverable:** A running Flask server on port 5000 that serves a blank chat HTML template.

---

## 🎨 3. Frontend Developer 2: UI/UX Designer
**Responsibilities:**
- Design the Chat Interface using HTML and CSS inside the Flask Jinja templates.
- Implement the "Role Selection" dropdown (Student, Faculty, Admin).
- Make the chat window look modern, responsive, and academic.
- **Deliverable:** A beautiful, fully styled frontend chat interface (static).

---

## ⚡ 4. Frontend Developer 3: API/AJAX Logic
**Responsibilities:**
- Write the JavaScript code (inside the Flask templates) to capture user input from the chat box.
- Write the AJAX/Fetch code to send the message from the Flask UI to the FastAPI backend (`http://localhost:8000/api/v1/chat`).
- Render the AI's response back into the chat window dynamically.
- **Deliverable:** The chat interface can successfully send and receive messages without reloading the page.

---

## 🧠 5. AI/NLP Developer (LangChain Integration)
**Responsibilities:**
- Upgrade `chatbot_chain.py` to dynamically use the `PromptTemplates` created in Week 1.
- Write logic to determine what the user is asking about (Intent Classification: Attendance vs. GPA vs. Timetable).
- **Deliverable:** The LangChain pipeline can switch prompt templates based on what the user asks.

---

## 🔌 6. Backend Developer 1: ERP Connector
**Responsibilities:**
- Finalize `app/services/erp_connector.py` using `httpx`.
- Write functions to call the `mock_erp` endpoints (e.g., `get_student_attendance(student_id)`).
- **Deliverable:** FastAPI can successfully request and receive synthetic JSON data from the Mock ERP server on port 8001.

---

## ⚙️ 7. Backend Developer 2: API Gateway
**Responsibilities:**
- Update `app/main.py`'s `/api/v1/chat` endpoint to connect everything.
- When a chat request comes in, extract the `user_id` and `role`.
- Call Backend Dev 1's ERP connector to fetch data -> pass data to AI Dev's LangChain pipeline -> return AI string to Frontend.
- **Deliverable:** The `/api/v1/chat` endpoint returns a real AI-generated response based on real data.

---

## 📚 8. Knowledge Base (RAG) Developer
**Responsibilities:**
- Write a `query_knowledge_base(query)` function that connects to the ChromaDB created in Week 1.
- Perform a similarity search on the University Policy documents.
- Pass the retrieved text chunks to the LangChain Developer.
- **Deliverable:** If a user asks a policy question, the RAG developer's code successfully pulls the right paragraph from ChromaDB.

---

## 🛡️ 9. QA, Security & Testing Engineer
**Responsibilities:**
- Write Pytest integration tests to ensure the Flask app and FastAPI app communicate securely.
- Ensure CORS (Cross-Origin Resource Sharing) is configured correctly between Flask (port 5000) and FastAPI (port 8000).
- Test role-based security (ensure a Student cannot query Faculty data).
- **Deliverable:** A passing test suite verifying the end-to-end flow.
