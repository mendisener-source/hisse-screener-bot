import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import warnings
warnings.filterwarnings('ignore')

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "7651339989:AAEH88cimbHLwq3D01AyN95ohadu3RWthjM")
TELEGRAM_CHAT_ID = int(os.environ.get("TELEGRAM_CHAT_ID", 6084552159))

# Breakout Stratejisi İzleme Listesi (Kaldıraçlı & Yüksek Oynaklıklı Varlıklar)
WATCHLIST = [
    "AMZZ", "NFLU", "AVL", "SMCX", "GOOX", "FUGU", "PTIR",
    "USD", "CONL", "BITX", "LABU", "CURE", "ERX", "DRN", "RETU"
]

TIMEFRAMES = {
    "1 Saatlik (1H)": {"interval": "1h", "period": "14d"},
    "4 Saatlik (4H)": {"interval": "60m", "period": "60d", "resample": "4h"},
    "Günlük (1D)": {"interval": "1d", "period": "120d"}
}

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Breakout Screener Bot Alive")

def run_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram gönderme hatası: {e}")

def calculate_indicators(df):
    # Donchian Kanalları (20)
    df['Donchian_High'] = df['High'].rolling(window=20).max().shift(1)
    df['Donchian_Low'] = df['Low'].rolling(window=20).min().shift(1)
    
    # Trend Göstergeleri (EMA 50 & EMA 200)
    df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['EMA200'] = df['Close'].ewm(span=200, adjust=False).mean()
    
    # Hacim Ortalaması (20)
    df['Vol_SMA20'] = df['Volume'].rolling(window=20).mean()
    
    return df

def fetch_data(symbol, tf_info):
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(interval=tf_info['interval'], period=tf_info['period'])
        if df.empty or len(df) < 50:
            return None
            
        if "resample" in tf_info:
            df = df.resample(tf_info['resample']).agg({
                'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
            }).dropna()
            
        return calculate_indicators(df)
    except Exception as e:
        print(f"{symbol} veri çekme hatası: {e}")
        return None

def check_breakout_signals():
    print("--- Breakout & Trend Taraması Başlatıldı ---")
    for symbol in WATCHLIST:
        for tf_name, tf_info in TIMEFRAMES.items():
            df = fetch_data(symbol, tf_info)
            if df is None or len(df) < 2:
                continue
                
            curr = df.iloc[-1]
            prev = df.iloc[-2]
            
            close_price = round(curr['Close'], 2)
            vol_ratio = round(curr['Volume'] / curr['Vol_SMA20'], 2) if curr['Vol_SMA20'] > 0 else 0
            
            # 🚀 TREND AL (Breakout Buy) Koşulları:
            # 1. Kapanış > Donchian Üst Bandı
            # 2. Close > EMA50 > EMA200 (Yükseliş Trendi)
            # 3. Hacim > 1.5 * Hacim Ortalaması
            is_breakout_buy = (
                curr['Close'] > prev['Donchian_High'] and
                curr['Close'] > curr['EMA50'] and
                curr['EMA50'] > curr['EMA200'] and
                vol_ratio >= 1.5
            )
            
            # 🔻 TREND SAT / STOP Koşulları:
            # Kapanış Donchian Alt Bandına temas eder veya EMA50 altına düşerse
            is_breakout_sell = (
                curr['Close'] < prev['Donchian_Low'] or
                curr['Close'] < curr['EMA50']
            )
            
            if is_breakout_buy:
                msg = (
                    f"🚀 <b>TREND & BREAKOUT AL SİNYALİ</b>\n\n"
                    f"<b>Varlık:</b> {symbol}\n"
                    f"<b>Periyot:</b> {tf_name}\n"
                    f"<b>Kapanış Fiyatı:</b> ${close_price}\n"
                    f"<b>Hacim Artışı:</b> {vol_ratio}x (Hacim Onaylı)\n"
                    f"<b>Trend Durumu:</b> Fiyat > EMA50 > EMA200 🟢"
                )
                send_telegram(msg)
                
            elif is_breakout_sell and curr['Close'] < curr['EMA50']:
                msg = (
                    f"🔻 <b>TREND STOP / CIKIS SİNYALİ</b>\n\n"
                    f"<b>Varlık:</b> {symbol}\n"
                    f"<b>Periyot:</b> {tf_name}\n"
                    f"<b>Kapanış Fiyatı:</b> ${close_price}\n"
                    f"<b>Neden:</b> EMA50 Kırıldı / Donchian Alt Band Teması 🔴"
                )
                send_telegram(msg)

if __name__ == "__main__":
    threading.Thread(target=run_health_check_server, daemon=True).start()
    send_telegram("⚡ Breakout & Trend Takip Botu Aktif Edildi!")
    
    while True:
        try:
            check_breakout_signals()
        except Exception as e:
            print(f"Tarama döngüsü hatası: {e}")
        time.sleep(900)  # 15 dakikada bir tarar
