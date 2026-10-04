import os
import asyncio
import logging
import numpy as np
import pandas as pd
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# --- CONFIG - Railway Variables se ---
TOKEN = os.getenv("8722261999:AAF5_67b8rMkAf8tJEEC6BKAlkNPsS2CWoE")
CHAT_ID = os.getenv("5976851878")

OTC_PAIRS = ["EUR/USD OTC","GBP/USD OTC","USD/JPY OTC","AUD/USD OTC","EUR/JPY OTC","GBP/JPY OTC","EUR/GBP OTC","USD/CHF OTC","EUR/AUD OTC","GBP/AUD OTC","AUD/JPY OTC","CHF/JPY OTC","EUR/CAD OTC","GBP/CAD OTC","AUD/CAD OTC","NZD/USD OTC","EUR/NZD OTC","USD/CAD OTC"]
LIVE_PAIRS = ["EUR/USD","GBP/USD","USD/JPY","AUD/USD","USD/CAD","EUR/JPY","GBP/JPY"]
selected_pairs = OTC_PAIRS
selected_timeframe = "1 min"
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
    score = 0
    breakdown = []
    direction = None
    entry_triggers = []
    last = df.iloc[-1]
    prev = df.iloc[-2]

    if last['close'] > last['open'] and last['low'] < last['lower'] * 1.001:
        score += 30; breakdown.append("• Price Action (30pts): Bullish +30"); entry_triggers.append("Price Action Bullish"); direction = "BUY"
    elif last['close'] < last['open'] and last['high'] > last['upper'] * 0.999:
        score += 30; breakdown.append("• Price Action (30pts): Bearish +30"); entry_triggers.append("Price Action Bearish"); direction = "SELL"
    else: breakdown.append("• Price Action (30pts): Neutral +0")

    if last['close'] < last['lower'] and last['close'] > last['open']:
        score += 30; breakdown.append("• Bollinger Band Bounce (30pts): Bullish +30"); direction = "BUY" if direction is None else direction; entry_triggers.append("Bollinger Lower Bounce")
    elif last['close'] > last['upper'] and last['close'] < last['open']:
        score += 30; breakdown.append("• Bollinger Band Bounce (30pts): Bearish +30"); direction = "SELL" if direction is None else direction; entry_triggers.append("Bollinger Upper Rejection")
    else: breakdown.append("• Bollinger Band Bounce (30pts): Neutral +0")

    if last['rsi'] < 35:
        score += 25; breakdown.append(f"• RSI Divergence (25pts): Bullish +25 (RSI {last['rsi']:.1f})"); direction = "BUY" if direction is None else direction; entry_triggers.append(f"RSI Oversold {last['rsi']:.1f}")
    elif last['rsi'] > 65:
        score += 25; breakdown.append(f"• RSI Divergence (25pts): Bearish +25 (RSI {last['rsi']:.1f})"); direction = "SELL" if direction is None else direction; entry_triggers.append(f"RSI Overbought {last['rsi']:.1f}")
    else: breakdown.append("• RSI Divergence (25pts): Neutral +0")

    if last['%K'] < 20 and last['%K'] > last['%D'] and prev['%K'] <= prev['%D']:
        score += 20; breakdown.append("• Stochastic Cross (20pts): Bullish +20"); direction = "BUY" if direction is None else direction; entry_triggers.append("Stoch Bullish Cross")
    elif last['%K'] > 80 and last['%K'] < last['%D'] and prev['%K'] >= prev['%D']:
        score += 20; breakdown.append("• Stochastic Cross (20pts): Bearish +20"); direction = "SELL" if direction is None else direction; entry_triggers.append("Stoch Bearish Cross")
    else: breakdown.append("• Stochastic Cross (20pts): Neutral +0")

    if last['cci'] < -100:
        score += 15; breakdown.append(f"• CCI Extreme (15pts): Bullish +15 (CCI {last['cci']:.0f})"); direction = "BUY" if direction is None else direction; entry_triggers.append(f"CCI Extreme {last['cci']:.0f}")
    elif last['cci'] > 100:
        score += 15; breakdown.append(f"• CCI Extreme (15pts): Bearish +15 (CCI {last['cci']:.0f})"); direction = "SELL" if direction is None else direction; entry_triggers.append(f"CCI Extreme {last['cci']:.0f}")
    else: breakdown.append("• CCI Extreme (15pts): Neutral +0")

    if last['close'] > last['open'] and prev['close'] < prev['open'] and last['close'] > prev['open']:
        score += 10; breakdown.append("• Candlestick Pattern (10pts): Bullish Engulfing +10"); entry_triggers.append("Bullish Engulfing"); direction = "BUY" if direction is None else direction
    elif last['close'] < last['open'] and prev['close'] > prev['open'] and last['close'] < prev['open']:
        score += 10; breakdown.append("• Candlestick Pattern (10pts): Bearish Engulfing +10"); entry_triggers.append("Bearish Engulfing"); direction = "SELL" if direction is None else direction
    else: breakdown.append("• Candlestick Pattern (10pts): Neutral +0")

    if score < 60: return None
    confidence = 60 + (score - 60) * (39 / 70)
    confidence = min(99, max(60, confidence))
    return {"direction": direction, "score": score, "confidence": round(confidence,1), "breakdown": breakdown, "triggers": entry_triggers}

