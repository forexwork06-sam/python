import os, logging
import pandas as pd
import yfinance as yf
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

OTC_PAIRS = [
    "EUR/USD (OTC)", "GBP/USD (OTC)", "USD/JPY (OTC)", "AUD/USD (OTC)",
    "USD/CAD (OTC)", "USD/CHF (OTC)", "NZD/USD (OTC)", "EUR/GBP (OTC)",
    "EUR/JPY (OTC)", "GBP/JPY (OTC)", "USD/INR (OTC)", "USD/BRL (OTC)",
    "USD/TRY (OTC)", "USD/PKR (OTC)", "AUD/CHF (OTC)", "AUD/JPY (OTC)",
    "EUR/NZD (OTC)", "GBP/NZD (OTC)"
]
LIVE_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD",
    "USD/CAD", "USD/CHF", "NZD/USD"
]
YF_MAP = {
    "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/JPY": "USDJPY=X",
    "AUD/USD": "AUDUSD=X", "USD/CAD": "USDCAD=X", "USD/CHF": "USDCHF=X",
    "NZD/USD": "NZDUSD=X", "EUR/GBP": "EURGBP=X", "EUR/JPY": "EURJPY=X",
    "GBP/JPY": "GBPJPY=X", "USD/INR": "USDINR=X", "USD/BRL": "USDBRL=X",
    "USD/TRY": "USDTRY=X", "USD/PKR": "USDPKR=X", "AUD/CHF": "AUDCHF=X",
    "AUD/JPY": "AUDJPY=X", "EUR/NZD": "EURNZD=X", "GBP/NZD": "GBPNZD=X"
}

selected_pairs = OTC_PAIRS
selected_timeframe = "1m"
bot_active = False
current_market = "OTC"
logging.basicConfig(level=logging.INFO)

def rsi(s, p=14):
    d=s.diff(); g=(d.where(d>0,0)).rolling(p).mean(); l=(-d.where(d<0,0)).rolling(p).mean(); rs=g/l; return 100-(100/(1+rs))
def bollinger(df, p=20, std=2):
    df['ma']=df['close'].rolling(p).mean(); df['sd']=df['close'].rolling(p).std(); df['upper']=df['ma']+(df['sd']*std); df['lower']=df['ma']-(df['sd']*std); return df
def stochastic(df, k=14, d=3):
    low_min=df['low'].rolling(k).min(); high_max=df['high'].rolling(k).max(); df['%K']=((df['close']-low_min)/(high_max-low_min))*100; df['%D']=df['%K'].rolling(d).mean(); return df
def cci(df, p=20):
    tp=(df['high']+df['low']+df['close'])/3; ma=tp.rolling(p).mean(); md=(tp-ma).abs().rolling(p).mean(); df['cci']=(tp-ma)/(0.015*md); return df
def ema(s,p): return s.ewm(span=p, adjust=False).mean()

