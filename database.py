import sqlite3

DB = sqlite3.connect("trading_bot.db", check_same_thread=False)
cursor = DB.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    expiry TEXT,
    balance REAL DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    trades INTEGER DEFAULT 0,
    playback_step INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    direction TEXT,
    risk REAL,
    amount REAL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")

DB.commit()

def get_db():
    return DB, cursor