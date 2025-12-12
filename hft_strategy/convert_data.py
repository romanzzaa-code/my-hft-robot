import pandas as pd
import numpy as np
import requests
import gzip
import shutil
import os
import io

# === НАСТРОЙКИ ===
SYMBOL = "SOLUSDT"
DATE = "2025-12-10" # Свежие данные
OUTPUT_FILE = f"data/{SYMBOL}_bybit_{DATE}.npz"

# Ссылка на публичные данные Bybit (Trading Data)
BASE_URL = "https://public.bybit.com/trading"
CSV_FILENAME = f"{SYMBOL}{DATE}.csv.gz"
URL = f"{BASE_URL}/{SYMBOL}/{CSV_FILENAME}"

def download_and_convert():
    print(f"🚀 Start downloading {SYMBOL} for {DATE} from Bybit...")
    print(f"🔗 URL: {URL}")
    
    # 1. Скачивание
    try:
        response = requests.get(URL)
        if response.status_code != 200:
            print(f"❌ Error downloading: Status {response.status_code}")
            return
    except Exception as e:
        print(f"❌ Network error: {e}")
        return

    print("📦 Download complete. Decompressing and Parsing...")
    
    # 2. Распаковка и чтение в Pandas
    with gzip.open(io.BytesIO(response.content), 'rt') as f:
        # Bybit CSV columns: timestamp, symbol, side, size, price, tickDirection, trdMatchID, ...
        df = pd.read_csv(f)

    # Приводим к стандарту
    # timestamp у Bybit в секундах (float), нам нужны наносекунды (int)
    # Иногда колонка называется 'timestamp', иногда 'exec_time'
    ts_col = 'timestamp' if 'timestamp' in df.columns else 'execTime'
    
    # Сортируем по времени
    df = df.sort_values(by=ts_col).reset_index(drop=True)
    
    print(f"📊 Processing {len(df)} trades...")

    # 3. Конвертация в формат HftBacktest
    # Структура события: [event_type, exch_ts, local_ts, side, price, qty]
    # event_type: 1=Depth Clear, 2=Snapshot, 3=Depth Update, 4=Trade
    
    # Мы будем создавать ПСЕВДО-СТАКАН на основе сделок, чтобы стратегия видела BID/ASK
    rows = []
    
    # Начальные настройки
    tick_size = 0.01
    
    for row in df.itertuples():
        # Время в наносекундах (Bybit дает секунды, например 1672531200.123)
        ts = int(getattr(row, ts_col) * 1_000_000_000)
        price = float(row.price)
        qty = float(row.size)
        side = 1 if row.side == 'Buy' else -1 # 1=Buy, -1=Sell
        
        # --- СОБЫТИЕ 1: Сама сделка (Trade) ---
        # EventType=4 (Trade)
        rows.append([4, ts, ts, side, price, qty])
        
        # --- СОБЫТИЕ 2: Обновление стакана (Depth Update) ---
        # Чтобы стратегия видела "Bid" и "Ask", мы искусственно двигаем BBO к цене сделки
        # Это эмуляция: считаем, что спред минимален
        
        # EventType=3 (Depth Update)
        # Bid = Price - tick_size
        rows.append([3, ts, ts, 1, price - tick_size, 1000.0]) # 1 = Bid
        # Ask = Price + tick_size
        rows.append([3, ts, ts, -1, price + tick_size, 1000.0]) # -1 = Ask

    # 4. Собираем NumPy массив
    data_array = np.array(rows, dtype=np.float64)
    
    # Проверка на пустой массив
    if len(data_array) == 0:
        print("❌ Error: No data processed.")
        return

    # 5. Сохранение
    # Структура HftBacktest требует, чтобы данные были валидными
    print(f"💾 Saving to {OUTPUT_FILE}...")
    np.savez_compressed(OUTPUT_FILE, data=data_array)
    
    print("✅ DONE! Now you can run:")
    print(f"   python hft_strategy/backtest.py --symbol {SYMBOL} --input {OUTPUT_FILE}")

if __name__ == "__main__":
    download_and_convert()