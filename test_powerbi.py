"""รัน: python test_powerbi.py  เพื่อทดสอบการเชื่อมต่อ Power BI"""
import logging
logging.basicConfig(level=logging.DEBUG)

from dotenv import load_dotenv
load_dotenv()

from powerbi_connector import fetch_table
import os

for table in [os.getenv('TABLE_NAME', 'BookingMaster'), os.getenv('TABLE_NAME_MC', 'Table_MC')]:
    print(f"\n{'='*50}")
    print(f"Testing table: {table}")
    print('='*50)
    try:
        result = fetch_table(table)
        rows = result.get('data', [])
        print(f"SUCCESS — {len(rows)} rows")
        if rows:
            print(f"Columns: {list(rows[0].keys())}")
            print(f"Sample row: {rows[0]}")
    except Exception as e:
        print(f"ERROR: {e}")
