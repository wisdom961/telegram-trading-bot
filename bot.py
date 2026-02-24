import os
import random
import string
import requests
import pandas as pd
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TWELVE_KEY = os.getenv("TWELVE_DATA_KEY")
ADMIN_ID = 6419235456

if not BOT_TOKEN or not TWELVE_KEY:
    raise RuntimeError("Environment variables missing")

DB = sqlite3.connect("trading_bot.db", check_same_thread=False)
cursor = DB.cursor()

# ================= DATABASE SETUP =================
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
CREATE TABLE IF NOT EXISTS codes (
    code TEXT PRIMARY KEY,
    days INTEGER,
    used INTEGER
)
""")

DB.commit()

# ================= RISK MODEL =================
RISK_STEPS = {
    0: 0.02,
    1: 0.03,
    2: 0.05
}
MAX_PLAYBACK = 2

# ================= HELPERS =================
def get_user(user_id):
    cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    return cursor.fetchone()

def create_user(user_id):
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    DB.commit()

def has_access(user_id):
    if int(user_id) == ADMIN_ID:
        return True

    user = get_user(user_id)
    if not user or not user[1]:
        return False

    expiry = datetime.strptime(user[1], "%Y-%m-%d %H:%M:%S")
    return datetime.now() < expiry

def calculate_trade(balance, step):
    risk = RISK_STEPS.get(step, 0.02)
    return round(balance * risk, 2), risk * 100

# ================= ADMIN =================
async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    days = int(context.args[0])
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

    cursor.execute("INSERT INTO codes VALUES (?, ?, 0)", (code, days))
    DB.commit()

    await update.message.reply_text(f"Code: {code} | {days} days")

async def activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    code = context.args[0]

    cursor.execute("SELECT * FROM codes WHERE code=? AND used=0", (code,))
    row = cursor.fetchone()

    if not row:
        await update.message.reply_text("Invalid or used code")
        return

    expiry = datetime.now() + timedelta(days=row[1])
    create_user(user_id)

    cursor.execute("UPDATE users SET expiry=? WHERE user_id=?",
                   (expiry.strftime("%Y-%m-%d %H:%M:%S"), user_id))
    cursor.execute("UPDATE codes SET used=1 WHERE code=?", (code,))
    DB.commit()

    await update.message.reply_text(f"Activated until {expiry.strftime('%Y-%m-%d')}")

# ================= SET BALANCE =================
async def setbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    if len(context.args) != 1:
        await update.message.reply_text("Usage: /setbalance 200")
        return

    balance = float(context.args[0])
    create_user(user_id)

    cursor.execute("UPDATE users SET balance=? WHERE user_id=?",
                   (balance, user_id))
    DB.commit()

    await update.message.reply_text(f"Balance set to ${balance}")

# ================= STRATEGY =================
async def forex_signal(update, symbol):

    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=5min&outputsize=150&apikey={TWELVE_KEY}"
    data = requests.get(url).json()

    if "values" not in data:
        await update.message.reply_text("Market unavailable")
        return

    values = list(reversed(data["values"]))
    closes = [float(c["close"]) for c in values]
    opens = [float(c["open"]) for c in values]

    df = pd.DataFrame({"close": closes, "open": opens})
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["ema50"] = df["close"].ewm(span=50).mean()

    last = df.iloc[-2]

    trend_up = last["ema20"] > last["ema50"]
    trend_down = last["ema20"] < last["ema50"]
    pullback_zone = abs(last["close"] - last["ema20"]) / last["close"] < 0.002

    if trend_up and pullback_zone:
        direction = "BUY"
    elif trend_down and pullback_zone:
        direction = "SELL"
    else:
        await update.message.reply_text("No setup now.")
        return

    user_id = str(update.effective_user.id)
    user = get_user(user_id)
    balance = user[2]
    step = user[6]

    amount, risk_percent = calculate_trade(balance, step)

    keyboard = ReplyKeyboardMarkup(
        [["✅ Win", "❌ Loss"], ["🔙 Back"]],
        resize_keyboard=True
    )

    await update.message.reply_text(
        f"🚨 SIGNAL 🚨\n\n{symbol}\n{direction}\n\n"
        f"Risk: {risk_percent}%\n"
        f"Trade Amount: ${amount}\n"
        f"Playback Step: {step}",
        reply_markup=keyboard
    )

# ================= MESSAGE HANDLER =================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = str(update.effective_user.id)
    text = update.message.text

    create_user(user_id)

    if not has_access(user_id):
        await update.message.reply_text("Subscription required.")
        return

    if text == "🚀 Start Trading":
        keyboard = ReplyKeyboardMarkup(
            [["📊 EUR/USD", "📊 GBP/USD"],
             ["📊 USD/JPY", "📊 GOLD"]],
            resize_keyboard=True
        )
        await update.message.reply_text("Choose market", reply_markup=keyboard)

    elif text in ["📊 EUR/USD", "📊 GBP/USD", "📊 USD/JPY", "📊 GOLD"]:
        symbol_map = {
            "📊 EUR/USD": "EUR/USD",
            "📊 GBP/USD": "GBP/USD",
            "📊 USD/JPY": "USD/JPY",
            "📊 GOLD": "XAU/USD",
        }
        await forex_signal(update, symbol_map[text])

    elif text == "✅ Win":
        cursor.execute("""
        UPDATE users
        SET wins=wins+1, trades=trades+1, playback_step=0
        WHERE user_id=?""", (user_id,))
        DB.commit()
        await update.message.reply_text("Win recorded. Playback reset.")

    elif text == "❌ Loss":
        user = get_user(user_id)
        step = user[6]

        if step < MAX_PLAYBACK:
            step += 1
        else:
            step = 0

        cursor.execute("""
        UPDATE users
        SET losses=losses+1, trades=trades+1, playback_step=?
        WHERE user_id=?""", (step, user_id))
        DB.commit()

        await update.message.reply_text(f"Loss recorded. New step: {step}")

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("generate", generate))
    app.add_handler(CommandHandler("activate", activate))
    app.add_handler(CommandHandler("setbalance", setbalance))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()