import os
import time
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
    # Dev Teknoloji & Büyüme Hisseleri (2x)
    "AMZZ", "NFLU", "AVL", "SMCX", "GOOX", "FUGU", "PTIR",
    # Yarı İletken, Kripto & Dijital Varlıklar (2x)
    "USD", "CONL", "BITX",
    # Sektörel & Ters Korelasyonlu ETF'ler (2x / 3x)
    "LABU", "CURE", "ERX", "DRN", "RETU"
]

TIMEFRAMES = {
    "1 Saatlik (1H)": {"interval": "1h", "period": "7d"},
    "4 Saatlik (4H)": {"interval": "60m", "period": "30d", "resample": "4h"},
    "Günlük (1D)":    {"interval": "1d", "period": "60d"}
}

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

def run_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    import threading
    threading.Thread(target=server.serve_forever, daemon=True).start()

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram hatasi: {e}")

def calculate_indicators(df):
    # Bollinger Bands
    df['SMA20'] = df['Close'].rolling(20).mean()
    df['STD20'] = df['Close'].rolling(20).std()
    df['Upper'] = df['SMA20'] + (df['STD20'] * 2)
    df['Lower'] = df['SMA20'] - (df['STD20'] * 2)

    # RSI (3)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(3).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(3).mean()
    rs = gain / loss.replace(0, np.nan)
    df['RSI3'] = 100 - (100 / (1 + rs))

    # Stochastic %K
    low14 = df['Low'].rolling(14).min()
    high14 = df['High'].rolling(14).max()
    df['Stoch_K'] = 100 * ((df['Close'] - low14) / (high14 - low14))

    # Heikin Ashi
    ha_close = (df['Open'] + df['High'] + df['Low'] + df['Close']) / 4
    ha_open = [ (df['Open'].iloc[0] + df['Close'].iloc[0]) / 2 ]
    for i in range(1, len(df)):
        ha_open.append((ha_open[-1] + ha_close.iloc[i-1]) / 2)
    df['HA_Close'] = ha_close
    df['HA_Open'] = ha_open
    df['HA_Green'] = df['HA_Close'] > df['HA_Open']

    # Volume Average
    df['Vol_SMA20'] = df['Volume'].rolling(20).mean()
    
    return df

def analyze_symbol(symbol):
    for tf_name, tf_config in TIMEFRAMES.items():
        try:
            time.sleep(1.5) # Yahoo Finance Rate Limit Korumasi
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=tf_config["period"], interval=tf_config["interval"])
            
            if df.empty or len(df) < 25:
                continue

            if tf_config.get("resample") == "4h":
                df = df.resample('4h').agg({
                    'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
                }).dropna()

            df = calculate_indicators(df)
            
            # Kapanmis son mumu al (Bar Close)
            last = df.iloc[-2]

            # Veri Temizleme & Sınır Kontrolü (RSI = 0 veya NaN Hatası Önleyici)
            if pd.isna(last['RSI3']) or last['RSI3'] <= 1 or last['RSI3'] >= 99:
                continue
                
            # Hacim Teyidi (Son mum hacmi > 20 mumluk ortalama hacim)
            has_volume = last['Volume'] > (last['Vol_SMA20'] * 1.1)

            # DIP ALIS SINYALI (4 Onay Aynı Anda)
            is_dip_buy = (
                last['Close'] <= last['Lower'] and
                last['RSI3'] < 25 and
                last['Stoch_K'] < 25 and
                last['HA_Green'] and
                has_volume
            )

            # TEPE SATIS SINYALI (4 Onay Aynı Anda)
            is_tepe_sell = (
                last['Close'] >= last['Upper'] and
                last['RSI3'] > 75 and
                last['Stoch_K'] > 75 and
                (not last['HA_Green']) and
                has_volume
            )

            if is_dip_buy:
                msg = (
                    f"🟢 <b>DİP ALIM SİNYALİ</b>\n\n"
                    f"<b>Varlık:</b> {symbol}\n"
                    f"<b>Periyot:</b> {tf_name}\n"
                    f"<b>Fiyat:</b> ${last['Close']:.2f}\n"
                    f"<b>RSI (3):</b> {last['RSI3']:.1f} | <b>Stoch %K:</b> {last['Stoch_K']:.1f}\n"
                    f"<b>Mum:</b> HA Yeşil | <b>Hacim:</b> Onaylı"
                )
                send_telegram(msg)

            elif is_tepe_sell:
                msg = (
                    f"🔴 <b>TEPE SATIŞ SİNYALİ</b>\n\n"
                    f"<b>Varlık:</b> {symbol}\n"
                    f"<b>Periyot:</b> {tf_name}\n"
                    f"<b>Fiyat:</b> ${last['Close']:.2f}\n"
                    f"<b>RSI (3):</b> {last['RSI3']:.1f} | <b>Stoch %K:</b> {last['Stoch_K']:.1f}\n"
                    f"<b>Mum:</b> HA Kırmızı | <b>Hacim:</b> Onaylı"
                )
                send_telegram(msg)

        except Exception as e:
            print(f"{symbol} ({tf_name}) analiz hatasi: {e}")

def main():
    run_health_check_server()
    send_telegram("🚀 <b>Hisse Screener Bot (Mükemmelleştirilmiş Sürüm) Aktif Edildi!</b>")
    
    while True:
        print("Tarama baslatiliyor...")
        for symbol in WATCHLIST:
            analyze_symbol(symbol)
        print("Tarama tamamlandi. 15 dakika bekleniyor...")
        time.sleep(900)

if __name__ == "__main__":
    main()
