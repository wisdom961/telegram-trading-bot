import os
import json
import random
import string
import requests
import pandas as pd
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
)

# =============================
# CONFIG
# =============================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TWELVE_KEY = os.getenv("TWELVE_DATA_KEY")
ADMIN_ID = 6419235456

if not BOT_TOKEN:
    raise RuntimeError("❌ TELEGRAM_BOT_TOKEN not set")

if not TWELVE_KEY:
    raise RuntimeError("❌ TWELVE_DATA_KEY not set")

STATS_FILE = "stats.json"
SUB_FILE = "subscriptions.json"
CODE_FILE = "codes.json"

# =============================
# FILE HELPERS
# =============================
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
codes = load_json(CODE_FILE)

# =============================
# STATE MEMORY
# =============================
last_signal_market = {}

FOREX_PAIRS = {
    "📊 EUR/USD": "EUR/USD",
    "📊 GBP/USD": "GBP/USD",
    "📊 USD/JPY": "USD/JPY",
    "📊 GOLD": "XAU/USD",
}

# =============================
# KEYBOARDS
# =============================
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

# =============================
# ACCESS CONTROL
# =============================
def has_access(user_id):
    if int(user_id) == ADMIN_ID:
        return True

    user_id = str(user_id)
    if user_id not in subscriptions:
        return False

    expiry = datetime.strptime(subscriptions[user_id], "%Y-%m-%d %H:%M:%S")
    return datetime.now() < expiry

# =============================
# USER INIT
# =============================
def initialize_user(user_id):
    if user_id not in user_stats:
        user_stats[user_id] = {
            "lifetime": {
                "wins": 0,
                "losses": 0,
                "best_streak": 0,
                "worst_streak": 0,
                "current_streak": 0,
                "markets": {}
            },
            "daily": {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "wins": 0,
                "losses": 0,
                "current_streak": 0
            }
        }
        save_json(STATS_FILE, user_stats)

def check_daily_reset(user_id):
    today = datetime.now().strftime("%Y-%m-%d")
    if user_stats[user_id]["daily"]["date"] != today:
        user_stats[user_id]["daily"] = {
            "date": today,
            "wins": 0,
            "losses": 0,
            "current_streak": 0
        }

# =============================
# RECORD RESULT
# =============================
def record_result(user_id, market, win):
    lifetime = user_stats[user_id]["lifetime"]
    daily = user_stats[user_id]["daily"]

    if market not in lifetime["markets"]:
        lifetime["markets"][market] = {"wins": 0, "losses": 0}

    if win:
        lifetime["wins"] += 1
        daily["wins"] += 1
        lifetime["markets"][market]["wins"] += 1
        lifetime["current_streak"] = max(1, lifetime["current_streak"] + 1)
        daily["current_streak"] = max(1, daily["current_streak"] + 1)
        lifetime["best_streak"] = max(lifetime["best_streak"], lifetime["current_streak"])
    else:
        lifetime["losses"] += 1
        daily["losses"] += 1
        lifetime["markets"][market]["losses"] += 1
        lifetime["current_streak"] = min(-1, lifetime["current_streak"] - 1)
        daily["current_streak"] = min(-1, daily["current_streak"] - 1)
        lifetime["worst_streak"] = min(lifetime["worst_streak"], lifetime["current_streak"])

    save_json(STATS_FILE, user_stats)

# =============================
# ADMIN CODE GENERATOR
# =============================
async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text("Usage: /generate <days>")
        return

    days = int(context.args[0])
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    codes[code] = days
    save_json(CODE_FILE, codes)

    await update.message.reply_text(f"Code: {code} | Valid {days} days")

# =============================
# ACTIVATE SUBSCRIPTION
# =============================
async def activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    if not context.args:
        await update.message.reply_text("Usage: /activate CODE")
        return

    code = context.args[0]

    if code not in codes:
        await update.message.reply_text("Invalid code.")
        return

    days = codes[code]
    expiry_date = datetime.now() + timedelta(days=days)

    subscriptions[user_id] = expiry_date.strftime("%Y-%m-%d %H:%M:%S")
    save_json(SUB_FILE, subscriptions)

    del codes[code]
    save_json(CODE_FILE, codes)

    await update.message.reply_text(
        f"✅ Activated until {expiry_date.strftime('%Y-%m-%d %H:%M:%S')}",
        reply_markup=main_keyboard
    )

