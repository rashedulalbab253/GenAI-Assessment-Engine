"""
FastAPI application for AI-based Exam System
Contains all API routes and web endpoints
"""

from fastapi import FastAPI, Request, Form, HTTPException, Depends, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic
from typing import Dict, Optional
import json
import uuid
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from fastapi import File, UploadFile
from fastapi.staticfiles import StaticFiles
import shutil
from pathlib import Path

from utils import (
    ExamSystem, ExamSession, AdminSession,
    create_admin_session, verify_admin_session,
    convert_utc_to_bangladesh, order_questions_by_type,
    group_questions_by_section_for_navigation, validate_form_data,
    generate_safe_filename
)
from db import db
from evaluation_queue import init_evaluation_queue, get_evaluation_queue
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get environment variables
API_KEY = os.getenv("API_KEY")
API_KEY_BACKUP = os.getenv("API_KEY_BACKUP")  # Backup API key for failover
ADMIN_SECRET_KEY = os.getenv("ADMIN_SECRET_KEY")
ADMIN_SESSION_TIMEOUT = 30  # Session timeout in minutes

UPLOAD_DIR = Path("uploads/images")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Admin-Controlled Exam System")
templates = Jinja2Templates(directory="templates", auto_reload=True)
security = HTTPBasic()

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Initialize exam system with primary and backup API keys
exam_system = ExamSystem(API_KEY, API_KEY_BACKUP)

# Initialize evaluation queue for background processing
# Rate limit: 10 requests per minute to prevent API quota exhaustion
evaluation_queue = init_evaluation_queue(
    exam_system=exam_system,
    db=db,
    requests_per_minute=1
)

# In-memory session storage (exam_sessions now backed by database for persistence)
# Thread-safe session management using locks
_exam_sessions_lock = threading.Lock()
_admin_sessions_lock = threading.Lock()
exam_sessions = {}  # Cache for quick access, but database is source of truth
admin_sessions = {}


def get_exam_session(session_id: str) -> Optional[ExamSession]:
    """Thread-safe getter for exam sessions"""
    with _exam_sessions_lock:
        return exam_sessions.get(session_id)


def set_exam_session(session_id: str, session: ExamSession):
    """Thread-safe setter for exam sessions"""
    with _exam_sessions_lock:
        exam_sessions[session_id] = session


def delete_exam_session(session_id: str):
    """Thread-safe deletion for exam sessions"""
    with _exam_sessions_lock:
        if session_id in exam_sessions:
            del exam_sessions[session_id]


def get_admin_session(session_id: str) -> Optional[AdminSession]:
    """Thread-safe getter for admin sessions"""
    with _admin_sessions_lock:
        return admin_sessions.get(session_id)


def set_admin_session(session_id: str, session: AdminSession):
    """Thread-safe setter for admin sessions"""
    with _admin_sessions_lock:
        admin_sessions[session_id] = session


def delete_admin_session(session_id: str):
    """Thread-safe deletion for admin sessions"""
    with _admin_sessions_lock:
        if session_id in admin_sessions:
            del admin_sessions[session_id]


def recover_exam_sessions():
    """
    Recover active exam sessions from database after server restart.
    This ensures candidates can continue their exams even if the server restarts.
    """
    try:
        active_sessions = db.get_all_active_exam_sessions()

        if not active_sessions:
            print("✅ No active exam sessions to recover")
            return

        print(f"🔄 Recovering {len(active_sessions)} active exam sessions from database...")

        recovered_count = 0
        for session_data in active_sessions:
            try:
                # Recreate the in-memory ExamSession object using thread-safe setter
                set_exam_session(session_data['session_id'], ExamSession(
                    session_id=session_data['session_id'],
                    candidate_name=session_data['candidate_name'],
                    candidate_id=session_data['candidate_id'],
                    exam_id=session_data['exam_id'],
                    started_at=datetime.fromisoformat(session_data['started_at']) if isinstance(session_data['started_at'], str) else session_data['started_at'],
                    time_limit=session_data['time_limit']
                ))
                recovered_count += 1
                print(f"  ✅ Recovered session for {session_data['candidate_name']}")
            except Exception as e:
                print(f"  ❌ Failed to recover session {session_data['session_id']}: {e}")

        print(f"✅ Recovered {recovered_count}/{len(active_sessions)} exam sessions")

        # Also clean up expired sessions
        expired_count = db.cleanup_expired_exam_sessions(extra_minutes=60)
        if expired_count > 0:
            print(f"🧹 Cleaned up {expired_count} expired exam sessions")

    except Exception as e:
        print(f"❌ Error recovering exam sessions: {e}")


def recover_pending_evaluations():
    """
    Recover pending evaluations from database after server restart.
    This ensures NO DATA IS LOST even if the server crashes or restarts.
    """
    try:
        pending_results = db.get_pending_results_for_recovery()

        if not pending_results:
            print("✅ No pending evaluations to recover")
            return

        print(f"🔄 Recovering {len(pending_results)} pending evaluations from database...")

        recovered_count = 0
        for result in pending_results:
            try:
                success = evaluation_queue.add_task(
                    result_id=result['result_id'],
                    session_id=result['session_id'],
                    exam_id=result['exam_id'],
                    candidate_name=result['candidate_name'],
                    candidate_id=result['candidate_id'],
                    answers=result['answers'],
                    questions=result['questions'],
                    negative_marking_config=result['negative_marking_config'],
                    show_feedback=result['show_feedback'],
                    multi_select_scoring_mode=result.get('multi_select_scoring_mode', 'partial'),
                    priority=0  # High priority for recovered tasks
                )

                if success:
                    recovered_count += 1
                    print(f"   ✅ Recovered: {result['candidate_name']} ({result['result_id'][:8]}...)")
                else:
                    print(f"   ⚠️ Failed to recover: {result['candidate_name']}")

            except Exception as e:
                print(f"   ❌ Error recovering {result['candidate_name']}: {str(e)}")

        print(f"🎉 Recovery complete: {recovered_count}/{len(pending_results)} evaluations re-queued")

    except Exception as e:
        print(f"❌ Error during evaluation recovery: {str(e)}")


# Startup and shutdown events for the evaluation queue
@app.on_event("startup")
async def startup_event():
    """Start the background evaluation worker when the app starts"""
    print("🚀 Starting application...")
    evaluation_queue.start()
    print("✅ Background evaluation queue started")

    # Recover active exam sessions from database after server restart
    recover_exam_sessions()

    # Recover pending evaluations from database after server restart
    recover_pending_evaluations()


@app.on_event("shutdown")
async def shutdown_event():
    """Stop the background evaluation worker gracefully"""
    print("🛑 Shutting down application...")
    evaluation_queue.stop()
    print("✅ Background evaluation queue stopped")


# Helper Functions for Session Management

def safe_error_message(e: Exception, context: str = "operation") -> str:
    """
    Generate a safe error message that doesn't expose internal details.

    Logs the full error for debugging but returns a generic message to users.
    """
    import traceback
    # Log the full error for debugging
    print(f"❌ Error during {context}: {str(e)}")
    traceback.print_exc()

    # Return generic message to user
    return f"An error occurred during {context}. Please try again or contact the administrator."


def get_admin_session_from_request(request: Request) -> Optional[str]:
    """Get admin session ID from request cookies"""
    return request.cookies.get("admin_session")


async def verify_admin_access(request: Request):
    """Dependency to verify admin access"""
    session_id = get_admin_session_from_request(request)
    # Use thread-safe verification with lock
    if not session_id or not verify_admin_session(session_id, admin_sessions, ADMIN_SESSION_TIMEOUT, lock=_admin_sessions_lock):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin access required"
        )
    return session_id


