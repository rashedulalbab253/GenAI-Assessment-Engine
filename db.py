"""
Database management for AI-based Exam System
Handles all database operations and data persistence
"""

import sqlite3
import json
import uuid
import secrets
from datetime import datetime
from typing import Dict, List, Optional
import os


class ExamDatabase:
    def __init__(self, db_path: str = "exam_system.db"):
        """Initialize the database connection and create tables if they don't exist"""
        self.db_path = db_path
        self.init_database()
        self._enable_wal_mode()

    def _enable_wal_mode(self):
        """Enable WAL (Write-Ahead Logging) mode for better concurrent access.

        WAL mode provides:
        - Better concurrent read/write performance
        - Readers don't block writers and vice versa
        - Better crash recovery
        - Improved performance for web applications
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                result = cursor.fetchone()
                if result and result[0].lower() == 'wal':
                    print("✅ SQLite WAL mode enabled for better concurrency")
                else:
                    print(f"⚠️ SQLite journal mode: {result[0] if result else 'unknown'}")
        except sqlite3.Error as e:
            print(f"⚠️ Could not enable WAL mode: {e}")

    def init_database(self):
        """Create database tables if they don't exist"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Create exams table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS exams (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    department TEXT NOT NULL,
                    position TEXT NOT NULL,
                    description TEXT,
                    time_limit INTEGER NOT NULL,
                    instructions TEXT,
                    question_structure TEXT,
                    sections_structure TEXT,
                    negative_marking_config TEXT,
                    exam_language TEXT DEFAULT 'english',
                    exam_link TEXT UNIQUE,
                    is_finalized BOOLEAN DEFAULT FALSE,
                    is_active BOOLEAN DEFAULT TRUE,
                    show_feedback BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Database migrations - add missing columns
            self._add_column_if_not_exists(cursor, 'exams', 'sections_structure', 'TEXT')
            self._add_column_if_not_exists(cursor, 'exams', 'is_active', 'BOOLEAN DEFAULT TRUE')
            self._add_column_if_not_exists(cursor, 'exams', 'show_feedback', 'BOOLEAN DEFAULT TRUE')
            self._add_column_if_not_exists(cursor, 'exams', 'negative_marking_config', 'TEXT')
            self._add_column_if_not_exists(cursor, 'exams', 'exam_language', 'TEXT DEFAULT "english"')
            self._add_column_if_not_exists(cursor, 'exams', 'evaluation_paused', 'BOOLEAN DEFAULT FALSE')
            self._add_column_if_not_exists(cursor, 'exams', 'multi_select_scoring_mode', 'TEXT DEFAULT "partial"')
            
            # Create questions table with image support
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS questions (
                    id TEXT PRIMARY KEY,
                    exam_id TEXT NOT NULL,
                    section_type TEXT NOT NULL,
                    question_type TEXT NOT NULL,
                    question_text TEXT NOT NULL,
                    options TEXT,
                    correct_answer INTEGER,
                    expected_answer TEXT,
                    evaluation_criteria TEXT,
                    marks INTEGER NOT NULL,
                    question_order INTEGER,
                    explanation TEXT,
                    image_url TEXT,
                    image_caption TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (exam_id) REFERENCES exams (id)
                )
            ''')
            
            # Add image columns if they don't exist
            self._add_column_if_not_exists(cursor, 'questions', 'section_type', 'TEXT DEFAULT "technical"')
            self._add_column_if_not_exists(cursor, 'questions', 'image_url', 'TEXT')
            self._add_column_if_not_exists(cursor, 'questions', 'image_caption', 'TEXT')

            # Add multi-select MCQ support
            # is_multi_select: Boolean flag for multi-select MCQs
            # correct_answers: JSON array of correct answer indices for multi-select (e.g., "[0, 2]")
            self._add_column_if_not_exists(cursor, 'questions', 'is_multi_select', 'BOOLEAN DEFAULT FALSE')
            self._add_column_if_not_exists(cursor, 'questions', 'correct_answers', 'TEXT')
            
            # Create question_images table for multiple images per question
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS question_images (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL,
                    image_url TEXT NOT NULL,
                    image_caption TEXT,
                    image_order INTEGER DEFAULT 0,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (question_id) REFERENCES questions (id) ON DELETE CASCADE
                )
            ''')
            
            # Create live_sessions table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS live_sessions (
                    session_id TEXT PRIMARY KEY,
                    exam_id TEXT NOT NULL,
                    candidate_name TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE,
                    FOREIGN KEY (exam_id) REFERENCES exams (id)
                )
            ''')
            
            # Create exam_results table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS exam_results (
                    id TEXT PRIMARY KEY,
                    session_id TEXT UNIQUE NOT NULL,
                    exam_id TEXT NOT NULL,
                    candidate_name TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    total_marks INTEGER NOT NULL,
                    obtained_marks REAL NOT NULL,
                    negative_marks REAL DEFAULT 0,
                    percentage REAL NOT NULL,
                    performance_level TEXT NOT NULL,
                    time_taken TEXT,
                    has_feedback BOOLEAN DEFAULT TRUE,
                    evaluation_status TEXT DEFAULT 'pending',
                    evaluation_error TEXT,
                    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    evaluated_at TIMESTAMP,
                    FOREIGN KEY (exam_id) REFERENCES exams (id)
                )
            ''')
            
            self._add_column_if_not_exists(cursor, 'exam_results', 'has_feedback', 'BOOLEAN DEFAULT TRUE')
            self._add_column_if_not_exists(cursor, 'exam_results', 'negative_marks', 'REAL DEFAULT 0')
            self._add_column_if_not_exists(cursor, 'exam_results', 'evaluation_status', 'TEXT DEFAULT "pending"')
            self._add_column_if_not_exists(cursor, 'exam_results', 'evaluation_error', 'TEXT')
            self._add_column_if_not_exists(cursor, 'exam_results', 'evaluated_at', 'TIMESTAMP')
            
            # Create candidate_answers table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS candidate_answers (
                    id TEXT PRIMARY KEY,
                    result_id TEXT NOT NULL,
                    question_id TEXT NOT NULL,
                    candidate_answer TEXT,
                    marks_obtained REAL NOT NULL,
                    negative_marks_applied REAL DEFAULT 0,
                    is_correct BOOLEAN,
                    feedback TEXT,
                    evaluation_details TEXT,
                    FOREIGN KEY (result_id) REFERENCES exam_results (id),
                    FOREIGN KEY (question_id) REFERENCES questions (id)
                )
            ''')
            
            self._add_column_if_not_exists(cursor, 'candidate_answers', 'negative_marks_applied', 'REAL DEFAULT 0')
            
            # Create detailed_evaluations table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS detailed_evaluations (
                    id TEXT PRIMARY KEY,
                    answer_id TEXT NOT NULL,
                    strengths TEXT,
                    improvements TEXT,
                    overall_feedback TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (answer_id) REFERENCES candidate_answers (id)
                )
            ''')

            # Create exam_sessions table for persistent session storage
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS exam_sessions (
                    session_id TEXT PRIMARY KEY,
                    exam_id TEXT NOT NULL,
                    candidate_name TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    time_limit INTEGER NOT NULL,
                    answers_data TEXT,
                    is_submitted BOOLEAN DEFAULT FALSE,
                    submitted_at TIMESTAMP,
                    FOREIGN KEY (exam_id) REFERENCES exams (id)
                )
            ''')

            conn.commit()
            print("✅ Exam database initialized successfully with image support and persistent sessions")

    def _add_column_if_not_exists(self, cursor, table_name: str, column_name: str, column_definition: str):
        """Add a column to table if it doesn't exist"""
        try:
            cursor.execute(f"SELECT {column_name} FROM {table_name} LIMIT 1")
        except sqlite3.OperationalError:
            print(f"🔄 Adding {column_name} column to {table_name} table...")
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")
            print("✅ Database migration completed")

    # Image Management Functions
    
    def add_question_image(self, question_id: str, image_url: str, caption: str = None, order: int = 0) -> str:
        """Add an image to a question"""
        try:
            image_id = str(uuid.uuid4())
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO question_images (id, question_id, image_url, image_caption, image_order)
                    VALUES (?, ?, ?, ?, ?)
                ''', (image_id, question_id, image_url, caption, order))
                
                # Also update the main question table for backward compatibility
                if order == 0:  # Primary image
                    cursor.execute('''
                        UPDATE questions SET image_url = ?, image_caption = ?
                        WHERE id = ?
                    ''', (image_url, caption, question_id))
                
                conn.commit()
                print(f"✅ Image added to question {question_id}")
                return image_id
        except sqlite3.Error as e:
            print(f"❌ Error adding question image: {e}")
            return None

    def get_question_images(self, question_id: str) -> List[Dict]:
        """Get all images for a question"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, image_url, image_caption, image_order
                    FROM question_images
                    WHERE question_id = ?
                    ORDER BY image_order
                ''', (question_id,))
                
                images = []
                for row in cursor.fetchall():
                    images.append({
                        'id': row[0],
                        'url': row[1],
                        'caption': row[2],
                        'order': row[3]
                    })
                return images
        except sqlite3.Error as e:
            print(f"❌ Error getting question images: {e}")
            return []

    def delete_question_image(self, image_id: str) -> bool:
        """Delete a specific image from a question"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Get image info before deletion
                cursor.execute('SELECT question_id, image_order FROM question_images WHERE id = ?', (image_id,))
                row = cursor.fetchone()
                
                if row:
                    question_id, order = row
                    
                    # Delete the image
                    cursor.execute('DELETE FROM question_images WHERE id = ?', (image_id,))
                    
                    # If it was the primary image, clear from questions table
                    if order == 0:
                        cursor.execute('UPDATE questions SET image_url = NULL, image_caption = NULL WHERE id = ?', (question_id,))
                    
                    conn.commit()
                    return True
                return False
        except sqlite3.Error as e:
            print(f"❌ Error deleting question image: {e}")
            return False

    def delete_questions_by_section(self, exam_id: str, section_type: str) -> bool:
        """Delete all questions for a specific section of an exam"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # First, get all question IDs for this section
                cursor.execute('''
                    SELECT id FROM questions WHERE exam_id = ? AND section_type = ?
                ''', (exam_id, section_type))
                question_ids = [row[0] for row in cursor.fetchall()]

                # Delete images for these questions
                for question_id in question_ids:
                    cursor.execute('DELETE FROM question_images WHERE question_id = ?', (question_id,))

                # Delete the questions
                cursor.execute('''
                    DELETE FROM questions WHERE exam_id = ? AND section_type = ?
                ''', (exam_id, section_type))

                deleted_count = cursor.rowcount
                conn.commit()
                print(f"✅ Deleted {deleted_count} questions from section {section_type}")
                return True
        except sqlite3.Error as e:
            print(f"❌ Error deleting questions by section: {e}")
            return False

    def update_sections_structure(self, exam_id: str, sections_structure: Dict) -> bool:
        """Update the sections_structure for an exam"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE exams SET sections_structure = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (json.dumps(sections_structure), exam_id))
                conn.commit()
                print(f"✅ Updated sections_structure for exam {exam_id}")
                return True
        except sqlite3.Error as e:
            print(f"❌ Error updating sections_structure: {e}")
            return False

    def get_section_question_count(self, exam_id: str, section_type: str) -> int:
        """Get the count of questions for a specific section"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT COUNT(*) FROM questions WHERE exam_id = ? AND section_type = ?
                ''', (exam_id, section_type))
                return cursor.fetchone()[0]
        except sqlite3.Error as e:
            print(f"❌ Error getting section question count: {e}")
            return 0

    # Live Session Management

    def create_live_session(self, session_id: str, exam_id: str, candidate_name: str, candidate_id: str) -> bool:
        """Create a new live session when candidate starts exam"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO live_sessions (session_id, exam_id, candidate_name, candidate_id)
                    VALUES (?, ?, ?, ?)
                ''', (session_id, exam_id, candidate_name, candidate_id))
                conn.commit()
                print(f"✅ Live session created for {candidate_name} ({candidate_id})")
                return True
        except sqlite3.Error as e:
            print(f"❌ Error creating live session: {e}")
            return False

    def update_session_activity(self, session_id: str) -> bool:
        """Update last activity time for a live session"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE live_sessions 
                    SET last_activity = CURRENT_TIMESTAMP 
                    WHERE session_id = ? AND is_active = TRUE
                ''', (session_id,))
                conn.commit()
                return True
        except sqlite3.Error as e:
            print(f"❌ Error updating session activity: {e}")
            return False

    def end_live_session(self, session_id: str) -> bool:
        """End a live session when candidate submits exam"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE live_sessions 
                    SET is_active = FALSE 
                    WHERE session_id = ?
                ''', (session_id,))
                conn.commit()
                print(f"✅ Live session ended for session {session_id}")
                return True
        except sqlite3.Error as e:
            print(f"❌ Error ending live session: {e}")
            return False

    def get_live_candidates(self, exam_id: str) -> List[Dict]:
        """Get all currently live candidates for an exam"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT session_id, candidate_name, candidate_id, started_at, last_activity
                    FROM live_sessions 
                    WHERE exam_id = ? AND is_active = TRUE
                    ORDER BY started_at DESC
                ''', (exam_id,))
                
                live_candidates = []
                for row in cursor.fetchall():
                    live_candidates.append({
                        'session_id': row[0],
                        'candidate_name': row[1],
                        'candidate_id': row[2],
                        'started_at': row[3],
                        'last_activity': row[4]
                    })
                
                return live_candidates
        except sqlite3.Error as e:
            print(f"❌ Error getting live candidates: {e}")
            return []

    def cleanup_stale_sessions(self, timeout_minutes: int = 30) -> int:
        """Remove sessions that have been inactive for too long"""
        try:
            # Validate timeout_minutes is a positive integer to prevent any injection
            timeout_minutes = max(1, int(timeout_minutes))
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Use parameterized query with string concatenation done safely
                # SQLite doesn't support parameters in datetime arithmetic, so we build the interval string safely
                interval = f'+{timeout_minutes} minutes'
                cursor.execute('''
                    UPDATE live_sessions
                    SET is_active = FALSE
                    WHERE is_active = TRUE
                    AND datetime(last_activity, ?) < datetime('now')
                ''', (interval,))
                
                cleaned_count = cursor.rowcount
                conn.commit()
                
                if cleaned_count > 0:
                    print(f"🧹 Cleaned up {cleaned_count} stale sessions")
                
                return cleaned_count
        except sqlite3.Error as e:
            print(f"❌ Error cleaning up stale sessions: {e}")
            return 0

    # Persistent Exam Session Management

    def has_candidate_submitted_exam(self, exam_id: str, candidate_id: str) -> bool:
        """Check if a candidate has already submitted an exam.

        Returns True if the candidate has already submitted this exam.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Check both exam_results (completed submissions) and exam_sessions (submitted but maybe pending evaluation)
                cursor.execute('''
                    SELECT 1 FROM exam_results
                    WHERE exam_id = ? AND candidate_id = ?
                    LIMIT 1
                ''', (exam_id, candidate_id))
                if cursor.fetchone():
                    return True

                # Also check if there's an active/submitted session
                cursor.execute('''
                    SELECT 1 FROM exam_sessions
                    WHERE exam_id = ? AND candidate_id = ? AND is_submitted = TRUE
                    LIMIT 1
                ''', (exam_id, candidate_id))
                if cursor.fetchone():
                    return True

                return False
        except sqlite3.Error as e:
            print(f"❌ Error checking if candidate submitted exam: {e}")
            # Return False on error to allow the candidate to proceed (fail-open for usability)
            return False

    def has_candidate_active_session(self, exam_id: str, candidate_id: str) -> Optional[str]:
        """Check if a candidate has an active (non-submitted) session for an exam.

        Returns the session_id if an active session exists, None otherwise.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT session_id FROM exam_sessions
                    WHERE exam_id = ? AND candidate_id = ? AND is_submitted = FALSE
                    ORDER BY started_at DESC
                    LIMIT 1
                ''', (exam_id, candidate_id))
                row = cursor.fetchone()
                return row[0] if row else None
        except sqlite3.Error as e:
            print(f"❌ Error checking active session: {e}")
            return None

    def create_exam_session(self, session_id: str, exam_id: str, candidate_name: str,
                           candidate_id: str, time_limit: int) -> bool:
        """Create a persistent exam session in the database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO exam_sessions (session_id, exam_id, candidate_name, candidate_id, time_limit, answers_data)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (session_id, exam_id, candidate_name, candidate_id, time_limit, json.dumps({})))
                conn.commit()
                print(f"✅ Persistent exam session created: {session_id} for {candidate_name}")
                return True
        except sqlite3.Error as e:
            print(f"❌ Error creating exam session: {e}")
            return False

    def get_exam_session(self, session_id: str) -> Optional[Dict]:
        """Get an exam session by its ID"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT session_id, exam_id, candidate_name, candidate_id, started_at,
                           time_limit, answers_data, is_submitted, submitted_at
                    FROM exam_sessions
                    WHERE session_id = ?
                ''', (session_id,))
                row = cursor.fetchone()
                if row:
                    return {
                        'session_id': row[0],
                        'exam_id': row[1],
                        'candidate_name': row[2],
                        'candidate_id': row[3],
                        'started_at': row[4],
                        'time_limit': row[5],
                        'answers': json.loads(row[6]) if row[6] else {},
                        'is_submitted': bool(row[7]),
                        'submitted_at': row[8]
                    }
                return None
        except sqlite3.Error as e:
            print(f"❌ Error getting exam session: {e}")
            return None

    def update_exam_session_answers(self, session_id: str, answers: Dict) -> bool:
        """Update the answers data for an exam session"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE exam_sessions
                    SET answers_data = ?
                    WHERE session_id = ? AND is_submitted = FALSE
                ''', (json.dumps(answers), session_id))
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            print(f"❌ Error updating exam session answers: {e}")
            return False

    def mark_exam_session_submitted(self, session_id: str) -> bool:
        """Mark an exam session as submitted"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE exam_sessions
                    SET is_submitted = TRUE, submitted_at = CURRENT_TIMESTAMP
                    WHERE session_id = ?
                ''', (session_id,))
                conn.commit()
                print(f"✅ Exam session marked as submitted: {session_id}")
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            print(f"❌ Error marking session as submitted: {e}")
            return False

    def get_all_active_exam_sessions(self) -> List[Dict]:
        """Get all active (non-submitted) exam sessions for recovery"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT session_id, exam_id, candidate_name, candidate_id, started_at,
                           time_limit, answers_data
                    FROM exam_sessions
                    WHERE is_submitted = FALSE
                ''')
                sessions = []
                for row in cursor.fetchall():
                    sessions.append({
                        'session_id': row[0],
                        'exam_id': row[1],
                        'candidate_name': row[2],
                        'candidate_id': row[3],
                        'started_at': row[4],
                        'time_limit': row[5],
                        'answers': json.loads(row[6]) if row[6] else {}
                    })
                return sessions
        except sqlite3.Error as e:
            print(f"❌ Error getting active exam sessions: {e}")
            return []

    def delete_exam_session(self, session_id: str) -> bool:
        """Delete an exam session (after successful submission or cleanup)"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM exam_sessions WHERE session_id = ?', (session_id,))
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            print(f"❌ Error deleting exam session: {e}")
            return False

    def cleanup_expired_exam_sessions(self, extra_minutes: int = 60) -> int:
        """Clean up exam sessions that have exceeded their time limit plus buffer"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Delete sessions where started_at + time_limit + extra_minutes has passed
                cursor.execute('''
                    DELETE FROM exam_sessions
                    WHERE is_submitted = FALSE
                    AND datetime(started_at, '+' || (time_limit + ?) || ' minutes') < datetime('now')
                ''', (extra_minutes,))
                cleaned_count = cursor.rowcount
                conn.commit()
                if cleaned_count > 0:
                    print(f"🧹 Cleaned up {cleaned_count} expired exam sessions")
                return cleaned_count
        except sqlite3.Error as e:
            print(f"❌ Error cleaning up expired exam sessions: {e}")
            return 0

    # Exam Management

    def create_exam(self, title: str, department: str, position: str, description: str,
                   time_limit: int, instructions: str, question_structure: Dict,
                   sections_structure: Dict = None, show_feedback: bool = True,
                   negative_marking_config: Dict = None, exam_language: str = 'english',
                   multi_select_scoring_mode: str = 'partial') -> str:
        """Create a new exam

        Args:
            multi_select_scoring_mode: 'partial' for partial scoring, 'strict' for exact match only
        """
        try:
            exam_id = str(uuid.uuid4())
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO exams (id, title, department, position, description,
                                     time_limit, instructions, question_structure, sections_structure,
                                     show_feedback, negative_marking_config, exam_language, multi_select_scoring_mode)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (exam_id, title, department, position, description,
                     time_limit, instructions, json.dumps(question_structure),
                     json.dumps(sections_structure), show_feedback,
                     json.dumps(negative_marking_config or {}), exam_language, multi_select_scoring_mode))
                conn.commit()
                print(f"✅ Exam created with ID: {exam_id}")
                return exam_id
        except sqlite3.Error as e:
            print(f"❌ Error creating exam: {e}")
            return None

    def get_exam_by_id(self, exam_id: str) -> Optional[Dict]:
        """Get exam by ID"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, title, department, position, description, time_limit,
                           instructions, question_structure, sections_structure, exam_link,
                           is_finalized, is_active, show_feedback, negative_marking_config,
                           exam_language, created_at, multi_select_scoring_mode
                    FROM exams WHERE id = ?
                ''', (exam_id,))

                row = cursor.fetchone()
                if row:
                    return {
                        'id': row[0], 'title': row[1], 'department': row[2], 'position': row[3],
                        'description': row[4], 'time_limit': row[5], 'instructions': row[6],
                        'question_structure': json.loads(row[7]) if row[7] else {},
                        'sections_structure': json.loads(row[8]) if row[8] else {},
                        'exam_link': row[9], 'is_finalized': bool(row[10]), 'is_active': bool(row[11]),
                        'show_feedback': bool(row[12]) if row[12] is not None else True,
                        'negative_marking_config': json.loads(row[13]) if row[13] else {},
                        'exam_language': row[14] or 'english', 'created_at': row[15],
                        'multi_select_scoring_mode': row[16] or 'partial'
                    }
                return None
        except sqlite3.Error as e:
            print(f"❌ Error getting exam: {e}")
            return None

    def get_exam_by_link(self, exam_link: str) -> Optional[Dict]:
        """Get exam by link"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, title, department, position, description, time_limit,
                           instructions, question_structure, sections_structure, exam_link,
                           is_finalized, is_active, show_feedback, negative_marking_config,
                           exam_language, multi_select_scoring_mode
                    FROM exams WHERE exam_link = ?
                ''', (exam_link,))

                row = cursor.fetchone()
                if not row:
                    return None

                exam_data = {
                    'id': row[0], 'title': row[1], 'department': row[2], 'position': row[3],
                    'description': row[4], 'time_limit': row[5], 'instructions': row[6],
                    'question_structure': json.loads(row[7]) if row[7] else {},
                    'sections_structure': json.loads(row[8]) if row[8] else {},
                    'exam_link': row[9], 'is_finalized': row[10], 'is_active': row[11],
                    'show_feedback': bool(row[12]) if row[12] is not None else True,
                    'negative_marking_config': json.loads(row[13]) if row[13] else {},
                    'exam_language': row[14] or 'english',
                    'multi_select_scoring_mode': row[15] or 'partial'
                }
                
                # Check if exam is accessible
                if not exam_data['is_finalized'] or not exam_data['is_active']:
                    return None
                
                return exam_data
                
        except sqlite3.Error as e:
            print(f"❌ Error getting exam by link: {e}")
            return None

    def finalize_exam(self, exam_id: str) -> str:
        """Finalize exam and generate unique link"""
        try:
            exam_link = secrets.token_urlsafe(16)
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE exams SET exam_link = ?, is_finalized = TRUE, is_active = TRUE, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (exam_link, exam_id))
                conn.commit()
                print(f"✅ Exam finalized and activated with link: {exam_link}")
                return exam_link
        except sqlite3.Error as e:
            print(f"❌ Error finalizing exam: {e}")
            return None

    def update_exam_settings(self, exam_id: str, title: str = None, description: str = None,
                           time_limit: int = None, instructions: str = None,
                           show_feedback: bool = None, negative_marking_config: Dict = None,
                           exam_language: str = None, multi_select_scoring_mode: str = None) -> bool:
        """Update exam settings"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                update_fields = []
                update_values = []

                if title is not None:
                    update_fields.append("title = ?")
                    update_values.append(title)

                if description is not None:
                    update_fields.append("description = ?")
                    update_values.append(description)

                if time_limit is not None:
                    update_fields.append("time_limit = ?")
                    update_values.append(time_limit)

                if instructions is not None:
                    update_fields.append("instructions = ?")
                    update_values.append(instructions)

                if show_feedback is not None:
                    update_fields.append("show_feedback = ?")
                    update_values.append(show_feedback)

                if negative_marking_config is not None:
                    update_fields.append("negative_marking_config = ?")
                    update_values.append(json.dumps(negative_marking_config))

                if exam_language is not None:
                    update_fields.append("exam_language = ?")
                    update_values.append(exam_language)

                if multi_select_scoring_mode is not None:
                    update_fields.append("multi_select_scoring_mode = ?")
                    update_values.append(multi_select_scoring_mode)

                update_fields.append("updated_at = CURRENT_TIMESTAMP")
                update_values.append(exam_id)
                
                if len(update_fields) > 1:  # More than just timestamp
                    query = f"UPDATE exams SET {', '.join(update_fields)} WHERE id = ?"
                    cursor.execute(query, update_values)
                    conn.commit()
                
                return True
                
        except sqlite3.Error as e:
            print(f"❌ Error updating exam settings: {e}")
            return False

    def toggle_exam_status(self, exam_id: str, is_active: bool) -> bool:
        """Toggle exam active/inactive status"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE exams SET is_active = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (is_active, exam_id))
                conn.commit()
                return True
        except sqlite3.Error as e:
            print(f"❌ Error toggling exam status: {e}")
            return False

    def get_all_exams(self) -> List[Dict]:
        """Get all exams"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, title, department, position, description, time_limit, 
                           exam_link, is_finalized, is_active, show_feedback, 
                           negative_marking_config, exam_language, created_at
                    FROM exams ORDER BY created_at DESC
                ''')
                
                exams = []
                for row in cursor.fetchall():
                    exams.append({
                        'id': row[0], 'title': row[1], 'department': row[2], 'position': row[3],
                        'description': row[4], 'time_limit': row[5], 'exam_link': row[6],
                        'is_finalized': bool(row[7]), 'is_active': bool(row[8]),
                        'show_feedback': bool(row[9]) if row[9] is not None else True,
                        'negative_marking_config': json.loads(row[10]) if row[10] else {},
                        'exam_language': row[11] or 'english', 'created_at': row[12]
                    })
                return exams
        except sqlite3.Error as e:
            print(f"❌ Error getting all exams: {e}")
            return []

    def delete_exam(self, exam_id: str) -> bool:
        """Delete an exam and all related data"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Delete in order due to foreign key constraints
                cursor.execute('DELETE FROM live_sessions WHERE exam_id = ?', (exam_id,))
                
                # Delete question images first
                cursor.execute('''
                    DELETE FROM question_images 
                    WHERE question_id IN (SELECT id FROM questions WHERE exam_id = ?)
                ''', (exam_id,))
                
                cursor.execute('DELETE FROM questions WHERE exam_id = ?', (exam_id,))
                
                # Delete detailed evaluations
                cursor.execute('''
                    DELETE FROM detailed_evaluations 
                    WHERE answer_id IN (
                        SELECT ca.id FROM candidate_answers ca
                        JOIN exam_results er ON ca.result_id = er.id
                        WHERE er.exam_id = ?
                    )
                ''', (exam_id,))
                
                # Delete candidate answers
                cursor.execute('''
                    DELETE FROM candidate_answers 
                    WHERE result_id IN (
                        SELECT id FROM exam_results WHERE exam_id = ?
                    )
                ''', (exam_id,))
                
                # Delete exam results
                cursor.execute('DELETE FROM exam_results WHERE exam_id = ?', (exam_id,))
                
                # Delete exam
                cursor.execute('DELETE FROM exams WHERE id = ?', (exam_id,))
                
                conn.commit()
                print(f"✅ Exam {exam_id} deleted successfully")
                return True
        except sqlite3.Error as e:
            print(f"❌ Error deleting exam: {e}")
            return False

    # Question Management

    def save_exam_question(self, exam_id: str, question_data: Dict, section_type: str = 'technical') -> str:
        """Save a question for an exam with multi-select MCQ support"""
        try:
            question_id = str(uuid.uuid4())
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Get current max order for this exam and section
                cursor.execute('SELECT MAX(question_order) FROM questions WHERE exam_id = ? AND section_type = ?',
                             (exam_id, section_type))
                max_order = cursor.fetchone()[0] or 0

                # Handle multi-select MCQ
                is_multi_select = question_data.get('is_multi_select', False)
                correct_answers = question_data.get('correct_answers')
                correct_answers_json = None
                correct_answer_single = question_data.get('correct_answer')

                if is_multi_select and correct_answers:
                    correct_answers_json = json.dumps(correct_answers)
                    correct_answer_single = correct_answers[0] if correct_answers else None

                cursor.execute('''
                    INSERT INTO questions (id, exam_id, section_type, question_type, question_text,
                                         options, correct_answer, expected_answer,
                                         evaluation_criteria, marks, question_order, explanation,
                                         image_url, image_caption, is_multi_select, correct_answers)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    question_id, exam_id, section_type, question_data['type'], question_data['question'],
                    json.dumps(question_data.get('options', [])) if question_data.get('options') else None,
                    correct_answer_single,
                    question_data.get('expected_answer'),
                    question_data.get('evaluation_criteria'),
                    question_data['marks'],
                    max_order + 1,
                    question_data.get('explanation'),
                    question_data.get('image_url'),
                    question_data.get('image_caption'),
                    is_multi_select,
                    correct_answers_json
                ))
                conn.commit()
                return question_id
        except sqlite3.Error as e:
            print(f"❌ Error saving question: {e}")
            return None

    def get_exam_questions(self, exam_id: str) -> List[Dict]:
        """Get all questions for an exam with images"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, section_type, question_type, question_text, options, correct_answer,
                           expected_answer, evaluation_criteria, marks, explanation, image_url, image_caption,
                           is_multi_select, correct_answers
                    FROM questions WHERE exam_id = ? ORDER BY section_type, question_order
                ''', (exam_id,))

                questions = []
                for row in cursor.fetchall():
                    question = {
                        'id': row[0], 'section_type': row[1], 'type': row[2],
                        'question': row[3], 'marks': row[8], 'explanation': row[9],
                        'image_url': row[10], 'image_caption': row[11],
                        'is_multi_select': bool(row[12]) if row[12] is not None else False
                    }

                    # Get additional images from question_images table
                    question['images'] = self.get_question_images(row[0])

                    if row[4]:  # MCQ
                        question['options'] = json.loads(row[4])
                        # For multi-select MCQs, use correct_answers (JSON array)
                        if question['is_multi_select']:
                            if row[13]:
                                question['correct_answers'] = json.loads(row[13])
                            else:
                                # Fallback: use correct_answer as single item list
                                question['correct_answers'] = [row[5]] if row[5] is not None else []
                            question['correct_answer'] = question['correct_answers']  # For compatibility
                        else:
                            question['correct_answer'] = row[5]
                            question['correct_answers'] = [row[5]] if row[5] is not None else []
                    else:  # Short/Essay
                        question['expected_answer'] = row[6]
                        question['evaluation_criteria'] = row[7]

                    questions.append(question)

                return questions
        except sqlite3.Error as e:
            print(f"❌ Error getting exam questions: {e}")
            return []

    def get_exam_questions_by_section(self, exam_id: str) -> Dict[str, List[Dict]]:
        """Get questions grouped by section type with images"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, section_type, question_type, question_text, options, correct_answer,
                           expected_answer, evaluation_criteria, marks, explanation, image_url, image_caption,
                           is_multi_select, correct_answers
                    FROM questions WHERE exam_id = ? ORDER BY section_type, question_order
                ''', (exam_id,))

                sections = {}
                for row in cursor.fetchall():
                    section_type = row[1]
                    if section_type not in sections:
                        sections[section_type] = []

                    question = {
                        'id': row[0], 'section_type': section_type, 'type': row[2],
                        'question': row[3], 'marks': row[8], 'explanation': row[9],
                        'image_url': row[10], 'image_caption': row[11],
                        'is_multi_select': bool(row[12]) if row[12] is not None else False
                    }

                    # Get additional images
                    question['images'] = self.get_question_images(row[0])

                    if row[4]:  # MCQ
                        question['options'] = json.loads(row[4])
                        # For multi-select MCQs, use correct_answers (JSON array)
                        if question['is_multi_select']:
                            if row[13]:
                                question['correct_answers'] = json.loads(row[13])
                            else:
                                # Fallback: use correct_answer as single item list
                                question['correct_answers'] = [row[5]] if row[5] is not None else []
                            question['correct_answer'] = question['correct_answers']
                        else:
                            question['correct_answer'] = row[5]
                            question['correct_answers'] = [row[5]] if row[5] is not None else []
                    else:  # Short/Essay
                        question['expected_answer'] = row[6]
                        question['evaluation_criteria'] = row[7]

                    sections[section_type].append(question)

                return sections
        except sqlite3.Error as e:
            print(f"❌ Error getting exam questions by section: {e}")
            return {}

    def update_question(self, question_id: str, question_data: Dict) -> bool:
        """Update a question including image information and multi-select support"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Handle multi-select MCQ
                is_multi_select = question_data.get('is_multi_select', False)
                correct_answers = question_data.get('correct_answers')

                # For multi-select, store correct_answers as JSON array
                correct_answers_json = None
                correct_answer_single = question_data.get('correct_answer')

                if is_multi_select and correct_answers:
                    correct_answers_json = json.dumps(correct_answers)
                    # Also set correct_answer to first answer for backwards compatibility
                    correct_answer_single = correct_answers[0] if correct_answers else None

                cursor.execute('''
                    UPDATE questions SET question_text = ?, options = ?, correct_answer = ?,
                                       expected_answer = ?, evaluation_criteria = ?, marks = ?,
                                       explanation = ?, image_url = ?, image_caption = ?,
                                       is_multi_select = ?, correct_answers = ?
                    WHERE id = ?
                ''', (
                    question_data['question'],
                    json.dumps(question_data.get('options', [])) if question_data.get('options') else None,
                    correct_answer_single,
                    question_data.get('expected_answer'),
                    question_data.get('evaluation_criteria'),
                    question_data['marks'],
                    question_data.get('explanation'),
                    question_data.get('image_url'),
                    question_data.get('image_caption'),
                    is_multi_select,
                    correct_answers_json,
                    question_id
                ))
                conn.commit()
                return True
        except sqlite3.Error as e:
            print(f"❌ Error updating question: {e}")
            return False

    def delete_question(self, question_id: str) -> bool:
        """Delete a question and its images"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Delete question images first
                cursor.execute('DELETE FROM question_images WHERE question_id = ?', (question_id,))
                
                # Delete the question
                cursor.execute('DELETE FROM questions WHERE id = ?', (question_id,))
                
                conn.commit()
                return True
        except sqlite3.Error as e:
            print(f"❌ Error deleting question: {e}")
            return False

    # Results Management (keeping existing methods)
    
    def save_exam_result(self, session_id: str, exam_id: str, candidate_name: str, 
                        candidate_id: str, answers: Dict, evaluation: Dict, time_taken: str) -> bool:
        """Save exam result with feedback"""
        try:
            result_id = str(uuid.uuid4())
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Save main result
                cursor.execute('''
                    INSERT INTO exam_results (id, session_id, exam_id, candidate_name, candidate_id,
                                            total_marks, obtained_marks, negative_marks, percentage, performance_level, 
                                            time_taken, has_feedback)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    result_id, session_id, exam_id, candidate_name, candidate_id,
                    evaluation['total_marks'], evaluation['obtained_marks'], evaluation.get('negative_marks', 0),
                    evaluation['percentage'], evaluation['performance_level'], time_taken, True
                ))
                
                # Save individual answers
                for question_result in evaluation['question_results']:
                    answer_id = str(uuid.uuid4())
                    cursor.execute('''
                        INSERT INTO candidate_answers (id, result_id, question_id, candidate_answer,
                                                     marks_obtained, negative_marks_applied, is_correct, feedback, evaluation_details)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        answer_id, result_id, question_result['question_id'],
                        question_result['candidate_answer'], question_result['marks_obtained'],
                        question_result.get('negative_marks_applied', 0),
                        question_result.get('is_correct'), question_result['feedback'],
                        question_result.get('evaluation_details')
                    ))
                    
                    # Save detailed evaluation if available
                    if question_result.get('strengths') or question_result.get('improvements'):
                        cursor.execute('''
                            INSERT INTO detailed_evaluations (id, answer_id, strengths, improvements, overall_feedback)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (
                            str(uuid.uuid4()), answer_id,
                            question_result.get('strengths'),
                            question_result.get('improvements'),
                            evaluation.get('overall_feedback')
                        ))
                
                # End the live session
                self.end_live_session(session_id)
                
                conn.commit()
                print(f"✅ Exam result saved for {candidate_name}")
                return True
        except sqlite3.Error as e:
            print(f"❌ Error saving exam result: {e}")
            return False

    def save_exam_result_no_feedback(self, session_id: str, exam_id: str, candidate_name: str, 
                                    candidate_id: str, answers: Dict, time_taken: str) -> bool:
        """Save exam submission without detailed evaluation"""
        try:
            result_id = str(uuid.uuid4())
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Save basic result without evaluation
                cursor.execute('''
                    INSERT INTO exam_results (id, session_id, exam_id, candidate_name, candidate_id,
                                            total_marks, obtained_marks, negative_marks, percentage, performance_level, 
                                            time_taken, has_feedback)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    result_id, session_id, exam_id, candidate_name, candidate_id,
                    0, 0, 0, 0, "Pending Review", time_taken, False
                ))
                
                # Save answers without evaluation
                for question_id, answer in answers.items():
                    answer_id = str(uuid.uuid4())
                    cursor.execute('''
                        INSERT INTO candidate_answers (id, result_id, question_id, candidate_answer,
                                                     marks_obtained, negative_marks_applied, is_correct, feedback, evaluation_details)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        answer_id, result_id, question_id, answer, 0, 0, None, 
                        "Answer submitted - awaiting review", "No evaluation provided"
                    ))
                
                # End the live session
                self.end_live_session(session_id)
                
                conn.commit()
                print(f"✅ Exam submission saved for {candidate_name} (no feedback mode)")
                return True
        except sqlite3.Error as e:
            print(f"❌ Error saving exam result without feedback: {e}")
            return False

    def get_exam_results(self, exam_id: str) -> List[Dict]:
        """Get all results for a specific exam"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, candidate_name, candidate_id, total_marks, obtained_marks, negative_marks,
                           percentage, performance_level, time_taken, submitted_at, has_feedback
                    FROM exam_results WHERE exam_id = ?
                    ORDER BY submitted_at DESC
                ''', (exam_id,))
                
                results = []
                for row in cursor.fetchall():
                    results.append({
                        'id': row[0], 'candidate_name': row[1], 'candidate_id': row[2],
                        'total_marks': row[3], 'obtained_marks': row[4], 'negative_marks': row[5] or 0,
                        'percentage': row[6], 'performance_level': row[7], 'time_taken': row[8],
                        'submitted_at': row[9], 'has_feedback': bool(row[10])
                    })
                return results
        except sqlite3.Error as e:
            print(f"❌ Error getting exam results: {e}")
            return []

    def get_recent_exam_results(self, limit: int = 50) -> List[Dict]:
        """Get recent exam results across all exams"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT er.id, er.candidate_name, er.candidate_id, er.total_marks,
                           er.obtained_marks, er.negative_marks, er.percentage, er.performance_level,
                           er.time_taken, er.submitted_at, er.has_feedback, e.title, e.department, e.position
                    FROM exam_results er
                    JOIN exams e ON er.exam_id = e.id
                    ORDER BY er.submitted_at DESC
                    LIMIT ?
                ''', (limit,))
                
                results = []
                for row in cursor.fetchall():
                    results.append({
                        'id': row[0], 'candidate_name': row[1], 'candidate_id': row[2],
                        'total_marks': row[3], 'obtained_marks': row[4], 'negative_marks': row[5] or 0,
                        'percentage': row[6], 'performance_level': row[7], 'time_taken': row[8],
                        'submitted_at': row[9], 'has_feedback': bool(row[10]),
                        'exam_title': row[11], 'department': row[12], 'position': row[13]
                    })
                return results
        except sqlite3.Error as e:
            print(f"❌ Error getting recent results: {e}")
            return []

    def get_exam_results_count(self, exam_id: str) -> int:
        """Get the count of results for a specific exam"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM exam_results WHERE exam_id = ?', (exam_id,))
                count = cursor.fetchone()[0]
                return count
        except sqlite3.Error as e:
            print(f"❌ Error getting exam results count: {e}")
            return 0

    def get_result_details(self, result_id: str) -> Optional[Dict]:
        """Get detailed results for a specific result"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Get main result info
                cursor.execute('''
                    SELECT er.candidate_name, er.candidate_id, er.total_marks, er.obtained_marks,
                           er.negative_marks, er.percentage, er.performance_level, er.time_taken, er.submitted_at,
                           er.has_feedback, e.title as exam_title, e.department, e.position
                    FROM exam_results er
                    JOIN exams e ON er.exam_id = e.id
                    WHERE er.id = ?
                ''', (result_id,))
                
                result_row = cursor.fetchone()
                if not result_row:
                    return None
                
                # Get detailed answers
                cursor.execute('''
                    SELECT ca.question_id, ca.candidate_answer, ca.marks_obtained, ca.negative_marks_applied, ca.is_correct,
                           ca.feedback, ca.evaluation_details, q.question_text, q.question_type,
                           q.marks, q.options, q.correct_answer, q.section_type, q.image_url, q.image_caption,
                           q.is_multi_select, q.correct_answers
                    FROM candidate_answers ca
                    JOIN questions q ON ca.question_id = q.id
                    WHERE ca.result_id = ?
                    ORDER BY q.section_type, q.question_order
                ''', (result_id,))

                questions = []
                letters = ['A', 'B', 'C', 'D', 'E', 'F']
                for row in cursor.fetchall():
                    question = {
                        'question_id': row[0], 'candidate_answer': row[1], 'marks_obtained': row[2],
                        'negative_marks_applied': row[3] or 0, 'is_correct': row[4],
                        'feedback': row[5], 'evaluation_details': row[6], 'question_text': row[7],
                        'question_type': row[8], 'marks_total': row[9], 'section_type': row[12],
                        'image_url': row[13], 'image_caption': row[14],
                        'is_multi_select': bool(row[15]) if row[15] is not None else False
                    }

                    # Get question images
                    question['images'] = self.get_question_images(row[0])

                    # Add MCQ specific data
                    if row[8] == 'mcq' and row[10]:
                        options = json.loads(row[10])
                        question['options'] = options
                        is_multi_select = question['is_multi_select']

                        if is_multi_select:
                            # Multi-select MCQ
                            correct_answers = []
                            if row[16]:
                                try:
                                    correct_answers = json.loads(row[16])
                                except:
                                    correct_answers = [row[11]] if row[11] is not None else []
                            question['correct_answers'] = correct_answers

                            # Format correct answers with letters
                            correct_texts = []
                            for idx in correct_answers:
                                if 0 <= idx < len(options):
                                    correct_texts.append(f"{letters[idx]}) {options[idx]}")
                            question['correct_option'] = '; '.join(correct_texts) if correct_texts else 'N/A'

                            # Parse candidate's multi-select answer (comma-separated)
                            candidate_answer = row[1]
                            if candidate_answer:
                                selected_indices = []
                                if ',' in str(candidate_answer):
                                    for a in str(candidate_answer).split(','):
                                        if a.strip().isdigit():
                                            selected_indices.append(int(a.strip()))
                                elif str(candidate_answer).isdigit():
                                    selected_indices.append(int(candidate_answer))

                                selected_texts = []
                                for idx in selected_indices:
                                    if 0 <= idx < len(options):
                                        selected_texts.append(f"{letters[idx]}) {options[idx]}")
                                question['selected_option'] = '; '.join(selected_texts) if selected_texts else 'No answer'
                            else:
                                question['selected_option'] = 'No answer'
                        else:
                            # Single-select MCQ
                            question['correct_answer'] = row[11]

                            if row[1] is not None and str(row[1]).isdigit():
                                selected_idx = int(row[1])
                                if 0 <= selected_idx < len(options):
                                    question['selected_option'] = f"{letters[selected_idx]}) {options[selected_idx]}"
                            else:
                                question['selected_option'] = 'No answer'

                            if row[11] is not None and 0 <= row[11] < len(options):
                                question['correct_option'] = f"{letters[row[11]]}) {options[row[11]]}"

                    questions.append(question)
                
                return {
                    'result_id': result_id, 'candidate_name': result_row[0], 'candidate_id': result_row[1],
                    'total_marks': result_row[2], 'obtained_marks': result_row[3],
                    'negative_marks': result_row[4] or 0, 'percentage': result_row[5],
                    'performance_level': result_row[6], 'time_taken': result_row[7],
                    'submitted_at': result_row[8], 'has_feedback': bool(result_row[9]),
                    'exam_title': result_row[10], 'department': result_row[11],
                    'position': result_row[12], 'questions': questions
                }
                
        except sqlite3.Error as e:
            print(f"❌ Error getting result details: {e}")
            return None

    def get_result_summary(self, result_id: str) -> Optional[Dict]:
        """Get basic result information for editing"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT er.candidate_name, er.candidate_id, er.time_taken, er.total_marks,
                        er.obtained_marks, er.negative_marks, er.percentage, er.performance_level, 
                        er.has_feedback, e.title
                    FROM exam_results er
                    JOIN exams e ON er.exam_id = e.id
                    WHERE er.id = ?
                ''', (result_id,))
                
                row = cursor.fetchone()
                if not row:
                    return None
                
                return {
                    'result_id': result_id, 'candidate_name': row[0], 'candidate_id': row[1],
                    'time_taken': row[2], 'total_marks': row[3], 'obtained_marks': row[4],
                    'negative_marks': row[5] or 0, 'percentage': row[6],
                    'performance_level': row[7], 'has_feedback': bool(row[8]),
                    'exam_title': row[9]
                }
        except sqlite3.Error as e:
            print(f"❌ Error getting result summary: {e}")
            return None

    def update_result_info(self, result_id: str, candidate_name: str, candidate_id: str, time_taken: str) -> bool:
        """Update basic result information"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE exam_results 
                    SET candidate_name = ?, candidate_id = ?, time_taken = ?
                    WHERE id = ?
                ''', (candidate_name, candidate_id, time_taken, result_id))
                conn.commit()
                return True
        except sqlite3.Error as e:
            print(f"❌ Error updating result info: {e}")
            return False

    def update_question_marks(self, question_id: str, result_id: str, new_marks: float) -> bool:
        """Update marks for a specific question and recalculate totals"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Get question and exam details
                cursor.execute('''
                    SELECT q.marks, q.question_type, q.section_type, ca.candidate_answer, e.negative_marking_config
                    FROM candidate_answers ca
                    JOIN questions q ON ca.question_id = q.id
                    JOIN exam_results er ON ca.result_id = er.id
                    JOIN exams e ON er.exam_id = e.id
                    WHERE ca.question_id = ? AND ca.result_id = ?
                ''', (question_id, result_id))
                
                row = cursor.fetchone()
                if not row:
                    return False
                
                question_marks, question_type, section_type, candidate_answer, negative_config_json = row
                negative_config = json.loads(negative_config_json) if negative_config_json else {}
                
                # Calculate negative marks for MCQ
                new_negative_marks = 0
                is_correct = new_marks >= question_marks
                
                if question_type == 'mcq' and not is_correct and section_type in negative_config:
                    section_config = negative_config[section_type]
                    if section_config.get('enabled', False):
                        new_negative_marks = section_config.get('mcq_negative_marks', 0)
                
                # Update candidate answer
                cursor.execute('''
                    UPDATE candidate_answers 
                    SET marks_obtained = ?, negative_marks_applied = ?, is_correct = ?
                    WHERE question_id = ? AND result_id = ?
                ''', (new_marks, new_negative_marks, is_correct, question_id, result_id))
                
                # Recalculate totals
                cursor.execute('''
                    SELECT SUM(marks_obtained), SUM(negative_marks_applied) FROM candidate_answers 
                    WHERE result_id = ?
                ''', (result_id,))
                result = cursor.fetchone()
                total_obtained = result[0] or 0
                total_negative = result[1] or 0
                
                cursor.execute('''SELECT total_marks FROM exam_results WHERE id = ?''', (result_id,))
                total_marks = cursor.fetchone()[0] or 1
                
                final_score = total_obtained - total_negative
                new_percentage = (final_score / total_marks) * 100 if total_marks > 0 else 0
                
                # Determine performance level
                if new_percentage >= 85:
                    performance_level = "Excellent"
                elif new_percentage >= 70:
                    performance_level = "Good"
                elif new_percentage >= 50:
                    performance_level = "Average"
                else:
                    performance_level = "Poor"
                
                # Update exam results
                cursor.execute('''
                    UPDATE exam_results 
                    SET obtained_marks = ?, negative_marks = ?, percentage = ?, performance_level = ?
                    WHERE id = ?
                ''', (final_score, total_negative, new_percentage, performance_level, result_id))
                
                conn.commit()
                return True
        except Exception as e:
            print(f"❌ Error updating question marks: {e}")
            return False

    def delete_result(self, result_id: str) -> bool:
        """Delete a candidate's exam result and all associated data"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Get candidate info for logging
                cursor.execute('''
                    SELECT candidate_name, candidate_id FROM exam_results WHERE id = ?
                ''', (result_id,))
                result_info = cursor.fetchone()
                
                if not result_info:
                    return False
                
                candidate_name, candidate_id = result_info
                print(f"🗑️ Deleting exam result for {candidate_name} ({candidate_id})")
                
                # Delete in order due to foreign key constraints
                cursor.execute('''
                    DELETE FROM detailed_evaluations 
                    WHERE answer_id IN (
                        SELECT id FROM candidate_answers WHERE result_id = ?
                    )
                ''', (result_id,))
                
                cursor.execute('DELETE FROM candidate_answers WHERE result_id = ?', (result_id,))
                cursor.execute('DELETE FROM exam_results WHERE id = ?', (result_id,))
                
                conn.commit()
                print(f"✅ Successfully deleted exam result for {candidate_name}")
                return True
                    
        except sqlite3.Error as e:
            print(f"❌ Error deleting exam result: {e}")
            return False

    def get_database_info(self) -> Dict:
        """Get general database information"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('SELECT COUNT(*) FROM exams')
                total_exams = cursor.fetchone()[0]
                
                cursor.execute('SELECT COUNT(*) FROM exam_results')
                total_results = cursor.fetchone()[0]
                
                cursor.execute('SELECT COUNT(*) FROM exams WHERE is_finalized = TRUE')
                finalized_exams = cursor.fetchone()[0]
                
                db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
                
                return {
                    'total_exams': total_exams,
                    'finalized_exams': finalized_exams,
                    'total_results': total_results,
                    'database_size_bytes': db_size,
                    'database_size_mb': round(db_size / (1024 * 1024), 2),
                    'database_path': self.db_path
                }
        except sqlite3.Error as e:
            print(f"❌ Error getting database info: {e}")
            return {}


    def lookup_candidate_result(self, exam_link: str, candidate_id: str) -> Optional[Dict]:
        """
        Look up a candidate's result using exam link and candidate ID.
        Used for candidates to check their results later.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # First, find the exam by its link
                cursor.execute('''
                    SELECT id, title, show_feedback FROM exams WHERE exam_link = ?
                ''', (exam_link,))
                exam_row = cursor.fetchone()

                if not exam_row:
                    return None

                exam_id = exam_row[0]
                exam_title = exam_row[1]
                show_feedback = bool(exam_row[2])

                # Find the candidate's result for this exam
                cursor.execute('''
                    SELECT id, candidate_name, evaluation_status, total_marks, obtained_marks,
                           percentage, submitted_at, time_taken
                    FROM exam_results
                    WHERE exam_id = ? AND candidate_id = ?
                    ORDER BY submitted_at DESC
                    LIMIT 1
                ''', (exam_id, candidate_id))

                result_row = cursor.fetchone()

                if not result_row:
                    return None

                return {
                    'result_id': result_row[0],
                    'candidate_name': result_row[1],
                    'candidate_id': candidate_id,
                    'exam_title': exam_title,
                    'evaluation_status': result_row[2],
                    'total_marks': result_row[3],
                    'obtained_marks': result_row[4],
                    'percentage': result_row[5],
                    'submitted_at': result_row[6],
                    'time_taken': result_row[7],
                    'show_feedback': show_feedback
                }

        except sqlite3.Error as e:
            print(f"❌ Error looking up candidate result: {e}")
            return None

    # Queue System Methods

    def save_exam_submission_for_queue(self, session_id: str, exam_id: str, candidate_name: str,
                                       candidate_id: str, answers: Dict, time_taken: str,
                                       questions: List[Dict]) -> Optional[str]:
        """
        Save exam submission immediately without evaluation (for queue system).
        Returns the result_id for tracking.
        """
        try:
            result_id = str(uuid.uuid4())
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Calculate total marks from questions
                total_marks = sum(q.get('marks', 0) for q in questions)

                # Save main result with pending status
                cursor.execute('''
                    INSERT INTO exam_results (id, session_id, exam_id, candidate_name, candidate_id,
                                            total_marks, obtained_marks, negative_marks, percentage,
                                            performance_level, time_taken, has_feedback, evaluation_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    result_id, session_id, exam_id, candidate_name, candidate_id,
                    total_marks, 0, 0, 0, "Pending Evaluation", time_taken, True, "pending"
                ))

                # Save candidate answers (without evaluation)
                for question in questions:
                    question_id = str(question['id'])
                    answer = answers.get(question_id, "")
                    answer_id = str(uuid.uuid4())

                    cursor.execute('''
                        INSERT INTO candidate_answers (id, result_id, question_id, candidate_answer,
                                                     marks_obtained, negative_marks_applied, is_correct,
                                                     feedback, evaluation_details)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        answer_id, result_id, question_id, answer, 0, 0, None,
                        "Awaiting evaluation", "Pending"
                    ))

                conn.commit()
                print(f"✅ Exam submission saved for queue: {candidate_name} (Result ID: {result_id[:8]}...)")
                return result_id

        except sqlite3.Error as e:
            print(f"❌ Error saving exam submission for queue: {e}")
            return None

    def update_exam_result_with_evaluation(self, result_id: str, evaluation: Dict) -> bool:
        """
        Update an exam result with evaluation data (called by queue worker).
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Update main result
                cursor.execute('''
                    UPDATE exam_results
                    SET total_marks = ?, obtained_marks = ?, negative_marks = ?,
                        percentage = ?, performance_level = ?, has_feedback = ?,
                        evaluation_status = ?, evaluated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (
                    evaluation['total_marks'],
                    evaluation['obtained_marks'],
                    evaluation.get('negative_marks', 0),
                    evaluation['percentage'],
                    evaluation['performance_level'],
                    True,
                    "completed",
                    result_id
                ))

                # Update individual question results
                for question_result in evaluation.get('question_results', []):
                    cursor.execute('''
                        UPDATE candidate_answers
                        SET marks_obtained = ?, negative_marks_applied = ?, is_correct = ?,
                            feedback = ?, evaluation_details = ?
                        WHERE result_id = ? AND question_id = ?
                    ''', (
                        question_result['marks_obtained'],
                        question_result.get('negative_marks_applied', 0),
                        question_result.get('is_correct'),
                        question_result.get('feedback', ''),
                        json.dumps({
                            'strengths': question_result.get('strengths', ''),
                            'improvements': question_result.get('improvements', ''),
                            'selected_option': question_result.get('selected_option', '')
                        }),
                        result_id,
                        question_result['question_id']
                    ))

                    # Save detailed evaluation if available
                    if question_result.get('strengths') or question_result.get('improvements'):
                        # Get the answer_id first
                        cursor.execute('''
                            SELECT id FROM candidate_answers
                            WHERE result_id = ? AND question_id = ?
                        ''', (result_id, question_result['question_id']))
                        answer_row = cursor.fetchone()

                        if answer_row:
                            answer_id = answer_row[0]
                            # Check if detailed evaluation already exists
                            cursor.execute('''
                                SELECT id FROM detailed_evaluations WHERE answer_id = ?
                            ''', (answer_id,))

                            if cursor.fetchone():
                                # Update existing
                                cursor.execute('''
                                    UPDATE detailed_evaluations
                                    SET strengths = ?, improvements = ?, overall_feedback = ?
                                    WHERE answer_id = ?
                                ''', (
                                    question_result.get('strengths', ''),
                                    question_result.get('improvements', ''),
                                    evaluation.get('overall_feedback', ''),
                                    answer_id
                                ))
                            else:
                                # Insert new
                                cursor.execute('''
                                    INSERT INTO detailed_evaluations (id, answer_id, strengths, improvements, overall_feedback)
                                    VALUES (?, ?, ?, ?, ?)
                                ''', (
                                    str(uuid.uuid4()),
                                    answer_id,
                                    question_result.get('strengths', ''),
                                    question_result.get('improvements', ''),
                                    evaluation.get('overall_feedback', '')
                                ))

                conn.commit()
                print(f"✅ Exam result updated with evaluation: {result_id[:8]}...")
                return True

        except sqlite3.Error as e:
            print(f"❌ Error updating exam result with evaluation: {e}")
            return False

    def mark_result_as_failed_evaluation(self, result_id: str, error_message: str) -> bool:
        """
        Mark a result as failed evaluation (for manual review).
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE exam_results
                    SET evaluation_status = ?, evaluation_error = ?,
                        performance_level = ?, evaluated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', ("failed", error_message, "Pending Manual Review", result_id))

                # Update all answers to indicate manual review needed
                cursor.execute('''
                    UPDATE candidate_answers
                    SET feedback = ?, evaluation_details = ?
                    WHERE result_id = ?
                ''', (
                    "Automatic evaluation failed. Manual review required.",
                    "Pending manual review",
                    result_id
                ))

                conn.commit()
                print(f"⚠️ Result marked as failed evaluation: {result_id[:8]}...")
                return True

        except sqlite3.Error as e:
            print(f"❌ Error marking result as failed: {e}")
            return False

    def get_result_evaluation_status(self, result_id: str) -> Optional[Dict]:
        """
        Get the evaluation status of a result.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT er.evaluation_status, er.evaluation_error, er.submitted_at,
                           er.evaluated_at, er.candidate_name, er.candidate_id,
                           er.total_marks, er.obtained_marks, er.percentage,
                           er.performance_level, e.title as exam_title, e.show_feedback
                    FROM exam_results er
                    JOIN exams e ON er.exam_id = e.id
                    WHERE er.id = ?
                ''', (result_id,))

                row = cursor.fetchone()
                if row:
                    return {
                        'result_id': result_id,
                        'evaluation_status': row[0] or 'pending',
                        'evaluation_error': row[1],
                        'submitted_at': row[2],
                        'evaluated_at': row[3],
                        'candidate_name': row[4],
                        'candidate_id': row[5],
                        'total_marks': row[6],
                        'obtained_marks': row[7],
                        'percentage': row[8],
                        'performance_level': row[9],
                        'exam_title': row[10],
                        'show_feedback': bool(row[11]) if row[11] is not None else True,
                        'is_complete': row[0] in ['completed', 'failed']
                    }
                return None

        except sqlite3.Error as e:
            print(f"❌ Error getting result evaluation status: {e}")
            return None

    def get_pending_evaluations_count(self) -> int:
        """Get count of pending evaluations"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT COUNT(*) FROM exam_results
                    WHERE evaluation_status = 'pending'
                ''')
                return cursor.fetchone()[0]
        except sqlite3.Error as e:
            print(f"❌ Error getting pending evaluations count: {e}")
            return 0

    def get_pending_evaluations(self, limit: int = 50) -> List[Dict]:
        """Get list of pending evaluations for admin view"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT er.id, er.candidate_name, er.candidate_id, er.submitted_at,
                           er.evaluation_status, e.title as exam_title
                    FROM exam_results er
                    JOIN exams e ON er.exam_id = e.id
                    WHERE er.evaluation_status IN ('pending', 'processing')
                    ORDER BY er.submitted_at ASC
                    LIMIT ?
                ''', (limit,))

                results = []
                for row in cursor.fetchall():
                    results.append({
                        'result_id': row[0],
                        'candidate_name': row[1],
                        'candidate_id': row[2],
                        'submitted_at': row[3],
                        'evaluation_status': row[4],
                        'exam_title': row[5]
                    })
                return results

        except sqlite3.Error as e:
            print(f"❌ Error getting pending evaluations: {e}")
            return []

    def get_failed_evaluations(self, limit: int = 50) -> List[Dict]:
        """Get list of failed evaluations for admin review"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT er.id, er.candidate_name, er.candidate_id, er.submitted_at,
                           er.evaluation_error, e.title as exam_title
                    FROM exam_results er
                    JOIN exams e ON er.exam_id = e.id
                    WHERE er.evaluation_status = 'failed'
                    ORDER BY er.submitted_at DESC
                    LIMIT ?
                ''', (limit,))

                results = []
                for row in cursor.fetchall():
                    results.append({
                        'result_id': row[0],
                        'candidate_name': row[1],
                        'candidate_id': row[2],
                        'submitted_at': row[3],
                        'evaluation_error': row[4],
                        'exam_title': row[5]
                    })
                return results

        except sqlite3.Error as e:
            print(f"❌ Error getting failed evaluations: {e}")
            return []

    def get_pending_evaluations_by_exam(self, exam_id: str, limit: int = 50) -> List[Dict]:
        """Get list of pending evaluations for a specific exam"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT er.id, er.candidate_name, er.candidate_id, er.submitted_at,
                           er.evaluation_status, e.title as exam_title
                    FROM exam_results er
                    JOIN exams e ON er.exam_id = e.id
                    WHERE er.exam_id = ? AND er.evaluation_status IN ('pending', 'processing')
                    ORDER BY er.submitted_at ASC
                    LIMIT ?
                ''', (exam_id, limit))

                results = []
                for row in cursor.fetchall():
                    results.append({
                        'result_id': row[0],
                        'candidate_name': row[1],
                        'candidate_id': row[2],
                        'submitted_at': row[3],
                        'evaluation_status': row[4],
                        'exam_title': row[5]
                    })
                return results

        except sqlite3.Error as e:
            print(f"❌ Error getting pending evaluations by exam: {e}")
            return []

    def get_failed_evaluations_by_exam(self, exam_id: str, limit: int = 50) -> List[Dict]:
        """Get list of failed evaluations for a specific exam"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT er.id, er.candidate_name, er.candidate_id, er.submitted_at,
                           er.evaluation_error, e.title as exam_title
                    FROM exam_results er
                    JOIN exams e ON er.exam_id = e.id
                    WHERE er.exam_id = ? AND er.evaluation_status = 'failed'
                    ORDER BY er.submitted_at DESC
                    LIMIT ?
                ''', (exam_id, limit))

                results = []
                for row in cursor.fetchall():
                    results.append({
                        'result_id': row[0],
                        'candidate_name': row[1],
                        'candidate_id': row[2],
                        'submitted_at': row[3],
                        'evaluation_error': row[4],
                        'exam_title': row[5]
                    })
                return results

        except sqlite3.Error as e:
            print(f"❌ Error getting failed evaluations by exam: {e}")
            return []

    def set_exam_evaluation_paused(self, exam_id: str, paused: bool) -> bool:
        """Pause or resume evaluation processing for a specific exam"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE exams SET evaluation_paused = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (paused, exam_id))
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            print(f"❌ Error setting exam evaluation paused: {e}")
            return False

    def is_exam_evaluation_paused(self, exam_id: str) -> bool:
        """Check if evaluation is paused for a specific exam"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT evaluation_paused FROM exams WHERE id = ?
                ''', (exam_id,))
                row = cursor.fetchone()
                return bool(row[0]) if row else False
        except sqlite3.Error as e:
            print(f"❌ Error checking exam evaluation paused: {e}")
            return False

    def get_exam_evaluation_status(self, exam_id: str) -> Dict:
        """Get evaluation status for a specific exam including pause state"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Get exam pause status
                cursor.execute('''
                    SELECT evaluation_paused FROM exams WHERE id = ?
                ''', (exam_id,))
                row = cursor.fetchone()
                is_paused = bool(row[0]) if row else False

                # Get pending count
                cursor.execute('''
                    SELECT COUNT(*) FROM exam_results
                    WHERE exam_id = ? AND evaluation_status IN ('pending', 'processing')
                ''', (exam_id,))
                pending_count = cursor.fetchone()[0]

                # Get failed count
                cursor.execute('''
                    SELECT COUNT(*) FROM exam_results
                    WHERE exam_id = ? AND evaluation_status = 'failed'
                ''', (exam_id,))
                failed_count = cursor.fetchone()[0]

                return {
                    'evaluation_paused': is_paused,
                    'pending_count': pending_count,
                    'failed_count': failed_count
                }
        except sqlite3.Error as e:
            print(f"❌ Error getting exam evaluation status: {e}")
            return {'evaluation_paused': False, 'pending_count': 0, 'failed_count': 0}

    def get_pending_results_for_recovery(self) -> List[Dict]:
        """
        Get all pending/failed results for queue recovery after server restart.
        This ensures NO DATA IS LOST even if the server crashes.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT er.id, er.session_id, er.exam_id, er.candidate_name, er.candidate_id,
                           er.time_taken, e.show_feedback, e.negative_marking_config, e.multi_select_scoring_mode
                    FROM exam_results er
                    JOIN exams e ON er.exam_id = e.id
                    WHERE er.evaluation_status IN ('pending', 'processing')
                    ORDER BY er.submitted_at ASC
                ''')

                results = []
                for row in cursor.fetchall():
                    result_id = row[0]

                    # Get answers for this result
                    cursor.execute('''
                        SELECT ca.question_id, ca.candidate_answer
                        FROM candidate_answers ca
                        WHERE ca.result_id = ?
                    ''', (result_id,))

                    answers = {}
                    for ans_row in cursor.fetchall():
                        answers[str(ans_row[0])] = ans_row[1] or ""

                    # Get questions for this exam
                    questions = self.get_exam_questions(row[2])

                    # Parse negative marking config
                    neg_config = {}
                    if row[7]:
                        try:
                            neg_config = json.loads(row[7]) if isinstance(row[7], str) else row[7]
                        except:
                            pass

                    results.append({
                        'result_id': result_id,
                        'session_id': row[1],
                        'exam_id': row[2],
                        'candidate_name': row[3],
                        'candidate_id': row[4],
                        'time_taken': row[5],
                        'show_feedback': bool(row[6]) if row[6] is not None else True,
                        'negative_marking_config': neg_config,
                        'multi_select_scoring_mode': row[8] or 'partial',
                        'answers': answers,
                        'questions': questions
                    })

                print(f"📋 Found {len(results)} pending evaluations for recovery")
                return results

        except sqlite3.Error as e:
            print(f"❌ Error getting pending results for recovery: {e}")
            return []

    def get_result_for_manual_evaluation(self, result_id: str) -> Optional[Dict]:
        """
        Get full result details for manual evaluation by admin.
        Includes all answers and questions for grading.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Get result info
                cursor.execute('''
                    SELECT er.id, er.session_id, er.exam_id, er.candidate_name, er.candidate_id,
                           er.total_marks, er.time_taken, er.submitted_at, er.evaluation_status,
                           er.evaluation_error, e.title as exam_title, e.department, e.position
                    FROM exam_results er
                    JOIN exams e ON er.exam_id = e.id
                    WHERE er.id = ?
                ''', (result_id,))

                row = cursor.fetchone()
                if not row:
                    return None

                # Get answers with question details
                cursor.execute('''
                    SELECT ca.id, ca.question_id, ca.candidate_answer, ca.marks_obtained,
                           ca.is_correct, q.question_text, q.question_type, q.marks,
                           q.options, q.correct_answer, q.section_type, q.explanation
                    FROM candidate_answers ca
                    JOIN questions q ON ca.question_id = q.id
                    WHERE ca.result_id = ?
                    ORDER BY q.section_type, q.question_order
                ''', (result_id,))

                answers = []
                for ans_row in cursor.fetchall():
                    answer_data = {
                        'answer_id': ans_row[0],
                        'question_id': ans_row[1],
                        'candidate_answer': ans_row[2],
                        'marks_obtained': ans_row[3] or 0,
                        'is_correct': ans_row[4],
                        'question_text': ans_row[5],
                        'question_type': ans_row[6],
                        'max_marks': ans_row[7],
                        'section_type': ans_row[10],
                        'explanation': ans_row[11]
                    }

                    # Add MCQ options
                    if ans_row[6] == 'mcq' and ans_row[8]:
                        try:
                            options = json.loads(ans_row[8]) if isinstance(ans_row[8], str) else ans_row[8]
                            answer_data['options'] = options
                            answer_data['correct_answer'] = ans_row[9]

                            # Get selected option text
                            if ans_row[2] and ans_row[2].isdigit():
                                idx = int(ans_row[2])
                                if 0 <= idx < len(options):
                                    answer_data['selected_option_text'] = options[idx]
                            if ans_row[9] is not None and 0 <= ans_row[9] < len(options):
                                answer_data['correct_option_text'] = options[ans_row[9]]
                        except:
                            pass

                    answers.append(answer_data)

                return {
                    'result_id': row[0],
                    'session_id': row[1],
                    'exam_id': row[2],
                    'candidate_name': row[3],
                    'candidate_id': row[4],
                    'total_marks': row[5],
                    'time_taken': row[6],
                    'submitted_at': row[7],
                    'evaluation_status': row[8],
                    'evaluation_error': row[9],
                    'exam_title': row[10],
                    'department': row[11],
                    'position': row[12],
                    'answers': answers
                }

        except sqlite3.Error as e:
            print(f"❌ Error getting result for manual evaluation: {e}")
            return None

    def save_manual_evaluation(self, result_id: str, evaluations: List[Dict]) -> bool:
        """
        Save manual evaluation from admin.
        evaluations: List of {answer_id, marks_obtained, feedback}
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                total_obtained = 0
                total_marks = 0

                for eval_item in evaluations:
                    # Get the maximum marks for this question
                    cursor.execute('''
                        SELECT q.marks
                        FROM candidate_answers ca
                        JOIN questions q ON ca.question_id = q.id
                        WHERE ca.id = ?
                    ''', (eval_item['answer_id'],))

                    max_marks_row = cursor.fetchone()
                    max_marks = max_marks_row[0] if max_marks_row else 0

                    # Clamp marks_obtained to not exceed max_marks and not be negative
                    marks_obtained = eval_item['marks_obtained']
                    marks_obtained = max(0, min(marks_obtained, max_marks))

                    cursor.execute('''
                        UPDATE candidate_answers
                        SET marks_obtained = ?, feedback = ?, is_correct = ?
                        WHERE id = ?
                    ''', (
                        marks_obtained,
                        eval_item.get('feedback', 'Manually evaluated'),
                        marks_obtained > 0,
                        eval_item['answer_id']
                    ))
                    total_obtained += marks_obtained

                # Get total marks
                cursor.execute('''
                    SELECT SUM(q.marks)
                    FROM candidate_answers ca
                    JOIN questions q ON ca.question_id = q.id
                    WHERE ca.result_id = ?
                ''', (result_id,))
                total_marks = cursor.fetchone()[0] or 0

                # Calculate percentage and performance
                percentage = (total_obtained / total_marks * 100) if total_marks > 0 else 0
                if percentage >= 85:
                    performance = "Excellent"
                elif percentage >= 70:
                    performance = "Good"
                elif percentage >= 50:
                    performance = "Average"
                else:
                    performance = "Poor"

                # Update main result
                cursor.execute('''
                    UPDATE exam_results
                    SET obtained_marks = ?, percentage = ?, performance_level = ?,
                        evaluation_status = 'completed', evaluated_at = CURRENT_TIMESTAMP,
                        evaluation_error = NULL
                    WHERE id = ?
                ''', (total_obtained, percentage, performance, result_id))

                conn.commit()
                print(f"✅ Manual evaluation saved for result: {result_id[:8]}...")
                return True

        except sqlite3.Error as e:
            print(f"❌ Error saving manual evaluation: {e}")
            return False

    def retry_failed_evaluation(self, result_id: str) -> bool:
        """Mark a failed evaluation for retry by resetting its status to pending"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE exam_results
                    SET evaluation_status = 'pending', evaluation_error = NULL
                    WHERE id = ? AND evaluation_status = 'failed'
                ''', (result_id,))
                conn.commit()

                if cursor.rowcount > 0:
                    print(f"🔄 Result {result_id[:8]}... marked for retry")
                    return True
                return False

        except sqlite3.Error as e:
            print(f"❌ Error marking result for retry: {e}")
            return False


# Initialize database instance
db = ExamDatabase()

if __name__ == "__main__":
    # Test database functionality
    print("Testing exam database functionality...")
    
    # Test database info
    info = db.get_database_info()
    print(f"Database info: {info}")
    
    print("✅ Database test completed")