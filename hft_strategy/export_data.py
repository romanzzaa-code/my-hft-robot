# hft_strategy/export_data.py
import asyncio
import asyncpg
import numpy as np
import logging
import json
import os
from datetime import datetime

# Конфиг подключения
DB_CONFIG = {
    "user": "hft_user",
    "password": "password",
    "database": "hft_data",
    "host": "localhost",
    "port": "5432"
}

# --- КОНСТАНТЫ HFTBACKTEST ---
# https://github.com/nkaz001/hftbacktest/wiki/Data-Format
EVENT_TRADE = 1
EVENT_CLEAR = 2
EVENT_BID = 3
EVENT_ASK = 4

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("EXPORTER")

async def export_combined_data(symbol: str, output_file: str):
    logger.info(f"⏳ Connecting to DB to export {symbol}...")
    conn = await asyncpg.connect(**DB_CONFIG)
    
    try:
        # 1. Загружаем СДЕЛКИ (Trades)
        logger.info("📊 Fetching TRADES...")
        trades_query = """
            SELECT 
                EXTRACT(EPOCH FROM exch_time) * 1000000 AS exch_ts, 
                EXTRACT(EPOCH FROM time) * 1000000 AS local_ts,
                price,
                volume,
                is_buyer_maker
            FROM market_ticks
            WHERE symbol = $1
            ORDER BY exch_time ASC
        """
        trade_rows = await conn.fetch(trades_query, symbol)
        logger.info(f"✅ Loaded {len(trade_rows)} trades.")

        # 2. Загружаем СТАКАНЫ (Snapshots)
        logger.info("📚 Fetching DEPTH SNAPSHOTS...")
        # Берем только нужные поля. JSON уже будет строкой или объектом (зависит от драйвера)
        depth_query = """
            SELECT 
                EXTRACT(EPOCH FROM exch_time) * 1000000 AS exch_ts,
                EXTRACT(EPOCH FROM time) * 1000000 AS local_ts,
                bids,
                asks
            FROM market_depth_snapshots
            WHERE symbol = $1
            ORDER BY exch_time ASC
        """
        depth_rows = await conn.fetch(depth_query, symbol)
        logger.info(f"✅ Loaded {len(depth_rows)} snapshots.")

        # 3. Объединение и конвертация в NumPy
        # Нам нужно заранее оценить размер массива, но это сложно, так как 1 снэпшот = N событий.
        # Поэтому используем список для сбора, потом конвертируем.
        
        raw_data = []

        # --- Процессинг Сделок ---
        for row in trade_rows:
            # Trade Event: [Event, ExchTS, LocalTS, Price, Qty, ...]
            # Флаг is_buyer_maker часто кодируется в sign(qty) или flags, но для простоты пока так:
            # HftBacktest использует 'ev' для типа.
            
            # Важно: hftbacktest требует, чтобы данные были отсортированы.
            # Мы добавим их в общий котел.
            
            evt = [
                EVENT_TRADE,              # ev
                int(row['exch_ts']),      # exch_ts
                int(row['local_ts']),     # local_ts
                float(row['price']),      # px
                float(row['volume']),     # qty
                0, 0, 0                   # ival, f, res (резерв)
            ]
            raw_data.append(evt)

        # --- Процессинг Стаканов ---
        for row in depth_rows:
            ts_exch = int(row['exch_ts'])
            ts_local = int(row['local_ts'])
            
            # Десериализация JSON (asyncpg возвращает строку для jsonb)
            bids = json.loads(row['bids']) if isinstance(row['bids'], str) else row['bids']
            asks = json.loads(row['asks']) if isinstance(row['asks'], str) else row['asks']
            
            # ВАЖНО: Перед каждым снимком вставляем событие CLEAR, 
            # чтобы бэктестер "забыл" старые уровни.
            # Это имитирует приход полного снэпшота.
            raw_data.append([
                EVENT_CLEAR, 
                ts_exch, 
                ts_local, 
                0, 0, 0, 0, 0
            ])
            
            # Добавляем Биды
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
            
            # Добавляем Аски
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
        
        # 4. Создаем Structured Array
        dtype = [
            ('ev', 'i8'),         # Event Type
            ('exch_ts', 'i8'),    # Exchange Timestamp
            ('local_ts', 'i8'),   # Local Timestamp
            ('px', 'f8'),         # Price
            ('qty', 'f8'),        # Quantity
            ('ival', 'i8'),       # Reserved
            ('f', 'i8'),          # Flags
            ('res', 'i8')         # Reserved
        ]
        
        # Конвертируем список списков в numpy array
        # Это может занять память, если данных много. В продакшене лучше писать чанками.
        data_np = np.array([tuple(x) for x in raw_data], dtype=dtype)
        
        # 5. Сортировка
        # Сортируем по времени биржи (exch_ts). 
        # Если время совпадает (снэпшот), порядок внутри важен (Clear -> Bids/Asks),
        # но наш алгоритм добавления (append) уже сохранил этот порядок для одного TS.
        # sort order: exch_ts, then event type (Trade=1 vs Clear=2 is tricky, usually snapshot updates precede trades at same micros?)
        # Оставим просто по времени, полагаясь на стабильность сортировки (mergesort).
        
        data_np.sort(order=['exch_ts'])
        
        # 6. Коррекция Local TS (если локальное время "убежало" назад или рассинхрон)
        # HftBacktest падает, если local_ts < exch_ts.
        # Исправим это грубо: local_ts = max(local_ts, exch_ts)
        mask = data_np['local_ts'] < data_np['exch_ts']
        if np.any(mask):
            logger.warning(f"⚠️ Fixing {np.sum(mask)} timestamps where Local < Exchange")
            data_np['local_ts'][mask] = data_np['exch_ts'][mask]

        # 7. Сохранение
        os.makedirs("data", exist_ok=True)
        logger.info(f"💾 Saving to {output_file}...")
        np.savez_compressed(output_file, data=data_np)
        
        # Валидация
        logger.info(f"🎉 Export complete! File size: {os.path.getsize(output_file) / 1024 / 1024:.2f} MB")
        logger.info(f"Events breakdown: Trades={len(trade_rows)}, Snapshots={len(depth_rows)}, Total Rows={len(data_np)}")

    finally:
        await conn.close()

if __name__ == "__main__":
    # Запускать лучше, когда наберется хотя бы 5-10 минут данных
    try:
        asyncio.run(export_combined_data("BTCUSDT", "data/btcusdt_full.npz"))
    except KeyboardInterrupt:
        pass