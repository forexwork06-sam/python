import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import time
import threading
import yfinance as yf
import pandas as pd
import ta
import os
import datetime
import pytz

BOT_TOKEN = os.getenv("BOT_TOKEN")

# Support multiple owners like 5976xxx,75xxx
OWNER_RAW = os.getenv("OWNER_ID") or os.getenv("CHAT_ID") or ""
OWNER_IDS = []
for x in OWNER_RAW.replace(" ", "").split(","):
    if x.lstrip('-').isdigit():
        OWNER_IDS.append(int(x))

OWNER_ID = OWNER_IDS[0] if OWNER_IDS else None
CHAT_ID = str(OWNER_ID) if OWNER_ID else os.getenv("CHAT_ID")

print(f"Owners loaded: {OWNER_IDS}")
IST = pytz.timezone('Asia/Kolkata')
bot = telebot.TeleBot(BOT_TOKEN)

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
PENDING_TRADES = {}

def get_main_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton("Start Bot", callback_data="start_bot"),InlineKeyboardButton("Stop Bot", callback_data="stop_bot"))
    markup.add(InlineKeyboardButton("Select Market (25)", callback_data="select_market"),InlineKeyboardButton("Timeframe", callback_data="timeframe"))
    markup.add(InlineKeyboardButton("Score Filter", callback_data="score_menu"),InlineKeyboardButton("Status", callback_data="status"))
    return markup

def get_score_keyboard():
    markup = InlineKeyboardMarkup(row_width=3)
    markup.add(InlineKeyboardButton("40% (All)", callback_data="score_40"),InlineKeyboardButton("50%", callback_data="score_50"),InlineKeyboardButton("60%", callback_data="score_60"))
    markup.add(InlineKeyboardButton("65%", callback_data="score_65"),InlineKeyboardButton("70%", callback_data="score_70"),InlineKeyboardButton("80%", callback_data="score_80"))
    markup.add(InlineKeyboardButton("Back", callback_data="back_main"))
    return markup

def get_market_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    for pair in ALL_PAIRS:
        check = "✅ " if pair in selected_pairs else ""
        markup.add(InlineKeyboardButton(f"{check}{pair}", callback_data=f"pair_{pair}"))
    markup.add(InlineKeyboardButton("Back", callback_data="back_main"))
    return markup

def get_timeframe_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton("1m", callback_data="tf_1m"),InlineKeyboardButton("5m", callback_data="tf_5m"))
    markup.add(InlineKeyboardButton("Back", callback_data="back_main"))
    return markup