def price_action_volume_check(df):
    if len(df)<3: return [],0,[],None,"No Data"
    last=df.iloc[-1]; prev=df.iloc[-2]
    body=abs(last['close']-last['open']); rng=last['high']-last['low']
    if rng==0: return [],0,[],None,"No Range"
    upper=last['high']-max(last['close'],last['open']); lower=min(last['close'],last['open'])-last['low']
    avg_vol = df['volume'].tail(20).mean() if 'volume' in df.columns else 0
    last_vol = last['volume'] if 'volume' in df.columns else 0
    vol_ratio = (last_vol/avg_vol) if avg_vol>0 else 1
    is_strong = vol_ratio >= 1.15; is_fake = vol_ratio < 0.75
    vol_status = f"Vol {vol_ratio:.2f}x ({'STRONG' if is_strong else 'FAKE' if is_fake else 'Normal'})"
    if is_fake:
        return [], -100, [f"FAKE Volume {vol_ratio:.2f}x - Blocked"], None, vol_status
    triggers=[]; breakdown=[]; score=0; direction=None
    if prev['close']<prev['open'] and last['close']>last['open'] and last['close']>prev['open'] and last['open']<prev['close']:
        pts=30 if is_strong else 10; triggers.append(f"Bullish Engulfing {vol_status}"); breakdown.append(f"Candlestick Pattern: Bullish Engulfing +{pts}pts"); score+=pts; direction="BUY"
    if prev['close']>prev['open'] and last['close']<last['open'] and last['close']<prev['open'] and last['open']>prev['close']:
        pts=30 if is_strong else 10; triggers.append(f"Bearish Engulfing {vol_status}"); breakdown.append(f"Candlestick Pattern: Bearish Engulfing +{pts}pts"); score+=pts; direction="SELL"
    if lower > (body*2) and upper < (body*0.4):
        triggers.append(f"Hammer Pin Bar {vol_status}"); breakdown.append(f"Price Action: Hammer Pin Bar +25pts"); score+=25
        if not direction: direction="BUY"
    if upper > (body*2) and lower < (body*0.4):
        triggers.append(f"Shooting Star {vol_status}"); breakdown.append(f"Price Action: Shooting Star +25pts"); score+=25
        if not direction: direction="SELL"
    recent_low=df['low'].tail(20).min(); recent_high=df['high'].tail(20).max()
    if last['low'] <= recent_low*1.0008 and last['close']>last['open'] and is_strong:
        triggers.append(f"Support Bounce {vol_status}"); breakdown.append(f"Price Action: Support Bounce +20pts"); score+=20
        if not direction: direction="BUY"
    if last['high'] >= recent_high*0.9992 and last['close']<last['open'] and is_strong:
        triggers.append(f"Resistance Rejection {vol_status}"); breakdown.append(f"Price Action: Resistance Rejection +20pts"); score+=20
        if not direction: direction="SELL"
    return triggers, score, breakdown, direction, vol_status

def get_signal_analysis(df):
    if len(df)<30: return None
    df=bollinger(df); df=stochastic(df); df=cci(df)
    df['rsi']=rsi(df['close']); df['ema20']=ema(df['close'],20); df['ema50']=ema(df['close'],50)
    last=df.iloc[-1]; prev=df.iloc[-2]
    triggers=[]; breakdown=[]; score=0; direction=None
    boll_touch_lower = last['low'] <= last['lower'] or last['close'] <= last['lower']*1.0003
    boll_touch_upper = last['high'] >= last['upper'] or last['close'] >= last['upper']*0.9997
    bullish_candle = last['close'] > last['open']; bearish_candle = last['close'] < last['open']
    stoch_bull_cross = prev['%K'] < prev['%D'] and last['%K'] > last['%D'] and last['%K'] < 20 and last['%D'] < 20
    stoch_bear_cross = prev['%K'] > prev['%D'] and last['%K'] < last['%D'] and last['%K'] > 80 and last['%D'] > 80
    rsi_bull = last['rsi'] < 35; rsi_bear = last['rsi'] > 65
    cci_bull = last['cci'] < -100; cci_bear = last['cci'] > 100
    if boll_touch_lower and bullish_candle and stoch_bull_cross and rsi_bull:
        breakdown.append("Bollinger Band Bounce (30pts) ▲ Bullish +30"); triggers.append("Bollinger Lower Touch + Bullish Close"); score+=30
        breakdown.append(f"RSI Divergence (25pts) ▲ Bullish +25 (RSI {last['rsi']:.1f})"); triggers.append(f"RSI {last['rsi']:.1f} <35"); score+=25
        breakdown.append(f"Stochastic Cross (20pts) ▲ Bullish +20 (%K {last['%K']:.1f} > %D {last['%D']:.1f} below 20)"); triggers.append(f"Stoch Cross below 20"); score+=20
        if cci_bull:
            breakdown.append(f"CCI Extreme (15pts) ▲ Bullish +15 (CCI {last['cci']:.1f})"); triggers.append(f"CCI {last['cci']:.1f} <-100"); score+=15
        direction="BUY"
    elif boll_touch_upper and bearish_candle and stoch_bear_cross and rsi_bear:
        breakdown.append("Bollinger Band Bounce (30pts) ▼ Bearish +30"); triggers.append("Bollinger Upper Touch + Bearish Close"); score+=30
        breakdown.append(f"RSI Divergence (25pts) ▼ Bearish +25 (RSI {last['rsi']:.1f})"); triggers.append(f"RSI {last['rsi']:.1f} >65"); score+=25
        breakdown.append(f"Stochastic Cross (20pts) ▼ Bearish +20 (%K {last['%K']:.1f} < %D {last['%D']:.1f} above 80)"); triggers.append(f"Stoch Cross above 80"); score+=20
        if cci_bear:
            breakdown.append(f"CCI Extreme (15pts) ▼ Bearish +15 (CCI {last['cci']:.1f})"); triggers.append(f"CCI {last['cci']:.1f} >100"); score+=15
        direction="SELL"
    else:
        return None
    c_trig, c_score, c_break, c_dir, vol_status = price_action_volume_check(df)
    if c_score < 0: return None
    triggers.extend(c_trig); breakdown.extend(c_break); score+=c_score; triggers.append(vol_status)
    if score < 75 or not direction: return None
    conf = 70 + (score-75)*(25/40)
    return {"direction":direction, "score":score, "confidence":round(min(95, max(70, conf)),1), "breakdown":breakdown, "triggers":triggers, "vol":vol_status}

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Start Bot", callback_data='start_bot'), InlineKeyboardButton("🔴 Stop Bot", callback_data='stop_bot')],
        [InlineKeyboardButton("📈 Select Market", callback_data='menu_market'), InlineKeyboardButton("⏰ Timeframe", callback_data='menu_tf')],
        [InlineKeyboardButton("📊 Status", callback_data='status')]
    ])
