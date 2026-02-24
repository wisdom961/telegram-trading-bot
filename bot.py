import os
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

# ================= STATE (Memory Safe) =================
user_stats = {}
active_trades = {}

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
    [["✅ Win", "❌ Loss"], ["🔙 Back"]],
    resize_keyboard=True
)

# ================= USER INIT =================
def init_user(user_id):
    if user_id not in user_stats:
        user_stats[user_id] = {
            "wins": 0,
            "losses": 0
        }

# ================= STRATEGY =================
async def forex_signal(update, symbol):

    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=5min&outputsize=150&apikey={TWELVE_KEY}"
    data = requests.get(url).json()

    if "values" not in data:
        await update.message.reply_text("Market data unavailable.")
        return

    values = list(reversed(data["values"]))

    closes = [float(c["close"]) for c in values]
    opens = [float(c["open"]) for c in values]
    highs = [float(c["high"]) for c in values]
    lows = [float(c["low"]) for c in values]

    df = pd.DataFrame({
        "close": closes,
        "open": opens,
        "high": highs,
        "low": lows
    })

    df["ema20"] = df["close"].ewm(span=20).mean()
    df["ema50"] = df["close"].ewm(span=50).mean()

    last = df.iloc[-2]  # last closed candle

    ema20 = last["ema20"]
    ema50 = last["ema50"]

    trend_up = ema20 > ema50
    trend_down = ema20 < ema50

    # Pullback near EMA20 (within 0.2%)
    pullback_zone = abs(last["close"] - ema20) / last["close"] < 0.002

    bullish = last["close"] > last["open"]
    bearish = last["close"] < last["open"]

    if trend_up and pullback_zone and bullish:
        direction = "BUY"

    elif trend_down and pullback_zone and bearish:
        direction = "SELL"

    else:
        await update.message.reply_text(
            "No pullback continuation setup right now.",
            reply_markup=market_keyboard
        )
        return

    user_id = str(update.effective_user.id)
    active_trades[user_id] = True

    await update.message.reply_text(
        f"🚨 PULLBACK CONTINUATION SIGNAL 🚨\n\n"
        f"{symbol}\n"
        f"Direction: {direction}\n\n"
        f"Entry: Next candle open\n"
        f"Expiry: 5 Minutes\n\n"
        f"⚠️ Enter only at new candle open.",
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

        if user_id not in active_trades:
            await update.message.reply_text("No active trade.")
            return

        user_stats[user_id]["wins"] += 1
        del active_trades[user_id]

        await update.message.reply_text("Win recorded ✅", reply_markup=main_keyboard)

    elif text == "❌ Loss":

        if user_id not in active_trades:
            await update.message.reply_text("No active trade.")
            return

        user_stats[user_id]["losses"] += 1
        del active_trades[user_id]

        await update.message.reply_text("Loss recorded ❌", reply_markup=main_keyboard)

    elif text == "📈 Stats":
        wins = user_stats[user_id]["wins"]
        losses = user_stats[user_id]["losses"]
        total = wins + losses
        winrate = (wins / total * 100) if total > 0 else 0

        await update.message.reply_text(
            f"Trades: {total}\n"
            f"Wins: {wins}\n"
            f"Losses: {losses}\n"
            f"Win Rate: {winrate:.2f}%",
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