def calculate_score_6factor(df):
    try:
        close = df['Close'].iloc[-1]
        open_p = df['Open'].iloc[-1]
        high = df['High'].iloc[-1]
        low = df['Low'].iloc[-1]
        prev_close = df['Close'].iloc[-2]
        prev_open = df['Open'].iloc[-2]
        bb = ta.volatility.BollingerBands(df['Close'], window=20, window_dev=2)
        bb_upper = bb.bollinger_hband().iloc[-1]
        bb_lower = bb.bollinger_lband().iloc[-1]
        rsi_val = ta.momentum.RSIIndicator(df['Close'], window=14).rsi().iloc[-1]
        stoch = ta.momentum.StochasticOscillator(df['High'], df['Low'], df['Close'], window=14, smooth_window=3)
        k = stoch.stoch().iloc[-1]
        d = stoch.stoch_signal().iloc[-1]
        k_prev = stoch.stoch().iloc[-2]
        d_prev = stoch.stoch_signal().iloc[-2]
        cci = ta.trend.CCIIndicator(df['High'], df['Low'], df['Close'], window=20).cci().iloc[-1]
        if 'Volume' in df.columns and df['Volume'].sum() > 0:
            avg_vol = df['Volume'].rolling(20).mean().iloc[-1]
            curr_vol = df['Volume'].iloc[-1]
            vol_strong = curr_vol > avg_vol * 1.2
        else:
            avg_range = (df['High'] - df['Low']).rolling(20).mean().iloc[-1]
            curr_range = high - low
            vol_strong = curr_range > avg_range * 1.1
        candle_range = high - low
        body = abs(close - open_p)
        body_pct = (body / candle_range * 100) if candle_range > 0 else 0
        bullish_candle = close > open_p
        bearish_candle = close < open_p
        is_hammer = (body_pct < 40) and ((min(open_p, close) - low) > body * 2) if body>0 else False
        is_engulfing_bull = (prev_close < prev_open) and bullish_candle and (close > prev_open) and (open_p < prev_close)
        is_engulfing_bear = (prev_close > prev_open) and bearish_candle and (close < prev_open) and (open_p > prev_close)
        score = 0
        reason = []
        signal_type = None
        is_bb_touch_lower = low <= bb_lower
        is_bb_touch_upper = high >= bb_upper
        if is_bb_touch_lower:
            score += 30
            reason.append("BB Lower Touch +30")
            signal_type = "BUY"
        if signal_type == "BUY":
            if rsi_val < 35:
                score += 20
                reason.append(f"RSI Oversold {rsi_val:.1f} +20")
            if k_prev < d_prev and k > d and k < 20 and d < 20:
                score += 20
                reason.append(f"Stoch Cross UP <20 +20")
            if cci < -100:
                score += 10
                reason.append(f"CCI Extreme {cci:.0f} +10")
            if bullish_candle and (is_hammer or is_engulfing_bull or body_pct > 50):
                score += 10
                reason.append(f"Candle Strong +10")
            if vol_strong and body_pct > 50:
                score += 10
                reason.append("Volume Strong +10")
            else:
                if not vol_strong:
                    score -= 15
                    reason.append("Weak Volume -15 Fake")
        if is_bb_touch_upper:
            if signal_type!= "BUY" or score < 40:
                score = 0
                reason = []
                signal_type = "SELL"
                score += 30
                reason.append("BB Upper Touch +30")
                if rsi_val > 65:
                    score += 20
                    reason.append(f"RSI Overbought {rsi_val:.1f} +20")
                if k_prev > d_prev and k < d and k > 80 and d > 80:
                    score += 20
                    reason.append(f"Stoch Cross DOWN >80 +20")
                if cci > 100:
                    score += 10
                    reason.append(f"CCI Extreme {cci:.0f} +10")
                if bearish_candle and (is_engulfing_bear or body_pct > 50):
                    score += 10
                    reason.append(f"Candle Bearish +10")
                if vol_strong and body_pct > 50:
                    score += 10
                    reason.append("Volume Strong +10")
                else:
                    if not vol_strong:
                        score -= 15
                        reason.append("Weak Volume -15 Fake")
        if signal_type == "BUY" and not bullish_candle:
            return 0, 0, None, ["No bullish close"]
        if signal_type == "SELL" and not bearish_candle:
            return 0, 0, None, ["No bearish close"]
        confidence = min(95, score)
        return score, confidence, signal_type, reason
    except Exception as e:
        print(f"Score error {e}")
        return 0, 0, None, []

def get_data(symbol="EURUSD=X"):
    try:
        df = yf.download(symbol, period="1d", interval="1m", progress=False, auto_adjust=True)
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC').tz_convert(IST)
        else:
            df.index = df.index.tz_convert(IST)
        return df
    except: return None

def check_win_loss(chat_id, pair, signal_type, entry_price, entry_time_ist):
    time.sleep(70)
    try:
        if pair not in PENDING_TRADES: return
        clean_pair = pair.replace(" (OTC)", "").replace("/", "")
        df = get_data(f"{clean_pair}=X")
        if df is None: return
        close_price = df['Close'].iloc[-1]
        win = (signal_type == "BUY" and close_price > entry_price) or (signal_type == "SELL" and close_price < entry_price)
        now_ist = datetime.datetime.now(IST).strftime('%I:%M:%S %p IST')
        result_msg = f"{'WIN' if win else 'LOSS'} - {pair}\n\nSignal: {signal_type}\nEntry: {entry_price:.5f}\nClose: {close_price:.5f}\nTime: {now_ist}\nEntry: {entry_time_ist}"
        bot.send_message(chat_id, result_msg)
        if pair in PENDING_TRADES: del PENDING_TRADES[pair]
    except Exception as e:
        print(f"Result error {e}")
        if pair in PENDING_TRADES: del PENDING_TRADES[pair]

