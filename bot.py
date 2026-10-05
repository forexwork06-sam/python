import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import time
import threading
import yfinance as yf
import pandas as pd
import ta
import os
import datetime

# --- CONFIG ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
OWNER_ID = int(CHAT_ID) if CHAT_ID and CHAT_ID.lstrip('-').isdigit() else None

bot = telebot.TeleBot(BOT_TOKEN)

# --- 18 OTC + 7 LIVE = 25 PAIRS ---
ALL_PAIRS = [
    "EUR/USD (OTC)", "GBP/USD (OTC)", "USD/JPY (OTC)", "AUD/USD (OTC)",
    "EUR/GBP (OTC)", "USD/CHF (OTC)", "EUR/JPY (OTC)", "GBP/JPY (OTC)",
    "AUD/JPY (OTC)", "EUR/AUD (OTC)", "USD/CAD (OTC)", "NZD/USD (OTC)",
    "EUR/CAD (OTC)", "GBP/AUD (OTC)", "AUD/CAD (OTC)", "GBP/CAD (OTC)",
    "EUR/NZD (OTC)", "GBP/NZD (OTC)",
    "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD", "EUR/JPY", "GBP/JPY"
]

selected_pairs = ["EUR/USD (OTC)"]
timeframe = "1m"
bot_active = False
SCORE_THRESHOLD = 40
LAST_SIGNAL = {}

# --- KEYBOARDS ---
def get_main_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🟢 Start Bot", callback_data="start_bot"),
        InlineKeyboardButton("🔴 Stop Bot", callback_data="stop_bot")
    )
    markup.add(
        InlineKeyboardButton("📈 Select Market (25)", callback_data="select_market"),
        InlineKeyboardButton("⏱️ Timeframe", callback_data="timeframe")
    )
    markup.add(
        InlineKeyboardButton("🎯 Score Filter", callback_data="score_menu"),
        InlineKeyboardButton("📊 Status", callback_data="status")
    )
    return markup