# Candidate Routes

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page for candidates"""
    return templates.TemplateResponse("candidate_home.html", {
        "request": request
    })


@app.get("/exam/{exam_link}", response_class=HTMLResponse)
async def exam_page(request: Request, exam_link: str):
    """Exam page for candidates"""
    exam = db.get_exam_by_link(exam_link)
    if not exam:
        return templates.TemplateResponse("candidate_home.html", {
            "request": request,
            "error": "This exam is either invalid, has been deactivated, or is no longer available. Please contact the administrator for assistance."
        })

    return templates.TemplateResponse("exam_start.html", {
        "request": request,
        "exam": exam,
        "exam_link": exam_link
    })


@app.get("/exam/{exam_link}/results", response_class=HTMLResponse)
async def exam_results_lookup_page(request: Request, exam_link: str):
    """Page for candidates to look up their results using candidate ID"""
    exam = db.get_exam_by_link(exam_link)
    if not exam:
        return templates.TemplateResponse("candidate_home.html", {
            "request": request,
            "error": "Invalid exam link. Please check the link and try again."
        })

    return templates.TemplateResponse("result_lookup.html", {
        "request": request,
        "exam": exam,
        "exam_link": exam_link
    })


@app.post("/exam/{exam_link}/results", response_class=HTMLResponse)
async def lookup_exam_results(request: Request, exam_link: str):
    """Look up results using candidate ID"""
    exam = db.get_exam_by_link(exam_link)
    if not exam:
        return templates.TemplateResponse("candidate_home.html", {
            "request": request,
            "error": "Invalid exam link."
        })

    form_data = await request.form()
    candidate_id = form_data.get("candidate_id", "").strip()

    if not candidate_id:
        return templates.TemplateResponse("result_lookup.html", {
            "request": request,
            "exam": exam,
            "exam_link": exam_link,
            "error": "Please enter your Candidate ID."
        })

    # Look up the result
    result = db.lookup_candidate_result(exam_link, candidate_id)

    if not result:
        return templates.TemplateResponse("result_lookup.html", {
            "request": request,
            "exam": exam,
            "exam_link": exam_link,
            "error": "No results found for this Candidate ID. Please check your ID and try again."
        })

    # Redirect to the results page
    return RedirectResponse(url=f"/results/{result['result_id']}", status_code=303)


@app.post("/exam/{exam_link}/start", response_class=HTMLResponse)
async def start_exam(request: Request, exam_link: str):
    """Start exam for candidate with proper question ordering and live session tracking"""
    exam = db.get_exam_by_link(exam_link)
    if not exam:
        return templates.TemplateResponse("candidate_home.html", {
            "request": request,
            "error": "Invalid exam link. Please check the link and try again."
        })
    
    # Get form data
    form_data = await request.form()
    candidate_name = form_data.get("candidate_name", "").strip()
    candidate_id = form_data.get("candidate_id", "").strip()
    
    # Validate form data
    if not candidate_name or not candidate_id:
        return templates.TemplateResponse("exam_start.html", {
            "request": request,
            "exam": exam,
            "exam_link": exam_link,
            "error": "Please fill in both your name and candidate ID."
        })

    # Check if candidate has already submitted this exam
    if db.has_candidate_submitted_exam(exam['id'], candidate_id):
        return templates.TemplateResponse("exam_already_submitted.html", {
            "request": request,
            "exam": exam,
            "exam_link": exam_link,
            "candidate_id": candidate_id,
            "message": "You have already submitted this exam. Each candidate can only take the exam once."
        })

    # Check if candidate has an active session (resume functionality)
    existing_session_id = db.has_candidate_active_session(exam['id'], candidate_id)
    if existing_session_id:
        # Candidate has an active session, recover it
        db_session = db.get_exam_session(existing_session_id)
        if db_session:
            session_id = existing_session_id
            set_exam_session(session_id, ExamSession(
                session_id=db_session['session_id'],
                candidate_name=db_session['candidate_name'],
                candidate_id=db_session['candidate_id'],
                exam_id=db_session['exam_id'],
                started_at=datetime.fromisoformat(db_session['started_at']) if isinstance(db_session['started_at'], str) else db_session['started_at'],
                time_limit=db_session['time_limit']
            ))
            print(f"🔄 Resuming existing session for {candidate_name} ({candidate_id})")

            # Get questions and continue with existing session
            questions = db.get_exam_questions(exam['id'])
            questions = order_questions_by_type(questions)
            sections = group_questions_by_section_for_navigation(questions)

            # Get previously saved answers
            saved_answers = db_session.get('answers_data', {})
            if isinstance(saved_answers, str):
                import json as json_module
                saved_answers = json_module.loads(saved_answers) if saved_answers else {}

            return templates.TemplateResponse("exam_page.html", {
                "request": request,
                "exam": exam,
                "questions": questions,
                "sections": sections,
                "session_id": session_id,
                "candidate_name": db_session['candidate_name'],
                "time_limit": db_session['time_limit'],
                "saved_answers": saved_answers,
                "resumed": True
            })

    # Create new exam session using thread-safe setter
    session_id = str(uuid.uuid4())
    set_exam_session(session_id, ExamSession(
        session_id=session_id,
        candidate_name=candidate_name,
        candidate_id=candidate_id,
        exam_id=exam['id'],
        started_at=datetime.now(),
        time_limit=exam['time_limit']
    ))

    # Create persistent exam session in database (survives server restart)
    db.create_exam_session(
        session_id=session_id,
        exam_id=exam['id'],
        candidate_name=candidate_name,
        candidate_id=candidate_id,
        time_limit=exam['time_limit']
    )

    # Create live session in database (for admin monitoring)
    db.create_live_session(session_id, exam['id'], candidate_name, candidate_id)
    
    # Get questions for the exam
    questions = db.get_exam_questions(exam['id'])
    
    # Order questions by type: MCQ → Short → Essay
    ordered_questions = order_questions_by_type(questions)
    
    # Get sections structure for navigation
    sections_by_type = group_questions_by_section_for_navigation(ordered_questions)
    
    print(f"📝 Exam started with {len(ordered_questions)} questions ordered by type")
    print(f"📊 Sections for navigation: {list(sections_by_type.keys())}")
    print(f"🔴 Live session created for {candidate_name} ({candidate_id})")
    
    return templates.TemplateResponse("exam_page.html", {
        "request": request,
        "session_id": session_id,
        "candidate_name": candidate_name,
        "candidate_id": candidate_id,
        "exam": exam,
        "questions": ordered_questions,
        "sections": sections_by_type
    })


@app.post("/exam/submit", response_class=HTMLResponse)
async def submit_exam(request: Request):
    """
    Submit exam answers with background queue-based evaluation.

    This new implementation:
    1. Saves answers immediately to database
    2. Queues evaluation for background processing
    3. Redirects candidate to status page (they can leave)
    4. Evaluation happens in background with rate limiting and retries
    """
    form_data = await request.form()
    session_id = form_data.get("session_id")
    client_time_taken = form_data.get("time_taken", "00:00")  # Client-reported time (not trusted)

    print(f"📄 Processing exam submission for session: {session_id}")

    if not session_id:
        print(f"❌ No session ID provided")
        return templates.TemplateResponse("exam_error.html", {
            "request": request,
            "error_title": "Session Not Found",
            "error_message": "No exam session was found. This may happen if you've already submitted your exam or your session has expired.",
            "error_type": "session_not_found"
        }, status_code=404)

    # Try to get session from memory first (thread-safe), then from database
    session = get_exam_session(session_id)

    if not session:
        # Session not in memory, try to recover from database
        print(f"🔄 Session not in memory, checking database: {session_id}")
        db_session = db.get_exam_session(session_id)

        if db_session and not db_session.get('is_submitted'):
            # Recover session from database using thread-safe setter
            session = ExamSession(
                session_id=db_session['session_id'],
                candidate_name=db_session['candidate_name'],
                candidate_id=db_session['candidate_id'],
                exam_id=db_session['exam_id'],
                started_at=datetime.fromisoformat(db_session['started_at']) if isinstance(db_session['started_at'], str) else db_session['started_at'],
                time_limit=db_session['time_limit']
            )
            set_exam_session(session_id, session)
            print(f"✅ Session recovered from database for {session.candidate_name}")
        else:
            # Check if it was already submitted
            is_already_submitted = db_session and db_session.get('is_submitted')
            print(f"❌ Invalid session ID: {session_id} (already_submitted: {is_already_submitted})")

            if is_already_submitted:
                # Already submitted - show success page instead of error
                return templates.TemplateResponse("exam_already_submitted.html", {
                    "request": request,
                    "candidate_name": db_session.get('candidate_name', 'Candidate'),
                    "candidate_id": db_session.get('candidate_id', 'N/A'),
                    "message": "Your exam has already been submitted successfully. You cannot submit again."
                })
            else:
                return templates.TemplateResponse("exam_error.html", {
                    "request": request,
                    "error_title": "Session Not Found",
                    "error_message": "Your exam session was not found. This may happen if the session has expired or there was a technical issue. Please contact the administrator if you believe this is an error.",
                    "error_type": "session_not_found"
                }, status_code=404)

    exam = db.get_exam_by_id(session.exam_id)
    questions = db.get_exam_questions(session.exam_id)

    # SERVER-SIDE TIME ENFORCEMENT
    # Check if the exam time has expired (with 1 minute grace period for network latency)
    time_elapsed = datetime.now() - session.started_at
    time_limit_seconds = session.time_limit * 60
    grace_period_seconds = 60  # 1 minute grace period
    max_allowed_seconds = time_limit_seconds + grace_period_seconds

    if time_elapsed.total_seconds() > max_allowed_seconds:
        print(f"⏰ Exam time exceeded for {session.candidate_name}: elapsed {time_elapsed.total_seconds():.0f}s, limit {time_limit_seconds}s")
        # Still accept the submission but log the overtime
        overtime_minutes = (time_elapsed.total_seconds() - time_limit_seconds) / 60
        print(f"⚠️ Candidate {session.candidate_name} submitted {overtime_minutes:.1f} minutes after time limit")

    # Calculate actual time taken (capped at time limit for fairness)
    actual_time_seconds = min(time_elapsed.total_seconds(), time_limit_seconds)

    # Format server-side time_taken as MM:SS (used instead of client-reported time)
    time_taken_minutes = int(actual_time_seconds // 60)
    time_taken_seconds = int(actual_time_seconds % 60)
    time_taken = f"{time_taken_minutes:02d}:{time_taken_seconds:02d}"
    print(f"⏱️ Server-side time taken: {time_taken} (client reported: {client_time_taken})")

    # IMMEDIATELY end live session when submission starts
    print(f"🔴 Ending live session for {session.candidate_name}")
    db.end_live_session(session_id)

    # Extract candidate answers (handling both single-select and multi-select MCQs)
    candidate_answers = {}
    processed_keys = set()

    for key in form_data.keys():
        if key.startswith("question_") and key not in processed_keys:
            processed_keys.add(key)
            question_id = key.replace("question_", "")

            # Get all values for this key (handles checkbox multi-select)
            values = form_data.getlist(key)

            if len(values) == 1:
                # Single value (radio button or textarea)
                candidate_answers[question_id] = values[0]
            elif len(values) > 1:
                # Multiple values (checkboxes for multi-select MCQ)
                # Store as comma-separated string for compatibility
                candidate_answers[question_id] = ','.join(values)

    print(f"📊 Received {len(candidate_answers)} answers from {session.candidate_name}")

    # Check if feedback should be shown
    show_feedback = exam.get('show_feedback', True)

    try:
        # Step 1: Save submission immediately (answers are safe!)
        result_id = db.save_exam_submission_for_queue(
            session_id=session_id,
            exam_id=session.exam_id,
            candidate_name=session.candidate_name,
            candidate_id=session.candidate_id,
            answers=candidate_answers,
            time_taken=time_taken,
            questions=questions
        )

        if not result_id:
            raise Exception("Failed to save exam submission")

        print(f"✅ Answers saved immediately for {session.candidate_name} (Result ID: {result_id[:8]}...)")

        # Step 2: Queue for background evaluation
        negative_marking_config = exam.get('negative_marking_config', {})
        multi_select_scoring_mode = exam.get('multi_select_scoring_mode', 'partial')

        queue_success = evaluation_queue.add_task(
            result_id=result_id,
            session_id=session_id,
            exam_id=session.exam_id,
            candidate_name=session.candidate_name,
            candidate_id=session.candidate_id,
            answers=candidate_answers,
            questions=questions,
            negative_marking_config=negative_marking_config,
            show_feedback=show_feedback,
            multi_select_scoring_mode=multi_select_scoring_mode
        )

        if queue_success:
            print(f"📋 Evaluation queued for {session.candidate_name}")
        else:
            print(f"⚠️ Queue failed, but answers are saved for {session.candidate_name}")

        # Clean up in-memory session (thread-safe)
        delete_exam_session(session_id)

        # Mark database session as submitted and clean up
        db.mark_exam_session_submitted(session_id)

        # Step 3: Redirect to status page
        # Candidate can now close the browser - their answers are safe!
        return templates.TemplateResponse("evaluation_status.html", {
            "request": request,
            "result_id": result_id,
            "candidate_name": session.candidate_name,
            "candidate_id": session.candidate_id,
            "exam_title": exam['title'],
            "time_taken": time_taken,
            "show_feedback": show_feedback,
            "status": "pending",
            "message": "Your exam has been submitted successfully! Your answers are being evaluated."
        })

    except Exception as e:
        print(f"❌ Error during exam submission: {str(e)}")

        # Ensure live session is ended
        db.end_live_session(session_id)

        # Clean up in-memory session (thread-safe)
        delete_exam_session(session_id)

        # Mark database session as submitted (even on error, prevent resubmission)
        db.mark_exam_session_submitted(session_id)

        # Show error page but reassure candidate
        return templates.TemplateResponse("candidate_submission_complete.html", {
            "request": request,
            "candidate_name": session.candidate_name,
            "candidate_id": session.candidate_id,
            "exam_title": exam['title'],
            "time_taken": time_taken,
            "error": "There was an issue processing your submission. Please contact the administrator."
        })


# Admin Routes

@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    """Admin login page"""
    return templates.TemplateResponse("admin_login.html", {"request": request})


@app.post("/admin/login")
async def admin_login(request: Request, secret_key: str = Form(...)):
    """Process admin login"""
    if secret_key == ADMIN_SECRET_KEY:
        session_id = create_admin_session(ADMIN_SESSION_TIMEOUT)
        # Use thread-safe setter for admin session
        set_admin_session(session_id, AdminSession(
            session_id=session_id,
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(minutes=ADMIN_SESSION_TIMEOUT)
        ))

        response = RedirectResponse(url="/admin", status_code=303)
        response.set_cookie(
            key="admin_session",
            value=session_id,
            max_age=ADMIN_SESSION_TIMEOUT * 60,
            httponly=True,
            secure=False,
            samesite="lax"
        )
        return response
    else:
        return templates.TemplateResponse("admin_login.html", {
            "request": request,
            "error": "Invalid secret key. Please try again."
        })


@app.get("/admin/logout")
async def admin_logout(request: Request):
    """Logout admin user"""
    session_id = get_admin_session_from_request(request)
    if session_id:
        # Use thread-safe deletion for admin session
        delete_admin_session(session_id)

    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("admin_session")
    return response


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, session_id: str = Depends(verify_admin_access)):
    """Admin dashboard"""
    try:
        exams = db.get_all_exams()
        recent_results = db.get_recent_exam_results(20)
        
        # Clean up stale sessions
        db.cleanup_stale_sessions(30)
        
        return templates.TemplateResponse("admin_dashboard.html", {
            "request": request,
            "exams": exams,
            "recent_results": recent_results
        })
    except Exception as e:
        # Log the full error for debugging but don't expose to user
        print(f"❌ Error in admin dashboard: {str(e)}")
        import traceback
        traceback.print_exc()
        return HTMLResponse("""
        <html><body>
            <h1>Admin Dashboard Error</h1>
            <p>An unexpected error occurred while loading the dashboard. Please try again later.</p>
            <p>If this problem persists, please contact the system administrator.</p>
            <p><a href="/admin/login">Back to Login</a></p>
        </body></html>
        """, status_code=500)


@app.get("/admin/create-exam", response_class=HTMLResponse)
async def create_exam_page(request: Request, session_id: str = Depends(verify_admin_access)):
    """Create new exam page"""
    return templates.TemplateResponse("create_exam.html", {
        "request": request
    })


@app.post("/admin/create-exam", response_class=HTMLResponse)
async def create_exam(request: Request, session_id: str = Depends(verify_admin_access)):
    """Create exam and generate questions with sections support"""
    form_data = await request.form()
    
    try:
        # Extract form fields
        department = form_data.get("department", "").strip()
        position = form_data.get("position", "").strip()
        title = form_data.get("title", "").strip()
        description = form_data.get("description", "").strip()
        time_limit = int(form_data.get("time_limit", "120"))
        instructions = form_data.get("instructions", "").strip()
        generation_method = form_data.get("generation_method", "ai").strip()
        exam_language = form_data.get("exam_language", "english").strip()
        show_feedback = form_data.get("show_feedback") == "on"

        # Extract AI generation instructions
        difficulty_level = form_data.get("difficulty_level", "medium").strip()
        ai_custom_instructions = form_data.get("ai_custom_instructions", "").strip()

        # Parse sections structure and negative marking config
        sections_structure = json.loads(form_data.get("sections_structure", "{}"))
        negative_marking_config = json.loads(form_data.get("negative_marking_config", "{}"))

        # Multi-select scoring mode: 'partial' or 'strict'
        multi_select_scoring_mode = form_data.get("multi_select_scoring_mode", "partial").strip()

        # MCQ options count (2-6, default 4)
        mcq_options_count = int(form_data.get("mcq_options_count", "4"))
        mcq_options_count = max(2, min(6, mcq_options_count))  # Clamp to 2-6

        # Add custom syllabus to sections
        for section_name in sections_structure.keys():
            syllabus_field = f"{section_name}_syllabus"
            if syllabus_field in form_data:
                syllabus_content = form_data.get(syllabus_field, "").strip()
                if syllabus_content:
                    sections_structure[section_name]['syllabus'] = syllabus_content

        print(f"📊 Creating exam: {title}")
        print(f"🌍 Language: {exam_language}")
        print(f"💬 Feedback enabled: {show_feedback}")
        print(f"🎯 Difficulty level: {difficulty_level}")
        print(f"📝 Custom AI instructions: {ai_custom_instructions[:100] if ai_custom_instructions else 'None'}...")
        print(f"➖ Negative marking config: {negative_marking_config}")
        print(f"☑️ Multi-select scoring mode: {multi_select_scoring_mode}")
        print(f"🔢 MCQ options count: {mcq_options_count}")
        
        # Validate form data
        is_valid, error_message = validate_form_data({
            'department': department,
            'position': position, 
            'title': title,
            'time_limit': time_limit
        })
        
        if not is_valid:
            return templates.TemplateResponse("create_exam.html", {
                "request": request,
                "error": error_message
            })
        
        # Validate at least one section has questions
        total_questions = sum(
            section_config.get('mcq_count', 0) + 
            section_config.get('short_count', 0) + 
            section_config.get('essay_count', 0)
            for section_config in sections_structure.values()
        )
        
        if total_questions == 0:
            return templates.TemplateResponse("create_exam.html", {
                "request": request,
                "error": "Please add at least one question by enabling sections and setting question counts."
            })
            
    except (ValueError, TypeError, json.JSONDecodeError) as e:
        return templates.TemplateResponse("create_exam.html", {
            "request": request,
            "error": f"Invalid input format: {str(e)}"
        })
    
    # Create exam in database
    try:
        exam_id = db.create_exam(
            title=title, department=department, position=position, description=description,
            time_limit=time_limit, instructions=instructions, question_structure={},
            sections_structure=sections_structure, show_feedback=show_feedback,
            negative_marking_config=negative_marking_config, exam_language=exam_language,
            multi_select_scoring_mode=multi_select_scoring_mode
        )
        
        if not exam_id:
            return templates.TemplateResponse("create_exam.html", {
                "request": request,
                "error": "Failed to create exam in database. Please try again."
            })
        
        print(f"✅ Exam created with ID: {exam_id}")

        # Separate sections by generation mode
        ai_sections = {}
        manual_sections = {}

        for section_type, section_config in sections_structure.items():
            section_mode = section_config.get('generation_mode', generation_method)
            if section_mode == 'ai':
                ai_sections[section_type] = section_config
            else:
                manual_sections[section_type] = section_config

        print(f"🤖 AI sections: {list(ai_sections.keys())}")
        print(f"✍️ Manual sections: {list(manual_sections.keys())}")

        question_count = 0
        failed_sections = []

        # Process AI-generated sections
        if ai_sections:
            print(f"🤖 Generating questions using AI for {len(ai_sections)} sections in {exam_language}")
            generation_result = exam_system.generate_exam_questions_by_sections(
                department, position, ai_sections, exam_language,
                difficulty_level=difficulty_level,
                custom_instructions=ai_custom_instructions,
                mcq_options_count=mcq_options_count
            )

            # Handle successful sections
            generated_sections = generation_result.get('questions', {})
            for section_type, questions in generated_sections.items():
                print(f"💾 Saving {len(questions)} AI-generated questions for {section_type}")
                # Mark section as successfully generated
                sections_structure[section_type]['generation_status'] = 'generated'
                sections_structure[section_type]['last_generated'] = datetime.now().isoformat()
                for question in questions:
                    question_id = db.save_exam_question(exam_id, question, section_type)
                    if question_id:
                        question_count += 1

            if generated_sections:
                print(f"✅ Saved {question_count} AI-generated questions")

            # Handle failed sections - create placeholders
            failed_sections = generation_result.get('failed_sections', [])
            if failed_sections:
                print(f"⚠️ AI generation failed for sections: {', '.join(failed_sections)}")
                for section_type in failed_sections:
                    # Mark section as failed and move to manual
                    sections_structure[section_type]['generation_status'] = 'failed'
                    manual_sections[section_type] = ai_sections[section_type]

        # Process manual sections (create placeholders)
        if manual_sections:
            print(f"📝 Creating placeholder questions for {len(manual_sections)} manual/failed sections")

            for section_type, section_config in manual_sections.items():
                # Mark generation status for manual sections
                if section_type not in failed_sections:
                    sections_structure[section_type]['generation_status'] = 'manual'

                # Create MCQ placeholders
                for i in range(section_config.get('mcq_count', 0)):
                    placeholder_question = {
                        'type': 'mcq',
                        'question': f'[MCQ Question {question_count + 1}] - Edit this question or click "Regenerate Section" to generate with AI',
                        'options': ['Option A', 'Option B', 'Option C', 'Option D'],
                        'correct_answer': 0,
                        'marks': section_config.get('mcq_marks', 1),
                        'explanation': 'Add explanation here'
                    }
                    if db.save_exam_question(exam_id, placeholder_question, section_type):
                        question_count += 1

                # Create Short Answer placeholders
                for i in range(section_config.get('short_count', 0)):
                    placeholder_question = {
                        'type': 'short',
                        'question': f'[Short Answer Question {question_count + 1}] - Edit this question or click "Regenerate Section" to generate with AI',
                        'expected_answer': 'Expected answer guidelines here',
                        'evaluation_criteria': 'Evaluation criteria here',
                        'marks': section_config.get('short_marks', 1)
                    }
                    if db.save_exam_question(exam_id, placeholder_question, section_type):
                        question_count += 1

                # Create Essay placeholders
                for i in range(section_config.get('essay_count', 0)):
                    placeholder_question = {
                        'type': 'essay',
                        'question': f'[Essay Question {question_count + 1}] - Edit this question or click "Regenerate Section" to generate with AI',
                        'expected_answer': 'Expected answer structure here',
                        'evaluation_criteria': 'Detailed evaluation criteria here',
                        'marks': section_config.get('essay_marks', 1)
                    }
                    if db.save_exam_question(exam_id, placeholder_question, section_type):
                        question_count += 1

            print(f"✅ Created placeholder questions for manual/failed sections")

        # Update sections_structure with generation status
        db.update_sections_structure(exam_id, sections_structure)

        print(f"✅ Total {question_count} questions created")

        if question_count == 0:
            return templates.TemplateResponse("create_exam.html", {
                "request": request,
                "error": "Failed to create questions. Please try again."
            })

        # Redirect with appropriate flags
        redirect_url = f"/admin/edit-exam/{exam_id}"
        if manual_sections or failed_sections:
            # Add flags to indicate manual editing needed and which sections failed
            redirect_url += "?manual=1"
            if failed_sections:
                redirect_url += f"&failed={','.join(failed_sections)}"

        return RedirectResponse(url=redirect_url, status_code=303)
        
    except Exception as e:
        error_msg = safe_error_message(e, "exam creation")
        return templates.TemplateResponse("create_exam.html", {
            "request": request,
            "error": error_msg
        })


@app.get("/admin/edit-exam/{exam_id}", response_class=HTMLResponse)
async def edit_exam_page(request: Request, exam_id: str, session_id: str = Depends(verify_admin_access)):
    """Edit exam questions page"""
    exam = db.get_exam_by_id(exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    manual_mode = request.query_params.get("manual") == "1"
    failed_sections_param = request.query_params.get("failed", "")
    failed_sections = failed_sections_param.split(",") if failed_sections_param else []

    sections = db.get_exam_questions_by_section(exam_id)
    sections_structure = exam.get('sections_structure', {})

    # Convert to flat list for template and ensure images are loaded
    questions = []
    for section_type, section_questions in sections.items():
        for question in section_questions:
            question['section_type'] = section_type
            # Ensure images are loaded for each question
            if 'images' not in question:
                question['images'] = db.get_question_images(question['id'])
            questions.append(question)

    return templates.TemplateResponse("edit_exam.html", {
        "request": request,
        "exam": exam,
        "questions": questions,
        "sections": sections,
        "sections_structure": sections_structure,
        "manual_mode": manual_mode,
        "failed_sections": failed_sections,
        "total_questions": len(questions)
    })

@app.get("/admin/view-exam/{exam_id}", response_class=HTMLResponse)
async def view_exam_page(request: Request, exam_id: str, session_id: str = Depends(verify_admin_access)):
    """View exam page with live candidates tracking"""
    try:
        exam = db.get_exam_by_id(exam_id)
        if not exam:
            raise HTTPException(status_code=404, detail="Exam not found")
        
        sections = db.get_exam_questions_by_section(exam_id)
        
        # Convert to flat list
        questions = []
        for section_type, section_questions in sections.items():
            for question in section_questions:
                question['section_type'] = section_type
                questions.append(question)
        
        results_count = db.get_exam_results_count(exam_id)
        live_candidates = db.get_live_candidates(exam_id)
        
        # Convert times to Bangladesh timezone
        for candidate in live_candidates:
            if candidate.get('started_at'):
                candidate['started_at'] = convert_utc_to_bangladesh(candidate['started_at'])
            if candidate.get('last_activity'):
                candidate['last_activity'] = convert_utc_to_bangladesh(candidate['last_activity'])
        
        live_count = len(live_candidates)
        
        return templates.TemplateResponse("view_exam.html", {
            "request": request,
            "exam": exam,
            "questions": questions,
            "sections": sections,
            "total_questions": len(questions),
            "results_count": results_count,
            "live_candidates": live_candidates,
            "live_count": live_count
        })
        
    except Exception as e:
        print(f"❌ Error in view_exam_page: {str(e)}")
        return HTMLResponse(f"""
        <html><body>
            <h1>View Exam Error</h1>
            <p>Error: {str(e)}</p>
            <p><a href="/admin">Back to Dashboard</a></p>
        </body></html>
        """, status_code=500)


@app.get("/admin/exam-results/{exam_id}", response_class=HTMLResponse)
async def exam_results(request: Request, exam_id: str, session_id: str = Depends(verify_admin_access)):
    """View exam results"""
    exam = db.get_exam_by_id(exam_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    
    results = db.get_exam_results(exam_id)
    
    return templates.TemplateResponse("exam_results.html", {
        "request": request,
        "exam": exam,
        "results": results
    })


# API Endpoints

@app.post("/api/update-exam-settings/{exam_id}")
async def update_exam_settings(exam_id: str, request: Request, session_id: str = Depends(verify_admin_access)):
    """Update exam settings"""
    try:
        settings_data = await request.json()
        
        success = db.update_exam_settings(
            exam_id=exam_id,
            title=settings_data.get('title'),
            description=settings_data.get('description'),
            time_limit=settings_data.get('time_limit'),
            instructions=settings_data.get('instructions'),
            show_feedback=settings_data.get('show_feedback', True),
            negative_marking_config=settings_data.get('negative_marking_config', {}),
            exam_language=settings_data.get('exam_language', 'english'),
            multi_select_scoring_mode=settings_data.get('multi_select_scoring_mode', 'partial')
        )
        
        if success:
            return {"success": True, "message": "Exam settings updated successfully"}
        else:
            return {"success": False, "error": "Failed to update exam settings"}
            
    except Exception as e:
        print(f"❌ Error updating exam settings: {str(e)}")
        return {"success": False, "error": "Failed to update exam settings. Please try again."}


@app.post("/admin/finalize-exam/{exam_id}")
async def finalize_exam(exam_id: str, session_id: str = Depends(verify_admin_access)):
    """Finalize exam and generate link"""
    exam_link = db.finalize_exam(exam_id)
    return {"success": True, "exam_link": exam_link}


@app.post("/api/update-question/{question_id}")
async def update_question(question_id: str, request: Request, session_id: str = Depends(verify_admin_access)):
    """Update a question including image support"""
    try:
        question_data = await request.json()
        
        # Handle main image URL if provided
        if 'remove_main_image' in question_data and question_data['remove_main_image']:
            question_data['image_url'] = None
            question_data['image_caption'] = None
        
        success = db.update_question(question_id, question_data)
        return {"success": success}
    except Exception as e:
        print(f"❌ Error updating question: {str(e)}")
        return {"success": False, "error": "Failed to update question. Please try again."}


@app.delete("/api/delete-question/{question_id}")
async def delete_question(question_id: str, session_id: str = Depends(verify_admin_access)):
    """Delete a question"""
    try:
        success = db.delete_question(question_id)
        return {"success": success}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/add-question/{exam_id}")
async def add_question(exam_id: str, request: Request, session_id: str = Depends(verify_admin_access)):
    """Add a new question to exam"""
    try:
        question_data = await request.json()
        section_type = question_data.get('section_type', 'technical')
        question_id = db.save_exam_question(exam_id, question_data, section_type)
        return {"success": True, "question_id": question_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/regenerate-section/{exam_id}/{section_type}")
async def regenerate_section(exam_id: str, section_type: str, request: Request, session_id: str = Depends(verify_admin_access)):
    """Regenerate questions for a specific section using AI.

    This allows:
    1. Regenerating failed sections that got placeholder questions
    2. Regenerating any section with updated syllabus/instructions
    """
    try:
        # Get request data (optional custom syllabus and instructions)
        data = await request.json()
        custom_syllabus = data.get('syllabus', '').strip()
        custom_instructions = data.get('custom_instructions', '').strip()
        difficulty_level = data.get('difficulty_level', 'medium').strip()

        # Get exam details
        exam = db.get_exam_by_id(exam_id)
        if not exam:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "Exam not found"}
            )

        if exam.get('is_finalized'):
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Cannot regenerate questions for a finalized exam"}
            )

        # Get current sections structure
        sections_structure = exam.get('sections_structure', {})
        if section_type not in sections_structure:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": f"Section '{section_type}' not found in exam"}
            )

        section_config = sections_structure[section_type].copy()

        # Update syllabus if provided
        if custom_syllabus:
            section_config['syllabus'] = custom_syllabus
            # Also update in sections_structure for persistence
            sections_structure[section_type]['syllabus'] = custom_syllabus

        print(f"🔄 Regenerating section '{section_type}' for exam {exam_id}")
        print(f"📝 Syllabus: {section_config.get('syllabus', 'None')[:100]}...")
        print(f"📋 Custom instructions: {custom_instructions[:100] if custom_instructions else 'None'}...")

        # Generate questions for this single section
        result = exam_system.regenerate_section_questions(
            department=exam['department'],
            position=exam['position'],
            section_type=section_type,
            section_config=section_config,
            exam_language=exam.get('exam_language', 'english'),
            difficulty_level=difficulty_level,
            custom_instructions=custom_instructions
        )

        if not result['success']:
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": result.get('error', 'Failed to generate questions'),
                    "message": "AI generation failed. You can try again or edit questions manually."
                }
            )

        # Delete existing questions for this section
        db.delete_questions_by_section(exam_id, section_type)

        # Save new questions
        saved_count = 0
        for question in result['questions']:
            question_id = db.save_exam_question(exam_id, question, section_type)
            if question_id:
                saved_count += 1

        # Update sections_structure with new syllabus and mark as generated
        sections_structure[section_type]['generation_status'] = 'generated'
        sections_structure[section_type]['last_generated'] = datetime.now().isoformat()
        db.update_sections_structure(exam_id, sections_structure)

        print(f"✅ Regenerated {saved_count} questions for section '{section_type}'")

        return {
            "success": True,
            "message": f"Successfully regenerated {saved_count} questions for {section_type} section",
            "questions_count": saved_count,
            "section_type": section_type
        }

    except Exception as e:
        print(f"❌ Error regenerating section: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.get("/api/section-info/{exam_id}/{section_type}")
async def get_section_info(exam_id: str, section_type: str, session_id: str = Depends(verify_admin_access)):
    """Get information about a specific section including current syllabus and question count"""
    try:
        exam = db.get_exam_by_id(exam_id)
        if not exam:
            return JSONResponse(status_code=404, content={"success": False, "error": "Exam not found"})

        sections_structure = exam.get('sections_structure', {})
        if section_type not in sections_structure:
            return JSONResponse(status_code=404, content={"success": False, "error": "Section not found"})

        section_config = sections_structure[section_type]
        question_count = db.get_section_question_count(exam_id, section_type)

        return {
            "success": True,
            "section_type": section_type,
            "display_name": section_config.get('display_name', section_type.replace('_', ' ').title()),
            "syllabus": section_config.get('syllabus', ''),
            "mcq_count": section_config.get('mcq_count', 0),
            "short_count": section_config.get('short_count', 0),
            "essay_count": section_config.get('essay_count', 0),
            "mcq_marks": section_config.get('mcq_marks', 1),
            "short_marks": section_config.get('short_marks', 5),
            "essay_marks": section_config.get('essay_marks', 10),
            "generation_status": section_config.get('generation_status', 'unknown'),
            "current_question_count": question_count,
            "is_custom": section_config.get('is_custom', False)
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.get("/api/live-candidates/{exam_id}")
async def get_live_candidates(exam_id: str, session_id: str = Depends(verify_admin_access)):
    """Get currently live candidates for an exam"""
    try:
        cleaned_sessions = db.cleanup_stale_sessions(30)
        if cleaned_sessions > 0:
            print(f"🧹 Auto-cleaned {cleaned_sessions} stale sessions")
        
        live_candidates = db.get_live_candidates(exam_id)
        
        # Convert times to Bangladesh timezone
        for candidate in live_candidates:
            if candidate.get('started_at'):
                candidate['started_at'] = convert_utc_to_bangladesh(candidate['started_at'])
            if candidate.get('last_activity'):
                candidate['last_activity'] = convert_utc_to_bangladesh(candidate['last_activity'])
        
        return {
            "success": True,
            "live_candidates": live_candidates,
            "live_count": len(live_candidates)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/end-live-session/{session_id}")
async def manually_end_live_session(session_id: str, admin_session: str = Depends(verify_admin_access)):
    """Manually end a live session"""
    try:
        success = db.end_live_session(session_id)
        if success:
            return {"success": True, "message": f"Live session {session_id[:8]} ended successfully"}
        else:
            return {"success": False, "error": "Failed to end live session"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/update-session-activity/{session_id}")
async def update_session_activity(session_id: str):
    """Update session activity"""
    try:
        success = db.update_session_activity(session_id)
        return {"success": success}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/admin/download-result")
async def download_result_pdf(request: Request, session_id: str = Depends(verify_admin_access)):
    """Generate and download result report"""
    try:
        form_data = await request.form()
        result_id = form_data.get("result_id")
        
        if not result_id:
            raise HTTPException(status_code=400, detail="Result ID is required")
        
        result_details = db.get_result_details(result_id)
        if not result_details:
            raise HTTPException(status_code=404, detail="Result not found")
        
        # Generate HTML content for download
        if not result_details.get('has_feedback', True):
            # Simple submission confirmation
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head><title>Exam Submission - {result_details['candidate_name']}</title></head>
            <body>
                <h1>📋 Exam Submission Confirmation</h1>
                <h2>{result_details['exam_title']}</h2>
                <p><strong>Name:</strong> {result_details['candidate_name']}</p>
                <p><strong>ID:</strong> {result_details['candidate_id']}</p>
                <p><strong>Time Taken:</strong> {result_details['time_taken']}</p>
                <p><strong>Status:</strong> Successfully Submitted</p>
            </body>
            </html>
            """
        else:
            # Full results with sections
            sections = {}
            for question in result_details['questions']:
                section_type = question.get('section_type', 'technical')
                if section_type not in sections:
                    sections[section_type] = []
                sections[section_type].append(question)
            
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head><title>Exam Results - {result_details['candidate_name']}</title></head>
            <body>
                <h1>📊 Exam Results Report</h1>
                <h2>{result_details['exam_title']}</h2>
                <p><strong>Name:</strong> {result_details['candidate_name']}</p>
                <p><strong>Score:</strong> {result_details['obtained_marks']}/{result_details['total_marks']} ({result_details['percentage']:.1f}%)</p>
                <p><strong>Performance:</strong> {result_details['performance_level']}</p>
                
                <!-- Questions and answers would be formatted here -->
                <h3>Detailed Results</h3>
                <p>Total Questions: {len(result_details['questions'])}</p>
            </body>
            </html>
            """
        
        filename = generate_safe_filename(result_details['candidate_name'], result_id)
        
        return Response(
            content=html_content,
            media_type="text/html",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating report: {str(e)}")


@app.get("/admin/download-exam-questions/{exam_id}")
async def download_exam_questions(exam_id: str, request: Request, session_id: str = Depends(verify_admin_access)):
    """Generate and download exam questions as a print-friendly HTML/PDF document"""
    try:
        exam = db.get_exam_by_id(exam_id)
        if not exam:
            raise HTTPException(status_code=404, detail="Exam not found")

        sections = db.get_exam_questions_by_section(exam_id)
        sections_structure = exam.get('sections_structure', {})

        # Calculate total marks
        total_marks = 0
        total_questions = 0
        for section_questions in sections.values():
            for q in section_questions:
                total_marks += q.get('marks', 0)
                total_questions += 1

        # Check if we should include answers (query param)
        include_answers = request.query_params.get("answers", "false").lower() == "true"

        # Generate section HTML
        sections_html = ""
        question_number = 1

        for section_type, section_questions in sections.items():
            section_config = sections_structure.get(section_type, {})
            display_name = section_config.get('display_name', section_type.replace('_', ' ').title())

            # Calculate section marks
            section_marks = sum(q.get('marks', 0) for q in section_questions)

            sections_html += f"""
            <div class="section">
                <div class="section-header">
                    <h2>{display_name}</h2>
                    <span class="section-info">{len(section_questions)} Questions | {section_marks} Marks</span>
                </div>
            """

            for question in section_questions:
                q_type = question.get('type', 'unknown').upper()
                marks = question.get('marks', 0)

                sections_html += f"""
                <div class="question">
                    <div class="question-header">
                        <span class="question-number">Q{question_number}.</span>
                        <span class="question-type">[{q_type}]</span>
                        <span class="question-marks">[{marks} Mark{'s' if marks != 1 else ''}]</span>
                    </div>
                    <div class="question-text">{question.get('question', '')}</div>
                """

                # Add images if present
                if question.get('image_url'):
                    sections_html += f"""
                    <div class="question-image">
                        <img src="{question['image_url']}" alt="Question figure">
                        {f'<p class="image-caption">{question["image_caption"]}</p>' if question.get('image_caption') else ''}
                    </div>
                    """

                # Load additional images
                question_images = db.get_question_images(question['id'])
                for img in question_images:
                    sections_html += f"""
                    <div class="question-image">
                        <img src="{img['url']}" alt="Question figure">
                        {f'<p class="image-caption">{img["caption"]}</p>' if img.get('caption') else ''}
                    </div>
                    """

                # Add options for MCQ
                if question.get('type') == 'mcq' and question.get('options'):
                    sections_html += '<div class="options">'
                    for idx, option in enumerate(question['options']):
                        option_letter = ['A', 'B', 'C', 'D'][idx]
                        is_correct = idx == question.get('correct_answer')
                        correct_class = ' correct-answer' if include_answers and is_correct else ''
                        sections_html += f"""
                        <div class="option{correct_class}">
                            <span class="option-letter">{option_letter})</span>
                            <span class="option-text">{option}</span>
                            {' <span class="correct-mark">✓</span>' if include_answers and is_correct else ''}
                        </div>
                        """
                    sections_html += '</div>'

                # Add answer space for subjective questions
                elif question.get('type') in ['short', 'essay']:
                    if include_answers and question.get('expected_answer'):
                        sections_html += f"""
                        <div class="expected-answer">
                            <strong>Expected Answer:</strong>
                            <p>{question['expected_answer']}</p>
                        </div>
                        """
                    else:
                        lines = 5 if question.get('type') == 'short' else 12
                        sections_html += f"""
                        <div class="answer-space">
                            {'<div class="answer-line"></div>' * lines}
                        </div>
                        """

                sections_html += '</div>'  # Close question div
                question_number += 1

            sections_html += '</div>'  # Close section div

        # Generate the full HTML document
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{exam['title']} - Exam Questions</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Times New Roman', Times, serif;
            font-size: 12pt;
            line-height: 1.5;
            color: #000;
            background: #fff;
            padding: 20mm;
        }}

        @media print {{
            body {{
                padding: 15mm;
            }}

            .no-print {{
                display: none !important;
            }}

            .section {{
                page-break-inside: avoid;
            }}

            .question {{
                page-break-inside: avoid;
            }}
        }}

        .exam-header {{
            text-align: center;
            border-bottom: 2px solid #000;
            padding-bottom: 15px;
            margin-bottom: 20px;
        }}

        .exam-header h1 {{
            font-size: 18pt;
            margin-bottom: 10px;
            text-transform: uppercase;
        }}

        .exam-meta {{
            display: flex;
            justify-content: space-between;
            flex-wrap: wrap;
            margin-top: 10px;
            font-size: 11pt;
        }}

        .exam-meta-item {{
            margin: 5px 15px;
        }}

        .candidate-info {{
            border: 1px solid #000;
            padding: 15px;
            margin: 20px 0;
            background: #f9f9f9;
        }}

        .candidate-info table {{
            width: 100%;
        }}

        .candidate-info td {{
            padding: 8px;
            border-bottom: 1px dotted #999;
        }}

        .candidate-info td:first-child {{
            font-weight: bold;
            width: 150px;
        }}

        .instructions {{
            border: 1px solid #ccc;
            padding: 15px;
            margin: 20px 0;
            background: #fffef0;
        }}

        .instructions h3 {{
            margin-bottom: 10px;
            font-size: 12pt;
        }}

        .instructions ul {{
            margin-left: 20px;
        }}

        .instructions li {{
            margin: 5px 0;
        }}

        .section {{
            margin: 25px 0;
        }}

        .section-header {{
            background: #f0f0f0;
            padding: 10px 15px;
            border: 1px solid #ccc;
            margin-bottom: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .section-header h2 {{
            font-size: 14pt;
            margin: 0;
        }}

        .section-info {{
            font-size: 10pt;
            color: #666;
        }}

        .question {{
            margin: 20px 0;
            padding: 15px;
            border-left: 3px solid #333;
            background: #fafafa;
        }}

        .question-header {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 10px;
            font-weight: bold;
        }}

        .question-number {{
            font-size: 12pt;
        }}

        .question-type {{
            font-size: 9pt;
            color: #666;
            background: #e0e0e0;
            padding: 2px 6px;
            border-radius: 3px;
        }}

        .question-marks {{
            font-size: 10pt;
            color: #333;
            margin-left: auto;
        }}

        .question-text {{
            font-size: 12pt;
            margin: 10px 0;
            line-height: 1.6;
        }}

        .question-image {{
            margin: 15px 0;
            text-align: center;
        }}

        .question-image img {{
            max-width: 400px;
            max-height: 300px;
            border: 1px solid #ddd;
        }}

        .image-caption {{
            font-size: 10pt;
            color: #666;
            font-style: italic;
            margin-top: 5px;
        }}

        .options {{
            margin: 15px 0 15px 20px;
        }}

        .option {{
            display: flex;
            align-items: flex-start;
            margin: 8px 0;
            padding: 5px 10px;
        }}

        .option-letter {{
            font-weight: bold;
            min-width: 25px;
        }}

        .option-text {{
            flex: 1;
        }}

        .correct-answer {{
            background: #d4edda;
            border-radius: 4px;
        }}

        .correct-mark {{
            color: #28a745;
            font-weight: bold;
            margin-left: 10px;
        }}

        .answer-space {{
            margin: 15px 0;
            padding: 10px;
        }}

        .answer-line {{
            border-bottom: 1px solid #ccc;
            height: 30px;
            margin: 5px 0;
        }}

        .expected-answer {{
            margin: 15px 0;
            padding: 10px;
            background: #e8f5e9;
            border: 1px solid #c8e6c9;
            border-radius: 4px;
        }}

        .expected-answer p {{
            margin-top: 8px;
            white-space: pre-wrap;
        }}

        .footer {{
            margin-top: 30px;
            padding-top: 15px;
            border-top: 1px solid #ccc;
            text-align: center;
            font-size: 10pt;
            color: #666;
        }}

        .print-buttons {{
            position: fixed;
            top: 20px;
            right: 20px;
            display: flex;
            gap: 10px;
            z-index: 1000;
        }}

        .print-btn {{
            padding: 10px 20px;
            font-size: 14px;
            cursor: pointer;
            border: none;
            border-radius: 5px;
            font-weight: bold;
        }}

        .btn-print {{
            background: #007bff;
            color: white;
        }}

        .btn-close {{
            background: #6c757d;
            color: white;
        }}

        .print-btn:hover {{
            opacity: 0.9;
        }}
    </style>
</head>
<body>
    <div class="print-buttons no-print">
        <button class="print-btn btn-print" onclick="window.print()">🖨️ Print</button>
        <button class="print-btn btn-close" onclick="window.close()">✕ Close</button>
    </div>

    <div class="exam-header">
        <h1>{exam['title']}</h1>
        <div class="exam-meta">
            <span class="exam-meta-item"><strong>Department:</strong> {exam['department']}</span>
            <span class="exam-meta-item"><strong>Position:</strong> {exam['position']}</span>
            <span class="exam-meta-item"><strong>Time:</strong> {exam['time_limit']} Minutes</span>
            <span class="exam-meta-item"><strong>Total Marks:</strong> {total_marks}</span>
            <span class="exam-meta-item"><strong>Total Questions:</strong> {total_questions}</span>
        </div>
    </div>

    <div class="candidate-info">
        <table>
            <tr>
                <td>Candidate Name:</td>
                <td>_________________________________________________</td>
            </tr>
            <tr>
                <td>Candidate ID:</td>
                <td>_________________________________________________</td>
            </tr>
            <tr>
                <td>Date:</td>
                <td>_________________________________________________</td>
            </tr>
            <tr>
                <td>Signature:</td>
                <td>_________________________________________________</td>
            </tr>
        </table>
    </div>

    <div class="instructions">
        <h3>📋 Instructions:</h3>
        <ul>
            <li>Read all questions carefully before answering.</li>
            <li>Total time allowed: <strong>{exam['time_limit']} minutes</strong></li>
            <li>Total marks: <strong>{total_marks}</strong></li>
            <li>Answer all questions in the space provided.</li>
            <li>For MCQ questions, clearly mark your answer.</li>
            {f"<li>{exam['instructions']}</li>" if exam.get('instructions') else ""}
        </ul>
    </div>

    {sections_html}

    <div class="footer">
        <p>--- End of Question Paper ---</p>
        <p>Total Questions: {total_questions} | Total Marks: {total_marks} | Time: {exam['time_limit']} Minutes</p>
    </div>
</body>
</html>
        """

        # Return as HTML that can be printed to PDF
        return Response(
            content=html_content,
            media_type="text/html"
        )

    except Exception as e:
        print(f"❌ Error generating exam questions PDF: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error generating exam questions: {str(e)}")