def scanner_loop(chat_id):
    global bot_active
    while bot_active:
        try:
            now_ist = datetime.datetime.now(IST)
            if now_ist.second < 40:
                time.sleep(2)
                continue
            for pair in selected_pairs[:]:
                if not bot_active: break
                if pair in LAST_SIGNAL and (now_ist - LAST_SIGNAL[pair]).total_seconds() < 70: continue
                if pair in PENDING_TRADES: continue
                clean_pair = pair.replace(" (OTC)", "").replace("/", "")
                df = get_data(f"{clean_pair}=X")
                if df is None or len(df) < 30: continue
                score, conf, sig_type, reasons = calculate_score_6factor(df)
                if sig_type and score >= SCORE_THRESHOLD:
                    LAST_SIGNAL[pair] = now_ist
                    entry_price = df['Close'].iloc[-1]
                    entry_time_str = now_ist.strftime('%I:%M:%S %p IST')
                    PENDING_TRADES[pair] = {"entry_price": entry_price, "type": sig_type, "time": now_ist}
                    msg = f"{pair} {sig_type} SIGNAL\n\nScore: {score}/100 | Conf: {conf}%\nEntry: Next 1m Candle OPEN - {entry_time_str}\n------------------------\n" + "\n".join(reasons) + f"\n------------------------\n{entry_time_str} | Filter {SCORE_THRESHOLD}%"
                    bot.send_message(chat_id, msg)
                    threading.Thread(target=check_win_loss, args=(chat_id, pair, sig_type, entry_price, entry_time_str), daemon=True).start()
            time.sleep(1)
        except Exception as e:
            print(f"Scanner error {e}")
            time.sleep(1)

@bot.message_handler(commands=['start'])
def start_handler(message):
    if message.chat.id not in OWNER_IDS:
         bot.send_message(message.chat.id, "Bot Locked.")
         return
    bot.send_message(message.chat.id, f"Status: {'ACTIVE' if bot_active else 'STOPPED'}\nPairs: {len(selected_pairs)}\nTF: {timeframe} | Filter: {SCORE_THRESHOLD}%", reply_markup=get_main_keyboard())

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    global bot_active, timeframe, selected_pairs, SCORE_THRESHOLD
    if call.message.chat.id not in OWNER_IDS:
         bot.answer_callback_query(call.id, "Locked")
         return
    chat_id = call.message.chat.id
    data = call.data
    if data == "start_bot":
        if not bot_active:
            bot_active = True
            bot.send_message(chat_id, f"Bot Started | Filter {SCORE_THRESHOLD}%", reply_markup=get_main_keyboard())
            threading.Thread(target=scanner_loop, args=(chat_id,), daemon=True).start()
    elif data == "stop_bot":
        bot_active = False
        bot.send_message(chat_id, "Bot Stopped", reply_markup=get_main_keyboard())
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
        bot.send_message(chat_id, f"TF: {timeframe} set", reply_markup=get_main_keyboard())
    elif data == "score_menu":
        bot.edit_message_text(f"Current: {SCORE_THRESHOLD}%", chat_id, call.message.message_id, reply_markup=get_score_keyboard())
    elif data.startswith("score_"):
        SCORE_THRESHOLD = int(data.split("_")[1])
        bot.send_message(chat_id, f"Filter: {SCORE_THRESHOLD}% set.", reply_markup=get_main_keyboard())
    elif data == "status":
        pending = ", ".join(PENDING_TRADES.keys()) if PENDING_TRADES else "None"
        bot.send_message(chat_id, f"Status: {'ACTIVE' if bot_active else 'STOPPED'}\nPairs: {selected_pairs}\nFilter: {SCORE_THRESHOLD}%\nPending: {pending}", reply_markup=get_main_keyboard())
    elif data == "back_main":
        bot.edit_message_text(f"Status: {'ACTIVE' if bot_active else 'STOPPED'}\nPairs: {len(selected_pairs)}\nFilter: {SCORE_THRESHOLD}%", chat_id, call.message.message_id, reply_markup=get_main_keyboard())

print("Bot running...")
try:
    bot.remove_webhook()
    time.sleep(1)
except: pass
bot.infinity_polling(skip_pending=True)
