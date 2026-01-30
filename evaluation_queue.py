"""
Background Evaluation Queue System
Handles asynchronous exam evaluation with rate limiting, retries, and fault tolerance.
This prevents system crashes when many candidates submit exams simultaneously.
"""

import asyncio
import threading
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from queue import PriorityQueue
import traceback

# Import shared MCQ evaluation function
from utils import evaluate_mcq_answer, get_performance_level


class EvaluationStatus(str, Enum):
    """Status of an evaluation task"""
    PENDING = "pending"           # Waiting in queue
    PROCESSING = "processing"     # Currently being evaluated
    COMPLETED = "completed"       # Successfully evaluated
    FAILED = "failed"            # Failed after all retries
    PARTIAL = "partial"          # Some questions evaluated, some failed


@dataclass(order=True)
class EvaluationTask:
    """A single evaluation task in the queue"""
    priority: int  # Lower = higher priority (0 = highest)
    created_at: float = field(compare=False)
    result_id: str = field(compare=False)
    session_id: str = field(compare=False)
    exam_id: str = field(compare=False)
    candidate_name: str = field(compare=False)
    candidate_id: str = field(compare=False)
    answers: Dict = field(compare=False)
    questions: List[Dict] = field(compare=False)
    negative_marking_config: Dict = field(compare=False, default_factory=dict)
    show_feedback: bool = field(compare=False, default=True)
    multi_select_scoring_mode: str = field(compare=False, default='partial')  # 'partial' or 'strict'
    retry_count: int = field(compare=False, default=0)
    max_retries: int = field(compare=False, default=5)
    long_retry_count: int = field(compare=False, default=0)
    max_long_retries: int = field(compare=False, default=6)  # 6 x 10min = 1 hour of retrying
    last_error: str = field(compare=False, default="")


