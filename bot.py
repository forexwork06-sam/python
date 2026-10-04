import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import time
import threading
import yfinance as yf
import pandas as pd
import ta

import os
# --- CONFIG ---
BOT_TOKEN = os.getenv("BOT_TOKEN") # Railway Variable se lega
CHAT_ID = os.getenv("CHAT_ID")
bot = telebot.TeleBot(BOT_TOKEN)

# --- GLOBAL SETTINGS (Purana wala same) ---
selected_pairs = ["EUR/USD (OTC)"]
timeframe = "1m"
bot_active = False
FAKE_FILTER = True
SCORE_THRESHOLD = 63 # Default

ALL_PAIRS = [
    "EUR/USD (OTC)", "GBP/USD (OTC)", "USD/JPY (OTC)", "AUD/USD (OTC)",
    "EUR/GBP (OTC)", "USD/CHF (OTC)", "EUR/JPY (OTC)", "GBP/JPY (OTC)"
]

# --- KEYBOARDS ---
def get_main_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🟢 Start Bot", callback_data="start_bot"),
        InlineKeyboardButton("🔴 Stop Bot", callback_data="stop_bot")
    )
    markup.add(
        InlineKeyboardButton("📈 Select Market", callback_data="select_market"),
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
        InlineKeyboardButton("40%", callback_data="score_40"),
        InlineKeyboardButton("50%", callback_data="score_50"),
        InlineKeyboardButton("60%", callback_data="score_60")
    )
    markup.add(
        InlineKeyboardButton("65%", callback_data="score_65"),
        InlineKeyboardButton("70%", callback_data="score_70"),
        InlineKeyboardButton("80%", callback_data="score_80")
    )
    markup.add(
        InlineKeyboardButton("90%", callback_data="score_90"),
        InlineKeyboardButton("99%", callback_data="score_99")
    )
    markup.add(InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
    return markup

def get_market_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    for pair in ALL_PAIRS:
        markup.add(InlineKeyboardButton(pair, callback_data=f"pair_{pair}"))
    markup.add(InlineKeyboardButton("⬅️ Back", callback_data="back_main"))
    return markup

def get_timeframe_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("1m", callback_data="tf_1m"),
        InlineKeyboardButton("5m", callback_data="tf_5m")
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
        vol_avg = df['Volume'].rolling(20).mean().iloc[-1] if 'Volume' in df else 1
        vol_curr = df['Volume'].iloc[-1] if 'Volume' in df else 1
        vol_ratio = vol_curr / vol_avg if vol_avg!= 0 else 1
        vol_strong = vol_ratio > 1.1

        score = 0
        reason = []
        signal_type = None

        if close <= bb_lower:
            score += 30
            reason.append(f"Bollinger Bounce +30")
            signal_type = "BUY"
        elif close >= bb_upper:
            score += 30
            reason.append(f"Bollinger Rejection +30")
            signal_type = "SELL"

        if rsi < 35 and signal_type == "BUY":
            score += 25
            reason.append(f"RSI Oversold {rsi:.1f} +25")
        elif rsi > 65 and signal_type == "SELL":
            score += 25
            reason.append(f"RSI Overbought {rsi:.1f} +25")

        if stoch < 20 and stoch > stoch_signal and signal_type == "BUY":
            score += 20
            reason.append(f"Stoch Cross +20")
        elif stoch > 80 and stoch < stoch_signal and signal_type == "SELL":
            score += 20
            reason.append(f"Stoch Cross +20")

        if vol_strong:
            score += 15
            reason.append(f"Vol {vol_ratio:.1f}x (STRONG)")
        else:
            reason.append(f"Vol {vol_ratio:.1f}x (Normal)")

        confidence = min(95, score + 10)
        return score, confidence, signal_type, reason, vol_strong
    except Exception as e:
        return 0, 0, None, [], False

def get_data(symbol="EURUSD=X"):
    try:
        df = yf.download(symbol, period="1d", interval="1m", progress=False)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except:
        return None

# --- SCANNER ---
def scanner_loop(chat_id):
    global bot_active
    while bot_active:
        try:
            for pair in selected_pairs:
                if not bot_active:
                    break
                clean_pair = pair.replace(" (OTC)", "").replace("/", "")
                yahoo_symbol = f"{clean_pair}=X"
                df = get_data(yahoo_symbol)
                if df is None or len(df) < 30:
                    continue

                score, conf, sig_type, reasons, vol_strong = calculate_score(df)
                print(f"Scanning {pair}... Score {score} vs Filter {SCORE_THRESHOLD}")

                if sig_type and score >= SCORE_THRESHOLD:
                    if FAKE_FILTER and not vol_strong and score < 70:
                        continue

                    msg = (
                        f"🔥 **{pair} {sig_type} SIGNAL** 🔥\n\n"
                        f"📊 **Score: {score} | Confidence: {conf}%**\n"
                        f"⏱️ TF: {timeframe} | Filter: {SCORE_THRESHOLD}%+\n"
                        f"-------------------------\n"
                        + "\n".join([f"• {r}" for r in reasons]) +
                        f"\n-------------------------\n"
                        f"⏰ Time: {time.strftime('%H:%M:%S')}"
                    )
                    bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=get_main_keyboard())
            time.sleep(60)
        except Exception as e:
            print(f"Scanner error: {e}")
            time.sleep(5)

