import os
import json
import random
import string
import requests
import pandas as pd
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters

# ================= CONFIG =================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TWELVE_KEY = os.getenv("TWELVE_DATA_KEY")
ADMIN_ID = 6419235456

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
if not TWELVE_KEY:
    raise RuntimeError("TWELVE_DATA_KEY not set")

SUB_FILE = "subscriptions.json"
CODE_FILE = "codes.json"

# ================= FILE HELPERS =================
def load_json(file):
    if os.path.exists(file):
        with open(file, "r") as f:
            return json.load(f)
    return {}

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=4)

subscriptions = load_json(SUB_FILE)
codes = load_json(CODE_FILE)

# ================= ACCESS CHECK =================
def has_access(user_id):
    if user_id == str(ADMIN_ID):
        return True

    if user_id not in subscriptions:
        return False

    expiry = datetime.strptime(subscriptions[user_id], "%Y-%m-%d %H:%M:%S")
    return datetime.now() < expiry

# ================= EXPIRY WARNING =================
async def check_expiry_warning(update, user_id):

    if user_id not in subscriptions:
        return

    expiry = datetime.strptime(subscriptions[user_id], "%Y-%m-%d %H:%M:%S")
    remaining = expiry - datetime.now()

    if timedelta(hours=23) < remaining < timedelta(hours=25):
        await update.message.reply_text(
            "⚠️ Your subscription expires in less than 24 hours.\nRenew soon."
        )

# ================= GENERATE CODE (ADMIN ONLY) =================
async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    if len(context.args) != 1:
        await update.message.reply_text("Usage: /generate DAYS")
        return

    days = int(context.args[0])
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

    codes[code] = {
        "days": days,
        "used": False
    }

    save_json(CODE_FILE, codes)

    await update.message.reply_text(
        f"✅ Code Generated:\n\n{code}\n\nValid for {days} days.\nOne-time use."
    )

# ================= ACTIVATE =================
async def activate(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = str(update.effective_user.id)

    if len(context.args) != 1:
        await update.message.reply_text("Usage: /activate YOUR_CODE")
        return

    code = context.args[0]

    if code not in codes:
        await update.message.reply_text("❌ Invalid code.")
        return

    if codes[code]["used"]:
        await update.message.reply_text("❌ Code already used.")
        return

    days = codes[code]["days"]
    expiry = datetime.now() + timedelta(days=days)

    subscriptions[user_id] = expiry.strftime("%Y-%m-%d %H:%M:%S")

    codes[code]["used"] = True

    save_json(SUB_FILE, subscriptions)
    save_json(CODE_FILE, codes)

    await update.message.reply_text(
        f"✅ Subscription activated!\nExpires: {expiry.strftime('%Y-%m-%d')}"
    )

# ================= MARKETS =================
FOREX_PAIRS = {
    "📊 EUR/USD": "EUR/USD",
    "📊 GBP/USD": "GBP/USD",
    "📊 USD/JPY": "USD/JPY",
    "📊 GOLD": "XAU/USD",
}

main_keyboard = ReplyKeyboardMarkup(
    [["🚀 Start Trading"]],
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
    [["🔙 Back"]],
    resize_keyboard=True
)

# ================= STRATEGY =================
async def forex_signal(update, symbol):

    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=5min&outputsize=100&apikey={TWELVE_KEY}"
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
        await update.message.reply_text("No setup right now.", reply_markup=market_keyboard)
        return

    await update.message.reply_text(
        f"🚨 SIGNAL 🚨\n\n{symbol}\nDirection: {direction}\nExpiry: 5 Minutes",
        reply_markup=result_keyboard
    )

# ================= HANDLER =================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = str(update.effective_user.id)
    text = update.message.text

    if not has_access(user_id):
        await update.message.reply_text(
            "🔒 This bot requires activation.\n\nUse:\n/activate YOUR_CODE"
        )
        return

    await check_expiry_warning(update, user_id)

    if text == "🚀 Start Trading":
        await update.message.reply_text("Choose expiry 👇", reply_markup=expiry_keyboard)

    elif text == "⏱ 5 Minutes":
        await update.message.reply_text("Choose market 👇", reply_markup=market_keyboard)

    elif text in FOREX_PAIRS:
        await forex_signal(update, FOREX_PAIRS[text])

    elif text == "🔙 Back":
        await update.message.reply_text("Main menu 👇", reply_markup=main_keyboard)

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = str(update.effective_user.id)

    if not has_access(user_id):
        await update.message.reply_text(
            "👋 Welcome!\n\n🔒 Activation required.\n\nUse:\n/activate YOUR_CODE"
        )
        return

    await update.message.reply_text("Welcome 👇", reply_markup=main_keyboard)

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("generate", generate))
    app.add_handler(CommandHandler("activate", activate))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()