class EvaluationQueue:
    """
    Background evaluation queue with rate limiting and retry logic.

    Features:
    - Rate limiting to prevent API quota exhaustion
    - Automatic retries with exponential backoff
    - Long-term retry for persistent failures (re-queues after extended delay)
    - Priority queue (earlier submissions processed first)
    - Fault tolerance - partial evaluations saved
    - Status tracking for candidates and admin
    """

    def __init__(self,
                 exam_system,
                 db,
                 requests_per_minute: int = 10,
                 retry_delay_base: float = 30.0,
                 max_retry_delay: float = 300.0,
                 max_retries: int = 5,
                 long_retry_delay: float = 600.0):
        """
        Initialize the evaluation queue.

        Args:
            exam_system: ExamSystem instance for evaluation
            db: Database instance for saving results
            requests_per_minute: Rate limit for API calls (default: 10/min)
            retry_delay_base: Base delay for retries in seconds (default: 30s)
            max_retry_delay: Maximum delay between retries in seconds (default: 300s = 5 min)
            max_retries: Maximum retry attempts before long-term retry (default: 5)
            long_retry_delay: Delay before re-queuing after all retries fail (default: 600s = 10 min)
        """
        self.exam_system = exam_system
        self.db = db
        self.requests_per_minute = requests_per_minute
        self.retry_delay_base = retry_delay_base
        self.max_retry_delay = max_retry_delay
        self.max_retries = max_retries
        self.long_retry_delay = long_retry_delay

        # Queue and state management
        self._queue = PriorityQueue()
        self._processing = {}  # result_id -> task being processed
        self._status = {}      # result_id -> EvaluationStatus
        self._progress = {}    # result_id -> progress info

        # Rate limiting
        self._last_request_time = 0
        self._min_request_interval = 60.0 / requests_per_minute

        # Worker control
        self._running = False
        self._worker_thread = None
        self._lock = threading.Lock()

        # Callbacks
        self._on_complete_callbacks: List[Callable] = []
        self._on_error_callbacks: List[Callable] = []

        # Automatic cleanup settings
        self._cleanup_interval_seconds = 3600  # Run cleanup every hour
        self._last_cleanup_time = time.time()
        self._cleanup_max_age_hours = 24  # Remove status entries older than 24 hours

        print(f"📋 Evaluation queue initialized (rate limit: {requests_per_minute}/min)")

    def start(self):
        """Start the background worker"""
        if self._running:
            return

        self._running = True
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        print("🚀 Background evaluation worker started")

    def stop(self):
        """Stop the background worker gracefully"""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5.0)
        print("🛑 Background evaluation worker stopped")

    def add_task(self,
                 result_id: str,
                 session_id: str,
                 exam_id: str,
                 candidate_name: str,
                 candidate_id: str,
                 answers: Dict,
                 questions: List[Dict],
                 negative_marking_config: Dict = None,
                 show_feedback: bool = True,
                 multi_select_scoring_mode: str = 'partial',
                 priority: int = 1) -> bool:
        """
        Add an evaluation task to the queue.

        Args:
            result_id: ID of the result record in database
            session_id: Exam session ID
            exam_id: Exam ID
            candidate_name: Candidate's name
            candidate_id: Candidate's ID
            answers: Dict of question_id -> answer
            questions: List of question dicts
            negative_marking_config: Negative marking settings
            show_feedback: Whether to generate detailed feedback
            multi_select_scoring_mode: 'partial' or 'strict' for multi-select MCQs
            priority: Task priority (0 = highest, default 1)

        Returns:
            True if task was added successfully
        """
        try:
            task = EvaluationTask(
                priority=priority,
                created_at=time.time(),
                result_id=result_id,
                session_id=session_id,
                exam_id=exam_id,
                candidate_name=candidate_name,
                candidate_id=candidate_id,
                answers=answers,
                questions=questions,
                negative_marking_config=negative_marking_config or {},
                show_feedback=show_feedback,
                multi_select_scoring_mode=multi_select_scoring_mode,
                max_retries=self.max_retries
            )

            with self._lock:
                self._queue.put(task)
                self._status[result_id] = EvaluationStatus.PENDING
                self._progress[result_id] = {
                    'status': 'pending',
                    'queued_at': datetime.now().isoformat(),
                    'position': self._queue.qsize(),
                    'total_questions': len(questions),
                    'evaluated_questions': 0,
                    'message': 'Your exam is queued for evaluation. You can close this page and check back later.'
                }

            print(f"📥 Added evaluation task for {candidate_name} (Queue size: {self._queue.qsize()})")
            return True

        except Exception as e:
            print(f"❌ Failed to add evaluation task: {str(e)}")
            return False

    def get_status(self, result_id: str) -> Dict:
        """
        Get the current status of an evaluation.

        Returns:
            Dict with status information
        """
        with self._lock:
            status = self._status.get(result_id, EvaluationStatus.PENDING)
            progress = self._progress.get(result_id, {})

            # Calculate queue position
            queue_position = 0
            if status == EvaluationStatus.PENDING:
                # Approximate position (we can't iterate PriorityQueue easily)
                queue_position = progress.get('position', self._queue.qsize())

            return {
                'result_id': result_id,
                'status': status.value if isinstance(status, EvaluationStatus) else status,
                'queue_position': queue_position,
                'queue_size': self._queue.qsize(),
                'is_complete': status in [EvaluationStatus.COMPLETED, EvaluationStatus.FAILED],
                'can_view_results': status == EvaluationStatus.COMPLETED,
                **progress
            }

    def get_queue_stats(self) -> Dict:
        """Get overall queue statistics for admin dashboard"""
        with self._lock:
            pending_count = sum(1 for s in self._status.values()
                               if s == EvaluationStatus.PENDING)
            processing_count = sum(1 for s in self._status.values()
                                  if s == EvaluationStatus.PROCESSING)
            completed_count = sum(1 for s in self._status.values()
                                 if s == EvaluationStatus.COMPLETED)
            failed_count = sum(1 for s in self._status.values()
                              if s == EvaluationStatus.FAILED)

            return {
                'queue_size': self._queue.qsize(),
                'pending': pending_count,
                'processing': processing_count,
                'completed': completed_count,
                'failed': failed_count,
                'is_running': self._running,
                'rate_limit': f"{self.requests_per_minute}/min"
            }

    def _worker_loop(self):
        """Main worker loop that processes the queue"""
        print("🔄 Evaluation worker loop started")

        while self._running:
            try:
                # Periodic cleanup to prevent memory leaks
                current_time = time.time()
                if current_time - self._last_cleanup_time >= self._cleanup_interval_seconds:
                    self.clear_old_status(self._cleanup_max_age_hours)
                    self._last_cleanup_time = current_time

                # Check if queue has items
                if self._queue.empty():
                    time.sleep(1)
                    continue

                # Rate limiting
                elapsed = time.time() - self._last_request_time
                if elapsed < self._min_request_interval:
                    time.sleep(self._min_request_interval - elapsed)

                # Get next task
                try:
                    task = self._queue.get(timeout=1)
                except:
                    continue

                # Process the task
                self._process_task(task)
                self._last_request_time = time.time()

            except Exception as e:
                print(f"❌ Worker loop error: {str(e)}")
                traceback.print_exc()
                time.sleep(5)  # Prevent tight loop on errors

        print("🔄 Evaluation worker loop stopped")

    def _process_task(self, task: EvaluationTask):
        """Process a single evaluation task"""
        result_id = task.result_id

        # Check if exam evaluation is paused
        if self.db.is_exam_evaluation_paused(task.exam_id):
            print(f"⏸️ Evaluation paused for exam {task.exam_id} - re-queuing {task.candidate_name}")

            with self._lock:
                self._progress[result_id].update({
                    'status': 'paused',
                    'message': 'Evaluation is paused by admin. Your answers are safe and will be evaluated when resumed.'
                })

            # Re-queue the task with a delay to avoid tight loop
            def requeue_paused_task():
                time.sleep(30)  # Check again after 30 seconds
                if self._running:
                    self._queue.put(task)

            requeue_thread = threading.Thread(target=requeue_paused_task, daemon=True)
            requeue_thread.start()
            return

        try:
            with self._lock:
                self._status[result_id] = EvaluationStatus.PROCESSING
                self._processing[result_id] = task
                self._progress[result_id].update({
                    'status': 'processing',
                    'started_at': datetime.now().isoformat(),
                    'message': 'Your exam is being evaluated...'
                })

            print(f"⚙️ Processing evaluation for {task.candidate_name}")

            # Check if there are any subjective questions (short/essay)
            has_subjective = any(q['type'] in ['short', 'essay'] for q in task.questions)

            # Perform the evaluation
            # Always use AI for subjective questions, regardless of show_feedback
            if has_subjective:
                print(f"📝 Exam has subjective questions - using AI evaluation")
                evaluation_result = self._evaluate_with_feedback(task)
            else:
                print(f"☑️ MCQ-only exam - using auto evaluation")
                evaluation_result = self._evaluate_mcq_only(task)

            # Save the results
            success = self._save_evaluation_result(task, evaluation_result)

            if success:
                with self._lock:
                    self._status[result_id] = EvaluationStatus.COMPLETED
                    self._progress[result_id].update({
                        'status': 'completed',
                        'completed_at': datetime.now().isoformat(),
                        'message': 'Evaluation complete! You can now view your results.',
                        'can_view_results': True
                    })
                    if result_id in self._processing:
                        del self._processing[result_id]

                print(f"✅ Evaluation completed for {task.candidate_name}")

                # Trigger callbacks
                for callback in self._on_complete_callbacks:
                    try:
                        callback(result_id, evaluation_result)
                    except:
                        pass
            else:
                raise Exception("Failed to save evaluation results")

        except Exception as e:
            error_msg = str(e)
            print(f"❌ Evaluation error for {task.candidate_name}: {error_msg}")

            # Handle retry logic
            task.retry_count += 1
            task.last_error = error_msg

            if task.retry_count < task.max_retries:
                # Exponential backoff with jitter
                delay = min(
                    self.retry_delay_base * (2 ** (task.retry_count - 1)),
                    self.max_retry_delay
                )

                print(f"🔄 Retrying in {delay:.0f}s (attempt {task.retry_count + 1}/{task.max_retries})")

                with self._lock:
                    self._progress[result_id].update({
                        'status': 'retrying',
                        'retry_count': task.retry_count,
                        'max_retries': task.max_retries,
                        'next_retry_at': (datetime.now() + timedelta(seconds=delay)).isoformat(),
                        'message': f'Evaluation temporarily delayed. Retrying in {int(delay)} seconds... (Attempt {task.retry_count + 1}/{task.max_retries})'
                    })

                # Schedule retry
                def retry_task():
                    time.sleep(delay)
                    if self._running:
                        self._queue.put(task)

                retry_thread = threading.Thread(target=retry_task, daemon=True)
                retry_thread.start()

            else:
                # Max retries exceeded - check if we should do long-term retry
                task.long_retry_count += 1

                if task.long_retry_count <= task.max_long_retries:
                    # Use long-term retry mechanism
                    print(f"⚠️ Max retries ({task.max_retries}) exceeded for {task.candidate_name}")
                    print(f"🔄 Scheduling long-term retry #{task.long_retry_count}/{task.max_long_retries} in {self.long_retry_delay:.0f}s ({self.long_retry_delay/60:.0f} minutes)")

                    with self._lock:
                        self._progress[result_id].update({
                            'status': 'long_retry_pending',
                            'retry_count': task.retry_count,
                            'long_retry_count': task.long_retry_count,
                            'max_long_retries': task.max_long_retries,
                            'next_retry_at': (datetime.now() + timedelta(seconds=self.long_retry_delay)).isoformat(),
                            'message': f'Evaluation service temporarily unavailable. Will retry in {int(self.long_retry_delay/60)} minutes (attempt {task.long_retry_count}/{task.max_long_retries}). Your answers are safe!'
                        })
                        if result_id in self._processing:
                            del self._processing[result_id]

                    # Schedule long-term retry (reset short retry count for fresh attempts)
                    def long_retry_task():
                        time.sleep(self.long_retry_delay)
                        if self._running:
                            # Reset short retry count for fresh attempts
                            task.retry_count = 0
                            task.priority = 0  # High priority for retried tasks
                            print(f"🔄 Long-term retry #{task.long_retry_count} triggered for {task.candidate_name}")
                            with self._lock:
                                self._status[result_id] = EvaluationStatus.PENDING
                                self._progress[result_id].update({
                                    'status': 'pending',
                                    'message': f'Re-queued for evaluation (long-term retry {task.long_retry_count}/{task.max_long_retries}).'
                                })
                            self._queue.put(task)

                    long_retry_thread = threading.Thread(target=long_retry_task, daemon=True)
                    long_retry_thread.start()

                else:
                    # All long-term retries exhausted - mark as permanently failed
                    total_attempts = task.max_retries * task.max_long_retries
                    total_time = int((task.max_long_retries * self.long_retry_delay) / 60)
                    print(f"❌ All retries exhausted for {task.candidate_name} after {total_attempts} attempts over ~{total_time} minutes")

                    with self._lock:
                        self._status[result_id] = EvaluationStatus.FAILED
                        self._progress[result_id].update({
                            'status': 'failed',
                            'failed_at': datetime.now().isoformat(),
                            'error': f'Evaluation failed after {total_attempts} attempts. Manual review required.',
                            'message': 'Automatic evaluation could not be completed. Your answers have been saved and will be reviewed manually by our team.'
                        })
                        if result_id in self._processing:
                            del self._processing[result_id]

                    # Save partial/fallback results for manual review
                    self._save_fallback_result(task)

                    # Trigger error callbacks
                    for callback in self._on_error_callbacks:
                        try:
                            callback(result_id, f"Permanent failure after all retries: {error_msg}")
                        except:
                            pass

    def _evaluate_with_feedback(self, task: EvaluationTask) -> Dict:
        """Evaluate with full AI feedback for subjective questions"""
        return self.exam_system.evaluate_exam(
            task.questions,
            task.answers,
            task.negative_marking_config,
            task.multi_select_scoring_mode
        )

    def _evaluate_mcq_only(self, task: EvaluationTask) -> Dict:
        """Evaluate MCQs only without AI (faster, no API calls for MCQ-only exams)"""
        total_marks = 0
        obtained_marks = 0
        negative_marks = 0
        question_results = []

        for question in task.questions:
            question_id = str(question['id'])
            candidate_answer = task.answers.get(question_id, "")
            section_type = question.get('section_type', 'technical')

            if question['type'] == 'mcq':
                # Auto-evaluate MCQ
                result = self._evaluate_mcq(question, candidate_answer,
                                           task.negative_marking_config, section_type,
                                           task.multi_select_scoring_mode)
                negative_marks += result.get('negative_marks_applied', 0)
            else:
                # For non-MCQ, mark as pending manual review
                result = {
                    'question_id': question['id'],
                    'question_type': question['type'],
                    'question_text': question['question'],
                    'candidate_answer': candidate_answer,
                    'marks_total': question['marks'],
                    'marks_obtained': 0,
                    'negative_marks_applied': 0,
                    'feedback': 'Answer submitted - awaiting review',
                    'evaluation_details': 'Manual review required'
                }

            total_marks += question['marks']
            obtained_marks += result['marks_obtained']
            question_results.append(result)

        final_score = obtained_marks - negative_marks
        percentage = (final_score / total_marks) * 100 if total_marks > 0 else 0

        return {
            'total_marks': total_marks,
            'obtained_marks': final_score,
            'negative_marks': negative_marks,
            'percentage': percentage,
            'question_results': question_results,
            'overall_feedback': 'Results recorded. Detailed feedback will be available after manual review.',
            'performance_level': self._get_performance_level(percentage)
        }

    def _evaluate_mcq(self, question: Dict, candidate_answer: str,
                      negative_marking_config: Dict, section_type: str,
                      multi_select_scoring_mode: str = 'partial') -> Dict:
        """Evaluate a single MCQ question.

        Delegates to the shared evaluate_mcq_answer function for consistency.
        """
        return evaluate_mcq_answer(question, candidate_answer, negative_marking_config, section_type, multi_select_scoring_mode)

    def _get_performance_level(self, percentage: float) -> str:
        """Get performance level based on percentage.

        Delegates to the shared get_performance_level function for consistency.
        """
        return get_performance_level(percentage)

    def _save_evaluation_result(self, task: EvaluationTask, evaluation: Dict) -> bool:
        """Save the evaluation result to database"""
        try:
            return self.db.update_exam_result_with_evaluation(
                result_id=task.result_id,
                evaluation=evaluation
            )
        except Exception as e:
            print(f"❌ Error saving evaluation result: {str(e)}")
            return False

    def _save_fallback_result(self, task: EvaluationTask):
        """Save a fallback result when evaluation fails"""
        try:
            self.db.mark_result_as_failed_evaluation(
                result_id=task.result_id,
                error_message=task.last_error
            )
        except Exception as e:
            print(f"❌ Error saving fallback result: {str(e)}")

    def on_complete(self, callback: Callable):
        """Register a callback for when evaluation completes"""
        self._on_complete_callbacks.append(callback)

    def on_error(self, callback: Callable):
        """Register a callback for when evaluation fails"""
        self._on_error_callbacks.append(callback)

    def clear_old_status(self, max_age_hours: int = 24):
        """Clean up old status entries to prevent memory leaks"""
        with self._lock:
            cutoff = datetime.now() - timedelta(hours=max_age_hours)
            to_remove = []

            for result_id, progress in self._progress.items():
                completed_at = progress.get('completed_at') or progress.get('failed_at')
                if completed_at:
                    try:
                        completed_time = datetime.fromisoformat(completed_at)
                        if completed_time < cutoff:
                            to_remove.append(result_id)
                    except:
                        pass

            for result_id in to_remove:
                self._status.pop(result_id, None)
                self._progress.pop(result_id, None)

            if to_remove:
                print(f"🧹 Cleaned up {len(to_remove)} old status entries")


# Global evaluation queue instance (initialized in app.py)
evaluation_queue: Optional[EvaluationQueue] = None


def get_evaluation_queue() -> Optional[EvaluationQueue]:
    """Get the global evaluation queue instance"""
    return evaluation_queue


def init_evaluation_queue(exam_system, db, requests_per_minute: int = 10) -> EvaluationQueue:
    """Initialize and return the global evaluation queue"""
    global evaluation_queue
    evaluation_queue = EvaluationQueue(
        exam_system=exam_system,
        db=db,
        requests_per_minute=requests_per_minute
    )
    return evaluation_queue
