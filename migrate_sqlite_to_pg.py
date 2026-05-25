"""
ย้ายข้อมูลจาก SQLite → PostgreSQL (รันครั้งเดียว)

วิธีใช้:
  1. ตั้งค่า DATABASE_URL ใน .env
  2. python migrate_sqlite_to_pg.py
"""
import sqlite3
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

SQLITE_PATH = os.getenv('SQLITE_PATH', 'powerbi_chat.db')
DATABASE_URL = os.environ['DATABASE_URL']

TABLES = [
    'users',
    'conversations',
    'messages',
    'powerbi_connections',
    'activity_logs',
    'intent_logs',
    'mcp_interactions',
    'suggestions',
    'token_usage',
]

BOOL_COLUMNS = {'is_active', 'success', 'was_clicked'}


def migrate():
    print(f"SQLite: {SQLITE_PATH}")
    print(f"PostgreSQL: {DATABASE_URL[:40]}...")
    print()

    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cur = sqlite_conn.cursor()

    pg_conn = psycopg2.connect(DATABASE_URL)
    pg_cur = pg_conn.cursor()

    for table in TABLES:
        # ตรวจว่า table มีใน SQLite
        sqlite_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        if not sqlite_cur.fetchone():
            print(f"  {table}: ไม่มีใน SQLite — ข้าม")
            continue

        sqlite_cur.execute(f"SELECT * FROM {table}")
        rows = sqlite_cur.fetchall()
        if not rows:
            print(f"  {table}: ว่างเปล่า — ข้าม")
            continue

        columns = [desc[0] for desc in sqlite_cur.description]
        placeholders = ','.join(['%s'] * len(columns))
        col_names = ','.join(columns)

        inserted = 0
        for row in rows:
            values = list(row)
            for i, col in enumerate(columns):
                if col in BOOL_COLUMNS and values[i] is not None:
                    values[i] = bool(values[i])
            try:
                pg_cur.execute(
                    f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING",
                    values
                )
                inserted += pg_cur.rowcount
            except Exception as e:
                print(f"    [WARN] row skip: {e}")
                pg_conn.rollback()

        # reset SERIAL sequence หลัง insert
        pg_cur.execute(
            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE(MAX(id), 1)) FROM {table}"
        )
        pg_conn.commit()
        print(f"  {table}: {inserted}/{len(rows)} rows ✓")

    pg_cur.close()
    pg_conn.close()
    sqlite_conn.close()
    print("\nMigration เสร็จสิ้น!")


if __name__ == '__main__':
    migrate()