# --- HANDLERS ---
@bot.message_handler(commands=['start'])
def start_handler(message):
    bot.send_message(
        message.chat.id,
        f"Status: {'ACTIVE 🟢' if bot_active else 'STOPPED 🔴'}\n"
        f"Market: OTC\n"
        f"Pairs: {len(selected_pairs)} {', '.join(selected_pairs)}\n"
        f"TF: {timeframe}\n"
        f"Score Filter: {SCORE_THRESHOLD}%\n"
        f"Fake Filter: {'ON' if FAKE_FILTER else 'OFF'}",
        reply_markup=get_main_keyboard()
    )

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    global bot_active, timeframe, selected_pairs, SCORE_THRESHOLD
    chat_id = call.message.chat.id
    data = call.data

    if data == "start_bot":
        if not bot_active:
            bot_active = True
            bot.send_message(chat_id, f"✅ Bot Started with Score {SCORE_THRESHOLD}%", reply_markup=get_main_keyboard())
            threading.Thread(target=scanner_loop, args=(chat_id,), daemon=True).start()

    elif data == "stop_bot":
        bot_active = False
        bot.send_message(chat_id, "🔴 Bot Stopped", reply_markup=get_main_keyboard())

    elif data == "select_market":
        bot.send_message(chat_id, "Select Market:", reply_markup=get_market_keyboard())

    elif data.startswith("pair_"):
        pair_name = data.replace("pair_", "")
        if pair_name in selected_pairs:
            selected_pairs.remove(pair_name)
        else:
            selected_pairs.append(pair_name)
            if len(selected_pairs) > 2:
                selected_pairs = selected_pairs[-2:]
        bot.send_message(
            chat_id,
            f"Status: {'ACTIVE 🟢' if bot_active else 'STOPPED 🔴'}\n"
            f"Market: OTC\n"
            f"Pairs: {len(selected_pairs)} {', '.join(selected_pairs)}\n"
            f"TF: {timeframe}\n"
            f"Score Filter: {SCORE_THRESHOLD}%\n"
            f"Fake Filter: {'ON' if FAKE_FILTER else 'OFF'}",
            reply_markup=get_main_keyboard()
        )

    elif data == "timeframe":
        bot.send_message(chat_id, "Select Timeframe:", reply_markup=get_timeframe_keyboard())

    elif data.startswith("tf_"):
        timeframe = data.replace("tf_", "")
        bot.send_message(chat_id, f"⏱️ TF: {timeframe} set", reply_markup=get_main_keyboard())

    elif data == "score_menu":
        bot.send_message(
            chat_id,
            f"🎯 **Current Score Filter: {SCORE_THRESHOLD}%**\n\n"
            f"40% = Sab signals (testing)\n"
            f"60% = Medium\n"
            f"70% = Strong (Recommended)\n"
            f"99% = Only super strong",
            parse_mode="Markdown",
            reply_markup=get_score_keyboard()
        )

    elif data.startswith("score_"):
        new_score = int(data.split("_")[1])
        SCORE_THRESHOLD = new_score
        bot.send_message(
            chat_id,
            f"✅ **Score Filter set: {SCORE_THRESHOLD}%**\n"
            f"Ab sirf {SCORE_THRESHOLD}%+ wale hi ayenge.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )

    elif data == "status":
        bot.send_message(
            chat_id,
            f"Status: {'ACTIVE 🟢' if bot_active else 'STOPPED 🔴'}\n"
            f"Market: OTC\n"
            f"Pairs: {len(selected_pairs)} {', '.join(selected_pairs)}\n"
            f"TF: {timeframe}\n"
            f"Score Filter: {SCORE_THRESHOLD}%\n"
            f"Fake Filter: {'ON' if FAKE_FILTER else 'OFF'}",
            reply_markup=get_main_keyboard()
        )

    elif data == "back_main":
        bot.send_message(
            chat_id,
            f"Status: {'ACTIVE 🟢' if bot_active else 'STOPPED 🔴'}\n"
            f"Market: OTC\n"
            f"Pairs: {len(selected_pairs)} {', '.join(selected_pairs)}\n"
            f"TF: {timeframe}\n"
            f"Score Filter: {SCORE_THRESHOLD}%\n"
            f"Fake Filter: {'ON' if FAKE_FILTER else 'OFF'}",
            reply_markup=get_main_keyboard()
        )

print("Sam.ai bot running...")
bot.infinity_polling()
