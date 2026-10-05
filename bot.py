import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import time, threading, os, datetime, pytz
import pandas as pd
import ta
from collections import defaultdict

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_RAW = os.getenv("OWNER_ID") or os.getenv("CHAT_ID") or ""
OWNER_IDS = [int(x) for x in OWNER_RAW.replace(" ", "").split(",") if x.lstrip('-').isdigit()]

if not BOT_TOKEN:
    print("CRITICAL: BOT_TOKEN missing!")
    time.sleep(3)
    exit(0)

IST = pytz.timezone('Asia/Kolkata')
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

ALL_PAIRS = ["EUR/USD","GBP/USD","USD/JPY","USD/CHF","AUD/USD","USD/CAD","NZD/USD","EUR/GBP","EUR/JPY","GBP/JPY","EUR/AUD","CAD/JPY","CHF/JPY","AUD/JPY","AUD/CAD","AUD/CHF","AUD/NZD","CAD/CHF","EUR/CAD","EUR/CHF","EUR/NZD","GBP/AUD","GBP/CAD","GBP/CHF","GBP/NZD","USD/INR","USD/TRY","USD/BRL","EUR/USD (OTC)","GBP/USD (OTC)","USD/JPY (OTC)","USD/CAD (OTC)","AUD/USD (OTC)","EUR/GBP (OTC)","USD/INR (OTC)"]
selected_pairs = ALL_PAIRS.copy()
bot_active=False
SCORE_THRESHOLD=65
LAST_SIGNAL={}
PENDING_TRADES={}
LOSS_COUNT=defaultdict(int)
DISABLED_TODAY=set()
CURRENT_DAY=datetime.datetime.now(IST).date()

def reset_daily_if_needed():
    global CURRENT_DAY, LOSS_COUNT, DISABLED_TODAY
    today=datetime.datetime.now(IST).date()
    if today!=CURRENT_DAY:
        LOSS_COUNT=defaultdict(int)
        DISABLED_TODAY=set()
        CURRENT_DAY=today

def get_main_keyboard():
    markup=InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton("▶️ Start Bot",callback_data="start_bot"),InlineKeyboardButton("⏹️ Stop Bot",callback_data="stop_bot"))
    markup.add(InlineKeyboardButton(f"Select Market ({len(selected_pairs)}/{len(ALL_PAIRS)})",callback_data="select_market"),InlineKeyboardButton("Timeframe: 1m",callback_data="timeframe"))
    markup.add(InlineKeyboardButton(f"Score Filter: {SCORE_THRESHOLD}%",callback_data="score_menu"),InlineKeyboardButton(f"Status [YFINANCE ✅]",callback_data="status"))
    markup.add(InlineKeyboardButton("🟢 Mode: YFINANCE ACTIVE ✅",callback_data="mode_yfinance"))
    return markup

def get_score_keyboard():
    markup=InlineKeyboardMarkup(row_width=3)
    markup.add(InlineKeyboardButton("20% (TEST)",callback_data="score_20"),InlineKeyboardButton("40% (All)",callback_data="score_40"),InlineKeyboardButton("50%",callback_data="score_50"))
    markup.add(InlineKeyboardButton("60%",callback_data="score_60"),InlineKeyboardButton("65% (REAL Best)",callback_data="score_65"),InlineKeyboardButton("70% (OTC Best)",callback_data="score_70"))
    markup.add(InlineKeyboardButton("80%",callback_data="score_80"))
    markup.add(InlineKeyboardButton("Back",callback_data="back_main"))
    return markup

def get_market_keyboard():
    markup=InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton("✅ Select All 35",callback_data="select_all"),InlineKeyboardButton("❌ Clear All",callback_data="clear_all"))
    for pair in ALL_PAIRS:
        if pair in DISABLED_TODAY:
            markup.add(InlineKeyboardButton(f"🚫 {pair} (2 Loss)",callback_data=f"pair_{pair}"))
        else:
            check="✅ " if pair in selected_pairs else "⬜ "
            markup.add(InlineKeyboardButton(f"{check}{pair}",callback_data=f"pair_{pair}"))
    markup.add(InlineKeyboardButton("⬅️ Back",callback_data="back_main"))
    markup.add(InlineKeyboardButton("♻️ Reset Disabled",callback_data="reset_disabled"))
    return markup

def get_timeframe_keyboard():
    markup=InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton("1m",callback_data="tf_1m"),InlineKeyboardButton("5m",callback_data="tf_5m"))
    markup.add(InlineKeyboardButton("Back",callback_data="back_main"))
    return markup

