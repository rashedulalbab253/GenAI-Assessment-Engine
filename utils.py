"""
Utility classes and functions for the AI-based Exam System
"""

import secrets
import pytz
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pydantic import BaseModel

from groq_analyzer import GroqAnalyzer


# Bangladesh timezone
BANGLADESH_TZ = pytz.timezone('Asia/Dhaka')


class ExamSession(BaseModel):
    session_id: str
    candidate_name: str
    candidate_id: str
    exam_id: str
    started_at: datetime
    time_limit: int  # in minutes


class AdminSession(BaseModel):
    session_id: str
    created_at: datetime
    expires_at: datetime


class ExamSystem:
    def __init__(self, api_key: str, backup_api_key: str = None):
        """Initialize the exam system with AI analyzer and optional backup key for failover"""
        self.analyzer = GroqAnalyzer(api_key, backup_api_key)

    def generate_exam_questions_by_sections(self, department: str, position: str, sections_structure: Dict, exam_language: str = 'english', difficulty_level: str = 'medium', custom_instructions: str = '', mcq_options_count: int = 4) -> Dict:
        """Generate exam questions organized by sections with language support and AI instructions.

        Returns a dict with:
        - 'questions': Dict of section_type -> list of questions (for successful sections)
        - 'failed_sections': List of section names that failed to generate
        - 'success': Boolean indicating if all sections generated successfully
        """
        return self.analyzer.generate_questions_by_sections(
            department, position, sections_structure, exam_language,
            difficulty_level=difficulty_level,
            custom_instructions=custom_instructions,
            mcq_options_count=mcq_options_count
        )

    def regenerate_section_questions(self, department: str, position: str, section_type: str, section_config: Dict, exam_language: str = 'english', difficulty_level: str = 'medium', custom_instructions: str = '') -> Dict:
        """Regenerate questions for a single section.

        Returns a dict with:
        - 'questions': List of generated questions (empty if failed)
        - 'success': Boolean indicating if generation was successful
        - 'error': Error message if failed
        """
        return self.analyzer.generate_single_section(
            department, position, section_type, section_config, exam_language,
            difficulty_level=difficulty_level,
            custom_instructions=custom_instructions
        )

    def evaluate_exam(self, questions: List[Dict], candidate_answers: Dict, negative_marking_config: Dict = None, multi_select_scoring_mode: str = 'partial') -> Dict:
        """Evaluate candidate answers and return detailed results with negative marking support"""
        total_marks = 0
        obtained_marks = 0
        negative_marks = 0
        question_results = []

        for question in questions:
            question_id = str(question['id'])
            candidate_answer = candidate_answers.get(question_id, "")
            section_type = question.get('section_type', 'technical')

            if question['type'] == 'mcq':
                # Auto-evaluate MCQ with negative marking
                result = self._evaluate_mcq(question, candidate_answer, negative_marking_config, section_type, multi_select_scoring_mode)
                negative_marks += result.get('negative_marks_applied', 0)
            else:
                # Use AI to evaluate short/essay answers
                result = self._evaluate_subjective(question, candidate_answer)
            
            total_marks += question['marks']
            obtained_marks += result['marks_obtained']
            question_results.append(result)

        # Calculate final score considering negative marks
        final_score = obtained_marks - negative_marks
        percentage = (final_score / total_marks) * 100 if total_marks > 0 else 0
        
        # Generate overall feedback
        overall_feedback = self._generate_overall_feedback(percentage, question_results, negative_marks)
        
        return {
            'total_marks': total_marks,
            'obtained_marks': final_score,
            'negative_marks': negative_marks,
            'percentage': percentage,
            'question_results': question_results,
            'overall_feedback': overall_feedback,
            'performance_level': get_performance_level(percentage)
        }

    def _evaluate_mcq(self, question: Dict, candidate_answer: str, negative_marking_config: Dict = None, section_type: str = 'technical', multi_select_scoring_mode: str = 'partial') -> Dict:
        """Evaluate MCQ answer with negative marking support.

        Delegates to the shared evaluate_mcq_answer function for consistency.
        """
        return evaluate_mcq_answer(question, candidate_answer, negative_marking_config, section_type, multi_select_scoring_mode)

    def _evaluate_subjective(self, question: Dict, candidate_answer: str) -> Dict:
        """Evaluate short/essay answer using AI"""
        if not candidate_answer.strip():
            return {
                'question_id': question['id'],
                'question_type': question['type'],
                'question_text': question['question'],
                'candidate_answer': candidate_answer,
                'marks_total': question['marks'],
                'marks_obtained': 0,
                'negative_marks_applied': 0,
                'feedback': 'No answer provided.',
                'evaluation_details': 'Answer was not provided by the candidate.',
                'ai_evaluated': True,
                'needs_manual_review': False
            }

        try:
            evaluation = self.analyzer.evaluate_subjective_answer(question, candidate_answer)

            # Check if AI evaluation was successful
            ai_evaluated = evaluation.get('ai_evaluated', True)
            needs_manual_review = evaluation.get('needs_manual_review', False)

            return {
                'question_id': question['id'],
                'question_type': question['type'],
                'question_text': question['question'],
                'candidate_answer': candidate_answer,
                'marks_total': question['marks'],
                'marks_obtained': evaluation['marks_awarded'],
                'negative_marks_applied': 0,  # No negative marking for subjective questions
                'feedback': evaluation.get('feedback', 'Evaluation completed'),
                'strengths': evaluation.get('strengths', ''),
                'improvements': evaluation.get('improvements', ''),
                'evaluation_details': f"AI Evaluation: {evaluation.get('feedback', '')}",
                'ai_evaluated': ai_evaluated,
                'needs_manual_review': needs_manual_review
            }

        except Exception as e:
            print(f"❌ Error evaluating subjective answer: {str(e)}")
            # Fallback - 0 marks until manual review (not 50% which is unfair)
            return {
                'question_id': question['id'],
                'question_type': question['type'],
                'question_text': question['question'],
                'candidate_answer': candidate_answer,
                'marks_total': question['marks'],
                'marks_obtained': 0,  # 0 marks until manual review
                'negative_marks_applied': 0,
                'feedback': 'AI evaluation failed. This answer needs manual review by admin.',
                'evaluation_details': f'Automatic evaluation failed: {str(e)}',
                'ai_evaluated': False,
                'needs_manual_review': True
            }

    def _generate_overall_feedback(self, percentage: float, question_results: List[Dict], negative_marks: float = 0) -> str:
        """Generate overall feedback for the candidate including negative marking information"""
        if percentage >= 85:
            base_feedback = "Excellent performance! You have demonstrated strong knowledge and understanding."
        elif percentage >= 70:
            base_feedback = "Good performance overall. You have shown solid understanding with room for improvement."
        elif percentage >= 50:
            base_feedback = "Average performance. You have basic understanding but need to strengthen your knowledge."
        else:
            base_feedback = "Below average performance. Significant improvement needed in your preparation."

        # Add specific feedback based on question types
        mcq_correct = len([r for r in question_results if r['question_type'] == 'mcq' and r.get('is_correct', False)])
        mcq_total = len([r for r in question_results if r['question_type'] == 'mcq'])
        
        if mcq_total > 0:
            mcq_percentage = (mcq_correct / mcq_total) * 100
            if mcq_percentage < 60:
                base_feedback += " Focus on improving your theoretical knowledge for multiple choice questions."

        # Add negative marking feedback if applicable
        if negative_marks > 0:
            base_feedback += f" Note: {negative_marks} marks were deducted due to incorrect answers in sections with negative marking. Be more careful with your responses in future exams."

        return base_feedback


