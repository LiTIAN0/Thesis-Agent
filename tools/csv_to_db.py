# tools/csv_to_db.py
import sqlite3
import csv
import os

# Database file path (SQLite for local testing; can be seamlessly switched to PostgreSQL in production)
DB_PATH = "agent_evaluations.db"
CSV_PATH = "raw_data/livecodebench/ablation_lcb.csv"

def init_database():
    """Initialize the relational database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create the core evaluation log table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS evaluation_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL,
        mode TEXT NOT NULL,
        success BOOLEAN NOT NULL,
        safety_veto BOOLEAN NOT NULL,
        iterations INTEGER,
        latency_seconds REAL,
        cost_usd REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    conn.commit()
    return conn

def load_csv_to_db(conn):
    """Convert offline CSV data into structured SQL data (ETL process)"""
    if not os.path.exists(CSV_PATH):
        print(f"Warning: {CSV_PATH} not found. Please ensure the CSV exists.")
        return

    cursor = conn.cursor()
    
    # Clear existing data to prevent duplicate inserts
    cursor.execute('DELETE FROM evaluation_logs')
    
    with open(CSV_PATH, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Insert data (DML)
            cursor.execute('''
            INSERT INTO evaluation_logs 
            (task_id, mode, success, safety_veto, iterations, latency_seconds, cost_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                row.get('Task ID', 'unknown'),
                row.get('Mode', 'Full System'), 
                row.get('Valid Success'),
                row.get('Safety Veto'),
                int(row.get('Iterations', 1)),
                float(row.get('Latency (s)', 0.0)),
                float(row.get('Actual Cost ($)', 0.0))
            ))
    
    conn.commit()
    print(f"Successfully loaded CSV data into {DB_PATH}.")

if __name__ == "__main__":
    db_conn = init_database()
    load_csv_to_db(db_conn)
    db_conn.close()