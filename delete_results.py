
import sqlite3

def clean_database():
    conn = sqlite3.connect('exam_system.db')
    cursor = conn.cursor()
    
    # Check tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]
    
    deleted_count = 0
    
    if 'exam_results' in tables:
        cursor.execute("PRAGMA table_info(exam_results)")
        columns = [row[1] for row in cursor.fetchall()]
        
        col_name = 'candidate_name' if 'candidate_name' in columns else None
        
        if col_name:
            # Count records before deletion
            target = '%enamul atiq%'
            cursor.execute(f"SELECT COUNT(*) FROM exam_results WHERE {col_name} LIKE ?", (target,))
            count = cursor.fetchone()[0]
            
            if count > 0:
                cursor.execute(f"DELETE FROM exam_results WHERE {col_name} LIKE ?", (target,))
                conn.commit()
                deleted_count = count
                print(f"DELETED_{count}_RECORDS_FROM_EXAM_RESULTS")
            else:
                print("NO_RESULTS_MATCHED")

    if 'live_sessions' in tables:
        cursor.execute("DELETE FROM live_sessions WHERE candidate_name LIKE ?", ('%enamul atiq%',))
        conn.commit()
        print("CLEANED_LIVE_SESSIONS")

    conn.close()
    print("FINISHED_CLEANING")

if __name__ == "__main__":
    clean_database()
