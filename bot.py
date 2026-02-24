import os
import random
import string
import requests
import pandas as pd
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from database import get_db

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TWELVE_KEY = os.getenv("TWELVE_DATA_KEY")
ADMIN_ID = 6419235456

DB, cursor = get_db()

RISK_STEPS = {0: 0.02, 1: 0.03, 2: 0.05}
MAX_PLAYBACK = 2

def calculate_trade(balance, step):
    risk = RISK_STEPS.get(step, 0.02)
    return round(balance * risk, 2), risk * 100

def get_user(user_id):
    cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    return cursor.fetchone()

def create_user(user_id):
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    DB.commit()

async def forex_signal(update, symbol):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=5min&outputsize=150&apikey={TWELVE_KEY}"
    data = requests.get(url).json()

    if "values" not in data:
        await update.message.reply_text("No setup now.")
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

    if trend_up:
        direction = "BUY"
    elif trend_down:
        direction = "SELL"
    else:
        await update.message.reply_text("No clear trend.")
        return

    user_id = str(update.effective_user.id)
    user = get_user(user_id)

    balance = user[2] if user else 0
    step = user[6] if user else 0

    amount, risk_percent = calculate_trade(balance, step)

    cursor.execute("""
    INSERT INTO signals (symbol, direction, risk, amount)
    VALUES (?, ?, ?, ?)
    """, (symbol, direction, risk_percent, amount))
    DB.commit()

    keyboard = ReplyKeyboardMarkup(
        [["✅ Win", "❌ Loss"], ["🔙 Back"]],
        resize_keyboard=True
    )

    await update.message.reply_text(
        f"{symbol} {direction}\nRisk: {risk_percent}%\nAmount: ${amount}",
        reply_markup=keyboard
    )

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text

    create_user(user_id)

    main_keyboard = ReplyKeyboardMarkup(
        [["🚀 Start Trading"]],
        resize_keyboard=True
    )

    if text == "🚀 Start Trading":
        keyboard = ReplyKeyboardMarkup(
            [["EUR/USD", "GBP/USD"], ["USD/JPY", "XAU/USD"]],
            resize_keyboard=True
        )
        await update.message.reply_text("Choose pair", reply_markup=keyboard)

    elif text in ["EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD"]:
        await forex_signal(update, text)

    elif text == "✅ Win":
        cursor.execute("UPDATE users SET wins=wins+1,trades=trades+1,playback_step=0 WHERE user_id=?", (user_id,))
        DB.commit()
        await update.message.reply_text("Win recorded", reply_markup=main_keyboard)

    elif text == "❌ Loss":
        user = get_user(user_id)
        step = user[6]
        step = step + 1 if step < MAX_PLAYBACK else 0
        cursor.execute("UPDATE users SET losses=losses+1,trades=trades+1,playback_step=? WHERE user_id=?", (step,user_id))
        DB.commit()
        await update.message.reply_text(f"Loss recorded. Step {step}", reply_markup=main_keyboard)

    elif text == "🔙 Back":
        await update.message.reply_text("Main Menu", reply_markup=main_keyboard)

def run_bot():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.run_polling()