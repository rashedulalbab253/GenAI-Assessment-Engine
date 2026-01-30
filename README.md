# exam-system

## Setup Instructions

### Local Development

#### 1. Clone the Repository

```bash
git clone https://github.com/ACI-MIS-Team/ai-exam-system.git
cd ai-exam-system
```

#### 2. Create a Virtual Environment

**Windows:**
```bash
python -m venv .venv
.venv\Scripts\activate
```

**macOS/Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

#### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

#### 4. Set Up Environment Variables

Create a `.env` file in the project root with the following content:

```env
API_KEY = "Your_Gemini_API"
ADMIN_SECRET_KEY = "exam_admin_2025"
```

#### 5. Run the Application

Start the FastAPI application using Uvicorn:

```bash
uvicorn app:app --reload
```

This will:
- Start the development server
- Enable auto-reload for code changes
- Make the API available at http://localhost:8000

Access the API documentation at http://localhost:8000/docs

To run the app on a different port:

```bash
uvicorn app:app --reload --port 9275
```

Now the API available at http://localhost:9275

### Docker Setup

#### Running the Docker Compose

Run the container from your locally built image:

```bash
docker compose up -d
```

Make the API available at http://localhost:7894
