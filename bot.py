import os
import logging
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

OTC_PAIRS = ["EUR/USD OTC","GBP/USD OTC","USD/JPY OTC","AUD/USD OTC","EUR/JPY OTC","GBP/JPY OTC","EUR/GBP OTC","USD/CHF OTC","EUR/AUD OTC","GBP/AUD OTC","AUD/JPY OTC","CHF/JPY OTC","EUR/CAD OTC","GBP/CAD OTC","AUD/CAD OTC","NZD/USD OTC","EUR/NZD OTC","USD/CAD OTC"]
LIVE_PAIRS = ["EUR/USD","GBP/USD","USD/JPY","AUD/USD","USD/CAD","EUR/JPY","GBP/JPY"]

# Yahoo Finance mapping for real data
YF_MAP = {
    "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/JPY": "USDJPY=X",
    "AUD/USD": "AUDUSD=X", "USD/CAD": "USDCAD=X", "EUR/JPY": "EURJPY=X",
    "GBP/JPY": "GBPJPY=X", "USD/CHF": "USDCHF=X", "EUR/GBP": "EURGBP=X",
    "EUR/AUD": "EURAUD=X", "GBP/AUD": "GBPAUD=X", "AUD/JPY": "AUDJPY=X",
    "CHF/JPY": "CHFJPY=X", "EUR/CAD": "EURCAD=X", "GBP/CAD": "GBPCAD=X",
    "AUD/CAD": "AUDCAD=X", "NZD/USD": "NZDUSD=X", "EUR/NZD": "EURNZD=X"
}

selected_pairs = OTC_PAIRS
selected_timeframe = "1m"
bot_active = False

logging.basicConfig(level=logging.INFO)

def rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def stochastic(df, k=14, d=3):
    low_min = df['low'].rolling(window=k).min()
    high_max = df['high'].rolling(window=k).max()
    df['%K'] = 100 * ((df['close'] - low_min) / (high_max - low_min))
    df['%D'] = df['%K'].rolling(window=d).mean()
    return df

def bollinger(df, period=20, std=2):
    df['ma'] = df['close'].rolling(window=period).mean()
    df['std'] = df['close'].rolling(window=period).std()
    df['upper'] = df['ma'] + (df['std'] * std)
    df['lower'] = df['ma'] - (df['std'] * std)
    return df

def cci(df, period=20):
    tp = (df['high'] + df['low'] + df['close']) / 3
    ma = tp.rolling(window=period).mean()
    md = tp.rolling(window=period).apply(lambda x: np.abs(x - x.mean()).mean())
    df['cci'] = (tp - ma) / (0.015 * md)
    return df

def get_signal_analysis(df):
    df = bollinger(df)
    df = stochastic(df)
    df = cci(df)
    df['rsi'] = rsi(df['close'])
    if len(df) < 30: return None
    score = 0
    breakdown = []
    direction = None
    triggers = []
    last = df.iloc[-1]

    if last['close'] > last['open'] and last['low'] < last['lower'] * 1.001:
        score += 30; breakdown.append("Price Action: Bullish +30"); triggers.append("Price Action Bullish"); direction = "BUY"
    elif last['close'] < last['open'] and last['high'] > last['upper'] * 0.999:
        score += 30; breakdown.append("Price Action: Bearish +30"); triggers.append("Price Action Bearish"); direction = "SELL"
    
    if last['close'] < last['lower'] and last['close'] > last['open']:
        score += 30; breakdown.append("Bollinger Bounce: Bullish +30"); direction = "BUY" if not direction else direction; triggers.append("Bollinger Lower Bounce")
    elif last['close'] > last['upper'] and last['close'] < last['open']:
        score += 30; breakdown.append("Bollinger Bounce: Bearish +30"); direction = "SELL" if not direction else direction; triggers.append("Bollinger Upper Rejection")

    if last['rsi'] < 35:
        score += 25; breakdown.append(f"RSI: Bullish +25 ({last['rsi']:.1f})"); direction = "BUY" if not direction else direction; triggers.append(f"RSI Oversold {last['rsi']:.1f}")
    elif last['rsi'] > 65:
        score += 25; breakdown.append(f"RSI: Bearish +25 ({last['rsi']:.1f})"); direction = "SELL" if not direction else direction; triggers.append(f"RSI Overbought {last['rsi']:.1f}")

    if score < 60: return None
    conf = 60 + (score - 60) * (30/70)
    return {"direction": direction, "score": score, "confidence": round(min(90, max(60, conf)),1), "breakdown": breakdown, "triggers": triggers}

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Start Bot", callback_data='start_bot'), InlineKeyboardButton("⏹ Stop Bot", callback_data='stop_bot')],
        [InlineKeyboardButton("📊 Select Market", callback_data='menu_market'), InlineKeyboardButton("⏰ Timeframe", callback_data='menu_tf')],
        [InlineKeyboardButton("📈 Status", callback_data='status')]
    ])