# Utility Functions

def create_admin_session(timeout_minutes: int = 30) -> str:
    """Create a new admin session"""
    session_id = secrets.token_urlsafe(32)
    expires_at = datetime.now() + timedelta(minutes=timeout_minutes)
    return session_id


def verify_admin_session(session_id: str, admin_sessions: Dict, timeout_minutes: int = 30, lock=None) -> bool:
    """Verify if admin session is valid and not expired.

    Args:
        session_id: The session ID to verify
        admin_sessions: Dictionary of admin sessions
        timeout_minutes: Session timeout in minutes
        lock: Optional threading.Lock for thread-safe access
    """
    def _verify():
        if session_id not in admin_sessions:
            return False

        session = admin_sessions[session_id]
        if datetime.now() > session.expires_at:
            # Session expired, remove it
            del admin_sessions[session_id]
            return False

        # Extend session
        session.expires_at = datetime.now() + timedelta(minutes=timeout_minutes)
        return True

    if lock:
        with lock:
            return _verify()
    else:
        return _verify()


def convert_utc_to_bangladesh(utc_time_str: str) -> Optional[str]:
    """Convert UTC time string to Bangladesh time"""
    if not utc_time_str or utc_time_str == 'None':
        return None
    
    try:
        # Parse the UTC time string
        utc_time = datetime.strptime(utc_time_str, '%Y-%m-%d %H:%M:%S')
        # Set it as UTC
        utc_time = pytz.utc.localize(utc_time)
        # Convert to Bangladesh time
        bd_time = utc_time.astimezone(BANGLADESH_TZ)
        return bd_time.strftime('%Y-%m-%d %H:%M:%S')
    except Exception as e:
        print(f"Error converting time: {e}")
        return utc_time_str


