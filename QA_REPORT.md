# ❓ AI Assessment Engine: Technical Q&A Report

This report provides a comprehensive breakdown of the project's technical architecture, design decisions, and implementation details through a Question & Answer format.

---

## 🏗️ 1. Architecture & Design

**Q: What is the core architectural pattern of this system?**
**A:** The system follows a **decoupled, event-driven-style architecture**. While the frontend is served via FastAPI templates, the heavy lifting (AI evaluation) is decoupled from the main request/response cycle using a background priority queue. This ensures high availability even when external AI services are slow.

**Q: Why was FastAPI chosen over Flask or Django?**
**A:** FastAPI was selected for its native **Asynchronous (async/await)** support, built-in Pydantic validation, and high performance. Since the system handles concurrent exam submissions and background tasks, FastAPI's non-blocking I/O is critical for maintaining responsiveness.

**Q: How do you handle database concurrency in SQLite?**
**A:** I enabled **Write-Ahead Logging (WAL) Mode**. This allows multiple readers to access the database even while a write operation is in progress, significantly reducing database locks during high-volume exam submissions. I also used thread-safe locks for in-memory session management.

---

## 🤖 2. AI & Evaluation Logic

**Q: Why use Groq instead of OpenAI or Gemini?**
**A:** Groq provides **extraordinary inference speeds** (tokens per second) using their LPU hardware. For an exam system, reducing the "result wait time" is critical for user experience. Groq allows us to grade complex essays in sub-second timeframes.

**Q: How does the system handle AI "hallucinations" or inconsistent grading?**
**A:** I used **Rigid System Prompting**. The AI is provided with a specific rubric and syllabus for each exam. Additionally, I force the model to respond in a structured format (JSON), which the backend validates. If the model provides an invalid score, the system detects it and can trigger a retry.

**Q: Can the system grade languages other than English?**
**A:** Yes. The system natively supports **Bengali** exam generation and evaluation by including language-specific instructions in the AI prompts.

---

## 📋 3. Task Management & Reliability

**Q: How does the "Evaluation Queue" work?**
**A:** The `evaluation_queue.py` implements a worker-based system. When a student submits, a "Task" is created in the DB with a `pending` status. The background worker picks up these tasks, calls the AI API, and updates the status to `completed`. It handles rate limiting to prevent API quota exhaustion.

**Q: What happens if the server crashes while grading an exam?**
**A:** The system is **Fault-Tolerant**. On startup, the application runs a `recover_pending_evaluations()` function that scans the DB for any results marked as `pending` or `processing`. It automatically re-appends these tasks to the active queue.

**Q: Is there a way for candidates to resume their exam?**
**A:** Yes. The system tracks active sessions in the `exam_sessions` table. If a candidate's internet fails, they can return to the site, enter their Candidate ID, and the system restores their specific session, including their previously saved answers and remaining time.

---

## 🐳 4. DevOps & Security

**Q: How is the project containerized?**
**A:** I used **Docker** with a multi-stage-style simplified `Dockerfile`. I also provided a `docker-compose.yml` that handles port mapping, environment variable injection, and volume mounting for the SQLite database to ensure data persistence across container restarts.

**Q: How do you manage secrets like API keys?**
**A:** Secrets are never hardcoded. They are managed via a `.env` file (loaded using `python-dotenv`). In the CI/CD pipeline, these are injected as **GitHub Actions Secrets**.

**Q: What is the CI/CD workflow?**
**A:** I implemented a GitHub Actions workflow (`docker-publish.yml`) that triggers on every push to the `main` branch. It automatically builds a new Docker image, tags it with the Git SHA, and pushes it to Docker Hub.

---

## 🚀 5. Scaling & Future Scope

**Q: How would you scale this to handle 10,000 concurrent students?**
**A:** 
1.  **Database**: Migrate from SQLite to a distributed DB like **PostgreSQL**.
2.  **Worker**: Move from an in-memory queue to **Redis + Celery**.
3.  **Load Balancing**: Deploy multiple instances of the FastAPI app behind an **Nginx** or **Traefik** load balancer.

**Q: What is the next major feature for this project?**
**A:** Implementing **RAG (Retrieval-Augmented Generation)**. This would allow the AI to grade questions based on specific textbooks or PDFs uploaded by the admin, ensuring even higher accuracy for specialized subjects.

---
**Report Summary:** This project demonstrates a high level of proficiency in backend engineering, asynchronous task management, and modern AI integration.