def calculate_score_6factor(df):
    try:
        close=df['Close'].iloc[-1]; open_p=df['Open'].iloc[-1]; high=df['High'].iloc[-1]; low=df['Low'].iloc[-1]
        prev_close=df['Close'].iloc[-2]; prev_open=df['Open'].iloc[-2]
        bb=ta.volatility.BollingerBands(df['Close'],window=20,window_dev=2)
        bb_upper=bb.bollinger_hband().iloc[-1]; bb_lower=bb.bollinger_lband().iloc[-1]
        rsi_val=ta.momentum.RSIIndicator(df['Close'],window=14).rsi().iloc[-1]
        stoch=ta.momentum.StochasticOscillator(df['High'],df['Low'],df['Close'],window=14,smooth_window=3)
        k=stoch.stoch().iloc[-1]; d=stoch.stoch_signal().iloc[-1]; k_prev=stoch.stoch().iloc[-2]; d_prev=stoch.stoch_signal().iloc[-2]
        cci=ta.trend.CCIIndicator(df['High'],df['Low'],df['Close'],window=20).cci().iloc[-1]
        ema200=ta.trend.EMAIndicator(df['Close'],window=200).ema_indicator().iloc[-1]
        avg_range=(df['High']-df['Low']).rolling(20).mean().iloc[-1]; curr_range=high-low
        vol_strong=curr_range>avg_range*1.1
        if not vol_strong: return 0,0,None,["Weak Volume - No Trade"]
        candle_range=high-low; body=abs(close-open_p)
        body_pct=(body/candle_range*100) if candle_range>0 else 0
        bullish_candle=close>open_p; bearish_candle=close<open_p
        is_hammer=(body_pct<40) and ((min(open_p,close)-low)>body*2) if body>0 else False
        is_engulfing_bull=(prev_close<prev_open) and bullish_candle and (close>prev_open) and (open_p<prev_close)
        is_engulfing_bear=(prev_close>prev_open) and bearish_candle and (close<prev_open) and (open_p>prev_close)
        best_score=0; best_type=None; best_reason=[]
        if low<=bb_lower:
            if close>=ema200*0.999 and bullish_candle:
                score=30; reason=["BB Lower Touch +30"]
                if rsi_val<35: score+=20; reason.append(f"RSI Oversold {rsi_val:.1f} +20")
                if k_prev<d_prev and k>d and k<20 and d<20: score+=20; reason.append("Stoch Cross UP <20 +20")
                if cci<-100: score+=10; reason.append(f"CCI {cci:.0f} +10")
                if is_hammer or is_engulfing_bull or body_pct>50: score+=10; reason.append("Candle Strong +10")
                if vol_strong and body_pct>50: score+=10; reason.append("Volume Strong +10")
                best_score=score; best_type="BUY"; best_reason=reason
        if high>=bb_upper:
            if close<=ema200*1.001 and bearish_candle:
                score=30; reason=["BB Upper Touch +30"]
                if rsi_val>65: score+=20; reason.append(f"RSI Overbought {rsi_val:.1f} +20")
                if k_prev>d_prev and k<d and k>80 and d>80: score+=20; reason.append("Stoch Cross DOWN >80 +20")
                if cci>100: score+=10; reason.append(f"CCI {cci:.0f} +10")
                if is_engulfing_bear or body_pct>50: score+=10; reason.append("Candle Bearish +10")
                if vol_strong and body_pct>50: score+=10; reason.append("Volume Strong +10")
                if score>best_score: best_score=score; best_type="SELL"; best_reason=reason
        if best_type is None: return 0,0,None,[]
        return best_score,min(95,best_score),best_type,best_reason
    except: return 0,0,None,[]

def get_data_yf(symbol="EURUSD=X"):
    try:
        import yfinance as yf
        df=yf.download(symbol,period="1d",interval="1m",progress=False,auto_adjust=True)
        if df.empty: return None
        if isinstance(df.columns,pd.MultiIndex): df.columns=df.columns.get_level_values(0)
        if df.index.tz is None: df.index=df.index.tz_localize('UTC').tz_convert(IST)
        else: df.index=df.index.tz_convert(IST)
        return df
    except: return None

