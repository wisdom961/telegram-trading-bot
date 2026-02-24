import os
import json
import random
import string
import requests
import pandas as pd
from datetime import datetime, timedelta
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TWELVE_KEY = os.getenv("TWELVE_DATA_KEY")
ADMIN_ID = 6419235456

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN not set")

if not TWELVE_KEY:
    raise RuntimeError("TWELVE_DATA_KEY not set")

STATS_FILE = "stats.json"
SUB_FILE = "subscriptions.json"
CODE_FILE = "codes.json"
USERS_FILE = "users.json"

# ================= FILE HELPERS =================
def load_json(file):
    if os.path.exists(file):
        with open(file, "r") as f:
            return json.load(f)
    return {}

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=4)

user_stats = load_json(STATS_FILE)
subscriptions = load_json(SUB_FILE)

# ================= STATE =================
last_signal_market = {}

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
    [["✅ Win", "❌ Loss"], ["🔙 Back"]],
    resize_keyboard=True
)

activation_keyboard = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("🔑 Activate Subscription", callback_data="activate_info")]
    ]
)

# ================= ACCESS =================
def has_access(user_id):
    if int(user_id) == ADMIN_ID:
        return True

    if user_id not in subscriptions:
        return False

    expiry = datetime.strptime(subscriptions[user_id], "%Y-%m-%d %H:%M:%S")
    return datetime.now() < expiry

# ================= USER INIT =================
def initialize_user(user_id):
    if user_id not in user_stats:
        user_stats[user_id] = {
            "wins": 0,
            "losses": 0
        }
        save_json(STATS_FILE, user_stats)

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = str(update.effective_user.id)

    if not has_access(user_id):
        await update.message.reply_text(
            "👋 Welcome!\n\n"
            "🔒 You must activate first.\n\n"
            "Use /activate YOUR_CODE",
            reply_markup=activation_keyboard
        )
        return

    initialize_user(user_id)

    await update.message.reply_text(
        "🚀 Welcome!\nChoose option below 👇",
        reply_markup=main_keyboard
    )

# ================= SIGNAL ENGINE =================
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
    last_signal_market[user_id] = True

    await update.message.reply_text(
        f"🚨 SIGNAL 🚨\n\n"
        f"{symbol}\nDirection: {direction}\n"
        f"Enter next candle\nExpiry: 5 Minutes",
        reply_markup=result_keyboard
    )

# ================= MESSAGE HANDLER =================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = str(update.effective_user.id)
    text = update.message.text

    if not has_access(user_id):
        await update.message.reply_text("🔒 Subscription required.")
        return

    initialize_user(user_id)

    if text == "🚀 Start Trading":
        await update.message.reply_text("Choose expiry 👇", reply_markup=expiry_keyboard)

    elif text == "⏱ 5 Minutes":
        await update.message.reply_text("Choose market 👇", reply_markup=market_keyboard)

    elif text in FOREX_PAIRS:
        await forex_signal(update, FOREX_PAIRS[text])

    elif text == "✅ Win":

        if user_id not in last_signal_market:
            await update.message.reply_text("No active trade.")
            return

        user_stats[user_id]["wins"] += 1
        del last_signal_market[user_id]
        save_json(STATS_FILE, user_stats)

        await update.message.reply_text("Win recorded ✅", reply_markup=main_keyboard)

    elif text == "❌ Loss":

        if user_id not in last_signal_market:
            await update.message.reply_text("No active trade.")
            return

        user_stats[user_id]["losses"] += 1
        del last_signal_market[user_id]
        save_json(STATS_FILE, user_stats)

        await update.message.reply_text("Loss recorded ❌", reply_markup=main_keyboard)

    elif text == "📈 Stats":

        wins = user_stats[user_id]["wins"]
        losses = user_stats[user_id]["losses"]
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
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🤖 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()