def market_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("OTC MARKET (18 Pairs)", callback_data='show_otc_pairs')],
        [InlineKeyboardButton("LIVE MARKET (7 Pairs)", callback_data='show_live_pairs')],
        [InlineKeyboardButton("⬅️ Back", callback_data='back_main')]
    ])
def pair_menu(pairs_list, market_name):
    keyboard=[]
    for i in range(0, len(pairs_list), 2):
        row=[]; row.append(InlineKeyboardButton(pairs_list[i], callback_data=f'pair_{pairs_list[i]}'))
        if i+1 < len(pairs_list): row.append(InlineKeyboardButton(pairs_list[i+1], callback_data=f'pair_{pairs_list[i+1]}'))
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton(f"✅ ALL {len(pairs_list)} PAIRS", callback_data=f'allpairs_{market_name}')])
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data='menu_market')])
    return InlineKeyboardMarkup(keyboard)
def timeframe_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1m", callback_data='tf_1m'), InlineKeyboardButton("2m", callback_data='tf_2m'), InlineKeyboardButton("3m", callback_data='tf_3m')],
        [InlineKeyboardButton("5m", callback_data='tf_5m'), InlineKeyboardButton("15m", callback_data='tf_15m')],
        [InlineKeyboardButton("⬅️ Back", callback_data='back_main')]
    ])

async def start_cmd(update, context):
    await update.message.reply_text(f"✅ Bot Ready\n{len(selected_pairs)} Pairs | {current_market} | TF: {selected_timeframe}\n\nOTC: 18 Pairs\nLIVE: 7 Pairs\n\nEntry: Bollinger(20,2)+RSI+Stoch+CCI+PriceAction+Volume", reply_markup=main_menu())
