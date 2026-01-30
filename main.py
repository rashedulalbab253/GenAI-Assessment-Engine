#!/usr/bin/env python3
"""
Main entry point for the AI-based Exam System
Handles uvicorn server startup and background evaluation worker
"""

import uvicorn
import os
import signal
import sys
import atexit
from dotenv import load_dotenv


def start_evaluation_worker():
    """Start the background evaluation worker"""
    try:
        from app import evaluation_queue
        if evaluation_queue:
            evaluation_queue.start()
            print("✅ Background evaluation worker started")
            return evaluation_queue
    except Exception as e:
        print(f"⚠️ Could not start evaluation worker: {e}")
    return None


def stop_evaluation_worker(queue):
    """Stop the background evaluation worker gracefully"""
    if queue:
        print("🛑 Stopping background evaluation worker...")
        queue.stop()
        print("✅ Background evaluation worker stopped")


def main():
    """Main function to start the FastAPI server with background worker"""
    load_dotenv()

    # Verify required environment variables
    required_vars = ["API_KEY", "ADMIN_SECRET_KEY"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]

    if missing_vars:
        print(f"Error: Missing required environment variables: {', '.join(missing_vars)}")
        print("Please set these variables in your .env file")
        return

    # Get server configuration from environment variables with defaults
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", "true").lower() == "true"
    log_level = os.getenv("LOG_LEVEL", "info")

    print("=" * 60)
    print("🎓 AI-based Exam System with Background Evaluation")
    print("=" * 60)
    print(f"🌐 Server: http://{host}:{port}")
    print(f"👤 Admin panel: http://{host}:{port}/admin")
    print(f"❤️  Health check: http://{host}:{port}/health")
    print(f"🔄 Reload mode: {reload}")
    print("=" * 60)
    print("")
    print("📋 Background Evaluation Queue Features:")
    print("   • Rate limiting: 10 API calls/minute (prevents quota exhaustion)")
    print("   • Automatic retries with exponential backoff")
    print("   • Candidates can leave after submission - answers are safe!")
    print("   • Results available when evaluation completes")
    print("=" * 60)
    print("")

    # Note: When using reload=True, the worker is started inside the app
    # When reload=False, we could start it here, but app.py handles it
    if not reload:
        print("💡 Starting in production mode (no auto-reload)")

    uvicorn.run(
        "app:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level
    )


if __name__ == "__main__":
    main()