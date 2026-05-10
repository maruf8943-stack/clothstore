"""
Run this script ONCE to set up the PostgreSQL database.
Usage:
    python init_db.py

Make sure DATABASE_URL is set in your .env file first.
"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL', '')
if not DATABASE_URL:
    print("❌ DATABASE_URL not found in .env file!")
    exit(1)

url = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

try:
    conn = psycopg2.connect(url)
    conn.autocommit = True
    cur = conn.cursor()

    with open('schema.sql', 'r', encoding='utf-8') as f:
        sql = f.read()

    cur.execute(sql)
    print("✅ Database setup complete!")
    print("   Tables created: users, products, cart, orders, order_items")
    print("   Tables created: vouchers, site_settings, chat_messages, reviews")
    print("   Admin login: admin@clothstore.com / admin123")

    cur.close()
    conn.close()

except Exception as e:
    print(f"❌ Error: {e}")