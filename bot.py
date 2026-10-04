import yfinance as yf
import time
import threading
import os
import pandas as pd
from datetime import datetime
import requests

PAIRS = {"EUR/USD":"EURUSD=X","GBP/USD":"GBPUSD=X","USD/JPY":"JPY=X","EUR/JPY":"EURJPY=X","AUD/USD":"AUDUSD=X"}
selected_pair = "EUR/USD"
selected_interval = "1m"
is_running = False
last_signal_time = 0

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8722261999:AAGXxvogJ8u_9tvB_GicqwU0izq6a4My25s")
CHAT_ID = os.getenv("CHAT_ID", "5976851878")

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except: pass

def calculate_rsi(data, period=14):
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def telegram_listener():
    print("Bot Ready")
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={offset}&timeout=10"
            r = requests.get(url, timeout=15).json()
            for update in r.get("result", []):
                offset = update["update_id"] + 1
                text = update.get("message", {}).get("text", "").lower()
                global is_running
                if "start" in text:
                    is_running = True
                    send_telegram("✅ Bot START ho gaya")
                elif "stop" in text:
                    is_running = False
                    send_telegram("🛑 Bot STOP ho gaya")
                elif "status" in text:
                    s = "CHALU ✅" if is_running else "BAND 🛑"
                    send_telegram(f"Status: {s}")
            time.sleep(2)
        except: time.sleep(2)

threading.Thread(target=telegram_listener, daemon=True).start()

while True:
    try:
        if not is_running:
            time.sleep(1)
            continue
        symbol = PAIRS.get(selected_pair)
        if time.time() - last_signal_time < 60:
            time.sleep(0.5)
            continue
        df = yf.download(symbol, period="1d", interval=selected_interval, progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if len(df) < 50:
            time.sleep(0.5)
            continue
        close = df['Close']
        ema9 = close.ewm(span=9).mean().iloc[-1]
        ema21 = close.ewm(span=21).mean().iloc[-1]
        ema50 = close.ewm(span=50).mean().iloc[-1]
        rsi = calculate_rsi(close).iloc[-1]
        last_candle = df.iloc[-1]
        body = abs(last_candle['Close'] - last_candle['Open'])
        upper_wick = last_candle['High'] - max(last_candle['Close'], last_candle['Open'])
        lower_wick = min(last_candle['Close'], last_candle['Open']) - last_candle['Low']
        trend_call = 0
        trend_put = 0
        if ema9 > ema21: trend_call += 1
        else: trend_put += 1
        if close.iloc[-1] > ema50: trend_call += 1
        else: trend_put += 1
        if rsi > 50 and rsi < 70: trend_call += 1
        elif rsi < 50 and rsi > 30: trend_put += 1
        if trend_call >= 2:
            score = 70 + int(rsi - 50) if rsi < 70 else 85
            if upper_wick > body: score -= 5
            msg = f"🚀 {selected_pair} CALL | Score: {score}% | RSI: {int(rsi)}"
            if score >= 70:
                send_telegram(msg)
                last_signal_time = time.time()
        elif trend_put >= 2:
            score = 70 + int(50 - rsi) if rsi > 30 else 85
            if lower_wick > body: score -= 5
            msg = f"🔻 {selected_pair} PUT | Score: {score}% | RSI: {int(rsi)}"
            if score >= 70:
                send_telegram(msg)
                last_signal_time = time.time()
        time.sleep(1)
    except Exception as e:
        print(e)
        time.sleep(1)