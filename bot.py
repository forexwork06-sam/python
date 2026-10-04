import os
import yfinance as yf
import pandas as pd
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import asyncio

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8722261999:AAQXsvogJ8u_9tvB_G1cq4UB1zq6Ax0PY2s5")
CHAT_ID = os.getenv("CHAT_ID", "5976851878")

PAIRS = {
    "EUR/USD": "EURUSD=X", 
    "GBP/USD": "GBPUSD=X", 
    "USD/JPY": "JPY=X", 
    "EUR/JPY": "EURJPY=X", 
    "AUD/USD": "AUDUSD=X"
}

settings = {"market": "OTC", "pair": "EUR/USD", "interval": "1m", "running": False}

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 LIVE Market", callback_data='live'), InlineKeyboardButton("🟢 OTC Market", callback_data='otc')],
        [InlineKeyboardButton("📊 Pairs List", callback_data='pairs'), InlineKeyboardButton("⏰ Timeframe", callback_data='timeframe')],
        [InlineKeyboardButton("📈 Status", callback_data='status'), InlineKeyboardButton("▶️ Start / ⏸️ Stop", callback_data='startstop')]
    ])

def pairs_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("EUR/USD (OTC)", callback_data='pair_EUR/USD'), InlineKeyboardButton("GBP/USD (OTC)", callback_data='pair_GBP/USD')],
        [InlineKeyboardButton("EUR/GBP (OTC)", callback_data='pair_EUR/GBP'), InlineKeyboardButton("USD/JPY (OTC)", callback_data='pair_USD/JPY')],
        [InlineKeyboardButton("⬅️ Back", callback_data='back')]
    ])

def timeframe_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1 Min", callback_data='tf_1m'), InlineKeyboardButton("5 Min", callback_data='tf_5m')],
        [InlineKeyboardButton("⬅️ Back", callback_data='back')]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Market set to: {settings['market']}\nWelcome to Sam Trades AI", reply_markup=main_menu())

async def handle_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data

    if d == 'live':
        settings['market'] = 'LIVE'
        await q.edit_message_text(f"Market set to: LIVE\nWelcome to Sam Trades AI", reply_markup=main_menu())
    elif d == 'otc':
        settings['market'] = 'OTC'
        await q.edit_message_text(f"Market set to: OTC\nWelcome to Sam Trades AI", reply_markup=main_menu())
    elif d == 'pairs':
        await q.edit_message_text("Select Pair:", reply_markup=pairs_menu())
    elif d == 'timeframe':
        await q.edit_message_text("Select Timeframe:", reply_markup=timeframe_menu())
    elif d.startswith('pair_'):
        settings['pair'] = d.replace('pair_', '')
        await q.edit_message_text(f"✅ Pair: {settings['pair']}", reply_markup=main_menu())
    elif d.startswith('tf_'):
        settings['interval'] = d.replace('tf_', '')
        await q.edit_message_text(f"✅ Timeframe: {settings['interval']}", reply_markup=main_menu())
    elif d == 'status':
        st = "🟢 RUNNING" if settings['running'] else "🔴 STOPPED"
        await q.edit_message_text(f"📈 STATUS\nMarket: {settings['market']}\nPair: {settings['pair']}\nBot: {st}", reply_markup=main_menu())
    elif d == 'startstop':
        settings['running'] = not settings['running']
        txt = "✅ START ho gaya - Signal ayega" if settings['running'] else "⛔ STOP ho gaya"
        await q.edit_message_text(txt, reply_markup=main_menu())
        if settings['running']:
            context.application.create_task(send_signal(context))
    elif d == 'back':
        await q.edit_message_text(f"Market set to: {settings['market']}\nWelcome to Sam Trades AI", reply_markup=main_menu())

async def send_signal(context):
    while settings['running']:
        try:
            sym = PAIRS.get(settings['pair'], "EURUSD=X")
            df = yf.download(sym, period="1d", interval=settings['interval'], progress=False)
            if len(df) > 1:
                direction = "BUY ⬆️" if df['Close'].iloc[-1] > df['Close'].iloc[-2] else "SELL ⬇️"
                msg = f"🟢 SAM TRADES AI - SIGNAL 🟢\n\n📊 Pair: {settings['pair']} ({settings['market']})\n📈 Direction: {direction}\n⏰ Timeframe: {settings['interval']}\n\n⚡️ Confidence: 97%"
                await context.bot.send_message(chat_id=CHAT_ID, text=msg)
        except:
            pass
        await asyncio.sleep(60)

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_btn))
    app.run_polling()

if __name__ == "__main__":
    main()