def main_menu():
    keyboard = [[InlineKeyboardButton("▶️ Start Bot", callback_data='start_bot')], [InlineKeyboardButton("⏹️ Stop Bot", callback_data='stop_bot')], [InlineKeyboardButton("📊 OTC (18)", callback_data='set_otc'), InlineKeyboardButton("📈 LIVE (7)", callback_data='set_live')]]
    return InlineKeyboardMarkup(keyboard)

async def start_cmd(update, context):
    await update.message.reply_text(f"🤖 Forex Bot Ready\nMin 60 Points = 60% Confidence\nID: {CHAT_ID}", reply_markup=main_menu())

async def button_handler(update, context):
    global selected_pairs, bot_active
    query = update.callback_query
    await query.answer()
    if query.data == 'start_bot': bot_active = True; await query.edit_message_text("✅ Bot Started! Scanning...", reply_markup=main_menu())
    elif query.data == 'stop_bot': bot_active = False; await query.edit_message_text("⛔ Bot Stopped", reply_markup=main_menu())
    elif query.data == 'set_otc': selected_pairs = OTC_PAIRS; await query.edit_message_text("✅ OTC (18) Selected", reply_markup=main_menu())
    elif query.data == 'set_live': selected_pairs = LIVE_PAIRS; await query.edit_message_text("✅ LIVE (7) Selected", reply_markup=main_menu())

def get_dummy_df():
    closes = np.random.normal(1.1, 0.001, 50)
    return pd.DataFrame({'open': closes, 'high': closes+0.0005, 'low': closes-0.0005, 'close': closes})

async def scanner(context):
    if not bot_active: return
    for pair in selected_pairs:
        df = get_dummy_df()
        analysis = get_signal_analysis(df)
        if analysis:
            emoji = "🟢" if analysis['direction'] == "BUY" else "🔴"
            triggers_text = "\n".join([f"  {i+1}. {t}" for i, t in enumerate(analysis['triggers'])])
            breakdown_text = "\n".join(analysis['breakdown'])
            msg = f"{emoji} {analysis['direction']} SIGNAL {emoji}\n━━━━━━━━━━━━━━━\nPair: {pair}\nTimeframe: {selected_timeframe}\nDirection: {analysis['direction']}\n\n🎯 ENTRY TRIGGERS ({len(analysis['triggers'])}):\n{triggers_text}\n\n📊 6-FACTOR BREAKDOWN:\n{breakdown_text}\n\nCONFLUENCE SCORE: {analysis['score']}/130\nCONFIDENCE: {analysis['confidence']}%\n━━━━━━━━━━━━━━━\nTime: {datetime.now().strftime('%H:%M:%S')} IST"
            await context.bot.send_message(chat_id=CHAT_ID, text=msg)

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.job_queue.run_repeating(scanner, interval=10, first=5)
    app.run_polling()

if __name__ == "__main__":
    main()
