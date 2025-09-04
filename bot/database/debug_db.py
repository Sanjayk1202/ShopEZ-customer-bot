import sqlite3
from db_connector import db

def debug_database():
    print("=== DATABASE DEBUG INFORMATION ===")
    
    # Check if database file exists
    import os
    db_path = "data/shopez.db"
    print(f"Database path: {db_path}")
    print(f"Database exists: {os.path.exists(db_path)}")
    
    if os.path.exists(db_path):
        # Connect to database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # List all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        print(f"\nTables in database: {[table[0] for table in tables]}")
        
        # Check users table
        if 'users' in [table[0] for table in tables]:
            cursor.execute("SELECT COUNT(*) FROM users")
            user_count = cursor.fetchone()[0]
            print(f"Number of users: {user_count}")
            
            cursor.execute("SELECT * FROM users")
            users = cursor.fetchall()
            print(f"Users: {users}")
        
        # Check user_sessions table
        if 'user_sessions' in [table[0] for table in tables]:
            cursor.execute("SELECT COUNT(*) FROM user_sessions")
            session_count = cursor.fetchone()[0]
            print(f"Number of sessions: {session_count}")
            
            cursor.execute("SELECT * FROM user_sessions")
            sessions = cursor.fetchall()
            print(f"Sessions: {sessions}")
        
        conn.close()
    
    print("\n=== SESSION VALIDATION TEST ===")
    
    # Test session validation
    session_token = "test_session_123"
    user = db.validate_session(session_token)
    print(f"Session validation for {session_token}: {user}")

if __name__ == "__main__":
    debug_database()