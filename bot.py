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
    CallbackQueryHandler,
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
codes = load_json(CODE_FILE)
users_db = load_json(USERS_FILE)

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

    user_id = str(user_id)
    if user_id not in subscriptions:
        return False

    expiry = datetime.strptime(subscriptions[user_id], "%Y-%m-%d %H:%M:%S")
    return datetime.now() < expiry

# ================= FIRST TIME DETECTION =================
def register_user(user_id):
    if user_id not in users_db:
        users_db[user_id] = {
            "joined": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        save_json(USERS_FILE, users_db)
        return True
    return False

# ================= START COMMAND =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = str(update.effective_user.id)
    is_new = register_user(user_id)

    if is_new:
        await update.message.reply_text(
            "👋 Welcome to the AI Trading Bot!\n\n"
            "This bot provides structured 5-minute signal analysis.\n\n"
            "⚠️ You must activate a subscription before using it.",
            reply_markup=activation_keyboard
        )
        return

    if not has_access(user_id):
        await update.message.reply_text(
            "🔒 Your subscription is inactive.\n\n"
            "Use your activation code to unlock access.",
            reply_markup=activation_keyboard
        )
        return

    await update.message.reply_text(
        "🚀 Welcome back!\n\nChoose an option below 👇",
        reply_markup=main_keyboard
    )

# ================= INLINE ACTIVATION INFO =================
async def activation_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "🔑 To activate:\n\n"
        "1️⃣ Purchase a subscription.\n"
        "2️⃣ Receive your activation code.\n"
        "3️⃣ Type:\n\n"
        "/activate YOUR_CODE"
    )

# ================= ADMIN CODE GENERATOR =================
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

# ================= ACTIVATE =================
async def activate(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = str(update.effective_user.id)

    if not context.args:
        await update.message.reply_text("Usage: /activate CODE")
        return

    code = context.args[0]

    if code not in codes:
        await update.message.reply_text("❌ Invalid activation code.")
        return

    days = codes[code]
    expiry_date = datetime.now() + timedelta(days=days)

    subscriptions[user_id] = expiry_date.strftime("%Y-%m-%d %H:%M:%S")
    save_json(SUB_FILE, subscriptions)

    del codes[code]
    save_json(CODE_FILE, codes)

    await update.message.reply_text(
        f"✅ Subscription active until {expiry_date.strftime('%Y-%m-%d %H:%M:%S')}",
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

    confidence = 50
    if ema20 > ema50:
        confidence += 20
    if 45 <= rsi <= 65:
        confidence += 20

    if ema20 > ema50:
        direction = "BUY"
    elif ema20 < ema50:
        direction = "SELL"
    else:
        await update.message.reply_text("No confirmed setup.", reply_markup=market_keyboard)
        return

    last_signal_market[str(update.effective_user.id)] = symbol

    await update.message.reply_text(
        f"🚨 SIGNAL 🚨\n\n"
        f"{symbol}\nDirection: {direction}\n"
        f"Confidence: {confidence}%\n"
        f"Enter at next candle open\nExpiry: 5 Minutes",
        reply_markup=result_keyboard
    )

# ================= MESSAGE HANDLER =================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = str(update.effective_user.id)
    text = update.message.text

    if not has_access(user_id):
        await update.message.reply_text(
            "🔒 Subscription required.\nUse /activate YOUR_CODE",
            reply_markup=activation_keyboard
        )
        return

    if text == "🚀 Start Trading":
        await update.message.reply_text("Choose expiry 👇", reply_markup=expiry_keyboard)

    elif text == "⏱ 5 Minutes":
        await update.message.reply_text("Choose market 👇", reply_markup=market_keyboard)

    elif text in FOREX_PAIRS:
        await forex_signal(update, FOREX_PAIRS[text])

    elif text == "🔙 Back":
        await update.message.reply_text("Main menu 👇", reply_markup=main_keyboard)

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("generate", generate))
    app.add_handler(CommandHandler("activate", activate))
    app.add_handler(CallbackQueryHandler(activation_info, pattern="activate_info"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()