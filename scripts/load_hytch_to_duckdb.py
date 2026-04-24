#!/usr/bin/env python3
"""
Load Hytch data from MySQL/CSV exports into DuckDB for analysis.

Usage:
    python scripts/load_hytch_to_duckdb.py --input-dir ~/hytch_data_export/ --output warehouse.duckdb
"""

import argparse
from pathlib import Path
import duckdb
import pandas as pd

def load_hytch_data(input_dir: Path, output_db: Path):
    """Load Hytch CSV exports into DuckDB."""
    
    conn = duckdb.connect(str(output_db))
    
    # Priority 1: Core trips
    print("Loading completed trips...")
    if (input_dir / "hytch_trips_completed.csv").exists():
        conn.execute("""
            CREATE TABLE IF NOT EXISTS raw_hytch_trips AS 
            SELECT * FROM read_csv_auto(?)
        """, [str(input_dir / "hytch_trips_completed.csv")])
    
    print("Loading trip participants...")
    if (input_dir / "hytch_participants.csv").exists():
        conn.execute("""
            CREATE TABLE IF NOT EXISTS raw_hytch_participants AS 
            SELECT * FROM read_csv_auto(?)
        """, [str(input_dir / "hytch_participants.csv")])
    
    print("Loading transactions...")
    if (input_dir / "hytch_transactions.csv").exists():
        conn.execute("""
            CREATE TABLE IF NOT EXISTS raw_hytch_transactions AS 
            SELECT * FROM read_csv_auto(?)
        """, [str(input_dir / "hytch_transactions.csv")])
    
    # Priority 2: Spatial
    print("Loading GPS trajectories...")
    if (input_dir / "hytch_trajectories_sample.parquet").exists():
        conn.execute("""
            CREATE TABLE IF NOT EXISTS raw_hytch_trajectories AS 
            SELECT * FROM read_parquet(?)
        """, [str(input_dir / "hytch_trajectories_sample.parquet")])
    
    print("Loading user addresses...")
    if (input_dir / "hytch_user_addresses.csv").exists():
        conn.execute("""
            CREATE TABLE IF NOT EXISTS raw_hytch_addresses AS 
            SELECT * FROM read_csv_auto(?)
        """, [str(input_dir / "hytch_user_addresses.csv")])
    
    # Priority 3: User profiles
    print("Loading user summaries...")
    if (input_dir / "hytch_user_summary.csv").exists():
        conn.execute("""
            CREATE TABLE IF NOT EXISTS raw_hytch_users AS 
            SELECT * FROM read_csv_auto(?)
        """, [str(input_dir / "hytch_user_summary.csv")])
    
    # Priority 4: Sponsors
    print("Loading sponsor data...")
    if (input_dir / "hytch_sponsors.csv").exists():
        conn.execute("""
            CREATE TABLE IF NOT EXISTS raw_hytch_sponsors AS 
            SELECT * FROM read_csv_auto(?)
        """, [str(input_dir / "hytch_sponsors.csv")])
    
    # Verify
    print("\nData loaded successfully!")
    print("\nTable counts:")
    tables = ['raw_hytch_trips', 'raw_hytch_participants', 'raw_hytch_transactions',
              'raw_hytch_trajectories', 'raw_hytch_addresses', 'raw_hytch_users']
    
    for table in tables:
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table}: {count:,} rows")
        except:
            print(f"  {table}: not loaded")
    
    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("warehouse.duckdb"))
    args = parser.parse_args()
    
    load_hytch_data(args.input_dir, args.output)