import sqlite3
import json
from typing import Dict, Any, List
import bcrypt
import uuid
import os
from datetime import datetime, timedelta

class DatabaseConnector:
    def __init__(self, db_path: str = "data/shopez.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_database()

    def _init_database(self):
        """Initialize database tables with proper schema migration"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create users table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            first_name TEXT,
            last_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Create conversations table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            message TEXT NOT NULL,
            response TEXT NOT NULL,
            intent TEXT,
            entities TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Create user_sessions table with proper schema
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            session_id TEXT UNIQUE NOT NULL,
            current_state TEXT,
            context TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP
        )
        ''')
        
        conn.commit()
        conn.close()

    def _hash_password(self, password: str) -> str:
        """Hash a password using bcrypt"""
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')

    def _verify_password(self, password: str, hashed_password: str) -> bool:
        """Verify a password against its hash"""
        try:
            return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))
        except (ValueError, TypeError):
            return False

    def register_user(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Register a new user with password hashing"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Generate unique user ID
            user_id = f"CUST-{str(uuid.uuid4())[:8].upper()}"
            
            # Hash password
            hashed_password = self._hash_password(user_data['password'])
            
            cursor.execute('''
            INSERT INTO users (user_id, username, email, password_hash, first_name, last_name)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                user_id,
                user_data['username'],
                user_data['email'],
                hashed_password,
                user_data.get('first_name', ''),
                user_data.get('last_name', '')
            ))
            
            conn.commit()
            
            return {
                "user_id": user_id,
                "username": user_data['username'],
                "email": user_data['email'],
                "first_name": user_data.get('first_name', ''),
                "last_name": user_data.get('last_name', '')
            }
            
        except sqlite3.IntegrityError as e:
            if "username" in str(e):
                raise ValueError("Username already exists")
            elif "email" in str(e):
                raise ValueError("Email already exists")
            raise ValueError("Registration failed")
        finally:
            conn.close()

    def authenticate_user(self, username: str, password: str) -> Dict[str, Any]:
        """Authenticate user with username and password"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT user_id, username, email, password_hash, first_name, last_name 
        FROM users WHERE username = ? OR email = ?
        ''', (username, username))
        
        row = cursor.fetchone()
        conn.close()
        
        if row and self._verify_password(password, row[3]):
            return {
                "user_id": row[0],
                "username": row[1],
                "email": row[2],
                "first_name": row[4],
                "last_name": row[5]
            }
        return None

    def get_user_by_id(self, user_id: str) -> Dict[str, Any]:
        """Get user by user_id"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT user_id, username, email, first_name, last_name 
        FROM users WHERE user_id = ?
        ''', (user_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "user_id": row[0],
                "username": row[1],
                "email": row[2],
                "first_name": row[3],
                "last_name": row[4]
            }
        return None

    def create_session(self, user_id: str, session_id: str) -> bool:
        """Create a new user session"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Set session to expire in 24 hours
            expires_at = datetime.now() + timedelta(hours=24)
            
            cursor.execute('''
            INSERT INTO user_sessions (user_id, session_id, expires_at)
            VALUES (?, ?, ?)
            ''', (user_id, session_id, expires_at))
            
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def validate_session(self, session_id: str) -> Dict[str, Any]:
        """Validate a user session"""
        if not session_id:
            return None
            
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Use SQLite's CURRENT_TIMESTAMP for proper comparison
            cursor.execute('''
            SELECT user_id, expires_at FROM user_sessions 
            WHERE session_id = ? AND expires_at > CURRENT_TIMESTAMP
            ''', (session_id,))
            
            row = cursor.fetchone()
            if row:
                user_id = row[0]
                expires_at = row[1]
                print(f"Session valid for user {user_id}, expires at {expires_at}")
                
                # Update last activity
                cursor.execute('''
                UPDATE user_sessions 
                SET last_activity = CURRENT_TIMESTAMP 
                WHERE session_id = ?
                ''', (session_id,))
                conn.commit()
                
                user = self.get_user_by_id(user_id)
                return user
            return None
        except Exception as e:
            print(f"Error validating session: {e}")
            return None
        finally:
            conn.close()

    def delete_session(self, session_id: str):
        """Delete a user session"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM user_sessions WHERE session_id = ?', (session_id,))
        conn.commit()
        conn.close()

    def cleanup_expired_sessions(self):
        """Clean up expired sessions"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM user_sessions WHERE expires_at <= CURRENT_TIMESTAMP")
        conn.commit()
        conn.close()

    def save_conversation(self, user_id: str, message: str, response: str, intent: str = None, entities: str = None):
        """Save conversation to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO conversations (user_id, message, response, intent, entities)
        VALUES (?, ?, ?, ?, ?)
        ''', (user_id, message, response, intent, entities))
        
        conn.commit()
        conn.close()

    def get_user_conversations(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get user conversation history"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT message, response, timestamp FROM conversations 
        WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?
        ''', (user_id, limit))
        
        conversations = []
        for row in cursor.fetchall():
            conversations.append({
                "message": row[0],
                "response": row[1],
                "timestamp": row[2]
            })
        
        conn.close()
        return conversations

    def update_user_session(self, user_id: str, session_id: str, current_state: str = None, context: str = None):
        """Update or create user session"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT id FROM user_sessions WHERE session_id = ?', (session_id,))
        existing = cursor.fetchone()
        
        # Set session to expire in 24 hours
        expires_at = datetime.now() + timedelta(hours=24)
        
        if existing:
            cursor.execute('''
            UPDATE user_sessions 
            SET current_state = ?, context = ?, last_activity = CURRENT_TIMESTAMP, expires_at = ?
            WHERE session_id = ?
            ''', (current_state, context, expires_at, session_id))
        else:
            cursor.execute('''
            INSERT INTO user_sessions (user_id, session_id, current_state, context, expires_at)
            VALUES (?, ?, ?, ?, ?)
            ''', (user_id, session_id, current_state, context, expires_at))
        
        conn.commit()
        conn.close()

    def get_user_session(self, session_id: str) -> Dict[str, Any]:
        """Get user session data"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT user_id, current_state, context FROM user_sessions WHERE session_id = ?
        ''', (session_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "user_id": row[0],
                "current_state": row[1],
                "context": row[2]
            }
        return None

    def reset_database(self):
        """Reset the database completely (for development only)"""
        try:
            os.remove(self.db_path)
            print(f"Database {self.db_path} removed.")
        except FileNotFoundError:
            print(f"Database {self.db_path} does not exist.")
        
        # Reinitialize
        self._init_database()
        print("Database reinitialized.")

# Singleton instance
db = DatabaseConnector()