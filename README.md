# 🎓 Albab AI-Powered Exam System
By **Rashedul Albab**

A robust, scalable exam management system powered by AI (Groq's Llama 3) for automated evaluation of MCQs, short answers, and essay questions. Built with FastAPI, SQLite, and modern web technologies.

---

## 📋 Table of Contents

- [Features](#-features)
- [Architecture](#-architecture)
- [Tech Stack](#-tech-stack)
- [Docker & CI/CD](#🐳-docker--cicd)
- [Setup Instructions](#-setup-instructions)
  - [Local Development](#local-development)
  - [Docker Setup](#docker-setup)
- [Usage Guide](#-usage-guide)
- [Project Structure](#-project-structure)
- [API Documentation](#-api-documentation)
- [Key Components](#-key-components)
- [Contributing](#-contributing)
- [License](#-license)

---

## ✨ Features

### 🎯 Core Features
- **AI-Powered Evaluation**: Automated grading using Groq's Llama 3 70B model
- **Multiple Question Types**: MCQ (single/multi-select), short answer, and essay questions
- **Section-Based Exams**: Organize questions into sections with custom syllabi
- **Negative Marking**: Configurable negative marking per section
- **Real-Time Monitoring**: Admin dashboard for live session tracking
- **Resume Functionality**: Candidates can resume interrupted exams
- **Background Processing**: Queue-based evaluation system prevents server overload

### 🔒 Security & Reliability
- **Session Management**: Secure exam sessions with timeout protection
- **Server-Side Time Enforcement**: Prevents client-side time manipulation
- **Crash Recovery**: Automatic recovery of pending evaluations after server restart
- **Data Persistence**: SQLite with WAL mode for concurrent access
- **Thread-Safe Operations**: Safe concurrent exam submissions

### 📊 Admin Features
- **Exam Creation**: AI-generated or manual question creation
- **Multi-Language Support**: English and Bengali exam generation
- **Difficulty Levels**: Easy, Medium, Hard, Mixed
- **Custom Instructions**: Fine-tune AI question generation
- **Results Management**: View, filter, and export exam results
- **Live Session Tracking**: Monitor active exam sessions in real-time

### 👨‍🎓 Candidate Features
- **User-Friendly Interface**: Clean, responsive exam interface
- **Progress Tracking**: Visual progress indicators
- **Auto-Save**: Answers saved automatically
- **Result Lookup**: Check results using candidate ID
- **Detailed Feedback**: AI-generated feedback for subjective answers (optional)

---

## 🏗️ Architecture

```
┌─────────────────┐
│   Candidate     │
│   Interface     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐      ┌──────────────────┐
│   FastAPI App   │◄────►│  Admin Dashboard │
└────────┬────────┘      └──────────────────┘
         │
         ├──────────────┬──────────────┬─────────────┐
         ▼              ▼              ▼             ▼
┌─────────────┐  ┌─────────────┐  ┌──────────┐  ┌─────────┐
│   SQLite    │  │ Evaluation  │  │  Groq    │  │ Session │
│  Database   │  │    Queue    │  │   API    │  │ Manager │
└─────────────┘  └─────────────┘  └──────────┘  └─────────┘
```

### Key Components:
1. **FastAPI Application** (`app.py`): Main web server and API routes
2. **Database Layer** (`db.py`): SQLite operations and data persistence
3. **Evaluation Queue** (`evaluation_queue.py`): Background task processing with rate limiting
4. **Groq Analyzer** (`groq_analyzer.py`): AI-powered question generation and evaluation
5. **Utilities** (`utils.py`): Helper functions and session management

---

## 🛠️ Tech Stack

- **Backend**: FastAPI (Python 3.8+)
- **Database**: SQLite with WAL mode
- **AI/ML**: Groq API (Llama 3 70B)
- **Frontend**: Jinja2 Templates, HTML, CSS, JavaScript
- **Deployment**: Docker, Uvicorn
- **Queue System**: Custom priority queue with retry logic

---

## 🐳 Docker & CI/CD

This project is fully containerized and set up for automated deployment.

### **Docker Hub**
The official container image is available at:
`rashedulalbab1234/ai-exam-system:latest`

### **GitHub Actions (CI/CD)**
The project uses GitHub Actions to automatically build and push the Docker image to Docker Hub on every push to the `main` branch.

**To set up the CI/CD pipeline:**
1. Go to your GitHub Repository **Settings** > **Secrets and variables** > **Actions**.
2. Add the following **Repository secrets**:
   - `DOCKER_USERNAME`: Your Docker Hub username (`rashedulalbab1234`)
   - `DOCKER_PASSWORD`: Your Docker Hub Personal Access Token (PAT).

### **Running with Docker**
```bash
docker pull rashedulalbab1234/ai-exam-system:latest
docker run -p 8000:8000 --env-file .env rashedulalbab1234/ai-exam-system:latest
```

---

## 🚀 Setup Instructions

### Prerequisites
- Python 3.8 or higher
- pip (Python package manager)
- Groq API key ([Get one here](https://console.groq.com/keys))

---

### Local Development

#### 1️⃣ Clone the Repository

```bash
git clone https://github.com/ACI-MIS-Team/ai-exam-system.git
cd ai-exam-system
```

#### 2️⃣ Create a Virtual Environment

**Windows:**
```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```

**macOS/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

#### 3️⃣ Install Dependencies

```bash
pip install -r requirements.txt
```

#### 4️⃣ Set Up Environment Variables

Create a `.env` file in the project root:

```bash
# Windows
Copy-Item .env.example .env

# macOS/Linux
cp .env.example .env
```

Edit the `.env` file with your configuration:

```env
# Groq API Key (Required)
API_KEY="your_groq_api_key_here"

# Backup API Key (Optional)
API_KEY_BACKUP="your_backup_api_key_here"

# Admin Secret Key (Required)
ADMIN_SECRET_KEY="your_secure_admin_password"

# Server Configuration (Optional)
HOST=0.0.0.0
PORT=9004
```

**Get your Groq API key:**
1. Visit [https://console.groq.com/keys](https://console.groq.com/keys)
2. Sign up or log in
3. Create a new API key
4. Copy and paste it into your `.env` file

#### 5️⃣ Run the Application

**Standard mode (port 8000):**
```bash
uvicorn app:app --reload
```

**Custom port:**
```bash
uvicorn app:app --reload --port 9275
```

**Production mode (no auto-reload):**
```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

#### 6️⃣ Access the Application

- **Candidate Interface**: [http://localhost:8000](http://localhost:8000)
- **Admin Login**: [http://localhost:8000/admin/login](http://localhost:8000/admin/login)
- **API Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)

---

### Docker Setup

#### 1️⃣ Using Docker Compose (Recommended)

```bash
# Build and start the container
docker compose up -d

# View logs
docker logs -f ai_exam_system

# Stop the container
docker compose down
```

The application will be available at: **http://localhost:7894**

#### 2️⃣ Using Makefile (Quick Commands)

```bash
# Start with Docker
make docker-up

# View logs
make docker-logs

# Push to Git (custom command)
make git-push
```

#### 3️⃣ Manual Docker Build

```bash
# Build the image
docker build -t ai-exam-system .

# Run the container
docker run -d -p 7894:9004 --name ai_exam_system ai-exam-system

# View logs
docker logs -f ai_exam_system
```

---

## 📖 Usage Guide

### For Administrators

1. **Login**: Navigate to `/admin/login` and enter your admin secret key
2. **Create Exam**: 
   - Choose AI generation or manual creation
   - Configure sections, time limits, and marking schemes
   - Generate questions using AI or add manually
3. **Share Exam Link**: Copy the unique exam link and share with candidates
4. **Monitor Sessions**: View live exam sessions in the admin dashboard
5. **Review Results**: Access detailed results with AI-generated feedback

### For Candidates

1. **Access Exam**: Open the exam link provided by the administrator
2. **Enter Details**: Provide your name and candidate ID
3. **Take Exam**: Answer questions (auto-saved)
4. **Submit**: Submit when complete or when time expires
5. **View Results**: Use your candidate ID to look up results

---

## 📁 Project Structure

```
ai-exam-system/
├── app.py                    # Main FastAPI application
├── db.py                     # Database operations
├── evaluation_queue.py       # Background evaluation queue
├── groq_analyzer.py          # AI question generation & evaluation
├── utils.py                  # Helper functions
├── main.py                   # Entry point
├── requirements.txt          # Python dependencies
├── Dockerfile                # Docker configuration
├── docker-compose.yml        # Docker Compose setup
├── Makefile                  # Quick commands
├── .env.example              # Environment variables template
├── templates/                # HTML templates
│   ├── admin_dashboard.html
│   ├── create_exam.html
│   ├── exam_page.html
│   └── ...
└── exam_system.db            # SQLite database (auto-generated)
```

---

## 🔌 API Documentation

Once the application is running, visit `/docs` for interactive API documentation (Swagger UI).

### Key Endpoints:

**Candidate Routes:**
- `GET /` - Home page
- `GET /exam/{exam_link}` - Exam start page
- `POST /exam/{exam_link}/start` - Start exam session
- `POST /exam/submit` - Submit exam answers
- `GET /results/{result_id}` - View results

**Admin Routes:**
- `GET /admin/login` - Admin login page
- `GET /admin` - Admin dashboard
- `POST /admin/create-exam` - Create new exam
- `GET /admin/exam/{exam_id}` - View exam details
- `GET /admin/results` - View all results

---

## 🔑 Key Components

### 1. Evaluation Queue System

The `evaluation_queue.py` implements a sophisticated background processing system:

- **Rate Limiting**: Prevents API quota exhaustion (configurable requests/minute)
- **Retry Logic**: Exponential backoff with up to 5 retries
- **Long Retries**: Additional 6 retries with 10-minute delays for persistent failures
- **Priority Queue**: Processes tasks by priority
- **Crash Recovery**: Recovers pending evaluations from database on restart
- **Status Tracking**: Real-time status updates (pending → processing → completed/failed)

### 2. Database Schema

**Main Tables:**
- `exams` - Exam metadata and configuration
- `questions` - All question types with answers
- `exam_sessions` - Active and completed exam sessions
- `exam_results` - Submitted answers and evaluations
- `live_sessions` - Real-time session monitoring

### 3. Session Management

- **Thread-Safe**: Uses locks for concurrent access
- **Timeout Protection**: Automatic session expiration
- **Resume Support**: Candidates can continue interrupted exams
- **Server-Side Validation**: Time limits enforced on server

---

## 🤝 Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **Groq** for providing the powerful Llama 3 70B API
- **FastAPI** for the excellent web framework
- **SQLite** for reliable data persistence

---

## 📞 Support

For issues, questions, or suggestions:
- Open an issue on GitHub
- Contact the development team

---

**Made with ❤️ by Rashedul Albab**
