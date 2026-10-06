"""
SAM.AI FINAL - TICK SELECT SYSTEM - PIC JAISA
Features: 60+ Pairs | Tick = Analysis ON | Unticked = BAND | <50% OFF | 50% TEST | 60%+ REAL
"""
import time, json, os, threading, requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz

IST = pytz.timezone('Asia/Kolkata')
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = str(os.getenv("OWNER_ID", "")).strip()

if not BOT_TOKEN:
    print("BOT_TOKEN missing in ENV")

CONFIG = {
    "max_trades_per_day": 10,
    "cooldown_candles": 2,
    "ema": 200, "bb_period": 20, "bb_dev": 2.5, "rsi_period": 5,
    "rsi_ob": 75, "rsi_os": 25, "atr_period": 14, "atr_mult": 1.3,
    "vol_ma": 20, "vol_mult": 1.5, "vol_filter_mult": 1.2,
    "zigzag_depth": 12, "zigzag_backstep": 3,
    "demarker_period": 14, "demarker_ob": 0.70, "demarker_os": 0.30,
    "doji_atr_mult": 0.3, "swing_atr_mult": 0.5,
}

ALL_PAIRS = [
    "AUDCAD-OTC", "AUDCHF-OTC", "AUDJPY-OTC", "AUDNZD-OTC", "AUDUSD-OTC",
    "CADCHF-OTC", "CADJPY-OTC", "CHFJPY-OTC",
    "EURAUD-OTC", "EURCAD-OTC", "EURCHF-OTC", "EURGBP-OTC", "EURJPY-OTC",
    "EURNZD-OTC", "EURSGD-OTC", "EURUSD-OTC",
    "GBPAUD-OTC", "GBPCAD-OTC", "GBPCHF-OTC", "GBPJPY-OTC", "GBPNZD-OTC", "GBPUSD-OTC",
    "NZDCAD-OTC", "NZDCHF-OTC", "NZDJPY-OTC", "NZDUSD-OTC",
    "USDCAD-OTC", "USDCHF-OTC", "USDJPY-OTC",
    "USDBRL-OTC", "USDINR-OTC", "USDBDT-OTC", "USDCOP-OTC", "USDDZD-OTC",
    "USDEGP-OTC", "USDIDR-OTC", "USDNGN-OTC", "USDPHP-OTC", "USDPKR-OTC",
    "USDZAR-OTC", "USDARS-OTC", "USDTRY-OTC", "USDMXN-OTC", "BRLUSD-OTC",
    "BTC-OTC", "ETH-OTC", "LTC-OTC", "XRP-OTC", "SOL-OTC", "BNB-OTC", "TON-OTC",
    "DOT-OTC", "AVAX-OTC", "MATIC-OTC",
    "GOLD-OTC", "SILVER-OTC", "UKBrent-OTC", "USCrude-OTC"
]

# SET hai - tick system ke liye
SELECTED_PAIRS = set(["EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC"])
TF = 1
BOT_RUNNING = False
daily_trades = []
pair_cooldown = {}

def now_ist(): return datetime.now(IST)

