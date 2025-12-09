import asyncio
import asyncpg
import numpy as np
import logging
from datetime import datetime
import os

# Конфиг (вынеси в env в продакшене)
DB_CONFIG = {
    "user": "hft_user",
    "password": "password",
    "database": "hft_data",
    "host": "localhost",
    "port": "5432"
}

# HFTBacktest Data Structure
# Event types: 1 = TRADE, (мы пока используем только trades)
TRADE_EVENT_ID = 1 

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("EXPORTER")

async def export_to_npz(symbol: str, output_file: str):
    logger.info(f"⏳ Connecting to DB to export {symbol}...")
    conn = await asyncpg.connect(**DB_CONFIG)
    
    try:
        # 1. Запрашиваем данные. 
        # ВАЖНО: hftbacktest требует сортировки по времени
        query = """
            SELECT 
                EXTRACT(EPOCH FROM time) * 1000000 AS ts_micros, -- Time in microseconds
                price,
                volume,
                is_buyer_maker
            FROM market_ticks
            WHERE symbol = $1
            ORDER BY time ASC
        """
        
        logger.info("📊 Fetching data (this might take time)...")
        rows = await conn.fetch(query, symbol)
        
        if not rows:
            logger.warning("⚠️ No data found for this symbol.")
            return

        logger.info(f"✅ Fetched {len(rows)} rows. Processing...")

        # 2. Создаем структуру для hftbacktest
        # Формат: [Event, ExchTS, LocalTS, Price, Qty, ...]
        # Так как у нас нет LocalTS, мы временно используем ExchTS для обоих полей
        
        dtype = [
            ('ev', 'i8'),         # Event Type
            ('exch_ts', 'i8'),    # Exchange Timestamp
            ('local_ts', 'i8'),   # Local Timestamp
            ('px', 'f8'),         # Price
            ('qty', 'f8'),        # Quantity
            ('ival', 'i8'),       # Reserved (Instrument Value?)
            ('f', 'i8'),          # Flags
            ('res', 'i8')         # Reserved
        ]
        
        data = np.zeros(len(rows), dtype=dtype)
        
        # Заполняем массив (векторизация тут сложна из-за asyncpg, делаем цикл или pandas)
        # Для скорости лучше использовать итерацию, если памяти мало
        
        for i, row in enumerate(rows):
            ts = int(row['ts_micros'])
            price = float(row['price'])
            qty = float(row['volume'])
            
            # В HFTBacktest 'buy' или 'sell' часто определяются флагом. 
            # Для простоты: Event=1 (Trade).
            # Maker/Taker флаги можно упаковать в 'f', но пока оставим простым.
            
            data[i]['ev'] = TRADE_EVENT_ID
            data[i]['exch_ts'] = ts
            data[i]['local_ts'] = ts # ⚠️ HACK: Нет локального времени
            data[i]['px'] = price
            data[i]['qty'] = qty

        # 3. Сохраняем в NPZ
        # hftbacktest ищет файл по имени (обычно)
        logger.info(f"💾 Saving to {output_file}...")
        np.savez_compressed(output_file, data=data)
        logger.info("🎉 Export complete!")

    finally:
        await conn.close()

if __name__ == "__main__":
    # Убедись, что папка data существует
    os.makedirs("data", exist_ok=True)
    asyncio.run(export_to_npz("BTCUSDT", "data/btcusdt_trades.npz"))