def check_win_loss(chat_id,pair,signal_type,entry_price,entry_time_ist):
    time.sleep(75)
    try:
        if pair not in PENDING_TRADES: return
        close_price=entry_price
        clean_pair=pair.replace(" (OTC)","").replace("/","")
        df=get_data_yf(f"{clean_pair}=X")
        if df is not None and len(df)>0: close_price=df['Close'].iloc[-1]
        win=(signal_type=="BUY" and close_price>entry_price) or (signal_type=="SELL" and close_price<entry_price)
        now_ist=datetime.datetime.now(IST).strftime('%I:%M:%S %p IST')
        reset_daily_if_needed()
        if win: result_msg=f"✅ WIN - {pair}\nSignal: {signal_type}\nEntry: {entry_price:.5f}\nClose: {close_price:.5f}\n{now_ist}"
        else:
            LOSS_COUNT[pair]+=1
            if LOSS_COUNT[pair]>=2:
                DISABLED_TODAY.add(pair)
                if pair in selected_pairs: selected_pairs.remove(pair)
                result_msg=f"❌ LOSS - {pair} [{LOSS_COUNT[pair]}/2]\nSignal: {signal_type}\nEntry: {entry_price:.5f}\nClose: {close_price:.5f}\n⚠️ {pair} Disabled for Today (2 Loss) 🚫\n{now_ist}"
            else: result_msg=f"❌ LOSS - {pair} [{LOSS_COUNT[pair]}/2]\nSignal: {signal_type}\nEntry: {entry_price:.5f}\nClose: {close_price:.5f}\n{now_ist}"
        bot.send_message(chat_id,result_msg)
        if pair in PENDING_TRADES: del PENDING_TRADES[pair]
    except:
        if pair in PENDING_TRADES: del PENDING_TRADES[pair]

def scanner_loop(chat_id):
    global bot_active
    last_min=-1
    while bot_active:
        try:
            reset_daily_if_needed()
            now_ist=datetime.datetime.now(IST)
            if now_ist.second<25 or now_ist.second>35:
                time.sleep(1)
                continue
            next_entry_time=(now_ist+datetime.timedelta(minutes=1)).replace(second=0,microsecond=0)
            if next_entry_time.minute==last_min:
                time.sleep(1)
                continue
            last_min=next_entry_time.minute
            for pair in selected_pairs[:]:
                if not bot_active: break
                if pair in DISABLED_TODAY: continue
                if pair in LAST_SIGNAL and (now_ist-LAST_SIGNAL[pair]).total_seconds()<70: continue
                if pair in PENDING_TRADES: continue
                clean_pair=pair.replace(" (OTC)","").replace("/","")
                df=get_data_yf(f"{clean_pair}=X")
                if df is None or len(df)<50: continue
                score,conf,sig_type,reasons=calculate_score_6factor(df)
                if sig_type and score>=SCORE_THRESHOLD:
                    LAST_SIGNAL[pair]=now_ist
                    entry_price=df['Close'].iloc[-1]
                    entry_time_str=next_entry_time.strftime('%I:%M:%S %p IST')
                    PENDING_TRADES[pair]={"entry_price":entry_price,"type":sig_type,"time":now_ist}
                    loss_info=f"Loss:{LOSS_COUNT[pair]}/2" if LOSS_COUNT[pair]>0 else "Loss:0/2"
                    msg=f"{pair} {sig_type} SIGNAL [YFINANCE]\nScore: {score}/100 | Conf: {conf}% | {loss_info}\nEntry: Next 1m OPEN - {entry_time_str}\n"+"\n".join(reasons)+f"\n{now_ist.strftime('%I:%M:%S %p IST')} | Filter {SCORE_THRESHOLD}%"
                    bot.send_message(chat_id,msg)
                    threading.Thread(target=check_win_loss,args=(chat_id,pair,sig_type,entry_price,entry_time_str),daemon=True).start()
            time.sleep(1)
        except Exception as e:
            print(f"Loop error {e}")
            time.sleep(1)

