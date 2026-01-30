"""
Groq AI Integration for Question Generation and Evaluation
Replaces GeminiAnalyzer with Groq API (using Llama 3 models)
"""

import os
import json
import re
from typing import Dict, List, Optional
import time
from groq import Groq, GroqError

class GroqAnalyzer:
    def __init__(self, api_key: str, backup_api_key: str = None):
        """Initialize Groq API with primary and optional backup key for failover"""
        self.primary_api_key = api_key
        self.backup_api_key = backup_api_key
        self.current_api_key = api_key
        self.using_backup = False
        
        # Initialize Groq client
        self.client = Groq(api_key=self.current_api_key)
        
        # Model configuration
        self.model_name = "llama-3.3-70b-versatile"
        self.temperature = 0.7

        if backup_api_key:
            print("🔑 Dual API key mode enabled - backup key configured for failover")
        else:
            print("🔑 Single API key mode - no backup key configured")

    def _switch_to_backup_key(self) -> bool:
        """Switch to backup API key. Returns True if switched successfully."""
        if not self.backup_api_key:
            print("⚠️ No backup API key configured - cannot failover")
            return False

        if self.using_backup:
            print("⚠️ Already using backup API key - no more failover options")
            return False

        print("🔄 Switching to backup API key...")
        self.current_api_key = self.backup_api_key
        self.using_backup = True
        
        # Re-initialize client with backup key
        self.client = Groq(api_key=self.current_api_key)
        
        print("✅ Successfully switched to backup API key")
        return True

    def _reset_to_primary_key(self):
        """Reset back to primary API key (for next operation)"""
        if self.using_backup:
            self.current_api_key = self.primary_api_key
            self.using_backup = False
            self.client = Groq(api_key=self.current_api_key)
            print("🔄 Reset to primary API key for next operation")

    def _is_quota_error(self, error: Exception) -> bool:
        """Check if the error is a quota exceeded or rate limit error"""
        error_str = str(error).lower()
        quota_indicators = [
            'rate limit', 'too many requests', '429', 
            'quota exceeded', 'resource exhausted'
        ]
        return any(indicator in error_str for indicator in quota_indicators)

    def generate_questions_by_sections(self, department: str, position: str, sections_structure: Dict, exam_language: str = 'english', difficulty_level: str = 'medium', custom_instructions: str = '', mcq_options_count: int = 4) -> Dict:
        """Generate exam questions organized by sections with language support, difficulty level, custom instructions, retry logic, and API key failover.

        Returns a dict with:
        - 'questions': Dict of section_type -> list of questions (for successful sections)
        - 'failed_sections': List of section names that failed to generate
        - 'success': Boolean indicating if all sections generated successfully
        """
        all_sections_questions = {}
        failed_sections = []

        # Store difficulty and instructions for use in section generation
        self._current_difficulty_level = difficulty_level
        self._current_custom_instructions = custom_instructions
        self._mcq_options_count = max(2, min(6, mcq_options_count))  # Clamp to 2-6

        print(f"🎯 Difficulty level: {difficulty_level}")
        print(f"🔢 MCQ options count: {self._mcq_options_count}")
        if custom_instructions:
            print(f"📝 Custom instructions provided: {custom_instructions[:80]}...")

        for section_type, section_config in sections_structure.items():
            print(f"🤖 Generating {section_type} questions in {exam_language} language...")

            # Retry logic for each section with API key failover
            max_retries = 3
            questions = None
            failover_attempted = False

            for attempt in range(max_retries):
                try:
                    questions = self._generate_section_questions(
                        department, position, section_type, section_config, exam_language,
                        difficulty_level, custom_instructions
                    )

                    if questions:
                        print(f"✅ {section_type.title()} questions generated successfully in {exam_language} (attempt {attempt + 1})!")
                        break
                    else:
                        print(f"⚠️ Attempt {attempt + 1} failed for {section_type}, retrying...")
                        if attempt < max_retries - 1:
                            time.sleep(1)  # Brief pause between retries

                except Exception as e:
                    print(f"⚠️ Attempt {attempt + 1} failed for {section_type}: {str(e)}")

                    # Check if this is a quota error and try to failover
                    if self._is_quota_error(e) and not failover_attempted:
                        print(f"🔴 Quota/rate limit error detected for {section_type}")
                        if self._switch_to_backup_key():
                            failover_attempted = True
                            print(f"🔄 Retrying {section_type} with backup API key...")
                            # Don't count this as a failed attempt - restart attempts with backup key
                            attempt = -1
                            continue

                    if attempt < max_retries - 1:
                        time.sleep(1)
                    continue

            if questions:
                all_sections_questions[section_type] = questions
            else:
                print(f"❌ Failed to generate questions for {section_type} section after {max_retries} attempts")
                failed_sections.append(section_type)

        total_sections = len(sections_structure)
        successful_sections = len(all_sections_questions)
        print(f"✅ Generated questions for {successful_sections}/{total_sections} sections in {exam_language}")

        if failed_sections:
            print(f"⚠️ Failed sections: {', '.join(failed_sections)}")

        return {
            'questions': all_sections_questions,
            'failed_sections': failed_sections,
            'success': len(failed_sections) == 0
        }

    def generate_single_section(self, department: str, position: str, section_type: str, section_config: Dict, exam_language: str = 'english', difficulty_level: str = 'medium', custom_instructions: str = '') -> Dict:
        """Generate questions for a single section. Used for regenerating failed or specific sections.

        Returns a dict with:
        - 'questions': List of generated questions (empty if failed)
        - 'success': Boolean indicating if generation was successful
        - 'error': Error message if failed
        """
        print(f"🔄 Regenerating {section_type} section questions...")

        max_retries = 3
        questions = None
        failover_attempted = False
        last_error = None

        for attempt in range(max_retries):
            try:
                questions = self._generate_section_questions(
                    department, position, section_type, section_config, exam_language,
                    difficulty_level, custom_instructions
                )

                if questions:
                    print(f"✅ {section_type.title()} questions regenerated successfully (attempt {attempt + 1})!")
                    return {
                        'questions': questions,
                        'success': True,
                        'error': None
                    }
                else:
                    print(f"⚠️ Attempt {attempt + 1} failed for {section_type}, retrying...")
                    last_error = "Generation returned empty result"
                    if attempt < max_retries - 1:
                        time.sleep(1)

            except Exception as e:
                last_error = str(e)
                print(f"⚠️ Attempt {attempt + 1} failed for {section_type}: {last_error}")

                # Check if this is a quota error and try to failover
                if self._is_quota_error(e) and not failover_attempted:
                    print(f"🔴 Quota/rate limit error detected for {section_type}")
                    if self._switch_to_backup_key():
                        failover_attempted = True
                        print(f"🔄 Retrying {section_type} with backup API key...")
                        attempt = -1
                        continue

                if attempt < max_retries - 1:
                    time.sleep(1)
                continue

        print(f"❌ Failed to regenerate {section_type} section after {max_retries} attempts")
        return {
            'questions': [],
            'success': False,
            'error': last_error or "Unknown error during generation"
        }

    def _generate_section_questions(self, department: str, position: str, section_type: str, section_config: Dict, exam_language: str = 'english', difficulty_level: str = 'medium', custom_instructions: str = '') -> Optional[List[Dict]]:
        """Generate questions for a specific section with language support, difficulty level, custom instructions, and custom section handling"""
        mcq_count = section_config.get('mcq_count', 0)
        multi_select_count = section_config.get('multi_select_count', 0)  # Multi-select MCQ count
        short_count = section_config.get('short_count', 0)
        essay_count = section_config.get('essay_count', 0)
        mcq_marks = section_config.get('mcq_marks', 1)
        short_marks = section_config.get('short_marks', 5)
        essay_marks = section_config.get('essay_marks', 10)
        syllabus = section_config.get('syllabus', '').strip()

        # For custom sections, log additional info
        if section_config.get('is_custom'):
            display_name = section_config.get('display_name', 'Custom Section')
            print(f"📚 Custom section detected: {display_name}")

        # Skip sections with no questions
        total_questions = mcq_count + multi_select_count + short_count + essay_count
        if total_questions == 0:
            return []

        # Get mcq_options_count from instance variable (set by generate_questions_by_sections)
        mcq_options_count = getattr(self, '_mcq_options_count', 4)

        # Generate appropriate prompt
        prompt = self._create_section_prompt(
            department, position, section_type,
            mcq_count, multi_select_count, short_count, essay_count,
            mcq_marks, short_marks, essay_marks,
            syllabus, exam_language,
            section_config,  # Pass section_config for custom section handling
            difficulty_level,  # Pass difficulty level
            custom_instructions,  # Pass custom instructions
            mcq_options_count  # Pass MCQ options count
        )

        try:
            # Use display name for custom sections in logging
            log_name = section_config.get('display_name', section_type) if section_config.get('is_custom') else section_type
            print(f"🤖 Generating {log_name} questions in {exam_language} using Groq...")
            if syllabus:
                print(f"📚 Using custom syllabus: {syllabus[:100]}...")
            
            # Using Groq chat completion
            response = self.client.chat.completions.create(
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                model=self.model_name,
                temperature=self.temperature,
            )

            response_text = response.choices[0].message.content

            # Clean the response to extract JSON
            response_text = self._clean_json_response(response_text)

            # Parse JSON
            questions = json.loads(response_text)

            # Validate the structure
            if not self._validate_questions_structure(questions, section_config):
                print(f"❌ Questions structure validation failed for {section_type}")
                raise ValueError(f"Invalid questions structure received for {section_type}")

            print(f"✅ {log_name.title()} questions generated successfully in {exam_language}!")
            return questions

        except json.JSONDecodeError as e:
            print(f"❌ JSON parsing error for {log_name}: {str(e)}")
            print(f"Raw response: {response_text[:500] if 'response_text' in locals() else 'No response'}...")
            return None
        except Exception as e:
            print(f"❌ Error generating {log_name} questions: {str(e)}")
            return None

    def evaluate_subjective_answer(self, question: Dict, candidate_answer: str) -> Dict:
        """Evaluate short/essay answer using Groq with API key failover"""
        if not candidate_answer.strip():
            return {
                'marks_awarded': 0,
                'feedback': 'No answer provided.',
                'strengths': '',
                'improvements': 'Answer was not provided by the candidate.',
                'evaluation_details': 'Answer was not provided by the candidate.',
                'ai_evaluated': True,
                'needs_manual_review': False
            }

        # Determine section context for better evaluation
        section_context = self._get_section_context(question.get('section_type'))

        evaluation_prompt = f"""
        You are an expert examiner evaluating a {question.get('section_type', 'technical')} question. {section_context}

        QUESTION: {question['question']}
        QUESTION TYPE: {question['type']}
        TOTAL MARKS: {question['marks']}
        SECTION: {question.get('section_type', 'technical').upper()}

        EXPECTED ANSWER: {question.get('expected_answer', 'Not provided')}
        EVALUATION CRITERIA: {question.get('evaluation_criteria', 'Standard evaluation criteria')}

        CANDIDATE'S ANSWER: {candidate_answer}

        Please evaluate this answer and provide:
        1. Marks out of {question['marks']} (as a number)
        2. Detailed feedback explaining the marks awarded
        3. Areas where the answer could be improved

        Format your response as JSON:
        {{
            "marks_awarded": <number between 0 and {question['marks']}>,
            "feedback": "Detailed feedback explaining the evaluation",
            "strengths": "What the candidate did well",
            "improvements": "Areas for improvement"
        }}

        Be fair but thorough in your evaluation. Consider accuracy, completeness, clarity, and relevance.
        """

        # Try evaluation with failover support
        max_attempts = 2  # 2 attempts (primary + backup if needed)
        failover_attempted = False

        for attempt in range(max_attempts):
            try:
                key_info = "(backup key)" if self.using_backup else "(primary key)"
                print(f"🤖 AI evaluating {question['type']} question (max marks: {question['marks']}) {key_info}...")

                response = self.client.chat.completions.create(
                    messages=[
                        {
                            "role": "user",
                            "content": evaluation_prompt,
                        }
                    ],
                    model=self.model_name,
                    temperature=self.temperature,
                )

                # Clean and parse response
                response_text = self._clean_json_response(response.choices[0].message.content)
                evaluation = json.loads(response_text)

                # Validate marks
                marks_awarded = min(max(0, evaluation.get('marks_awarded', 0)), question['marks'])
                evaluation['marks_awarded'] = marks_awarded
                evaluation['ai_evaluated'] = True
                evaluation['needs_manual_review'] = False

                print(f"✅ AI evaluation successful: {marks_awarded}/{question['marks']} marks")

                return evaluation

            except json.JSONDecodeError as e:
                print(f"❌ AI response JSON parsing error: {str(e)}")
                print(f"   Raw response: {response_text[:200] if 'response_text' in locals() else 'No response'}...")
                # JSON parsing errors are not quota errors, don't failover for these
                return {
                    'marks_awarded': 0,
                    'feedback': 'AI evaluation failed (invalid response format). This answer needs manual review by admin.',
                    'strengths': '',
                    'improvements': 'Automatic evaluation failed due to parsing error.',
                    'evaluation_details': f'JSON parsing error: {str(e)}',
                    'ai_evaluated': False,
                    'needs_manual_review': True
                }

            except Exception as e:
                print(f"❌ AI evaluation error: {str(e)}")

                # Check if this is a quota error and we haven't tried failover yet
                if self._is_quota_error(e) and not failover_attempted:
                    print(f"🔴 Quota/rate limit error detected during evaluation")
                    if self._switch_to_backup_key():
                        failover_attempted = True
                        print(f"🔄 Retrying evaluation with backup API key...")
                        continue  # Retry with backup key

                # Fallback - needs manual review, award 0 marks until reviewed
                return {
                    'marks_awarded': 0,
                    'feedback': 'AI evaluation failed. This answer needs manual review by admin.',
                    'strengths': '',
                    'improvements': 'Automatic evaluation failed. Please review manually.',
                    'evaluation_details': f'Error: {str(e)}',
                    'ai_evaluated': False,
                    'needs_manual_review': True
                }

        # Should not reach here, but just in case
        return {
            'marks_awarded': 0,
            'feedback': 'AI evaluation failed after all attempts. This answer needs manual review by admin.',
            'strengths': '',
            'improvements': 'Automatic evaluation failed after exhausting all API keys.',
            'evaluation_details': 'All API key attempts exhausted',
            'ai_evaluated': False,
            'needs_manual_review': True
        }

    def _clean_json_response(self, response_text: str) -> str:
        """Clean and fix common JSON formatting issues"""
        # Remove markdown code blocks
        if response_text.startswith('```json'):
            response_text = response_text[7:]
        if response_text.startswith('```'):
            response_text = response_text[3:]
        if response_text.endswith('```'):
            response_text = response_text[:-3]
        
        # Strip whitespace
        response_text = response_text.strip()
        
        # Fix trailing commas in arrays and objects
        response_text = re.sub(r',(\s*[}\]])', r'\1', response_text)
        
        # Fix any double commas
        response_text = re.sub(r',,+', r',', response_text)
        
        # Ensure proper JSON structure starts with [ and ends with ] OR starts with { and ends with } (for objects)
        # Note: Previous implementation might have been tailored for array only response for questions, 
        # but evaluation returns object.
        
        # Try to find start/end of JSON structure if potential garbage around it
        if not (response_text.startswith('[') or response_text.startswith('{')):
            start_arr = response_text.find('[')
            start_obj = response_text.find('{')
            
            if start_arr != -1 and (start_obj == -1 or start_arr < start_obj):
                response_text = response_text[start_arr:]
            elif start_obj != -1:
                response_text = response_text[start_obj:]
        
        if not (response_text.endswith(']') or response_text.endswith('}')):
            end_arr = response_text.rfind(']')
            end_obj = response_text.rfind('}')
            
            if end_arr != -1 and (end_obj == -1 or end_arr > end_obj):
                response_text = response_text[:end_arr + 1]
            elif end_obj != -1:
                response_text = response_text[:end_obj + 1]
        
        return response_text

    def _create_section_prompt(self, department: str, position: str, section_type: str,
                              mcq_count: int, multi_select_count: int, short_count: int, essay_count: int,
                              mcq_marks: int, short_marks: int, essay_marks: int,
                              syllabus: str = "", exam_language: str = 'english',
                              section_config: Dict = None,
                              difficulty_level: str = 'medium',
                              custom_instructions: str = '',
                              mcq_options_count: int = 4) -> str:
        """Create appropriate prompt based on section type with language specification, difficulty level, multi-select MCQ support, custom instructions, and variable options count"""

        # Determine the target language for questions
        if section_type == 'bengali':
            target_language = 'bengali'
            language_instruction = \"""
            📤 CRITICAL LANGUAGE REQUIREMENT: ALL questions, options, and explanations MUST be written in BENGALI language.
            Use proper Bengali script (বাংলা) for all content in this section.
            \"""
        elif section_type == 'english':
            target_language = 'english'
            language_instruction = \"""
            📤 CRITICAL LANGUAGE REQUIREMENT: ALL questions, options, and explanations MUST be written in ENGLISH language.
            This section tests English language proficiency, so use proper English for all content.
            \"""
        else:
            target_language = exam_language
            if exam_language == 'bengali':
                language_instruction = \"""
                📤 CRITICAL LANGUAGE REQUIREMENT: ALL questions, options, and explanations MUST be written in BENGALI language.
                Use proper Bengali script (বাংলা) for all content. This is a Bengali language exam.
                \"""
            else:
                language_instruction = \"""
                📤 CRITICAL LANGUAGE REQUIREMENT: ALL questions, options, and explanations MUST be written in ENGLISH language.
                Use proper English for all content. This is an English language exam.
                \"""

        # Get section description (pass section_config for custom sections)
        section_description = self._get_section_description(section_type, department, position, section_config)

        # For custom sections, use display_name in the prompt
        display_section_name = section_type.upper()
        if section_config and section_config.get('is_custom'):
            display_section_name = section_config.get('display_name', 'Custom Section').upper()

        # Difficulty level instruction
        difficulty_instructions = {
            'easy': \"""
            🟢 DIFFICULTY LEVEL: EASY
            - Questions should test basic knowledge and fundamental concepts
            - Use straightforward language and clear scenarios
            - MCQ options should be clearly distinguishable
            - Focus on recall and basic understanding
            - Suitable for entry-level candidates or freshers
            \""",
            'medium': \"""
            🟡 DIFFICULTY LEVEL: MEDIUM
            - Questions should test intermediate understanding and application
            - Include scenarios that require applying knowledge to solve problems
            - MCQ options should require careful thinking to differentiate
            - Balance between knowledge recall and practical application
            - Suitable for candidates with 1-3 years of experience
            \""",
            'hard': \"""
            🔴 DIFFICULTY LEVEL: HARD
            - Questions should test advanced concepts and deep understanding
            - Include complex scenarios requiring analysis and critical thinking
            - MCQ options should be challenging with subtle differences
            - Focus on problem-solving, analysis, and evaluation
            - Include edge cases and real-world complex scenarios
            - Suitable for senior/experienced candidates
            \""",
            'mixed': \"""
            🎯 DIFFICULTY LEVEL: MIXED (Progressive)
            - Include a mix of easy, medium, and hard questions
            - Start with easier questions and progressively increase difficulty
            - Distribution: approximately 30% easy, 40% medium, 30% hard
            - This provides a comprehensive assessment across all competency levels
            \"""
        }
        difficulty_instruction = difficulty_instructions.get(difficulty_level, difficulty_instructions['medium'])

        # Custom instructions from admin
        admin_instructions = ""
        if custom_instructions and custom_instructions.strip():
            admin_instructions = f\"""

            📋 ADMIN'S CUSTOM INSTRUCTIONS (IMPORTANT):
            {custom_instructions.strip()}

            ⚠️ Please follow these custom instructions provided by the exam administrator when generating questions.
            \"""

        # Enhanced custom syllabus handling
        syllabus_instruction = ""
        if syllabus.strip():
            syllabus_instruction = f\"""

            🎯 CUSTOM SYLLABUS/REQUIREMENTS (HIGHEST PRIORITY):
            {syllabus.strip()}

            ⚠️ CRITICAL INSTRUCTION: All questions MUST be based primarily on the custom syllabus above.
            The syllabus topics take HIGHEST PRIORITY over general section descriptions.
            Focus specifically on the topics, technologies, and requirements mentioned in the custom syllabus.
            Ensure every question directly relates to the specified syllabus content.
            \"""

        # Build multi-select instruction if needed
        multi_select_instruction = ""
        min_correct_for_multi = min(3, mcq_options_count - 1)  # At least 2 correct, max 3 or options-1
        if multi_select_count > 0:
            multi_select_instruction = f\"""
        - {multi_select_count} Multi-Select MCQ (questions with multiple correct answers) - {mcq_marks} marks each
          ⚠️ For multi-select MCQs: Set "is_multi_select": true and provide "correct_answers" as an array of indices (e.g., [0, 2])
          Multi-select questions should have 2-{min_correct_for_multi} correct options out of {mcq_options_count}.\"""

        # Generate dynamic option letters and example options based on mcq_options_count
        option_letters = ['A', 'B', 'C', 'D', 'E', 'F'][:mcq_options_count]
        example_options = ', '.join([f'\"Option {letter}\"' for letter in option_letters])
        valid_indices = ', '.join([str(i) for i in range(mcq_options_count)])
        example_correct_indices = [0, min(2, mcq_options_count - 1)]  # First and third (or last) option

        prompt = f\"""
        Create an exam section for {display_section_name} SKILLS for the position of {position} in the {department} department.

        {language_instruction}

        {difficulty_instruction}
        {admin_instructions}

        Generate exactly:
        - {mcq_count} Single-Answer MCQ (Multiple Choice Questions with ONE correct answer) - {mcq_marks} marks each{multi_select_instruction}
        - {short_count} Short Answer Questions - {short_marks} marks each
        - {essay_count} Essay/Long Answer Questions - {essay_marks} marks each

        {section_description}
        {syllabus_instruction}

        🔥 CRITICAL JSON FORMAT REQUIREMENTS:
        1. Return ONLY a valid JSON array, nothing else
        2. NO trailing commas in arrays or objects
        3. ALL strings must be properly escaped
        4. Use the EXACT structure shown below
        5. Keep content concise but meaningful
        6. For essay questions, keep expected_answer under 500 words
        7. Mix single-answer and multi-select MCQs randomly (do NOT group them together)

        🔢 MCQ OPTIONS REQUIREMENT:
        Each MCQ question MUST have exactly {mcq_options_count} options (labeled {', '.join(option_letters)}).

        Format your response as a JSON array with this exact structure:
        [
            {{
                "type": "mcq",
                "question": "Single-answer question text here",
                "options": [{example_options}],
                "correct_answer": 0,
                "is_multi_select": false,
                "marks": {mcq_marks},
                "explanation": "Brief explanation of why this is correct"
            }},
            {{
                "type": "mcq",
                "question": "Multi-select question text here (select all that apply)",
                "options": [{example_options}],
                "correct_answers": {example_correct_indices},
                "is_multi_select": true,
                "marks": {mcq_marks},
                "explanation": "Brief explanation of why these options are correct"
            }},
            {{
                "type": "short",
                "question": "Short answer question text here",
                "marks": {short_marks},
                "expected_answer": "Expected answer or key points",
                "evaluation_criteria": "Criteria for evaluating the answer"
            }},
            {{
                "type": "essay",
                "question": "Essay question text here",
                "marks": {essay_marks},
                "expected_answer": "Expected answer structure and key points (keep under 500 words)",
                "evaluation_criteria": "Detailed criteria for evaluating the essay"
            }}
        ]

        IMPORTANT REQUIREMENTS:
        - ALL content must be in {target_language.upper()} language as specified above
        - Each MCQ MUST have exactly {mcq_options_count} options
        - For SINGLE-ANSWER MCQs: Set "is_multi_select": false and "correct_answer" as index ({valid_indices})
        - For MULTI-SELECT MCQs: Set "is_multi_select": true and "correct_answers" as array of indices (e.g., {example_correct_indices})
        - Multi-select questions should clearly indicate "(select all that apply)" or similar in the question text
        - Mix single-answer and multi-select MCQs randomly throughout the questions
        - For short and essay questions, provide clear evaluation criteria
        - Questions should test different competency levels (knowledge, application, analysis)
        - Ensure cultural sensitivity and professional appropriateness
        - NO trailing commas anywhere in the JSON
        - Keep essay expected_answer concise (under 500 words)
        {"- Every question must directly relate to the specified syllabus content" if syllabus.strip() else ""}

        🔥 CRITICAL:
        1. The language requirement is NON-NEGOTIABLE. Use {target_language.upper()} language for ALL content.
        2. Return only valid JSON - no markdown, no extra text, no code blocks.
        3. Ensure no trailing commas in any arrays or objects.
        4. Generate exactly {mcq_count} single-answer MCQs and {multi_select_count} multi-select MCQs.
        5. Each MCQ MUST have exactly {mcq_options_count} options - no more, no less.

        Return only the JSON array, no additional text or formatting.
        \"""
        
        return prompt

    def _get_section_description(self, section_type: str, department: str, position: str, section_config: Dict = None) -> str:
        """Get section description based on type, with support for custom sections"""
        descriptions = {
            'technical': f\"""
            Technical skills and knowledge specific to {position} in {department}:
            - Programming concepts, algorithms, and data structures
            - System design and architecture
            - Industry best practices and methodologies
            - Tools and technologies used in {department}
            - Problem-solving scenarios relevant to {position}
            - Current trends and challenges in {department}
            \""",
            'english': \"""
            English Language Proficiency:
            - Grammar and sentence structure
            - Vocabulary and word usage
            - Reading comprehension
            - Writing skills and communication
            - Business English and professional communication
            - Spelling and punctuation
            \""",
            'mathematics': \"""
            Mathematics and Quantitative Skills:
            - Basic arithmetic and algebra
            - Statistics and probability
            - Logical reasoning and problem solving
            - Data interpretation and analysis
            - Mathematical concepts relevant to the workplace
            - Numerical reasoning
            \""",
            'bengali': \"""
            Bengali Language Skills:
            - Grammar and sentence construction (ব্যাকরণ এবং বাক্য গঠন)
            - Vocabulary and comprehension (শব্দভাণ্ডার এবং বোধগম্যতা)
            - Bengali literature basics (বাংলা সাহিত্যের মূল বিষয়)
            - Translation skills (অনুবাদ দক্ষতা)
            - Professional Bengali communication (পেশাদার বাংলা যোগাযোগ)
            - Cultural and linguistic knowledge (সাংস্কৃতিক ও ভাষাগত জ্ঞান)
            \""",
            'general_knowledge': \"""
            General Knowledge and Current Affairs:
            - Current events and news (local and international)
            - History, geography, and culture
            - Science and technology awareness
            - Sports and entertainment
            - Government and politics
            - Business and economics basics
            \""",
            'logical_reasoning': \"""
            Logical Reasoning and Intelligence:
            - Pattern recognition and sequences
            - Analytical thinking and problem solving
            - Critical thinking skills
            - Decision making scenarios
            - Abstract reasoning
            \"""
        }

        # Check if this is a custom section
        if section_config and section_config.get('is_custom'):
            display_name = section_config.get('display_name', 'Custom Section')
            return f\"""
            Custom Section: {display_name}
            This is a custom section for {position} in {department}.
            Generate questions based on the syllabus/requirements provided.
            Focus on practical knowledge and professional skills relevant to this custom topic.
            \"""

        return descriptions.get(section_type, f\"""
        Professional Skills for {position}:
        - Industry knowledge and best practices
        - Professional ethics and communication
        - Problem-solving and analytical thinking
        - Leadership and teamwork skills
        - Project management basics
        - Relevant subject matter expertise
        \""")

    def _get_section_context(self, section_type: str) -> str:
        """Get evaluation context for different sections"""
        contexts = {
            'english': "Focus on grammar, vocabulary, communication skills, and language proficiency.",
            'mathematics': "Focus on mathematical accuracy, problem-solving approach, and correct calculations.",
            'bengali': "Focus on Bengali language skills, grammar, and cultural understanding.",
            'general_knowledge': "Focus on factual accuracy and breadth of knowledge.",
            'logical_reasoning': "Focus on logical thinking, problem-solving approach, and reasoning skills."
        }

        # For custom sections (starting with 'custom_'), use generic professional context
        if section_type.startswith('custom_'):
            return "Focus on accuracy, completeness, and professional knowledge relevant to this custom section."

        return contexts.get(section_type, "Focus on technical accuracy and professional knowledge.")

    def _validate_questions_structure(self, questions: List[Dict], section_config: Dict) -> bool:
        """Validate that the questions have the correct structure including multi-select MCQs"""
        try:
            if not isinstance(questions, list):
                print(f"❌ Questions is not a list: {type(questions)}")
                return False

            # Count different question types
            all_mcqs = [q for q in questions if q.get('type') == 'mcq']
            single_select_mcqs = [q for q in all_mcqs if not q.get('is_multi_select', False)]
            multi_select_mcqs = [q for q in all_mcqs if q.get('is_multi_select', False)]
            short_count = len([q for q in questions if q.get('type') == 'short'])
            essay_count = len([q for q in questions if q.get('type') == 'essay'])

            expected_single_mcq = section_config.get('mcq_count', 0)
            expected_multi_mcq = section_config.get('multi_select_count', 0)
            expected_short = section_config.get('short_count', 0)
            expected_essay = section_config.get('essay_count', 0)

            # Check total count matches
            total_expected = expected_single_mcq + expected_multi_mcq + expected_short + expected_essay
            if len(questions) != total_expected:
                print(f"❌ Total question count mismatch: Expected {total_expected}, Got {len(questions)}")
                return False

            # More flexible count validation - allow slight variations
            # Total MCQ count should match (single + multi)
            total_mcq_expected = expected_single_mcq + expected_multi_mcq
            total_mcq_got = len(all_mcqs)
            mcq_diff = abs(total_mcq_got - total_mcq_expected)
            short_diff = abs(short_count - expected_short)
            essay_diff = abs(essay_count - expected_essay)

            if mcq_diff > 1 or short_diff > 1 or essay_diff > 1:
                print(f"❌ Count mismatch: Expected MCQ:{total_mcq_expected} (single:{expected_single_mcq}, multi:{expected_multi_mcq}), Short:{expected_short}, Essay:{expected_essay}")
                print(f"❌ Got MCQ:{total_mcq_got} (single:{len(single_select_mcqs)}, multi:{len(multi_select_mcqs)}), Short:{short_count}, Essay:{essay_count}")
                return False

            # Validate each question structure
            for i, q in enumerate(questions):
                if not isinstance(q, dict):
                    print(f"❌ Question {i} is not a dict: {type(q)}")
                    return False

                required_keys = ['type', 'question', 'marks']
                if not all(key in q for key in required_keys):
                    print(f"❌ Missing required keys in question {i}: {q.keys()}")
                    return False

                if q['type'] == 'mcq':
                    if 'options' not in q:
                        print(f"❌ MCQ missing options: {q.keys()}")
                        return False

                    # Get expected options count from instance variable (2-6 range)
                    expected_options_count = getattr(self, '_mcq_options_count', 4)
                    valid_indices = list(range(expected_options_count))

                    # Allow options count within valid range (2-6) and matching expected count
                    options_count = len(q['options']) if isinstance(q['options'], list) else 0
                    if not isinstance(q['options'], list) or options_count < 2 or options_count > 6:
                        print(f"❌ MCQ options invalid (must be 2-6 options): {q.get('options', 'missing')}")
                        return False

                    # Check for multi-select vs single-select MCQ
                    is_multi = q.get('is_multi_select', False)
                    actual_valid_indices = list(range(options_count))  # Use actual options count for validation

                    if is_multi:
                        # Multi-select MCQ: should have correct_answers as array
                        if 'correct_answers' not in q:
                            print(f"❌ Multi-select MCQ missing correct_answers: {q.keys()}")
                            return False
                        if not isinstance(q['correct_answers'], list) or len(q['correct_answers']) < 2:
                            print(f"❌ Multi-select MCQ should have at least 2 correct answers: {q.get('correct_answers', 'missing')}")
                            return False
                        for ans in q['correct_answers']:
                            if not isinstance(ans, int) or ans not in actual_valid_indices:
                                print(f"❌ Multi-select MCQ correct_answers contains invalid index: {ans} (valid: {actual_valid_indices})")
                                return False
                    else:
                        # Single-select MCQ: should have correct_answer as int
                        if 'correct_answer' not in q:
                            print(f"❌ Single-select MCQ missing correct_answer: {q.keys()}")
                            return False
                        if not isinstance(q['correct_answer'], int) or q['correct_answer'] not in actual_valid_indices:
                            print(f"❌ MCQ correct_answer invalid: {q.get('correct_answer', 'missing')} (valid: {actual_valid_indices})")
                            return False

                elif q['type'] in ['short', 'essay']:
                    if 'expected_answer' not in q:
                        print(f"❌ {q['type']} missing expected_answer")
                        return False

            return True
            
        except Exception as e:
            print(f"❌ Validation error: {str(e)}")
            return False
