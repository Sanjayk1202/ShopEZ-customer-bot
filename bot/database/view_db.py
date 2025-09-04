import sqlite3
import pandas as pd

def view_database():
    conn = sqlite3.connect('data/shopez.db')
    
    # Get all tables
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    
    for table in tables:
        table_name = table[0]
        print(f"\n=== {table_name} ===")
        
        # Get table data
        df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
        print(df)
    
    conn.close()

if __name__ == "__main__":
    view_database()