
import sqlite3

def clean_database():
    conn = sqlite3.connect('exam_system.db')
    cursor = conn.cursor()
    
    tables = ['exam_results', 'live_sessions', 'exam_sessions']
    search_terms = ['%enamul%', '%atiq%', '%enam%']
    
    total_deleted = 0
    
    for table in tables:
        try:
            for term in search_terms:
                cursor.execute(f"DELETE FROM {table} WHERE candidate_name LIKE ?", (term,))
                total_deleted += cursor.rowcount
            conn.commit()
            print(f"Cleaned {table}")
        except Exception as e:
            print(f"Error cleaning {table}: {e}")

    conn.close()
    print(f"TOTAL_DELETED: {total_deleted}")

if __name__ == "__main__":
    clean_database()
