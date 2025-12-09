# hft_strategy/export_data.py
import asyncio
import asyncpg
import numpy as np
import logging
import orjson
import os
from datetime import datetime

# [CONFIG] Импортируем настройки из единого центра
from config import DB_CONFIG

# --- КОНСТАНТЫ HFTBACKTEST ---
EVENT_TRADE = 1
EVENT_CLEAR = 2
EVENT_BID = 3
EVENT_ASK = 4

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("EXPORTER")

async def export_combined_data(symbol: str, output_file: str):
    logger.info(f"⏳ Connecting to DB to export {symbol}...")
    
    # Подключаемся через конфиг
    conn = await asyncpg.connect(**DB_CONFIG.as_dict())
    
    try:
        raw_data = []

        # Используем транзакцию для серверных курсоров
        async with conn.transaction():
            
            # 1. СДЕЛКИ (Trades) - Streaming Cursor
            logger.info("📊 Streaming TRADES...")
            # Читаем данные чанками, а не fetch() всего сразу
            async for row in conn.cursor(f"""
                SELECT 
                    EXTRACT(EPOCH FROM exch_time) * 1000000 AS exch_ts, 
                    EXTRACT(EPOCH FROM time) * 1000000 AS local_ts,
                    price,
                    volume
                FROM market_ticks
                WHERE symbol = '{symbol}'
                ORDER BY exch_time ASC
            """):
                evt = [
                    EVENT_TRADE,              # ev
                    int(row['exch_ts']),      # exch_ts
                    int(row['local_ts']),     # local_ts
                    float(row['price']),      # px
                    float(row['volume']),     # qty
                    0, 0, 0                   # ival, f, res
                ]
                raw_data.append(evt)
            
            logger.info(f"✅ Loaded trades. Current events: {len(raw_data)}")

            # 2. СТАКАНЫ (Snapshots) - Streaming Cursor
            logger.info("📚 Streaming DEPTH SNAPSHOTS...")
            
            async for row in conn.cursor(f"""
                SELECT 
                    EXTRACT(EPOCH FROM exch_time) * 1000000 AS exch_ts,
                    EXTRACT(EPOCH FROM time) * 1000000 AS local_ts,
                    bids,
                    asks
                FROM market_depth_snapshots
                WHERE symbol = '{symbol}'
                ORDER BY exch_time ASC
            """):
                ts_exch = int(row['exch_ts'])
                ts_local = int(row['local_ts'])
                
                # Десериализация JSON (orjson быстрее стандартного)
                # asyncpg может вернуть str или уже объект (зависит от codec), 
                # но orjson.loads работает с bytes/str
                bids_raw = row['bids']
                asks_raw = row['asks']

                bids = orjson.loads(bids_raw) if isinstance(bids_raw, str) else bids_raw
                asks = orjson.loads(asks_raw) if isinstance(asks_raw, str) else asks_raw
                
                # EVENT_CLEAR перед каждым снэпшотом
                raw_data.append([
                    EVENT_CLEAR, 
                    ts_exch, 
                    ts_local, 
                    0, 0, 0, 0, 0
                ])
                
                # Биды
                if bids:
                    for price, qty in bids:
                        raw_data.append([
                            EVENT_BID, 
                            ts_exch, 
                            ts_local, 
                            float(price), 
                            float(qty), 
                            0, 0, 0
                        ])
                
                # Аски
                if asks:
                    for price, qty in asks:
                        raw_data.append([
                            EVENT_ASK, 
                            ts_exch, 
                            ts_local, 
                            float(price), 
                            float(qty), 
                            0, 0, 0
                        ])

        logger.info(f"🔨 Merging and Sorting {len(raw_data)} total events...")
        
        # 3. Конвертация в NumPy
        dtype = [
            ('ev', 'i8'), ('exch_ts', 'i8'), ('local_ts', 'i8'), 
            ('px', 'f8'), ('qty', 'f8'), 
            ('ival', 'i8'), ('f', 'i8'), ('res', 'i8')
        ]
        
        data_np = np.array([tuple(x) for x in raw_data], dtype=dtype)
        
        # Сортировка по времени биржи
        data_np.sort(order=['exch_ts'])
        
        # Коррекция Local TS (если локальное время отстало от биржевого из-за NTP или лагов)
        mask = data_np['local_ts'] < data_np['exch_ts']
        if np.any(mask):
            count = np.sum(mask)
            logger.warning(f"⚠️ Fixing {count} timestamps where Local < Exchange")
            data_np['local_ts'][mask] = data_np['exch_ts'][mask]

        # 4. Сохранение
        os.makedirs("data", exist_ok=True)
        logger.info(f"💾 Saving to {output_file}...")
        np.savez_compressed(output_file, data=data_np)
        
        logger.info(f"🎉 Export complete! File size: {os.path.getsize(output_file) / 1024 / 1024:.2f} MB")

    finally:
        await conn.close()

if __name__ == "__main__":
    # Пример запуска
    try:
        # Можно передать символ и файл через аргументы командной строки (sys.argv)
        # Но для простоты пока так:
        asyncio.run(export_combined_data("BTCUSDT", "data/btcusdt_full.npz"))
    except KeyboardInterrupt:
        pass