def market_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("OTC (18 Pairs)", callback_data='set_otc')],
        [InlineKeyboardButton("LIVE (7 Pairs)", callback_data='set_live')],
        [InlineKeyboardButton("⬅️ Back", callback_data='back_main')]
    ])

def timeframe_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1 Min", callback_data='tf_1m'), InlineKeyboardButton("5 Min", callback_data='tf_5m')],
        [InlineKeyboardButton("⬅️ Back", callback_data='back_main')]
    ])

async def start_cmd(update, context):
    await update.message.reply_text(f"🤖 Forex Bot Ready (Real Data)\nMarket: {len(selected_pairs)} pairs\nTF: {selected_timeframe}", reply_markup=main_menu())

async def button_handler(update, context):
    global selected_pairs, bot_active, selected_timeframe
    q = update.callback_query
    await q.answer()
    if q.data == 'start_bot':
        bot_active = True
        await q.edit_message_text(f"✅ Bot Started!\nReal scanning {len(selected_pairs)} pairs / {selected_timeframe}", reply_markup=main_menu())
    elif q.data == 'stop_bot':
        bot_active = False
        await q.edit_message_text("🛑 Bot Stopped", reply_markup=main_menu())
    elif q.data == 'menu_market':
        await q.edit_message_text("Select Market:", reply_markup=market_menu())
    elif q.data == 'menu_tf':
        await q.edit_message_text(f"Current: {selected_timeframe}\nSelect TF:", reply_markup=timeframe_menu())
    elif q.data == 'set_otc':
        selected_pairs = OTC_PAIRS
        await q.edit_message_text("✅ OTC (18) Selected - Real Data", reply_markup=main_menu())
    elif q.data == 'set_live':
        selected_pairs = LIVE_PAIRS
        await q.edit_message_text("✅ LIVE (7) Selected - Real Data", reply_markup=main_menu())
    elif q.data == 'tf_1m':
        selected_timeframe = "1m"
        await q.edit_message_text("✅ TF: 1 Min set", reply_markup=main_menu())
    elif q.data == 'tf_5m':
        selected_timeframe = "5m"
        await q.edit_message_text("✅ TF: 5 Min set", reply_markup=main_menu())
    elif q.data == 'back_main':
        await q.edit_message_text(f"🤖 Ready\nPairs: {len(selected_pairs)}\nTF: {selected_timeframe}", reply_markup=main_menu())
    elif q.data == 'status':
        s = "ACTIVE 🟢" if bot_active else "STOPPED 🔴"
        await q.edit_message_text(f"Status: {s}\nPairs: {len(selected_pairs)}\nTF: {selected_timeframe}", reply_markup=main_menu())

def get_real_df(pair_name):
    base = pair_name.replace(" OTC","")
    yf_symbol = YF_MAP.get(base)
    if not yf_symbol: return None
    df = yf.download(yf_symbol, period="1d", interval=selected_timeframe, progress=False, auto_adjust=True)
    if df.empty or len(df) < 30: return None
    df.columns = [c.lower() for c in df.columns]
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[['open','high','low','close']].dropna()

async def scanner(context):
    if not bot_active: return
    for pair in selected_pairs:
        df = get_real_df(pair)
        if df is None: continue
        analysis = get_signal_analysis(df)
        if analysis:
            emoji = "🟢" if analysis['direction'] == "BUY" else "🔴"
            trig = "\n".join([f"{i+1}. {t}" for i,t in enumerate(analysis['triggers'])])
            brk = "\n".join(analysis['breakdown'])
            msg = f"{emoji} {analysis['direction']} SIGNAL {emoji}\nPair: {pair}\nTF: {selected_timeframe}\nDir: {analysis['direction']}\nConf: {analysis['confidence']}% ({analysis['score']} pts)\n\nTriggers:\n{trig}\n\nBreakdown:\n{brk}\n\n{datetime.now().strftime('%H:%M:%S')}"
            try:
                await context.bot.send_message(chat_id=CHAT_ID, text=msg)
            except Exception as e:
                logging.error(e)

def main():
    if not TOKEN or not CHAT_ID:
        logging.error("TOKEN/CHAT_ID missing!")
        return
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.job_queue.run_repeating(scanner, interval=60, first=10)
    app.run_polling()

if __name__ == "__main__":
    main()