def get_score_keyboard():
    markup = InlineKeyboardMarkup(row_width=3)
    markup.add(
        InlineKeyboardButton("40% (All)", callback_data="score_40"),
        InlineKeyboardButton("50%", callback_data="score_50"),
        InlineKeyboardButton("60%", callback_data="score_60")
    )
    markup.add(
        InlineKeyboardButton("65%", callback_data="score_65"),
        InlineKeyboardButton("70%", callback_data="score_70"),
        InlineKeyboardButton("80%", callback_data="score_80")
    )
    markup.add(InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
    return markup

def get_market_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    for pair in ALL_PAIRS:
        check = "✅ " if pair in selected_pairs else ""
        markup.add(InlineKeyboardButton(f"{check}{pair}", callback_data=f"pair_{pair}"))
    markup.add(InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
    return markup

def get_timeframe_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("1m", callback_data="tf_1m"),
        InlineKeyboardButton("5m", callback_data="tf_5m"),
    )
    markup.add(InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
    return markup

# --- SIGNAL LOGIC ---
def calculate_score(df):
    try:
        bb = ta.volatility.BollingerBands(df['Close'], window=20, window_dev=2)
        bb_upper = bb.bollinger_hband().iloc[-1]
        bb_lower = bb.bollinger_lband().iloc[-1]
        close = df['Close'].iloc[-1]
        rsi = ta.momentum.RSIIndicator(df['Close'], window=14).rsi().iloc[-1]
        stoch = ta.momentum.StochasticOscillator(df['High'], df['Low'], df['Close']).stoch().iloc[-1]
        stoch_signal = ta.momentum.StochasticOscillator(df['High'], df['Low'], df['Close']).stoch_signal().iloc[-1]

        score = 0
        reason = []
        signal_type = None

        if close <= bb_lower: score += 30; reason.append(f"Bollinger Bounce +30"); signal_type = "BUY"
        elif close >= bb_upper: score += 30; reason.append(f"Bollinger Rejection +30"); signal_type = "SELL"

        if rsi < 38 and signal_type == "BUY": score += 25; reason.append(f"RSI Oversold {rsi:.1f} +25")
        elif rsi > 62 and signal_type == "SELL": score += 25; reason.append(f"RSI Overbought {rsi:.1f} +25")

        if stoch < 25 and stoch > stoch_signal and signal_type == "BUY": score += 20; reason.append(f"Stoch Cross +20")
        elif stoch > 75 and stoch < stoch_signal and signal_type == "SELL": score += 20; reason.append(f"Stoch Cross +20")

        confidence = min(95, score + 20)
        return score, confidence, signal_type, reason
    except Exception as e:
        print(f"Score error {e}")
        return 0, 0, None, []

def get_data(symbol="EURUSD=X"):
    try:
        df = yf.download(symbol, period="1d", interval="1m", progress=False, auto_adjust=True)
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        return df
    except: return None

def check_win_loss(chat_id, pair, signal_type, entry_price):
    time.sleep(65)
    try:
        clean_pair = pair.replace(" (OTC)", "").replace("/", "")
        yahoo_symbol = f"{clean_pair}=X"
        df = get_data(yahoo_symbol)
        if df is None: return
        close_price = df['Close'].iloc[-1]
        win = (signal_type == "BUY" and close_price > entry_price) or (signal_type == "SELL" and close_price < entry_price)
        result_msg = f"{'✅ WIN 🟢' if win else '❌ LOSS 🔴'}\n\nPair: {pair}\nSignal: {signal_type}\nEntry: {entry_price:.5f}\nClose: {close_price:.5f}"
        bot.send_message(chat_id, result_msg)
    except Exception as e:
        print(f"Result error {e}")

# --- 40 SEC ANALYSIS + 20 SEC ENTRY ---
def scanner_loop(chat_id):
    global bot_active
    print("Scanner Started - 40s Analysis, 20s Entry")
    last_signal_minute = -1
    while bot_active:
        try:
            now = datetime.datetime.now()
            now_sec = now.second
            now_min = now.minute

            if now_sec < 40:
                for pair in selected_pairs[:]:
                    if not bot_active: break
                    clean_pair = pair.replace(" (OTC)", "").replace("/", "")
                    yahoo_symbol = f"{clean_pair}=X"
                    df = get_data(yahoo_symbol)
                    if df is None or len(df) < 30: continue
                    calculate_score(df)
                    print(f"Analyzing {pair}... sec {now_sec}")
                time.sleep(2)
                continue

            if now_min == last_signal_minute:
                time.sleep(1)
                continue

            for pair in selected_pairs[:]:
                if not bot_active: break
                if pair in LAST_SIGNAL and time.time() - LAST_SIGNAL[pair] < 120:
                    continue
                clean_pair = pair.replace(" (OTC)", "").replace("/", "")
                yahoo_symbol = f"{clean_pair}=X"
                df = get_data(yahoo_symbol)
                if df is None or len(df) < 30: continue

                score, conf, sig_type, reasons = calculate_score(df)
                print(f"Final Scan {pair}... Score {score} at {now_sec}s")

                if sig_type and score >= SCORE_THRESHOLD:
                    LAST_SIGNAL[pair] = time.time()
                    last_signal_minute = now_min
                    entry_price = df['Close'].iloc[-1]
                    msg = (
                        f"🔥 **{pair} {sig_type} SIGNAL** 🔥\n\n"
                        f"📊 Score: {score} | Conf: {conf}%\n"
                        f"⏱️ Entry in next 15-20 sec\n"
                        f"-------------------------\n"
                        + "\n".join([f"• {r}" for r in reasons]) +
                        f"\n-------------------------\n"
                        f"⏰ {time.strftime('%H:%M:%S')} | Filter {SCORE_THRESHOLD}%"
                    )
                    bot.send_message(chat_id, msg, parse_mode="Markdown")
                    threading.Thread(target=check_win_loss, args=(chat_id, pair, sig_type, entry_price), daemon=True).start()
            time.sleep(1)
        except Exception as e:
            print(f"Scanner error: {e}")
            time.sleep(1)

# --- HANDLERS ---
@bot.message_handler(commands=['start'])
def start_handler(message):
    if OWNER_ID and message.chat.id!= OWNER_ID:
        bot.send_message(message.chat.id, "🔒 Bot Locked. Unauthorized.")
        return
    bot.send_message(
        message.chat.id,
        f"Status: {'ACTIVE 🟢' if bot_active else 'STOPPED 🔴'}\n"
        f"Pairs: {len(selected_pairs)} | {', '.join(selected_pairs)}\n"
        f"TF: {timeframe} | Filter: {SCORE_THRESHOLD}%\n"
        f"Total: 18 OTC + 7 LIVE = 25",
        reply_markup=get_main_keyboard()
    )

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    global bot_active, timeframe, selected_pairs, SCORE_THRESHOLD
    if OWNER_ID and call.message.chat.id!= OWNER_ID:
        bot.answer_callback_query(call.id, "🔒 Locked")
        return
    chat_id = call.message.chat.id
    data = call.data

    if data == "start_bot":
        if not bot_active:
            bot_active = True
            bot.send_message(chat_id, f"✅ Bot Started | 40s Analysis | Filter {SCORE_THRESHOLD}% | 20s Entry", reply_markup=get_main_keyboard())
            threading.Thread(target=scanner_loop, args=(chat_id,), daemon=True).start()
    elif data == "stop_bot":
        bot_active = False
        bot.send_message(chat_id, "🔴 Bot Stopped", reply_markup=get_main_keyboard())
    elif data == "select_market":
        bot.edit_message_text("Select Market (25 Pairs):", chat_id, call.message.message_id, reply_markup=get_market_keyboard())
    elif data.startswith("pair_"):
        pair_name = data.replace("pair_", "")
        s = set(selected_pairs)
        if pair_name in s: s.remove(pair_name)
        else: s.add(pair_name)
        selected_pairs = list(s)
        bot.edit_message_text(f"Selected: {len(selected_pairs)} pairs", chat_id, call.message.message_id, reply_markup=get_market_keyboard())
    elif data == "timeframe":
        bot.edit_message_text("Select Timeframe:", chat_id, call.message.message_id, reply_markup=get_timeframe_keyboard())
    elif data.startswith("tf_"):
        timeframe = data.replace("tf_", "")
        bot.send_message(chat_id, f"⏱️ TF: {timeframe} set", reply_markup=get_main_keyboard())
    elif data == "score_menu":
        bot.edit_message_text(f"🎯 Current: {SCORE_THRESHOLD}%\n40% = All signals", chat_id, call.message.message_id, reply_markup=get_score_keyboard())
    elif data.startswith("score_"):
        SCORE_THRESHOLD = int(data.split("_")[1])
        bot.send_message(chat_id, f"✅ Filter: {SCORE_THRESHOLD}% set.", reply_markup=get_main_keyboard())
    elif data == "status":
        bot.send_message(chat_id, f"Status: {'ACTIVE 🟢' if bot_active else 'STOPPED 🔴'}\nPairs: {selected_pairs}\nFilter: {SCORE_THRESHOLD}%", reply_markup=get_main_keyboard())
    elif data == "back_main":
        bot.edit_message_text(f"Status: {'ACTIVE 🟢' if bot_active else 'STOPPED 🔴'}\nPairs: {len(selected_pairs)}\nFilter: {SCORE_THRESHOLD}%", chat_id, call.message.message_id, reply_markup=get_main_keyboard())

print("Bot running with 25 pairs, 40s analysis, 20s entry, WIN/LOSS, Lock...")
try:
    bot.remove_webhook()
    time.sleep(1)
except: pass
bot.infinity_polling(skip_pending=True, none_stop=True, timeout=60)
