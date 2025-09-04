import json
import os

def create_data_files():
    os.makedirs("data", exist_ok=True)
    os.makedirs("static", exist_ok=True)
    os.makedirs("templates", exist_ok=True)
    
    data_files = [
        "data/cancellations.json",
        "data/refunds.json", 
        "data/warranty_claims.json",
        "data/escalations.json"
    ]
    
    for file_path in data_files:
        with open(file_path, 'w') as f:
            json.dump([], f, indent=2)
        print(f"✅ Created {file_path}")
    
    from database.db_connector import DatabaseConnector
    db = DatabaseConnector()
    print("✅ Database initialized")
    
    print("✅ All data files created successfully!")

if __name__ == "__main__":
    create_data_files()