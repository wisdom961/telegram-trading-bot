from flask import Flask, render_template, jsonify
from database import get_db
import threading
from bot import run_bot

app = Flask(__name__)
DB, cursor = get_db()

# Run Telegram bot in background
threading.Thread(target=run_bot).start()

@app.route("/")
def index():
    cursor.execute("SELECT COUNT(*) FROM users")
    users = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(trades), SUM(wins), SUM(losses) FROM users")
    stats = cursor.fetchone()

    total_trades = stats[0] or 0
    total_wins = stats[1] or 0
    total_losses = stats[2] or 0
    winrate = (total_wins/total_trades*100) if total_trades else 0

    return render_template("index.html",
                           users=users,
                           trades=total_trades,
                           wins=total_wins,
                           losses=total_losses,
                           winrate=round(winrate,2))

@app.route("/latest-signal")
def latest_signal():
    cursor.execute("SELECT symbol,direction,risk,amount,timestamp FROM signals ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    if not row:
        return jsonify({"message":"No signals yet"})
    return jsonify({
        "symbol": row[0],
        "direction": row[1],
        "risk": row[2],
        "amount": row[3],
        "time": row[4]
    })