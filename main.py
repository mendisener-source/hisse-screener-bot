import os
import time
import threading
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from http.server import HTTPServer, BaseHTTPRequestHandler
import warnings
warnings.filterwarnings('ignore')

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "7651339989:AAEH88cimbHLwq3D01AyN95ohadu3RWthjM")
TELEGRAM_CHAT_ID = int(os.environ.get("TELEGRAM_CHAT_ID", 6084552159))

WATCHLIST = [
    # Dev Teknoloji & Büyüme Hisseleri (2x Kaldıraçlı)
    "AMZZ", "NFLU", "AVL", "SMCX", "GOOX", "FUGU", "PTIR",
    
    # Yarı İletken, Kripto & Dijital Varlıklar (2x Kaldıraçlı)
    "USD", "CONL", "BITX",
    
    # Sektörel & Ters Korelasyonlu ETF'ler (2x / 3x Kaldıraçlı)
    "LABU", "CURE", "ERX", "DRN", "RETU"
]

TIMEFRAMES = {
    "1 Saatlik (1H)": {"interval": "1h", "period": "7d"},
    "4 Saatlik (4H)": {"interval": "60m", "period": "30d", "resample": "4h"},
    "Günlük (1D)":    {"interval": "1d", "period": "60d"}
}

# Render'ın açık port bekleme uyarısını çözmek için basit HTTP Sunucusu
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Active")

def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

def send_telegram_msg(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": str(message)}
    for attempt in range(3):
        try:
            res = requests.post(url, json=payload, timeout=10)
            if res.status_code == 200:
                print("📲 Telegram bildirimi gönderildi.")
                return True
        except Exception as e:
            print(f"❌ Baglanti hatasi: {e}")
        time.sleep(2)
    return False

def fetch_and_process_data(ticker, tf_info):
    try:
        # Yahoo Finance rate limit engeline takılmamak için 1.5 sn bekleme
        time.sleep(1.5) 
        df = yf.download(ticker, period=tf_info["period"], interval=tf_info["interval"], progress=False)
        
        if df.empty or len(df) < 25:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        if tf_info.get("resample") == "4h":
            df = df.resample('4h').agg({
                'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
            }).dropna()

        if len(df) < 25:
            return None

        df['BB_Basis'] = df['Close'].rolling(window=20).mean()
        df['BB_Std']   = df['Close'].rolling(window=20).std()
        df['BB_Upper'] = df['BB_Basis'] + (2.2 * df['BB_Std'])
        df['BB_Lower'] = df['BB_Basis'] - (2.2 * df['BB_Std'])

        delta = df['Close'].diff()
        gain  = (delta.where(delta > 0, 0)).rolling(window=3).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(window=3).mean()
        rs    = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))

        low_14  = df['Low'].rolling(window=14).min()
        high_14 = df['High'].rolling(window=14).max()
        df['Stoch_K'] = 100 * ((df['Close'] - low_14) / (high_14 - low_14))
        df['Stoch_D'] = df['Stoch_K'].rolling(window=3).mean()

        ha_close = (df['Open'] + df['High'] + df['Low'] + df['Close']) / 4
        ha_open = np.zeros(len(df))
        ha_open[0] = (df['Open'].iloc[0] + df['Close'].iloc[0]) / 2
        for i in range(1, len(df)):
            ha_open[i] = (ha_open[i-1] + ha_close.iloc[i-1]) / 2
            
        df['HA_Green'] = ha_close > ha_open
        df['HA_Red']   = ha_close < ha_open

        curr = df.iloc[-1]
        prev = df.iloc[-2]

        touch_lower = (df['Low'].iloc[-3:].min() <= curr['BB_Lower'])
        touch_upper = (df['High'].iloc[-3:].max() >= curr['BB_Upper'])

        rsi_hook_up   = (curr['RSI'] > prev['RSI']) and (prev['RSI'] <= 15.0)
        rsi_hook_down = (curr['RSI'] < prev['RSI']) and (prev['RSI'] >= 85.0)

        stoch_turn_up   = (prev['Stoch_K'] <= curr['Stoch_D'] and curr['Stoch_K'] > curr['Stoch_D']) or (curr['Stoch_K'] > prev['Stoch_K'] and prev['Stoch_K'] <= 15.0)
        stoch_turn_down = (prev['Stoch_K'] >= curr['Stoch_D'] and curr['Stoch_K'] < curr['Stoch_D']) or (curr['Stoch_K'] < prev['Stoch_K'] and prev['Stoch_K'] >= 85.0)

        long_sig  = touch_lower and curr['HA_Green'] and rsi_hook_up and stoch_turn_up
        short_sig = touch_upper and curr['HA_Red'] and rsi_hook_down and stoch_turn_down

        if long_sig:
            return "🚀 DIP ALIM SINYALI", curr['Close'], curr['RSI'], curr['Stoch_K'], "HA Yesil"
        elif short_sig:
            return "🔻 TEPE SATIS SINYALI", curr['Close'], curr['RSI'], curr['Stoch_K'], "HA Kirmizi"
    except Exception as e:
        print(f"⚠️ Veri çekme hatası ({ticker}): {e}")
    return None

def run_screener():
    print("⏳ Piyasa taranıyor...")
    for tf_name, tf_info in TIMEFRAMES.items():
        for ticker in WATCHLIST:
            res = fetch_and_process_data(ticker, tf_info)
            if res:
                sig_type, price, rsi, stoch, ha_status = res
                msg = (f"{sig_type}\n\n"
                       f"Varlik: {ticker}\n"
                       f"Periyot: {tf_name}\n"
                       f"Kapanis Fiyati: ${price:.2f}\n"
                       f"RSI (3): {rsi:.1f} | Stoch %K: {stoch:.1f}\n"
                       f"Mum: {ha_status}")
                send_telegram_msg(msg)

if __name__ == "__main__":
    # Web sunucusunu arka planda başlat
    threading.Thread(target=start_health_server, daemon=True).start()
    send_telegram_msg("🤖 Screener Bot Render.com üzerinde 7/24 aktif edildi!")
    
    while True:
        run_screener()
        time.sleep(900)