@bot.message_handler(commands=['start'])
def start_handler(message):
    if message.chat.id not in OWNER_IDS: bot.send_message(message.chat.id,"Bot Locked."); return
    disabled=", ".join(DISABLED_TODAY) if DISABLED_TODAY else "None"
    bot.send_message(message.chat.id,f"Mode: YFINANCE REAL ✅\nStatus: {'ACTIVE' if bot_active else 'STOPPED'}\nPairs: {len(selected_pairs)}/{len(ALL_PAIRS)}\nFilter: {SCORE_THRESHOLD}%\nDisabled Today (2 Loss): {disabled}",reply_markup=get_main_keyboard())

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    global bot_active,selected_pairs,SCORE_THRESHOLD
    if call.message.chat.id not in OWNER_IDS: return
    chat_id=call.message.chat.id; data=call.data
    if data=="start_bot":
        if not bot_active:
            bot_active=True
            bot.send_message(chat_id,f"🚀 Started | Filter {SCORE_THRESHOLD}% | Mode: YFINANCE | Pairs: {len(selected_pairs)}",reply_markup=get_main_keyboard())
            threading.Thread(target=scanner_loop,args=(chat_id,),daemon=True).start()
    elif data=="stop_bot": bot_active=False; bot.send_message(chat_id,"⏹️ Stopped",reply_markup=get_main_keyboard())
    elif data=="select_market": bot.edit_message_text(f"Select Market ({len(ALL_PAIRS)} Pairs):",chat_id,call.message.message_id,reply_markup=get_market_keyboard())
    elif data=="select_all":
        selected_pairs=[p for p in ALL_PAIRS if p not in DISABLED_TODAY]
        bot.edit_message_text(f"Selected All: {len(selected_pairs)} pairs",chat_id,call.message.message_id,reply_markup=get_market_keyboard())
    elif data=="clear_all": selected_pairs=[]; bot.edit_message_text(f"Cleared",chat_id,call.message.message_id,reply_markup=get_market_keyboard())
    elif data=="reset_disabled":
        DISABLED_TODAY.clear(); LOSS_COUNT.clear()
        bot.send_message(chat_id,"♻️ All disabled pairs reset!",reply_markup=get_main_keyboard())
    elif data.startswith("pair_"):
        pair_name=data.replace("pair_","")
        if pair_name in DISABLED_TODAY:
            DISABLED_TODAY.remove(pair_name); LOSS_COUNT[pair_name]=0
            if pair_name not in selected_pairs: selected_pairs.append(pair_name)
        else:
            s=set(selected_pairs)
            if pair_name in s: s.remove(pair_name)
            else: s.add(pair_name)
            selected_pairs=list(s)
        bot.edit_message_text(f"Selected: {len(selected_pairs)} pairs",chat_id,call.message.message_id,reply_markup=get_market_keyboard())
    elif data=="timeframe": bot.edit_message_text("Select Timeframe:",chat_id,call.message.message_id,reply_markup=get_timeframe_keyboard())
    elif data.startswith("tf_"): bot.send_message(chat_id,f"TF set",reply_markup=get_main_keyboard())
    elif data=="score_menu": bot.edit_message_text(f"Current: {SCORE_THRESHOLD}%",chat_id,call.message.message_id,reply_markup=get_score_keyboard())
    elif data.startswith("score_"):
        SCORE_THRESHOLD=int(data.split("_")[1]); bot.send_message(chat_id,f"Filter: {SCORE_THRESHOLD}% set.",reply_markup=get_main_keyboard())
    elif data=="status":
        pending=", ".join(PENDING_TRADES.keys()) if PENDING_TRADES else "None"
        disabled=", ".join(DISABLED_TODAY) if DISABLED_TODAY else "None"
        loss_detail="\n".join([f"{k}:{v}/2" for k,v in LOSS_COUNT.items() if v>0]) or "No losses today"
        bot.send_message(chat_id,f"Mode: YFINANCE\nStatus: {'ACTIVE' if bot_active else 'STOPPED'}\nPairs: {len(selected_pairs)}\nFilter: {SCORE_THRESHOLD}%\nPending: {pending}\nLoss Count:\n{loss_detail}\nDisabled Today: {disabled}",reply_markup=get_main_keyboard())
    elif data=="back_main": bot.edit_message_text(f"Status: {'ACTIVE' if bot_active else 'STOPPED'}\nPairs: {len(selected_pairs)}/{len(ALL_PAIRS)}\nFilter: {SCORE_THRESHOLD}%",chat_id,call.message.message_id,reply_markup=get_main_keyboard())
    elif data=="mode_yfinance": bot.send_message(chat_id,"✅ YFINANCE mode ACTIVE hai",reply_markup=get_main_keyboard())

print("Bot running YFINANCE ONLY - CLEAN V4")
try:
    bot.remove_webhook()
    time.sleep(1)
    bot.delete_webhook(drop_pending_updates=True)
    time.sleep(2)
except Exception as e:
    print(f"Webhook clear: {e}")
    time.sleep(2)

while True:
    try:
        print("Starting polling...")
        bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
    except Exception as e:
        err=str(e)
        print(f"Polling error {err}")
        if "409" in err or "Conflict" in err:
            print("409 Conflict - waiting 15s...")
            try: bot.delete_webhook(drop_pending_updates=True)
            except: pass
            time.sleep(15)
        else: time.sleep(5)