def order_questions_by_type(questions: List[Dict]) -> List[Dict]:
    """Order questions by type: MCQ first, then Short, then Essay"""
    mcq_questions = [q for q in questions if q.get('type') == 'mcq']
    short_questions = [q for q in questions if q.get('type') == 'short']
    essay_questions = [q for q in questions if q.get('type') == 'essay']
    
    # Combine in order: MCQ → Short → Essay
    ordered_questions = mcq_questions + short_questions + essay_questions
    
    print(f"📄 Ordered questions: {len(mcq_questions)} MCQ, {len(short_questions)} Short, {len(essay_questions)} Essay")
    return ordered_questions


def group_questions_by_section_for_navigation(questions: List[Dict]) -> Dict[str, List[Dict]]:
    """Group questions by section type for navigation purposes"""
    sections = {}
    for question in questions:
        section_type = question.get('section_type', 'technical')
        if section_type not in sections:
            sections[section_type] = []
        sections[section_type].append(question)
    return sections


def get_performance_level(percentage: float) -> str:
    """Get performance level based on percentage"""
    if percentage >= 85:
        return "Excellent"
    elif percentage >= 70:
        return "Good"
    elif percentage >= 50:
        return "Average"
    else:
        return "Poor"


def evaluate_mcq_answer(question: Dict, candidate_answer,
                        negative_marking_config: Dict = None,
                        section_type: str = 'technical',
                        multi_select_scoring_mode: str = 'partial') -> Dict:
    """
    Evaluate a single MCQ answer with negative marking support.
    Supports both single-select and multi-select MCQs.

    This is the canonical MCQ evaluation function used throughout the application.
    All MCQ evaluation should use this function to ensure consistency.

    Args:
        question: Question dict with keys: id, question, options, correct_answer, marks, explanation
                  For multi-select: is_multi_select=True, correct_answers=[0, 2, 3]
        candidate_answer: For single-select: string index like "0", "1", "2", "3"
                          For multi-select: list of string indices ["0", "2"] or comma-separated string "0,2"
        negative_marking_config: Dict with section configs for negative marking
        section_type: The section type (technical, english, etc.) for negative marking lookup
        multi_select_scoring_mode: 'partial' for partial scoring, 'strict' for exact match only

    Returns:
        Dict with evaluation results
    """
    is_correct = False
    marks_obtained = 0
    negative_marks_applied = 0
    is_multi_select = question.get('is_multi_select', False)

    if is_multi_select:
        # Multi-select MCQ evaluation
        correct_answers = question.get('correct_answers', [])
        if isinstance(correct_answers, str):
            import json
            try:
                correct_answers = json.loads(correct_answers)
            except:
                correct_answers = []

        # Parse candidate answers
        candidate_selections = set()
        if candidate_answer:
            if isinstance(candidate_answer, list):
                # Already a list
                candidate_selections = set(int(a) for a in candidate_answer if str(a).isdigit())
            elif isinstance(candidate_answer, str):
                # Could be comma-separated or single value
                if ',' in candidate_answer:
                    candidate_selections = set(int(a.strip()) for a in candidate_answer.split(',') if a.strip().isdigit())
                elif candidate_answer.isdigit():
                    candidate_selections = {int(candidate_answer)}

        correct_set = set(correct_answers)

        if candidate_selections:
            # Check if candidate's answer exactly matches correct answers
            if candidate_selections == correct_set:
                is_correct = True
                marks_obtained = question['marks']
            else:
                # Different scoring based on mode
                correct_selected = len(candidate_selections & correct_set)
                incorrect_selected = len(candidate_selections - correct_set)

                if multi_select_scoring_mode == 'strict':
                    # Strict mode: 0 marks for any deviation from exact answer
                    marks_obtained = 0
                    # Apply negative marking if there are wrong selections
                    if incorrect_selected > 0 and negative_marking_config and section_type in negative_marking_config:
                        section_config = negative_marking_config[section_type]
                        if section_config.get('enabled', False):
                            negative_marks_applied = section_config.get('mcq_negative_marks', 0) * incorrect_selected
                else:
                    # Partial scoring mode (default)
                    # Formula: (correct_selected - incorrect_selected) / total_correct * marks
                    if correct_selected > incorrect_selected:
                        # Partial marks only if more correct than incorrect
                        partial_ratio = (correct_selected - incorrect_selected) / len(correct_set)
                        marks_obtained = max(0, question['marks'] * partial_ratio)
                        marks_obtained = round(marks_obtained, 2)

                    # Apply negative marking for wrong selections
                    if incorrect_selected > 0 and negative_marking_config and section_type in negative_marking_config:
                        section_config = negative_marking_config[section_type]
                        if section_config.get('enabled', False):
                            # Negative marking per incorrect selection
                            negative_marks_applied = section_config.get('mcq_negative_marks', 0) * incorrect_selected
        else:
            # No answer provided
            if negative_marking_config and section_type in negative_marking_config:
                section_config = negative_marking_config[section_type]
                if section_config.get('enabled', False) and section_config.get('apply_to_unanswered', False):
                    negative_marks_applied = section_config.get('mcq_negative_marks', 0)

        # Get selected options text safely
        selected_option_text = 'No answer'
        if candidate_selections:
            options = question.get('options', [])
            selected_texts = []
            for idx in sorted(candidate_selections):
                if 0 <= idx < len(options):
                    selected_texts.append(f"{chr(65 + idx)}) {options[idx]}")
            selected_option_text = '; '.join(selected_texts) if selected_texts else 'No answer'

        # Get correct answers text
        correct_answers_text = []
        options = question.get('options', [])
        for idx in correct_answers:
            if 0 <= idx < len(options):
                correct_answers_text.append(f"{chr(65 + idx)}) {options[idx]}")

        return {
            'question_id': question['id'],
            'question_type': 'mcq',
            'is_multi_select': True,
            'question_text': question['question'],
            'candidate_answer': list(candidate_selections) if candidate_selections else [],
            'correct_answer': correct_answers,
            'correct_answer_text': '; '.join(correct_answers_text),
            'is_correct': is_correct,
            'marks_total': question['marks'],
            'marks_obtained': marks_obtained,
            'negative_marks_applied': negative_marks_applied,
            'feedback': question.get('explanation', 'No explanation provided'),
            'selected_option': selected_option_text
        }

    else:
        # Single-select MCQ evaluation (original logic)
        if candidate_answer and str(candidate_answer).isdigit():
            selected_option = int(candidate_answer)
            is_correct = selected_option == question['correct_answer']
            if is_correct:
                marks_obtained = question['marks']
            else:
                # Apply negative marking if configured
                if negative_marking_config and section_type in negative_marking_config:
                    section_config = negative_marking_config[section_type]
                    if section_config.get('enabled', False):
                        negative_marks_applied = section_config.get('mcq_negative_marks', 0)
        else:
            # No answer provided - check if negative marking applies to unanswered questions
            if negative_marking_config and section_type in negative_marking_config:
                section_config = negative_marking_config[section_type]
                if section_config.get('enabled', False) and section_config.get('apply_to_unanswered', False):
                    negative_marks_applied = section_config.get('mcq_negative_marks', 0)

        # Get selected option text safely
        selected_option_text = 'No answer'
        if candidate_answer and str(candidate_answer).isdigit():
            idx = int(candidate_answer)
            options = question.get('options', [])
            if 0 <= idx < len(options):
                selected_option_text = options[idx]

        return {
            'question_id': question['id'],
            'question_type': 'mcq',
            'is_multi_select': False,
            'question_text': question['question'],
            'candidate_answer': candidate_answer,
            'correct_answer': question['correct_answer'],
            'is_correct': is_correct,
            'marks_total': question['marks'],
            'marks_obtained': marks_obtained,
            'negative_marks_applied': negative_marks_applied,
            'feedback': question.get('explanation', 'No explanation provided'),
            'selected_option': selected_option_text
        }


