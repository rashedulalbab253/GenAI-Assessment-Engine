
import sqlite3

def clean_database():
    conn = sqlite3.connect('exam_system.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]
    
    deleted_count = 0
    
    # Try multiple variations and case-insensitive search
    search_term = '%enamul%'
    
    if 'exam_results' in tables:
        cursor.execute(f"DELETE FROM exam_results WHERE candidate_name LIKE ?", (search_term,))
        deleted_count = cursor.rowcount
        conn.commit()
        print(f"DELETED_{deleted_count}_RECORDS_FROM_EXAM_RESULTS")

    if 'live_sessions' in tables:
        cursor.execute("DELETE FROM live_sessions WHERE candidate_name LIKE ?", (search_term,))
        print(f"DELETED_{cursor.rowcount}_RECORDS_FROM_LIVE_SESSIONS")
        conn.commit()

    conn.close()
    print("FINISHED_CLEANING")

if __name__ == "__main__":
    clean_database()