def send_to_owner(text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": OWNER_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def send_reply(chat_id, text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": str(chat_id), "text": text, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def send_with_buttons(chat_id, text, keyboard):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": str(chat_id), "text": text, "parse_mode": "Markdown", "reply_markup": json.dumps(keyboard)}, timeout=15)
    except Exception as e:
        print(f"Send Btn Err {e}")

def get_market_keyboard():
    keyboard = []
    for pair in ALL_PAIRS:
        disp = pair.replace("-OTC"," (OTC)").replace("/","")
        # Display ko pic jaisa: EUR/USD (OTC)
        if "EURUSD" in pair: disp = "EUR/USD (OTC)"
        elif "GBPUSD" in pair: disp = "GBP/USD (OTC)"
        elif "USDJPY" in pair: disp = "USD/JPY (OTC)"
        elif "AUDUSD" in pair: disp = "AUD/USD (OTC)"
        elif "EURGBP" in pair: disp = "EUR/GBP (OTC)"
        elif "USDCHF" in pair: disp = "USD/CHF (OTC)"
        elif "EURJPY" in pair: disp = "EUR/JPY (OTC)"
        elif "GBPJPY" in pair: disp = "GBP/JPY (OTC)"
        else: disp = pair.replace("-OTC"," (OTC)")

        if pair in SELECTED_PAIRS:
            btn_text = f"✅ {disp}"
        else:
            btn_text = f"{disp}"
        keyboard.append([{"text": btn_text, "callback_data": f"toggle_{pair}"}])

    keyboard.append([{"text": "✅ Select All", "callback_data": "pairs_all"}, {"text": "❌ Deselect All", "callback_data": "pairs_none"}])
    keyboard.append([{"text": "⬅️ Back", "callback_data": "back_panel"}])
    return {"inline_keyboard": keyboard}

def get_control_keyboard():
    return {"inline_keyboard": [
        [{"text": "🟢 Start Bot", "callback_data": "startbot"}, {"text": "🔴 Stop Bot", "callback_data": "stopbot"}],
        [{"text": "📈 Select Market", "callback_data": "show_market"}, {"text": "⏱ Timeframe", "callback_data": "show_tf"}],
        [{"text": "🎯 Score Filter", "callback_data": "show_filter"}, {"text": "📊 Status", "callback_data": "status"}]
    ]}

def get_tf_keyboard():
    return {"inline_keyboard": [
        [{"text": "1m", "callback_data": "tf_1"}, {"text": "2m", "callback_data": "tf_2"}, {"text": "5m", "callback_data": "tf_5"}],
        [{"text": "⬅️ Back", "callback_data": "back_panel"}]
    ]}

def get_panel():
    s = "🟢 RUNNING" if BOT_RUNNING else "🔴 STOPPED"
    return f"""🤖 *SAM.AI FINAL* {s}

Selected: {len(SELECTED_PAIRS)} pairs
TF: {TF}m | Filter: 50%+ Only | <50% OFF

1 tick = 1 pair analysis
10 tick = 10 pairs analysis
All tick = All analysis
Unticked = BAND 🔴

Click Select Market for tick system like pic
"""

def telegram_poller():
    global SELECTED_PAIRS, TF, BOT_RUNNING
    print(f"Poller START - {len(ALL_PAIRS)} pairs | Selected {len(SELECTED_PAIRS)}")
    try: requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=True", timeout=5)
    except: pass
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset}&timeout=30"
            r = requests.get(url, timeout=35).json()
            if not r.get("ok"): time.sleep(2); continue
            for upd in r.get("result", []):
                offset = upd["update_id"] + 1

                # BUTTON CALLBACKS
                if "callback_query" in upd:
                    cq = upd["callback_query"]
                    chat_id = str(cq["message"]["chat"]["id"])
                    data = cq["data"]
                    msg_id = cq["message"]["message_id"]
                    print(f"BTN {chat_id}: {data}")

                    try:
                        # Answer callback to remove loading
                        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery", data={"callback_query_id": cq["id"]}, timeout=5)
                    except: pass

                    if data.startswith("toggle_"):
                        pair = data.replace("toggle_", "")
                        if pair in SELECTED_PAIRS:
                            SELECTED_PAIRS.remove(pair)
                        else:
                            SELECTED_PAIRS.add(pair)
                        # Edit keyboard with new ticks
                        try:
                            edit_url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
                            txt = f"Select Market: ({len(SELECTED_PAIRS)} selected)\n1 tick = 1 analysis, {len(SELECTED_PAIRS)} tick = {len(SELECTED_PAIRS)} analysis\nAb sirf tick wale ka hi analysis hoga"
                            requests.post(edit_url, data={"chat_id": chat_id, "message_id": msg_id, "text": txt, "reply_markup": json.dumps(get_market_keyboard())}, timeout=10)
                        except Exception as e:
                            print(f"Edit err {e}")

                    elif data == "pairs_all":
                        SELECTED_PAIRS = set(ALL_PAIRS)
                        try:
                            edit_url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
                            requests.post(edit_url, data={"chat_id": chat_id, "message_id": msg_id, "text": f"Select Market: ({len(SELECTED_PAIRS)} selected) - All ticked - Sabka analysis hoga", "reply_markup": json.dumps(get_market_keyboard())}, timeout=10)
                        except: send_with_buttons(chat_id, f"All {len(SELECTED_PAIRS)} selected", get_market_keyboard())

                    elif data == "pairs_none":
                        SELECTED_PAIRS = set()
                        try:
                            edit_url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
                            requests.post(edit_url, data={"chat_id": chat_id, "message_id": msg_id, "text": "Select Market: (0 selected) - Sab BAND", "reply_markup": json.dumps(get_market_keyboard())}, timeout=10)
                        except: send_with_buttons(chat_id, "Sab deselect - BAND", get_market_keyboard())

                    elif data == "show_market":
                        send_with_buttons(chat_id, f"Select Market: ({len(SELECTED_PAIRS)} selected)\nPic jaisa tick system - 1 tick = 1 analysis", get_market_keyboard())
                    elif data == "show_tf":
                        send_with_buttons(chat_id, f"⏱ Current TF: {TF}m", get_tf_keyboard())
                    elif data.startswith("tf_"):
                        TF = int(data.split("_")[1])
                        send_reply(chat_id, f"✅ TF set to {TF}m")
                    elif data == "show_filter":
                        send_reply(chat_id, "🎯 Score Filter:\n<50% = OFF (Telegram pe nahi ayega)\n50% = 🧪 TEST (Count nahi)\n60%+ = 🚀 REAL (Count hoga)")
                    elif data == "startbot":
                        BOT_RUNNING = True
                        send_reply(chat_id, f"🟢 Bot Started\nAb sirf {len(SELECTED_PAIRS)} ticked pairs ka analysis hoga\nTF:{TF}m | Pairs:{len(SELECTED_PAIRS)}")
                    elif data == "stopbot":
                        BOT_RUNNING = False
                        send_reply(chat_id, "🔴 Bot Stopped")
                    elif data == "status":
                        today = now_ist().date()
                        todays = [t for t in daily_trades if t['date']==today]
                        send_reply(chat_id, f"📊 *Status* {'🟢' if BOT_RUNNING else '🔴'}\nSelected: {len(SELECTED_PAIRS)} / {len(ALL_PAIRS)}\n{', '.join(list(SELECTED_PAIRS)[:5])}\nTF:{TF}m REAL:{len(todays)}/{CONFIG['max_trades_per_day']}\nFilter: 50%+ | <50% OFF")
                    elif data == "back_panel":
                        send_with_buttons(chat_id, get_panel(), get_control_keyboard())
                    continue

                # TEXT COMMANDS
                msg = upd.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "").strip()
                if not chat_id: continue

                if text == "/start":
                    send_with_buttons(chat_id, get_panel(), get_control_keyboard())
                elif text == "/id":
                    if chat_id!= OWNER_ID:
                        send_reply(chat_id, "❌ Owner only command")
                    else:
                        send_reply(chat_id, f"ID:`{chat_id}` TF:{TF}m Sel:{len(SELECTED_PAIRS)} Run:{BOT_RUNNING}")
                elif text == "/status":
                    today = now_ist().date()
                    todays = [t for t in daily_trades if t['date']==today]
                    send_reply(chat_id, f"Status {'🟢' if BOT_RUNNING else '🔴'}\nSelected {len(SELECTED_PAIRS)}/{len(ALL_PAIRS)}\nTF:{TF}m")
                else:
                    # Fallback panel
                    if text.startswith("/"):
                        send_with_buttons(chat_id, get_panel(), get_control_keyboard())
        except Exception as e:
            print(f"Poller Err {e}")
            time.sleep(2)
        time.sleep(1)

