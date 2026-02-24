import os
import sqlite3
import requests
import pandas as pd
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters

# ================= CONFIG =================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TWELVE_KEY = os.getenv("TWELVE_DATA_KEY")

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN not set")

if not TWELVE_KEY:
    raise RuntimeError("TWELVE_DATA_KEY not set")

# ================= DATABASE =================
conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    active_trade INTEGER DEFAULT 0
)
""")
conn.commit()

# ================= MARKETS =================
FOREX_PAIRS = {
    "📊 EUR/USD": "EUR/USD",
    "📊 GBP/USD": "GBP/USD",
    "📊 USD/JPY": "USD/JPY",
    "📊 GOLD": "XAU/USD",
}

# ================= KEYBOARDS =================
main_keyboard = ReplyKeyboardMarkup(
    [["🚀 Start Trading"], ["📈 Stats"]],
    resize_keyboard=True
)

expiry_keyboard = ReplyKeyboardMarkup(
    [["⏱ 5 Minutes"], ["🔙 Back"]],
    resize_keyboard=True
)

market_keyboard = ReplyKeyboardMarkup(
    [
        ["📊 EUR/USD", "📊 GBP/USD"],
        ["📊 USD/JPY", "📊 GOLD"],
        ["🔙 Back"]
    ],
    resize_keyboard=True
)

result_keyboard = ReplyKeyboardMarkup(
    [["✅ Win", "❌ Loss"]],
    resize_keyboard=True
)

# ================= USER INIT =================
def init_user(user_id):
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()

# ================= SIGNAL =================
async def forex_signal(update, symbol):

    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=5min&outputsize=120&apikey={TWELVE_KEY}"
    data = requests.get(url).json()

    if "values" not in data:
        await update.message.reply_text("Market data unavailable.")
        return

    values = list(reversed(data["values"]))
    closes = [float(c["close"]) for c in values]

    df = pd.DataFrame({"close": closes})
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["ema50"] = df["close"].ewm(span=50).mean()

    last = df.iloc[-2]

    if last["ema20"] > last["ema50"]:
        direction = "BUY"
    elif last["ema20"] < last["ema50"]:
        direction = "SELL"
    else:
        await update.message.reply_text("No confirmed setup.", reply_markup=market_keyboard)
        return

    user_id = str(update.effective_user.id)
    cursor.execute("UPDATE users SET active_trade = 1 WHERE user_id = ?", (user_id,))
    conn.commit()

    await update.message.reply_text(
        f"🚨 SIGNAL 🚨\n\n"
        f"{symbol}\nDirection: {direction}\n"
        f"Enter next candle\nExpiry: 5 Minutes",
        reply_markup=result_keyboard
    )

# ================= HANDLER =================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = str(update.effective_user.id)
    text = update.message.text

    init_user(user_id)

    if text == "🚀 Start Trading":
        await update.message.reply_text("Choose expiry 👇", reply_markup=expiry_keyboard)

    elif text == "⏱ 5 Minutes":
        await update.message.reply_text("Choose market 👇", reply_markup=market_keyboard)

    elif text in FOREX_PAIRS:
        await forex_signal(update, FOREX_PAIRS[text])

    elif text == "✅ Win":
        cursor.execute("SELECT active_trade FROM users WHERE user_id = ?", (user_id,))
        active = cursor.fetchone()[0]

        if active == 0:
            await update.message.reply_text("No active trade.")
            return

        cursor.execute("UPDATE users SET wins = wins + 1, active_trade = 0 WHERE user_id = ?", (user_id,))
        conn.commit()

        await update.message.reply_text("Win recorded ✅", reply_markup=main_keyboard)

    elif text == "❌ Loss":
        cursor.execute("SELECT active_trade FROM users WHERE user_id = ?", (user_id,))
        active = cursor.fetchone()[0]

        if active == 0:
            await update.message.reply_text("No active trade.")
            return

        cursor.execute("UPDATE users SET losses = losses + 1, active_trade = 0 WHERE user_id = ?", (user_id,))
        conn.commit()

        await update.message.reply_text("Loss recorded ❌", reply_markup=main_keyboard)

    elif text == "📈 Stats":
        cursor.execute("SELECT wins, losses FROM users WHERE user_id = ?", (user_id,))
        wins, losses = cursor.fetchone()
        total = wins + losses
        winrate = (wins / total * 100) if total > 0 else 0

        await update.message.reply_text(
            f"Trades: {total}\nWins: {wins}\nLosses: {losses}\nWin Rate: {winrate:.2f}%",
            reply_markup=main_keyboard
        )

    elif text == "🔙 Back":
        await update.message.reply_text("Main menu 👇", reply_markup=main_keyboard)

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("Welcome 👇", reply_markup=main_keyboard)))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🤖 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()