# =============================
# SIGNAL ENGINE
# =============================
async def forex_signal(update, symbol):

    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=5min&outputsize=120&apikey={TWELVE_KEY}"
    data = requests.get(url).json()

    if "values" not in data:
        await update.message.reply_text("Market data unavailable.")
        return

    values = list(reversed(data["values"]))
    closes = [float(c["close"]) for c in values]
    opens = [float(c["open"]) for c in values]

    df = pd.DataFrame({"close": closes, "open": opens})
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["ema50"] = df["close"].ewm(span=50).mean()

    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = gain.rolling(14).mean() / loss.rolling(14).mean()
    df["rsi"] = 100 - (100 / (1 + rs))

    last = df.iloc[-2]

    ema20 = last["ema20"]
    ema50 = last["ema50"]
    rsi = last["rsi"]
    close_price = last["close"]
    open_price = last["open"]

    bullish = close_price > open_price
    bearish = close_price < open_price

    if ema20 > ema50 and 45 <= rsi <= 65 and bullish:
        direction = "BUY"
    elif ema20 < ema50 and 35 <= rsi <= 55 and bearish:
        direction = "SELL"
    else:
        await update.message.reply_text("No confirmed setup.", reply_markup=market_keyboard)
        return

    last_signal_market[str(update.effective_user.id)] = symbol

    await update.message.reply_text(
        f"🚨 CONFIRMED SIGNAL 🚨\n\n"
        f"{symbol}\nDirection: {direction}\nEnter at NEXT candle open\nExpiry: 5 Minutes",
        reply_markup=result_keyboard
    )

# =============================
# MAIN MESSAGE HANDLER
# =============================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = str(update.effective_user.id)
    text = update.message.text

    if not has_access(user_id):
        await update.message.reply_text("🔒 Subscription required.")
        return

    initialize_user(user_id)
    check_daily_reset(user_id)

    if text == "🚀 Start Trading":
        await update.message.reply_text("Choose expiry 👇", reply_markup=expiry_keyboard)

    elif text == "⏱ 5 Minutes":
        await update.message.reply_text("Choose market 👇", reply_markup=market_keyboard)

    elif text in FOREX_PAIRS:
        await forex_signal(update, FOREX_PAIRS[text])

    elif text == "✅ Win":
        market = last_signal_market.get(user_id)
        if market:
            record_result(user_id, market, True)
        await update.message.reply_text("Win recorded ✅", reply_markup=main_keyboard)

    elif text == "❌ Loss":
        market = last_signal_market.get(user_id)
        if market:
            record_result(user_id, market, False)
        await update.message.reply_text("Loss recorded ❌", reply_markup=main_keyboard)

    elif text == "📈 Stats":
        lifetime = user_stats[user_id]["lifetime"]
        daily = user_stats[user_id]["daily"]

        total = lifetime["wins"] + lifetime["losses"]
        winrate = (lifetime["wins"] / total * 100) if total > 0 else 0

        msg = (
            f"📊 LIFETIME\n"
            f"Trades: {total}\n"
            f"Wins: {lifetime['wins']}\n"
            f"Losses: {lifetime['losses']}\n"
            f"Win Rate: {winrate:.2f}%\n"
            f"Best Streak: {lifetime['best_streak']}\n"
            f"Worst Streak: {lifetime['worst_streak']}\n\n"
            f"📅 TODAY\n"
            f"Wins: {daily['wins']}\n"
            f"Losses: {daily['losses']}"
        )

        await update.message.reply_text(msg, reply_markup=main_keyboard)

    elif text == "🔙 Back":
        await update.message.reply_text("Main menu 👇", reply_markup=main_keyboard)

# =============================
# MAIN
# =============================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("generate", generate))
    app.add_handler(CommandHandler("activate", activate))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()