# INDICATORS
def ema(s, p): return s.ewm(span=p, adjust=False).mean()
def rsi(s, p=5):
    d = s.diff(); g = (d.where(d>0,0)).ewm(alpha=1/p).mean(); l = (-d.where(d<0,0)).ewm(alpha=1/p).mean(); rs=g/l; return 100-(100/(1+rs))
def bollinger(s, p=20, dev=2.5): ma=s.rolling(p).mean(); std=s.rolling(p).std(); return ma, ma+dev*std, ma-dev*std
def atr(df, p=14): hl=df['high']-df['low']; hc=(df['high']-df['close'].shift()).abs(); lc=(df['low']-df['close'].shift()).abs(); tr=pd.concat([hl,hc,lc], axis=1).max(axis=1); return tr.rolling(p).mean()
def demarker(df, p=14):
    demax=(df['high']-df['high'].shift(1)).clip(lower=0); demin=(df['low'].shift(1)-df['low']).clip(lower=0)
    demax=np.where(demax>demin, demax, 0); demin=np.where(demin>demax, demin, 0)
    return pd.Series(demax).rolling(p).mean() / (pd.Series(demax).rolling(p).mean() + pd.Series(demin).rolling(p).mean())
def zigzag_pivots(df, depth=12, backstep=3):
    highs=df['high'].rolling(depth).max(); lows=df['low'].rolling(depth).min(); pivots=[]
    for i in range(len(df)):
        if df['high'].iloc[i]==highs.iloc[i]: pivots.append((i,'H',df['high'].iloc[i]))
        if df['low'].iloc[i]==lows.iloc[i]: pivots.append((i,'L',df['low'].iloc[i]))
    return sorted(pivots)[-10:]