def validate_form_data(form_data: Dict) -> tuple[bool, str]:
    """Validate exam creation form data"""
    required_fields = ['department', 'position', 'title']
    
    for field in required_fields:
        if not form_data.get(field, '').strip():
            return False, f"Please fill in the required field: {field.title()}"
    
    try:
        time_limit = int(form_data.get('time_limit', 120))
        if time_limit <= 0:
            return False, "Time limit must be greater than 0"
    except (ValueError, TypeError):
        return False, "Invalid time limit format"
    
    return True, ""


def generate_safe_filename(candidate_name: str, result_id: str, extension: str = 'html') -> str:
    """Generate a safe filename for downloads"""
    safe_name = "".join(c for c in candidate_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
    return f"exam_result_{safe_name}_{result_id[:8]}.{extension}"


def calculate_exam_statistics(results: List[Dict]) -> Dict:
    """Calculate basic statistics for exam results"""
    if not results:
        return {
            'total_candidates': 0,
            'average_percentage': 0,
            'highest_score': 0,
            'lowest_score': 0,
            'pass_rate': 0
        }
    
    total_candidates = len(results)
    percentages = [result['percentage'] for result in results]
    
    average_percentage = sum(percentages) / total_candidates
    highest_score = max(percentages)
    lowest_score = min(percentages)
    pass_count = len([p for p in percentages if p >= 50])  # Assuming 50% is pass mark
    pass_rate = (pass_count / total_candidates) * 100
    
    return {
        'total_candidates': total_candidates,
        'average_percentage': round(average_percentage, 2),
        'highest_score': highest_score,
        'lowest_score': lowest_score,
        'pass_rate': round(pass_rate, 2)
    }


def format_time_duration(minutes: int) -> str:
    """Format time duration in minutes to human readable format"""
    if minutes < 60:
        return f"{minutes} minutes"
    
    hours = minutes // 60
    remaining_minutes = minutes % 60
    
    if remaining_minutes == 0:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    else:
        return f"{hours} hour{'s' if hours != 1 else ''} {remaining_minutes} minutes"


def sanitize_json_string(text: str) -> str:
    """Sanitize string for JSON serialization"""
    if not text:
        return ""
    
    # Replace problematic characters
    text = text.replace('\n', '\\n')
    text = text.replace('\r', '\\r')
    text = text.replace('\t', '\\t')
    text = text.replace('"', '\\"')
    text = text.replace('\\', '\\\\')
    
    return text