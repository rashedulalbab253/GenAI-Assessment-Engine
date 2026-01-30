
import sqlite3

def debug_database():
    conn = sqlite3.connect('exam_system.db')
    cursor = conn.cursor()
    
    # Check all records in exam_results
    cursor.execute("SELECT candidate_name FROM exam_results")
    results = cursor.fetchall()
    print("--- ALL CANDIDATES IN exam_results ---")
    for r in results:
        print(f"'{r[0]}'")
    
    # Check all records in live_sessions
    cursor.execute("SELECT candidate_name FROM live_sessions")
    live = cursor.fetchall()
    print("\n--- ALL CANDIDATES IN live_sessions ---")
    for r in live:
        print(f"'{r[0]}'")
        
    # Check all records in exam_sessions
    cursor.execute("SELECT candidate_name FROM exam_sessions")
    sessions = cursor.fetchall()
    print("\n--- ALL CANDIDATES IN exam_sessions ---")
    for r in sessions:
        print(f"'{r[0]}'")

    conn.close()

if __name__ == "__main__":
    debug_database()