@app.get("/api/result-details/{result_id}")
async def get_result_details(result_id: str, session_id: str = Depends(verify_admin_access)):
    """Get detailed results for a candidate"""
    try:
        details = db.get_result_details(result_id)
        if not details:
            raise HTTPException(status_code=404, detail="Result not found")
        return details
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/toggle-exam-status/{exam_id}")
async def toggle_exam_status(exam_id: str, request: Request, session_id: str = Depends(verify_admin_access)):
    """Toggle exam active/inactive status"""
    try:
        data = await request.json()
        is_active = data.get('is_active', True)
        success = db.toggle_exam_status(exam_id, is_active)
        return {"success": success}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/update-question-marks")
async def update_question_marks(request: Request, session_id: str = Depends(verify_admin_access)):
    """Update marks for a specific question"""
    try:
        data = await request.json()
        success = db.update_question_marks(
            data.get('question_id'),
            data.get('result_id'), 
            float(data.get('new_marks', 0))
        )
        return {"success": success}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.delete("/api/delete-result/{result_id}")
async def delete_result(result_id: str, session_id: str = Depends(verify_admin_access)):
    """Delete a candidate's exam result"""
    try:
        success = db.delete_result(result_id)
        if success:
            return {"success": True, "message": "Result deleted successfully"}
        else:
            return {"success": False, "error": "Failed to delete result"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.delete("/api/delete-exam/{exam_id}")
async def delete_exam(exam_id: str, session_id: str = Depends(verify_admin_access)):
    """Delete an exam and all related data"""
    try:
        success = db.delete_exam(exam_id)
        return {"success": success}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/update-result-info")
async def update_result_info(request: Request, session_id: str = Depends(verify_admin_access)):
    """Update basic result information"""
    try:
        data = await request.json()
        success = db.update_result_info(
            data.get('result_id'),
            data.get('candidate_name'),
            data.get('candidate_id'),
            data.get('time_taken')
        )
        return {"success": success}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/get-result-summary/{result_id}")
async def get_result_summary(result_id: str, session_id: str = Depends(verify_admin_access)):
    """Get quick summary of a result for editing"""
    try:
        summary = db.get_result_summary(result_id)
        if not summary:
            raise HTTPException(status_code=404, detail="Result not found")
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/exam-sections/{exam_id}")
async def get_exam_sections(exam_id: str, session_id: str = Depends(verify_admin_access)):
    """Get exam sections structure"""
    try:
        exam = db.get_exam_by_id(exam_id)
        if not exam:
            raise HTTPException(status_code=404, detail="Exam not found")
        
        sections = db.get_exam_questions_by_section(exam_id)
        return {
            "success": True,
            "exam_id": exam_id,
            "sections_structure": exam.get('sections_structure', {}),
            "sections": sections,
            "show_feedback": exam.get('show_feedback', True),
            "negative_marking_config": exam.get('negative_marking_config', {}),
            "exam_language": exam.get('exam_language', 'english')
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    
@app.post("/api/upload-question-image/{question_id}")
async def upload_question_image(
    question_id: str, 
    file: UploadFile = File(...), 
    caption: str = Form(None),
    session_id: str = Depends(verify_admin_access)
):
    """Upload an image for a question"""
    try:
        # Validate file type
        allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg'}
        file_ext = Path(file.filename).suffix.lower()
        
        if file_ext not in allowed_extensions:
            return {
                "success": False, 
                "error": f"Invalid file type. Allowed types: {', '.join(allowed_extensions)}"
            }
        
        # Validate file size (max 5MB)
        file_size = 0
        file_content = await file.read()
        file_size = len(file_content)
        
        if file_size > 5 * 1024 * 1024:  # 5MB limit
            return {"success": False, "error": "File size exceeds 5MB limit"}
        
        # Reset file position for saving
        await file.seek(0)
        
        # Generate unique filename
        unique_filename = f"{question_id}_{uuid.uuid4()}{file_ext}"
        file_path = UPLOAD_DIR / unique_filename
        
        # Save file
        with open(file_path, "wb") as buffer:
            buffer.write(file_content)
        
        # Save to database
        image_url = f"/uploads/images/{unique_filename}"
        image_id = db.add_question_image(question_id, image_url, caption)
        
        if image_id:
            return {
                "success": True,
                "image_id": image_id,
                "image_url": image_url,
                "caption": caption
            }
        else:
            # Delete the uploaded file if database save failed
            file_path.unlink(missing_ok=True)
            return {"success": False, "error": "Failed to save image to database"}
            
    except Exception as e:
        print(f"❌ Error uploading image: {str(e)}")
        return {"success": False, "error": str(e)}


@app.delete("/api/delete-question-image/{image_id}")
async def delete_question_image(image_id: str, session_id: str = Depends(verify_admin_access)):
    """Delete a question image"""
    try:
        # Get image info from database
        with sqlite3.connect(db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT image_url FROM question_images WHERE id = ?', (image_id,))
            row = cursor.fetchone()
            
            if not row:
                return {"success": False, "error": "Image not found"}
            
            image_url = row[0]
        
        # Delete from database
        success = db.delete_question_image(image_id)
        
        if success:
            # Delete physical file
            if image_url and image_url.startswith("/uploads/images/"):
                file_path = Path("uploads") / image_url.lstrip("/uploads/")
                file_path.unlink(missing_ok=True)
            
            return {"success": True, "message": "Image deleted successfully"}
        else:
            return {"success": False, "error": "Failed to delete image from database"}
            
    except Exception as e:
        print(f"❌ Error deleting image: {str(e)}")
        return {"success": False, "error": str(e)}


@app.get("/api/question-images/{question_id}")
async def get_question_images(question_id: str, session_id: str = Depends(verify_admin_access)):
    """Get all images for a question"""
    try:
        images = db.get_question_images(question_id)
        return {"success": True, "images": images}
    except Exception as e:
        return {"success": False, "error": str(e)}
    
@app.post("/api/cleanup-orphaned-images")
async def cleanup_orphaned_images(session_id: str = Depends(verify_admin_access)):
    """Clean up images that are no longer associated with any questions"""
    try:
        # Get all image URLs from database
        with sqlite3.connect(db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT DISTINCT image_url FROM question_images')
            db_images = {row[0] for row in cursor.fetchall()}
            cursor.execute('SELECT DISTINCT image_url FROM questions WHERE image_url IS NOT NULL')
            db_images.update({row[0] for row in cursor.fetchall()})
        
        # Get all files in upload directory
        upload_files = set()
        for file_path in UPLOAD_DIR.glob("*"):
            if file_path.is_file():
                relative_path = f"/uploads/images/{file_path.name}"
                upload_files.add(relative_path)
        
        # Find orphaned files
        orphaned_files = upload_files - db_images
        
        # Delete orphaned files
        deleted_count = 0
        for orphaned_url in orphaned_files:
            file_path = Path("uploads") / orphaned_url.lstrip("/uploads/")
            if file_path.exists():
                file_path.unlink()
                deleted_count += 1
        
        return {
            "success": True,
            "deleted_count": deleted_count,
            "orphaned_files": list(orphaned_files)
        }
        
    except Exception as e:
        print(f"❌ Error cleaning up orphaned images: {str(e)}")
        return {"success": False, "error": str(e)}

# Evaluation Queue API Endpoints

@app.get("/api/evaluation-status/{result_id}")
async def get_evaluation_status(result_id: str):
    """
    Get the current evaluation status for a result.
    Candidates can poll this to check if their results are ready.
    """
    try:
        # Get status from queue (in-memory) first
        queue_status = evaluation_queue.get_status(result_id)

        # Also get status from database
        db_status = db.get_result_evaluation_status(result_id)

        if not db_status:
            return {"success": False, "error": "Result not found"}

        # Merge information
        status = db_status['evaluation_status']

        # If queue says completed but DB hasn't updated yet, use queue status
        if queue_status.get('status') == 'completed' and status == 'pending':
            status = 'completed'

        return {
            "success": True,
            "result_id": result_id,
            "status": status,
            "is_complete": status in ['completed', 'failed'],
            "can_view_results": status == 'completed' and db_status.get('show_feedback', True),
            "candidate_name": db_status['candidate_name'],
            "exam_title": db_status['exam_title'],
            "queue_position": queue_status.get('queue_position', 0),
            "message": queue_status.get('message', 'Processing...'),
            "show_feedback": db_status.get('show_feedback', True)
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/results/{result_id}", response_class=HTMLResponse)
async def view_results_by_id(request: Request, result_id: str):
    """
    View results for a specific result ID.
    Candidates are redirected here after evaluation completes.
    """
    try:
        # Check evaluation status
        status_info = db.get_result_evaluation_status(result_id)

        if not status_info:
            return templates.TemplateResponse("candidate_home.html", {
                "request": request,
                "error": "Result not found. Please contact the administrator."
            })

        # If still pending, show status page
        if status_info['evaluation_status'] == 'pending':
            queue_status = evaluation_queue.get_status(result_id)
            return templates.TemplateResponse("evaluation_status.html", {
                "request": request,
                "result_id": result_id,
                "candidate_name": status_info['candidate_name'],
                "candidate_id": status_info['candidate_id'],
                "exam_title": status_info['exam_title'],
                "status": "pending",
                "queue_position": queue_status.get('queue_position', 0),
                "message": queue_status.get('message', 'Your exam is being evaluated...'),
                "show_feedback": status_info.get('show_feedback', True)
            })

        # If failed, show appropriate message
        if status_info['evaluation_status'] == 'failed':
            return templates.TemplateResponse("evaluation_status.html", {
                "request": request,
                "result_id": result_id,
                "candidate_name": status_info['candidate_name'],
                "candidate_id": status_info['candidate_id'],
                "exam_title": status_info['exam_title'],
                "status": "failed",
                "message": "Your exam has been submitted. Results will be available after manual review.",
                "show_feedback": False
            })

        # If completed, show results
        if status_info['evaluation_status'] == 'completed':
            # Check if feedback should be shown
            if not status_info.get('show_feedback', True):
                return templates.TemplateResponse("candidate_submission_complete.html", {
                    "request": request,
                    "candidate_name": status_info['candidate_name'],
                    "candidate_id": status_info['candidate_id'],
                    "exam_title": status_info['exam_title'],
                    "time_taken": "N/A"
                })

            # Get full result details
            result_details = db.get_result_details(result_id)

            if not result_details:
                return templates.TemplateResponse("candidate_home.html", {
                    "request": request,
                    "error": "Could not load result details."
                })

            # Build evaluation structure for template
            evaluation = {
                'total_marks': result_details['total_marks'],
                'obtained_marks': result_details['obtained_marks'],
                'negative_marks': result_details.get('negative_marks', 0),
                'percentage': result_details['percentage'],
                'performance_level': result_details['performance_level'],
                'question_results': [],
                'overall_feedback': ''
            }

            # Build question results
            for q in result_details.get('questions', []):
                q_result = {
                    'question_id': q['question_id'],
                    'question_type': q['question_type'],
                    'question_text': q['question_text'],
                    'candidate_answer': q['candidate_answer'],
                    'marks_total': q['marks_total'],
                    'marks_obtained': q['marks_obtained'],
                    'negative_marks_applied': q.get('negative_marks_applied', 0),
                    'feedback': q['feedback'],
                    'is_correct': q.get('is_correct'),
                    'is_multi_select': q.get('is_multi_select', False),
                    'options': q.get('options', []),
                    'correct_answer': q.get('correct_answer'),
                    'correct_answers': q.get('correct_answers', []),
                    'selected_option': q.get('selected_option', ''),
                    'correct_option': q.get('correct_option', '')
                }
                evaluation['question_results'].append(q_result)

            return templates.TemplateResponse("candidate_results.html", {
                "request": request,
                "candidate_name": result_details['candidate_name'],
                "candidate_id": result_details['candidate_id'],
                "exam_title": result_details['exam_title'],
                "evaluation": evaluation,
                "time_taken": result_details.get('time_taken', 'N/A')
            })

        # Default: show status page
        return templates.TemplateResponse("evaluation_status.html", {
            "request": request,
            "result_id": result_id,
            "candidate_name": status_info['candidate_name'],
            "exam_title": status_info['exam_title'],
            "status": status_info['evaluation_status'],
            "message": "Processing your results..."
        })

    except Exception as e:
        print(f"❌ Error viewing results: {str(e)}")
        return templates.TemplateResponse("candidate_home.html", {
            "request": request,
            "error": f"Error loading results: {str(e)}"
        })


@app.get("/api/queue-stats")
async def get_queue_stats(session_id: str = Depends(verify_admin_access)):
    """Get evaluation queue statistics for admin dashboard"""
    try:
        queue_stats = evaluation_queue.get_queue_stats()
        pending_evaluations = db.get_pending_evaluations(20)
        failed_evaluations = db.get_failed_evaluations(10)

        return {
            "success": True,
            "queue": queue_stats,
            "pending_evaluations": pending_evaluations,
            "failed_evaluations": failed_evaluations
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/exam-queue-stats/{exam_id}")
async def get_exam_queue_stats(exam_id: str, session_id: str = Depends(verify_admin_access)):
    """Get evaluation queue statistics for a specific exam"""
    try:
        pending_evaluations = db.get_pending_evaluations_by_exam(exam_id)
        failed_evaluations = db.get_failed_evaluations_by_exam(exam_id)
        eval_status = db.get_exam_evaluation_status(exam_id)

        return {
            "success": True,
            "pending_evaluations": pending_evaluations,
            "failed_evaluations": failed_evaluations,
            "pending_count": len(pending_evaluations),
            "failed_count": len(failed_evaluations),
            "evaluation_paused": eval_status.get('evaluation_paused', False)
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/exam-evaluation-pause/{exam_id}")
async def pause_exam_evaluation(exam_id: str, session_id: str = Depends(verify_admin_access)):
    """Pause evaluation processing for a specific exam"""
    try:
        success = db.set_exam_evaluation_paused(exam_id, True)

        if success:
            return {
                "success": True,
                "message": "Evaluation processing paused for this exam",
                "evaluation_paused": True
            }
        else:
            return {"success": False, "error": "Exam not found"}

    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/exam-evaluation-resume/{exam_id}")
async def resume_exam_evaluation(exam_id: str, session_id: str = Depends(verify_admin_access)):
    """Resume evaluation processing for a specific exam"""
    try:
        success = db.set_exam_evaluation_paused(exam_id, False)

        if success:
            return {
                "success": True,
                "message": "Evaluation processing resumed for this exam",
                "evaluation_paused": False
            }
        else:
            return {"success": False, "error": "Exam not found"}

    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/retry-evaluation/{result_id}")
async def retry_evaluation(result_id: str, session_id: str = Depends(verify_admin_access)):
    """
    Retry a failed evaluation by re-queuing it.
    Admin can use this to retry evaluations that failed due to API issues.
    """
    try:
        # First, mark the result for retry in the database
        db_success = db.retry_failed_evaluation(result_id)

        if not db_success:
            return {"success": False, "error": "Result not found or not in failed state"}

        # Get the result data to re-queue
        pending_results = db.get_pending_results_for_recovery()
        result_to_retry = None

        for result in pending_results:
            if result['result_id'] == result_id:
                result_to_retry = result
                break

        if not result_to_retry:
            return {"success": False, "error": "Could not retrieve result data for retry"}

        # Add back to the queue
        queue_success = evaluation_queue.add_task(
            result_id=result_to_retry['result_id'],
            session_id=result_to_retry['session_id'],
            exam_id=result_to_retry['exam_id'],
            candidate_name=result_to_retry['candidate_name'],
            candidate_id=result_to_retry['candidate_id'],
            answers=result_to_retry['answers'],
            questions=result_to_retry['questions'],
            negative_marking_config=result_to_retry['negative_marking_config'],
            show_feedback=result_to_retry['show_feedback'],
            multi_select_scoring_mode=result_to_retry.get('multi_select_scoring_mode', 'partial'),
            priority=0  # High priority for retried tasks
        )

        if queue_success:
            return {
                "success": True,
                "message": f"Evaluation for {result_to_retry['candidate_name']} has been re-queued"
            }
        else:
            return {"success": False, "error": "Failed to add to evaluation queue"}

    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/manual-evaluation/{result_id}")
async def get_manual_evaluation_data(result_id: str, session_id: str = Depends(verify_admin_access)):
    """
    Get the full result data for manual evaluation by admin.
    Returns all questions and answers for grading.
    """
    try:
        result_data = db.get_result_for_manual_evaluation(result_id)

        if not result_data:
            return {"success": False, "error": "Result not found"}

        return {
            "success": True,
            "result": result_data
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/manual-evaluation/{result_id}")
async def save_manual_evaluation(result_id: str, request: Request, session_id: str = Depends(verify_admin_access)):
    """
    Save manual evaluation from admin.
    Expects JSON body with evaluations: [{answer_id, marks_obtained, feedback}, ...]
    """
    try:
        data = await request.json()
        evaluations = data.get('evaluations', [])

        if not evaluations:
            return {"success": False, "error": "No evaluations provided"}

        # Ensure marks_obtained is numeric and non-negative at API level
        for eval_item in evaluations:
            try:
                eval_item['marks_obtained'] = float(eval_item.get('marks_obtained', 0))
                if eval_item['marks_obtained'] < 0:
                    eval_item['marks_obtained'] = 0
            except (ValueError, TypeError):
                eval_item['marks_obtained'] = 0

        success = db.save_manual_evaluation(result_id, evaluations)

        if success:
            return {
                "success": True,
                "message": "Manual evaluation saved successfully"
            }
        else:
            return {"success": False, "error": "Failed to save manual evaluation"}

    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/admin/manual-evaluate/{result_id}", response_class=HTMLResponse)
async def manual_evaluate_page(request: Request, result_id: str, session_id: str = Depends(verify_admin_access)):
    """
    Admin page for manually evaluating a failed submission.
    """
    try:
        result_data = db.get_result_for_manual_evaluation(result_id)

        if not result_data:
            return templates.TemplateResponse("admin_dashboard.html", {
                "request": request,
                "error": "Result not found"
            })

        return templates.TemplateResponse("manual_evaluation.html", {
            "request": request,
            "result": result_data
        })

    except Exception as e:
        return templates.TemplateResponse("admin_dashboard.html", {
            "request": request,
            "error": f"Error loading result: {str(e)}"
        })


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    queue_stats = evaluation_queue.get_queue_stats()
    return {
        "status": "healthy",
        "timestamp": datetime.now(),
        "evaluation_queue": {
            "running": queue_stats.get('is_running', False),
            "pending": queue_stats.get('pending', 0),
            "processing": queue_stats.get('processing', 0)
        }
    }