async def button_handler(update, context):
    global selected_pairs, bot_active, selected_timeframe, current_market
    q=update.callback_query; await q.answer(); data=q.data
    if data=='start_bot':
        bot_active=True; await q.edit_message_text(f"✅ Bot Started!\nScanning: {', '.join(selected_pairs[:3])}{'...' if len(selected_pairs)>3 else ''}\nTotal: {len(selected_pairs)} pairs | TF: {selected_timeframe}\nFake Filter ON", reply_markup=main_menu())
    elif data=='stop_bot':
        bot_active=False; await q.edit_message_text("🛑 Bot Stopped", reply_markup=main_menu())
    elif data=='menu_market':
        await q.edit_message_text("Select Market Type:", reply_markup=market_menu())
    elif data=='menu_tf':
        await q.edit_message_text(f"Current TF: {selected_timeframe}\nSelect Timeframe:", reply_markup=timeframe_menu())
    elif data=='show_otc_pairs':
        current_market="OTC"; await q.edit_message_text("OTC MARKET - Choose Pair (18):", reply_markup=pair_menu(OTC_PAIRS, "OTC"))
    elif data=='show_live_pairs':
        current_market="LIVE"; await q.edit_message_text("LIVE MARKET - Choose Pair (7):", reply_markup=pair_menu(LIVE_PAIRS, "LIVE"))
    elif data.startswith('pair_'):
        pair_name=data.replace('pair_',''); selected_pairs=[pair_name]; await q.edit_message_text(f"✅ Selected: {pair_name}\nSirf yahi pair scan hoga | TF: {selected_timeframe}", reply_markup=main_menu())
    elif data.startswith('allpairs_'):
        m=data.replace('allpairs_','')
        if m=="OTC": selected_pairs=OTC_PAIRS; current_market="OTC"
        else: selected_pairs=LIVE_PAIRS; current_market="LIVE"
        await q.edit_message_text(f"✅ ALL {m} Selected: {len(selected_pairs)} pairs | TF: {selected_timeframe}", reply_markup=main_menu())
    elif data=='tf_1m': selected_timeframe="1m"; await q.edit_message_text(f"✅ TF: 1 Min set", reply_markup=main_menu())
    elif data=='tf_2m': selected_timeframe="2m"; await q.edit_message_text(f"✅ TF: 2 Min set", reply_markup=main_menu())
    elif data=='tf_3m': selected_timeframe="3m"; await q.edit_message_text(f"✅ TF: 3 Min set", reply_markup=main_menu())
    elif data=='tf_5m': selected_timeframe="5m"; await q.edit_message_text(f"✅ TF: 5 Min set", reply_markup=main_menu())
    elif data=='tf_15m': selected_timeframe="15m"; await q.edit_message_text(f"✅ TF: 15 Min set", reply_markup=main_menu())
    elif data=='back_main': await q.edit_message_text(f"Ready | {len(selected_pairs)} pairs | {current_market} | TF: {selected_timeframe}", reply_markup=main_menu())
    elif data=='status':
        s="ACTIVE 🟢" if bot_active else "STOPPED 🔴"; await q.edit_message_text(f"Status: {s}\nMarket: {current_market}\nPairs: {len(selected_pairs)}\n{', '.join(selected_pairs[:5])}\nTF: {selected_timeframe}\nFake Filter: ON", reply_markup=main_menu())

def get_real_df(pair_name):
    base=pair_name.replace(" (OTC)","").replace(" OTC","").strip()
    yf_sym=YF_MAP.get(base)
    if not yf_sym: return None
    try:
        fetch_interval = "1m" if selected_timeframe in ["2m","3m"] else selected_timeframe
        period = "2d" if selected_timeframe in ["1m","2m","3m","5m"] else "5d"
        df=yf.download(yf_sym, period=period, interval=fetch_interval, progress=False, auto_adjust=True)
        if df.empty or len(df)<30: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns=df.columns.get_level_values(0)
        df.columns=[c.lower() for c in df.columns]
        cols=['open','high','low','close','volume'] if 'volume' in df.columns else ['open','high','low','close']
        df = df[cols].dropna()
        if selected_timeframe == "2m":
            df = df.resample('2min').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna()
        elif selected_timeframe == "3m":
            df = df.resample('3min').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna()
        return df
    except Exception as e:
        logging.error(f"YF {pair_name}: {e}")
        return None

async def scanner(context):
    if not bot_active: return
    for pair in selected_pairs:
        df=get_real_df(pair)
        if df is None: continue
        analysis=get_signal_analysis(df)
        if analysis:
            emoji="🟢" if analysis['direction']=="BUY" else "🔴"
            trig="\n".join([f"{i+1}. {t}" for i,t in enumerate(analysis['triggers'])])
            brk="\n".join(analysis['breakdown'])
            msg=f"{emoji} {analysis['direction']} SIGNAL {emoji}\nPair: {pair}\nMarket: {current_market} | TF: {selected_timeframe}\nConfidence: {analysis['confidence']}% | Score: {analysis['score']}/100\n\nENTRY: Enter {analysis['direction']} on next {selected_timeframe} open\n{analysis['vol']}\n\n5-Factor + PriceAction:\n{brk}\n\nTriggers:\n{trig}\n\nFake Filter: Passed ✅"
            try: await context.bot.send_message(chat_id=CHAT_ID, text=msg)
            except: pass

def main():
    if not TOKEN or not CHAT_ID: logging.error("TOKEN/CHAT_ID missing!"); return
    app=Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.job_queue.run_repeating(scanner, interval=60, first=10)
    app.run_polling()
if __name__=="__main__": main()