def analyze(df, pair):
    if len(df)<200: return {"signal":"HOLD","score":0,"win_chance":0,"signal_type":"HOLD","trend":"-","curr":df.iloc[-1],"confidence":"Low"}
    close=df['close']
    df['EMA200']=ema(close,CONFIG['ema']); df['BB_MA'],df['BB_UP'],df['BB_LOW']=bollinger(close,CONFIG['bb_period'],CONFIG['bb_dev']); df['RSI']=rsi(close,CONFIG['rsi_period']); df['ATR']=atr(df,CONFIG['atr_period']); df['VOL_MA']=df['volume'].rolling(CONFIG['vol_ma']).mean(); df['DeM']=demarker(df,CONFIG['demarker_period'])
    curr=df.iloc[-1]; trend="UP" if curr['close']>curr['EMA200'] else "DOWN"
    score=0; pivots=zigzag_pivots(df)
    t1=False
    if len(pivots)>=3:
        last_lows=[p for p in pivots if p[1]=='L'][-2:]; last_highs=[p for p in pivots if p[1]=='H'][-2:]
        if trend=="UP" and len(last_lows)==2 and last_lows[-1][2]>last_lows[-2][2]: t1=True
        if trend=="DOWN" and len(last_highs)==2 and last_highs[-1][2]<last_highs[-2][2]: t1=True
        if pivots[-1][0]>=len(df)-3: t1=True
    if t1: score+=20
    dem=curr['DeM']; rsi_v=curr['RSI']; t2_buy=dem<CONFIG['demarker_os'] and rsi_v<CONFIG['rsi_os']; t2_sell=dem>CONFIG['demarker_ob'] and rsi_v>CONFIG['rsi_ob']; t2=t2_buy or t2_sell
    if t2: score+=20
    atr_avg=df['ATR'].rolling(20).mean().iloc[-1]; t3=curr['ATR']>atr_avg*CONFIG['atr_mult'] if not pd.isna(atr_avg) else False
    if t3: score+=20
    t4=curr['volume']>curr['VOL_MA']*CONFIG['vol_mult'] if not pd.isna(curr['VOL_MA']) else False
    if t4: score+=20
    body=abs(curr['close']-curr['open']); up_w=curr['high']-max(curr['open'],curr['close']); lo_w=min(curr['open'],curr['close'])-curr['low']; t5=body>(up_w+lo_w)*0.6
    if trend=="UP" and curr['close']<curr['BB_LOW']*1.001: t5=True
    if trend=="DOWN" and curr['close']>curr['BB_UP']*0.999: t5=True
    if t5: score+=20
    swing_high=df['high'].rolling(20).max().iloc[-1]; swing_low=df['low'].rolling(20).min().iloc[-1]; atr_val=curr['ATR']
    f1=(abs(curr['close']-swing_high)<CONFIG['swing_atr_mult']*atr_val) or (abs(curr['close']-swing_low)<CONFIG['swing_atr_mult']*atr_val); f2=body<CONFIG['doji_atr_mult']*atr_val; f3=curr['volume']<curr['VOL_MA']*CONFIG['vol_filter_mult'] if not pd.isna(curr['VOL_MA']) else True
    block_count = (1 if f1 else 0) + (1 if f2 else 0) + (1 if f3 else 0)

    if score < 50:
        return {"signal":"HOLD","score":score,"win_chance":score,"signal_type":"HOLD","trend":trend,"curr":curr,"confidence":f"LOW {score}% OFF"}
    elif score == 60 and block_count == 1:
        return {"signal":"BUY" if (t2_buy or trend=="UP") else "SELL","score":score,"win_chance":50,"signal_type":"TEST","trend":trend,"curr":curr,"confidence":"TEST 50% MINIMUM (Not Counted)"}
    elif score == 60 and block_count == 0:
        return {"signal":"BUY" if (t2_buy or trend=="UP") else "SELL","score":score,"win_chance":60,"signal_type":"REAL","trend":trend,"curr":curr,"confidence":"GENUINE 60%"}
    elif score == 80 and block_count == 1:
        return {"signal":"BUY" if (t2_buy or trend=="UP") else "SELL","score":score,"win_chance":70,"signal_type":"REAL","trend":trend,"curr":curr,"confidence":"GOOD 70%"}
    elif score == 80 and block_count == 0:
        return {"signal":"BUY" if (t2_buy or trend=="UP") else "SELL","score":score,"win_chance":80,"signal_type":"REAL","trend":trend,"curr":curr,"confidence":"HIGH 80%"}
    elif score == 100 and block_count == 1:
        return {"signal":"BUY" if (t2_buy or trend=="UP") else "SELL","score":score,"win_chance":90,"signal_type":"REAL","trend":trend,"curr":curr,"confidence":"VERY HIGH 90%"}
    elif score == 100 and block_count == 0:
        return {"signal":"BUY" if (t2_buy or trend=="UP") else "SELL","score":score,"win_chance":100,"signal_type":"REAL","trend":trend,"curr":curr,"confidence":"SURE SHOT 100%"}
    else:
        return {"signal":"HOLD","score":score,"win_chance":score,"signal_type":"HOLD","trend":trend,"curr":curr,"confidence":f"{score}% HOLD"}

def fetch_ohlcv_dukas(pair, tf_minutes, count=500):
    # TODO: Yahan apna real Dukascopy fetch lagana, abhi random hai testing ke liye
    np.random.seed(int(time.time()*1000) % 9999 + hash(pair) % 1000)
    base = 1.10 + np.random.rand()*0.5
    closes = [base]
    for _ in range(count-1): closes.append(closes[-1] + np.random.normal(0, 0.0003))
    df = pd.DataFrame({'open': closes,'high': [c + abs(np.random.normal(0,0.0002)) for c in closes],'low': [c - abs(np.random.normal(0,0.0002)) for c in closes],'close': closes,'volume': np.random.randint(800, 2500, count)})
    return df

def wait_for_early_signal(tf_minutes):
    while True:
        now=now_ist(); sec=now.second
        if 30<=sec<=35:
            m=now.minute
            if tf_minutes==1: return True
            if tf_minutes==2 and m%2==1: return True
            if tf_minutes==5 and m%5==4: return True
        time.sleep(0.5)

def check_result_and_send(pair, signal, entry_price, entry_time, score, win_chance, signal_type, tf_minutes):
    def task():
        time.sleep(tf_minutes*60 + 7)
        try:
            df=fetch_ohlcv_dukas(pair, tf_minutes, 10); exit_price=float(df['close'].iloc[-1])
            win=(signal=="BUY" and exit_price>entry_price) or (signal=="SELL" and exit_price<entry_price)
            emoji="✅ WIN" if win else "❌ LOSS"
            msg=f"{emoji} *{signal_type} {win and 'WIN' or 'LOSS'}*\nPair:{pair} {signal} {score}/100\nEntry:{entry_price:.5f} Exit:{exit_price:.5f}"
            send_to_owner(msg)
        except: pass
    threading.Thread(target=task, daemon=True).start()

def run_multi_bot():
    print(f"Bot FINAL TICK MODE | Total {len(ALL_PAIRS)} | Selected {len(SELECTED_PAIRS)} | MIN 50%")
    send_to_owner(f"✅ *Bot FINAL TICK MODE Live*\n{get_panel()}")
    while True:
        if not BOT_RUNNING: time.sleep(5); continue
        today=now_ist().date(); todays=[t for t in daily_trades if t['date']==today]
        if len(todays)>=CONFIG['max_trades_per_day']: time.sleep(3600); continue
        wait_for_early_signal(TF)
        if not BOT_RUNNING: continue

        pairs_to_scan = list(SELECTED_PAIRS) # SIRF TICK WALE
        if len(pairs_to_scan)==0:
            print("No pairs ticked - BAND")
            time.sleep(5)
            continue

        print(f"[{now_ist().strftime('%H:%M:%S')}] Scanning ONLY {len(pairs_to_scan)} ticked: {pairs_to_scan}")
        for pair in pairs_to_scan:
            if pair in pair_cooldown and time.time()-pair_cooldown[pair]<TF*60*CONFIG['cooldown_candles']: continue
            df=fetch_ohlcv_dukas(pair,TF,500); res=analyze(df,pair)
            print(f" {pair} {res['score']}/100 {res['signal_type']}")
            if res['signal'] not in ["BUY","SELL"]: continue
            if res['score'] < 50: continue # OFF
            entry_time=(now_ist()+timedelta(seconds=(60-now_ist().second))).replace(microsecond=0)
            entry_price=float(res['curr']['close'])
            if res['signal_type']=="TEST":
                send_to_owner(f"🧪 *TEST {res['signal']}*\nPair:{pair}\nTime:{entry_time.strftime('%H:%M:%S IST')}\nTF:{TF}m\nPrice:{entry_price:.5f}\nScore:{res['score']}/100 ({res['win_chance']}%)\n{res['confidence']}")
                pair_cooldown[pair]=time.time()
                check_result_and_send(pair, res['signal'], entry_price, entry_time, res['score'], res['win_chance'], "TEST", TF)
            else:
                send_to_owner(f"🚀 *REAL {res['signal']}*\nPair:{pair}\nTime:{entry_time.strftime('%H:%M:%S IST')}\nTF:{TF}m\nPrice:{entry_price:.5f}\nScore:{res['score']}/100 ({res[
